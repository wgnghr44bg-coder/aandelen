"""Haalt koersen op via yfinance en schrijft docs/data.json.

Gebruik: python update.py
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
TICKERS_FILE = ROOT / "tickers.txt"
OUT = ROOT / "docs" / "data.json"
HIST = ROOT / "docs" / "history.json"
TOP_N = 100


def lees_tickers():
    tickers = []
    for regel in TICKERS_FILE.read_text().splitlines():
        regel = regel.split("#")[0].strip().upper()
        if regel and regel not in tickers:
            tickers.append(regel)
    return tickers


def schoon(x, digits=2):
    """Maak een getal JSON-veilig (geen NaN/inf)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, digits)


def pct(nu, toen):
    if toen is None or nu is None or toen == 0:
        return None
    return schoon((nu / toen - 1) * 100)


def koers_op(close, datum):
    """Laatste slotkoers op of vóór `datum`."""
    deel = close[close.index <= datum]
    if deel.empty:
        return None
    return float(deel.iloc[-1])


def bereken(df):
    """Berekent de koersveranderingen voor één ticker. df heeft kolommen Close/High."""
    df = df.dropna(subset=["Close"])
    if len(df) < 2:
        return None
    close = df["Close"]
    laatste_datum = close.index[-1]
    laatste = float(close.iloc[-1])
    vorige = float(close.iloc[-2])

    eerste = close.index[0]

    def periode(offset):
        datum = laatste_datum - offset
        if datum < eerste - pd.Timedelta(days=10):
            return None  # te weinig geschiedenis
        return pct(laatste, koers_op(close, max(datum, eerste)))

    jaar_start = pd.Timestamp(year=laatste_datum.year, month=1, day=1, tz=laatste_datum.tz)
    voor_jaar = close[close.index < jaar_start]
    ytd = pct(laatste, float(voor_jaar.iloc[-1])) if not voor_jaar.empty else None

    high = df["High"] if "High" in df else close
    high = high[high.index > laatste_datum - pd.Timedelta(days=365)].dropna()
    top = float(high.max()) if not high.empty else None
    onder_top = schoon((1 - laatste / top) * 100) if top else None
    if onder_top is not None and onder_top < 0:
        onder_top = 0.0

    return {
        "price": schoon(laatste),
        "d1": pct(laatste, vorige),
        "m1": periode(pd.DateOffset(months=1)),
        "m3": periode(pd.DateOffset(months=3)),
        "ytd": ytd,
        "y1": periode(pd.DateOffset(years=1)),
        "y5": periode(pd.DateOffset(years=5)),
        "high52": schoon(top),
        "fromHigh": onder_top,
        "_date": laatste_datum,
    }


def haal_info(ticker, pogingen=3):
    for poging in range(pogingen):
        try:
            info = yf.Ticker(ticker).info or {}
            if info.get("marketCap"):
                return info
        except Exception as e:  # noqa: BLE001
            print(f"  info {ticker} poging {poging + 1} mislukt: {e}")
        time.sleep(1.5 * (poging + 1))
    return None


def download(tickers, pogingen=3):
    for poging in range(pogingen):
        try:
            data = yf.download(
                tickers, period="5y", interval="1d", auto_adjust=True,
                group_by="ticker", threads=True, progress=False,
            )
            if data is not None and not data.empty:
                return data
        except Exception as e:  # noqa: BLE001
            print(f"download poging {poging + 1} mislukt: {e}")
        time.sleep(5 * (poging + 1))
    raise SystemExit("Kon geen koersen downloaden.")


def reeks(close, index):
    """Koersen op de gegeven datums (laatst bekende koers), None als er nog geen koers was."""
    s = close.reindex(index, method="ffill")
    s[index < close.index[0]] = float("nan")
    return [schoon(v) for v in s.tolist()]


def schrijf_historie(data, tickers, asof):
    """Schrijft docs/history.json: dagkoersen van 1 jaar en weekkoersen van 5 jaar voor de grafieken."""
    alles = data.index
    alles = alles[alles <= asof]
    dagen = alles[alles > asof - pd.DateOffset(years=1, days=7)]
    weken = pd.Series(alles, index=alles).resample("W-FRI").last().dropna()
    weken = pd.DatetimeIndex(weken.values)
    if len(weken) and weken[-1] != alles[-1]:
        weken = weken.append(pd.DatetimeIndex([alles[-1]]))
    uit = {
        "days": [d.strftime("%Y-%m-%d") for d in dagen],
        "weeks": [d.strftime("%Y-%m-%d") for d in weken],
        "series": {},
    }
    for t in tickers:
        try:
            df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
            close = df["Close"].dropna()
            if close.empty:
                continue
            uit["series"][t] = {"d": reeks(close, dagen), "w": reeks(close, weken)}
        except Exception as e:  # noqa: BLE001
            print(f"  historie {t}: overgeslagen ({e})")
    HIST.write_text(json.dumps(uit, separators=(",", ":")) + "\n")
    print(f"historie geschreven ({len(uit['series'])} aandelen, {HIST.stat().st_size // 1024} kB)")


def main():
    tickers = lees_tickers()
    print(f"{len(tickers)} tickers")
    data = download(tickers)

    rijen = []
    for t in tickers:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                if t not in data.columns.get_level_values(0):
                    print(f"  {t}: geen koersdata")
                    continue
                df = data[t]
            else:
                df = data
            stats = bereken(df)
            if not stats:
                print(f"  {t}: te weinig data")
                continue
            info = haal_info(t)
            time.sleep(0.3)
            if not info:
                print(f"  {t}: geen info")
                continue
            pe = schoon(info.get("trailingPE"), 1)
            rijen.append({
                "ticker": t,
                "name": info.get("shortName") or info.get("longName") or t,
                "sector": info.get("sector") or ("Financial Services" if t == "BRK-B" else "Overig"),
                "marketCap": int(info["marketCap"]),
                "pe": pe if pe and pe > 0 else None,
                **stats,
            })
        except Exception as e:  # noqa: BLE001
            print(f"  {t}: overgeslagen ({e})")

    if not rijen:
        raise SystemExit("Geen enkele ticker gelukt; data.json niet overschreven.")

    rijen.sort(key=lambda r: r["marketCap"], reverse=True)
    rijen = rijen[:TOP_N]
    asof = max(r["_date"] for r in rijen)
    for i, r in enumerate(rijen, 1):
        r["rank"] = i
        r.pop("_date")

    uit = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": pd.Timestamp(asof).strftime("%Y-%m-%d"),
        "rows": rijen,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(uit, ensure_ascii=False, indent=1) + "\n")
    try:
        schrijf_historie(data, [r["ticker"] for r in rijen], pd.Timestamp(asof))
    except Exception as e:  # noqa: BLE001
        print(f"historie mislukt: {e}")
    print(f"{len(rijen)} rijen geschreven naar {OUT} (slotkoersen {uit['asof']})")


if __name__ == "__main__":
    main()
