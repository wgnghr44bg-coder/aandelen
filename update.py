"""Haalt koersen op via yfinance en schrijft docs/data.json.

Gebruik: python update.py
"""
import json
import os
import urllib.request
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import fundamentals as fund

ROOT = Path(__file__).parent
TICKERS_FILE = ROOT / "tickers.txt"
AI_FILE = ROOT / "ai.txt"
OUT = ROOT / "docs" / "data.json"
HIST = ROOT / "docs" / "history.json"
TOP_N = 500

# Extra koersen bovenaan de site (in euro's).
EXTRAS = [
    {"ticker": "WEBN.DE", "label": "WEBN", "beurs": "Xetra"},
    {"ticker": "VALL.AS", "label": "VALL", "beurs": "Amsterdam"},
]
BITVAVO = "https://api.bitvavo.com/v2"


def lees_tickers(bestand=TICKERS_FILE):
    tickers = []
    if not bestand.exists():
        return tickers
    for regel in bestand.read_text().splitlines():
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


def slotkoersen(data, t):
    df = data[t] if isinstance(data.columns, pd.MultiIndex) else data
    return df["Close"].dropna()


def schrijf_historie(alles, closes, asof):
    """Schrijft docs/history.json: dagkoersen van 1 jaar en weekkoersen van 5 jaar voor de grafieken.

    alles: handelsdagen (DatetimeIndex), closes: {ticker: Series met slotkoersen}."""
    alles = pd.DatetimeIndex(alles)
    if alles.tz is not None:
        alles = alles.tz_localize(None)
    alles = alles.normalize().unique().sort_values()
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
    for t, close in closes.items():
        try:
            close = close.dropna()
            close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
            close = close[~close.index.duplicated(keep="last")]
            if close.empty:
                continue
            uit["series"][t] = {"d": reeks(close, dagen), "w": reeks(close, weken)}
        except Exception as e:  # noqa: BLE001
            print(f"  historie {t}: overgeslagen ({e})")
    HIST.write_text(json.dumps(uit, separators=(",", ":")) + "\n")
    print(f"historie geschreven ({len(uit['series'])} aandelen, {HIST.stat().st_size // 1024} kB)")


def http_json(url, pogingen=3):
    for poging in range(pogingen):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "aandelen-site/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"  {url} poging {poging + 1} mislukt: {e}")
            time.sleep(2 * (poging + 1))
    return None


def bitcoin():
    """BTC-EUR dagkoersen van Bitvavo (gratis, zonder sleutel). Geeft (rij, slotkoersen) of (None, None)."""
    candles = http_json(f"{BITVAVO}/BTC-EUR/candles?interval=1d&limit=1440")
    if not candles:
        return None, None
    df = pd.DataFrame(candles, columns=["t", "Open", "High", "Low", "Close", "Volume"])
    df.index = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    df = df.sort_index()[["High", "Close"]].astype(float)
    # Laatste prijs (live) in plaats van de nog lopende dagkaars
    prijs = http_json(f"{BITVAVO}/ticker/price?market=BTC-EUR")
    if prijs and prijs.get("price"):
        df.iloc[-1, df.columns.get_loc("Close")] = float(prijs["price"])
    stats = bereken(df)
    if not stats:
        return None, None
    stats.pop("_date")
    return {"ticker": "BTC-EUR", "label": "Bitcoin", "beurs": "Bitvavo", "name": "Bitcoin",
            "currency": "EUR", **stats}, df["Close"]


def haal_extras():
    """Koersen voor de balk bovenaan: ETF's via yfinance, bitcoin via Bitvavo."""
    rijen, closes = [], {}
    try:
        data = yf.download([e["ticker"] for e in EXTRAS], period="5y", interval="1d",
                           auto_adjust=True, group_by="ticker", progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"extras download mislukt: {e}")
        data = None
    for e in EXTRAS:
        try:
            df = data[e["ticker"]] if data is not None else None
            stats = bereken(df) if df is not None else None
            if not stats:
                print(f"  extra {e['ticker']}: geen koersdata")
                continue
            stats.pop("_date")
            info = {}
            try:
                info = yf.Ticker(e["ticker"]).info or {}
            except Exception:  # noqa: BLE001
                pass
            naam = info.get("shortName") or info.get("longName") or e["label"]
            print(f"  extra {e['ticker']}: {naam} ({info.get('currency')}, {info.get('exchange')}) {stats['price']}")
            rijen.append({**e, "name": naam, "currency": info.get("currency") or "EUR", **stats})
            closes[e["ticker"]] = df["Close"]
        except Exception as ex:  # noqa: BLE001
            print(f"  extra {e['ticker']}: overgeslagen ({ex})")
    try:
        btc, btc_close = bitcoin()
        if btc:
            print(f"  extra BTC-EUR: {btc['price']}")
            rijen.append(btc)
            closes["BTC-EUR"] = btc_close
    except Exception as ex:  # noqa: BLE001
        print(f"  bitcoin overgeslagen ({ex})")
    return rijen, closes


def historie_nodig(asof):
    """De grafiekdata (groot bestand) alleen vernieuwen bij een nieuwe beursdag,
    bij de avond-update of handmatig (VOLLEDIG=true). Zo blijft de repo klein bij de uurlijkse updates."""
    if os.environ.get("VOLLEDIG", "").lower() == "true" or not HIST.exists():
        return True
    try:
        dagen = json.loads(HIST.read_text()).get("days") or []
        return not dagen or dagen[-1] != asof
    except Exception:  # noqa: BLE001
        return True


def main():
    tickers = lees_tickers()
    ai = set(lees_tickers(AI_FILE))
    print(f"{len(tickers)} tickers")
    data = download(tickers)

    # Fundamentele data (info dagelijks, jaarcijfers wekelijks) uit de cache, aangevuld waar nodig
    cache = fund.load_cache()
    fund.refresh(cache, tickers)

    rijen, prijzen, alle_closes = [], {}, {}
    rf, fx = fund.market_data(cache)
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
            info = (cache.get(t) or {}).get("info")
            if not info or not info.get("marketCap"):
                print(f"  {t}: geen info")
                continue
            prijzen[t] = stats["price"]
            alle_closes[t] = df["Close"].dropna()
            # Beurswaarde (omgerekend naar USD voor een eerlijke rangschikking) en K/W, meegeschaald
            # met de koers sinds het ophalen van de info
            p_info = info.get("currentPrice") or info.get("regularMarketPrice")
            schaal = stats["price"] / p_info if (p_info and stats["price"]) else 1.0
            pe = schoon((info.get("trailingPE") or 0) * schaal, 1)
            mcap_q, usd = fund.market_cap_quote(info, stats["price"]), fund.usd_rate(info, fx)
            if not mcap_q or not usd:
                print(f"  {t}: beurswaarde of wisselkoers onbekend")
                continue
            rijen.append({
                "ticker": t,
                "name": info.get("shortName") or info.get("longName") or t,
                "sector": info.get("sector") or ("Financial Services" if t == "BRK-B" else "Overig"),
                "marketCap": int(mcap_q * usd),
                "currency": info.get("currency") or "USD",
                "pe": pe if pe and pe > 0 else None,
                "ai": t in ai,
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
    extras, extra_closes = haal_extras()
    uit["extras"] = extras

    # Waarderingsengine: analyseert het hele universum (voor sectorvergelijking); op de site alleen het advies
    analyse = None
    try:
        analyse = fund.run_engine(cache, prijzen, alle_closes, pd.Timestamp(asof).date(), rf, fx)
    except Exception as e:  # noqa: BLE001
        print(f"waarderingsengine mislukt: {e}")
    for r in rijen:
        r["rating"] = (analyse or {}).get(r["ticker"], {}).get("rating", "NO RATING")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(uit, ensure_ascii=False, indent=1) + "\n")
    nieuwe_dag = historie_nodig(uit["asof"])
    if analyse and (nieuwe_dag or not fund.ANALYSIS.exists()):
        fund.write_analysis(analyse, uit["asof"])
    if nieuwe_dag:
      try:
        closes = {r["ticker"]: slotkoersen(data, r["ticker"]) for r in rijen}
        closes.update(extra_closes)
        schrijf_historie(data.index, closes, pd.Timestamp(asof))
      except Exception as e:  # noqa: BLE001
        print(f"historie mislukt: {e}")
    else:
        print("historie ongewijzigd (zelfde beursdag)")
    print(f"{len(rijen)} rijen geschreven naar {OUT} (slotkoersen {uit['asof']})")


if __name__ == "__main__":
    main()
