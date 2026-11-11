"""Haalt koersen op via yfinance en schrijft docs/data.json.

Gebruik: python update.py
"""
import csv
import html as html_lib
import io
import json
import os
import re
import urllib.request
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import fundamentals as fund
from engine.uitleg import waarom
from indicatoren import EMA_PERIODES, ema
import grondstoffen
import macro
import nieuws

ROOT = Path(__file__).parent
TICKERS_FILE = ROOT / "tickers.txt"
SP500_FILE = ROOT / "sp500.txt"   # huidige S&P 500-samenstelling (bijgewerkt bij elke run, terugval op dit bestand)
SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
SP500_SECTOR_FILE = ROOT / "sp500_sectoren.json"  # officiële GICS-sector per S&P-lid (terugval als Yahoo geen sector geeft)
# GICS-sectornamen -> de sectornamen die Yahoo (en de site) gebruikt
GICS_NAAR_YAHOO = {
    "Information Technology": "Technology", "Health Care": "Healthcare", "Financials": "Financial Services",
    "Consumer Discretionary": "Consumer Cyclical", "Consumer Staples": "Consumer Defensive",
    "Communication Services": "Communication Services", "Energy": "Energy", "Industrials": "Industrials",
    "Materials": "Basic Materials", "Utilities": "Utilities", "Real Estate": "Real Estate",
}
AI_FILE = ROOT / "ai.txt"
OUT = ROOT / "docs" / "data.json"
HIST = ROOT / "docs" / "history.json"
GROND_HIST = ROOT / "docs" / "grond_hist.json"  # grafieken grondstoffen
MARKT_HIST = ROOT / "docs" / "markt_hist.json"  # blijvende dagkoersen WEBN/VALL/Bitcoin (wordt nooit ingekort)
# Wereld = de top 100 beursbedrijven van companiesmarketcap.com (alleen bedrijven, geen ETF's/grondstoffen).
CMC_URL = "https://companiesmarketcap.com/?download=csv"
CMC_FILE = ROOT / "cmc.json"   # laatst opgehaalde top (terugval als de site niet bereikbaar is)
CMC_TOP = 100
# companiesmarketcap gebruikt soms een OTC-symbool; Yahoo-ticker van de echte beurs
CMC_TICKER = {"TCEHY": "0700.HK", "XIACF": "1810.HK", "GMBXF": "GMEXICOB.MX", "GLCNF": "GLEN.L", "KBCSF": "KBC.BR",
              "ENR.F": "ENR.DE"}

# Extra koersen bovenaan de site (in euro's).
EXTRAS = [
    # "na" = zelfde ETF op beurzen die na de Xetra-slotveiling (±17:35) doorhandelen tot 22:00
    {"ticker": "WEBN.DE", "label": "WEBN", "beurs": "Xetra", "na": ["WEBN.MU", "WEBN.DU"]},
    {"ticker": "VALL.AS", "label": "VALL", "beurs": "Amsterdam"},
]
# Beursindexen onder WEBN/VALL/Bitcoin (in punten; tellen niet mee in "Markt vandaag")
INDICES = [
    {"ticker": "^IXIC", "label": "Nasdaq", "beurs": "Composite · VS"},
    {"ticker": "^AEX", "label": "AEX", "beurs": "Amsterdam"},
    {"ticker": "^GSPC", "label": "S&P 500", "beurs": "VS"},
]
BITVAVO = "https://api.bitvavo.com/v2"

# Grote assets naast aandelen (zoals "assets by market cap"). Edelmetalen: prijs (USD/troy ounce) ×
# geschatte bovengrondse voorraad. Bronnen/aannames: goud ±216.265 ton (World Gold Council, eind 2024),
# zilver ±1.751.000 ton (gangbare schatting). 1 ton = 32.150,75 troy ounce.
OZ_PER_TONNE = 32150.7466
ASSETS = [
    {"ticker": "GC=F", "name": "Goud", "kind": "metaal", "icon": "🥇", "ounces": 216265 * OZ_PER_TONNE},
    {"ticker": "SI=F", "name": "Zilver", "kind": "metaal", "icon": "🥈", "ounces": 1751000 * OZ_PER_TONNE},
    {"ticker": "BTC-USD", "name": "Bitcoin", "kind": "crypto", "icon": "₿"},
    {"ticker": "ETH-USD", "name": "Ethereum", "kind": "crypto", "icon": "Ξ"},
]


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

    # Rendement per volledig kalenderjaar: slot laatste beursdag vorig jaar -> slot laatste beursdag dat jaar
    jaren = {}
    for jaar in range(eerste.year + 1, laatste_datum.year):
        begin = close[close.index < pd.Timestamp(year=jaar, month=1, day=1, tz=laatste_datum.tz)]
        eind = close[close.index < pd.Timestamp(year=jaar + 1, month=1, day=1, tz=laatste_datum.tz)]
        if begin.empty or eind.empty or begin.index[-1].year != jaar - 1 or eind.index[-1].year != jaar:
            continue
        if begin.index[-1] < pd.Timestamp(year=jaar - 1, month=12, day=20, tz=laatste_datum.tz):
            continue  # geen koers vlak voor de jaarwisseling (bv. pas later genoteerd)
        v = pct(float(eind.iloc[-1]), float(begin.iloc[-1]))
        if v is not None:
            jaren[str(jaar)] = v

    return {
        "price": schoon(laatste),
        "jaren": jaren or None,
        "d1": pct(laatste, vorige),
        "w1": periode(pd.DateOffset(days=7)),
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
    """Schrijft docs/history.json: dagkoersen van 1 jaar en weekkoersen van 5 jaar voor de grafieken,
    plus EMA 50/200 (berekend op dagkoersen) als d50/d200 (dagdatums) en w50/w200 (weekdatums).

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
            rij = {"d": reeks(close, dagen), "w": reeks(close, weken)}
            for n in EMA_PERIODES:  # EMA over de volledige ~5 jaar dagkoersen, daarna op dag- en weekdatums gezet
                e = ema(close, n).dropna()
                if not e.empty:
                    rij[f"d{n}"] = reeks(e, dagen)
                    rij[f"w{n}"] = reeks(e, weken)
            uit["series"][t] = rij
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


def hist(close, days=5 * 366 + 10):
    """Slotkoersen van de laatste ~5 jaar als [[datum, koers], …] (voor D/W/M/YTD/Y en per jaar op de site)."""
    c = close.dropna()
    c = c[c.index >= c.index[-1] - pd.Timedelta(days=days)]
    return [[pd.Timestamp(d).strftime("%Y-%m-%d"), schoon(v, 4)] for d, v in c.items()]


def spark(close, n=30):
    """Laatste n slotkoersen voor een mini-grafiekje."""
    return [schoon(v, 4) for v in close.dropna().iloc[-n:].tolist()]


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
            "currency": "EUR", "spark": spark(df["Close"]), "h": hist(df["Close"]), **stats}, df["Close"]


TZ_NL = "Europe/Amsterdam"


def intraday_reeks(close, label):
    """Koersen binnen de dag als {"date": laatste handelsdag, "pts": [["UU:MM", koers], …]} (Nederlandse tijd)."""
    c = close.dropna()
    if c.empty:
        return None
    idx = pd.DatetimeIndex(c.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    c.index = idx.tz_convert(TZ_NL)
    dag = c.index[-1].date()
    c = c[[d.date() == dag for d in c.index]]
    if len(c) < 2:
        return None
    print(f"  intraday {label}: {len(c)} punten op {dag} ({c.index[0]:%H:%M}–{c.index[-1]:%H:%M})")
    return {"date": str(dag), "pts": [[d.strftime("%H:%M"), schoon(v, 4)] for d, v in c.items()]}


def week_reeks(close, label, stap="15min"):
    """Koersen van de laatste ±7 dagen, per `stap`: {"pts": [["DD-MM UU:MM", koers], …]} (Nederlandse tijd)."""
    c = close.dropna()
    if c.empty:
        return None
    idx = pd.DatetimeIndex(c.index)
    c.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(TZ_NL)
    c = c[c.index > c.index[-1] - pd.Timedelta(days=7)]
    if stap:
        c = c.resample(stap).last().dropna()
    if len(c) < 2:
        return None
    print(f"  week {label}: {len(c)} punten ({c.index[0]:%d-%m %H:%M} – {c.index[-1]:%d-%m %H:%M})")
    return {"pts": [[d.strftime("%d-%m %H:%M"), schoon(v, 4)] for d, v in c.items()]}


def intraday_etfs(tickers):
    """5-minutenkoersen van de laatste handelsdag, en per 15 minuten van de laatste 5 handelsdagen (Yahoo).
    Geeft ({ticker: dag}, {ticker: week})."""
    uit, week = {}, {}
    try:
        data = yf.download(tickers, period="5d", interval="5m", auto_adjust=True, group_by="ticker", progress=False)
        for t in tickers:
            try:
                r = intraday_reeks(data[t]["Close"], t)
                if r:
                    uit[t] = r
                w = week_reeks(data[t]["Close"], t)
                if w:
                    week[t] = w
            except Exception as e:  # noqa: BLE001
                print(f"  intraday {t}: {e}")
    except Exception as e:  # noqa: BLE001
        print(f"intraday download mislukt: {e}")
    return uit, week


NA_BEURS = {"MU": "gettex", "DU": "Düsseldorf"}
NA_VANAF = "17:40"   # pas na de slotveiling van Xetra; overdag blijft de hoofdbeurs leidend


def kies_na_koers(dag, laatst, reeksen):
    """Na sluiting: de nieuwste koers van dezelfde ETF op een andere beurs, als die op dezelfde dag minstens
    10 minuten na de laatste koers van de hoofdbeurs is. dag/laatst = datum + "UU:MM" van de hoofdbeurs (NL-tijd);
    reeksen = {ticker: Close-reeks}. Geeft {"p", "t", "beurs"} of None."""
    grens = pd.Timestamp(f"{dag} {laatst}", tz=TZ_NL) + pd.Timedelta(minutes=10)
    beste = None
    for t, c in reeksen.items():
        c = _nl(c.dropna())
        if c.empty:
            continue
        tijd, prijs = c.index[-1], float(c.iloc[-1])
        if str(tijd.date()) != dag or tijd < grens or tijd.strftime("%H:%M") < NA_VANAF or not prijs > 0:
            continue
        if beste is None or tijd > beste[0]:
            beste = (tijd, prijs, NA_BEURS.get(t.rsplit(".", 1)[-1], t))
    if not beste:
        return None
    return {"p": schoon(beste[1], 4), "t": beste[0].strftime("%H:%M"), "beurs": beste[2]}


def na_koers(e, intra):
    """Haalt de avondkoers (zie kies_na_koers) voor extra e op via yfinance."""
    i = intra.get(e["ticker"])
    if not e.get("na") or not i or not i.get("pts"):
        return None
    try:
        data = yf.download(e["na"], period="1d", interval="5m", auto_adjust=True, group_by="ticker", progress=False)
        reeksen = {t: (data[t] if len(e["na"]) > 1 else data)["Close"] for t in e["na"]}
        return kies_na_koers(i["date"], i["pts"][-1][0], reeksen)
    except Exception as ex:  # noqa: BLE001
        print(f"  na-koers {e['ticker']}: {ex}")
        return None


INTRA = ROOT / "docs" / "intra.json"   # koersen binnen de dag van alle aandelen (alleen geladen bij 1D/1W)


# Grondstoffen met koersen binnen de dag (grafiek 1D/1W op het Overzicht): goud, zilver, Brent, aardgas.
# Alleen tickers zonder omrekening (geen centen); index.html: GI.
INTRA_GROND = ["GC=F", "SI=F", "BZ=F", "NG=F"]


def intraday_alle(tickers, budget_s=240):
    """Per aandeel: 1D = per 15 min op de laatste handelsdag, 1W = per 30 min over ±7 dagen (Nederlandse tijd).
    Eén download in blokken; duurt het te lang, dan stopt het en blijft de rest van de vorige keer staan."""
    try:
        oud = json.loads(INTRA.read_text())
    except Exception:  # noqa: BLE001
        oud = {}
    uit, start = {}, time.time()
    for i in range(0, len(tickers), 150):
        if time.time() - start > budget_s:
            print(f"intraday: tijdsbudget op na {i} aandelen; rest van de vorige update")
            break
        blok = tickers[i:i + 150]
        try:
            data = yf.download(blok, period="5d", interval="15m", auto_adjust=True, group_by="ticker",
                               progress=False, threads=True)
        except Exception as e:  # noqa: BLE001
            print(f"intraday blok {i}: {e}")
            continue
        for t in blok:
            try:
                c = (data[t] if len(blok) > 1 else data)["Close"].dropna()
                d = intraday_reeks_stil(c)
                w = week_reeks_stil(c)
                if d or w:
                    uit[t] = {"d": d, "w": w}
            except Exception:  # noqa: BLE001
                pass
    for t in tickers:
        if t not in uit and t in oud:
            uit[t] = oud[t]
    INTRA.write_text(json.dumps(uit, separators=(",", ":")) + "\n")
    print(f"intraday: {len(uit)} van {len(tickers)} aandelen ({INTRA.stat().st_size // 1024} kB)")


def _nl(c):
    idx = pd.DatetimeIndex(c.index)
    c.index = (idx.tz_localize("UTC") if idx.tz is None else idx).tz_convert(TZ_NL)
    return c


def intraday_reeks_stil(c):
    if c.empty:
        return None
    c = _nl(c)
    dag = c.index[-1].date()
    c = c[[x.date() == dag for x in c.index]]
    return {"date": str(dag), "pts": [[x.strftime("%H:%M"), schoon(v, 4)] for x, v in c.items()]} if len(c) >= 2 else None


def week_reeks_stil(c):
    if c.empty:
        return None
    c = _nl(c)
    c = c[c.index > c.index[-1] - pd.Timedelta(days=7)].resample("30min").last().dropna()
    return {"pts": [[x.strftime("%d-%m %H:%M"), schoon(v, 4)] for x, v in c.items()]} if len(c) >= 2 else None


def intraday_bitcoin():
    """Bitcoin per 5 minuten over de laatste 24 uur (Bitvavo)."""
    candles = http_json(f"{BITVAVO}/BTC-EUR/candles?interval=5m&limit=288")
    if not candles:
        return None
    rij = sorted((int(c[0]), float(c[4])) for c in candles)
    idx = pd.to_datetime([r[0] for r in rij], unit="ms", utc=True).tz_convert(TZ_NL)
    pts = [[d.strftime("%d-%m %H:%M"), schoon(v, 2)] for d, (_, v) in zip(idx, rij)]
    print(f"  intraday BTC-EUR: {len(pts)} punten ({pts[0][0]} – {pts[-1][0]})")
    return {"date": str(idx[-1].date()), "pts": pts, "h24": True}


def week_bitcoin():
    """Bitcoin per uur over de laatste 7 dagen (Bitvavo)."""
    candles = http_json(f"{BITVAVO}/BTC-EUR/candles?interval=1h&limit=168")
    if not candles:
        return None
    rij = sorted((int(c[0]), float(c[4])) for c in candles)
    s = pd.Series([v for _, v in rij], index=pd.to_datetime([t for t, _ in rij], unit="ms", utc=True))
    return week_reeks(s, "BTC-EUR", stap=None)


def haal_extras():
    """Koersen voor de balk bovenaan: ETF's via yfinance, bitcoin via Bitvavo."""
    rijen, closes = reeksen(EXTRAS)
    try:
        btc, btc_close = bitcoin()
        if btc:
            print(f"  extra BTC-EUR: {btc['price']}")
            try:
                btc["i"] = intraday_bitcoin()
                btc["w"] = week_bitcoin()
            except Exception as ex:  # noqa: BLE001
                print(f"  intraday bitcoin: {ex}")
            rijen.append(btc)
            closes["BTC-EUR"] = btc_close
    except Exception as ex:  # noqa: BLE001
        print(f"  bitcoin overgeslagen ({ex})")
    return rijen, closes


def reeksen(lijst, index=False):
    """Dag-, week- en 5-jaarskoersen (+ statistieken) voor een lijst tickers via yfinance."""
    rijen, closes = [], {}
    intra, week = intraday_etfs([e["ticker"] for e in lijst])
    try:
        data = yf.download([e["ticker"] for e in lijst], period="5y", interval="1d",
                           auto_adjust=True, group_by="ticker", progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"download {[e['ticker'] for e in lijst]} mislukt: {e}")
        data = None
    for e in lijst:
        try:
            df = data[e["ticker"]] if data is not None else None
            na = na_koers(e, intra) if df is not None else None
            if na and pd.Timestamp(df["Close"].dropna().index[-1]).date() == pd.Timestamp(intra[e["ticker"]]["date"]).date():
                df = df.copy()   # avondkoers als laatste koers van vandaag (zoals bij Bitcoin de live prijs)
                df.loc[df["Close"].dropna().index[-1], "Close"] = na["p"]
                print(f"  extra {e['ticker']}: na sluiting {na['p']} om {na['t']} ({na['beurs']})")
            else:
                na = None
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
            stats["price"] = schoon(df["Close"].dropna().iloc[-1], 4)   # 4 decimalen: telt mee in het portfolio
            e = {k: v for k, v in e.items() if k != "na"}
            if na:
                e["na"] = na
            rijen.append({**e, "name": naam, "currency": "PT" if index else (info.get("currency") or "EUR"),
                          "spark": spark(df["Close"]), "h": hist(df["Close"]), "i": intra.get(e["ticker"]), "w": week.get(e["ticker"]), **stats})
            closes[e["ticker"]] = df["Close"]
        except Exception as ex:  # noqa: BLE001
            print(f"  extra {e['ticker']}: overgeslagen ({ex})")
    return rijen, closes


def bewaar_markt_hist(extras):
    """Voegt de nieuwe dagkoersen van WEBN, VALL en Bitcoin toe aan een blijvend archief, zodat oude jaren
    (bv. 2026 in 2030) niet verdwijnen als de bron maar een paar jaar teruggeeft. Niets wordt gewist."""
    try:
        archief = json.loads(MARKT_HIST.read_text()) if MARKT_HIST.exists() else {}
    except Exception:  # noqa: BLE001
        archief = {}
    for x in extras:
        t = x.get("ticker")
        oud = {d: v for d, v in archief.get(t, [])}
        for d, v in x.get("h") or []:
            if v is not None:
                oud[d] = v  # nieuwste waarde voor een datum wint
        if oud:
            archief[t] = [[d, oud[d]] for d in sorted(oud)]
            x["h"] = archief[t]
    MARKT_HIST.write_text(json.dumps(archief, separators=(",", ":")) + "\n")
    print("markt-archief: " + ", ".join(f"{t} {v[0][0]}→{v[-1][0]} ({len(v)})" for t, v in archief.items() if v))


def haal_assets():
    """Goud, zilver, bitcoin en ethereum met marktwaarde in USD en koersveranderingen."""
    uit = []
    try:
        data = yf.download([a["ticker"] for a in ASSETS], period="5y", interval="1d",
                           auto_adjust=True, group_by="ticker", progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"assets download mislukt: {e}")
        return uit
    for a in ASSETS:
        try:
            stats = bereken(data[a["ticker"]])
            if not stats:
                continue
            stats.pop("_date")
            if a.get("ounces"):
                mcap = stats["price"] * a["ounces"]
            else:
                info = yf.Ticker(a["ticker"]).info or {}
                p_info = info.get("regularMarketPrice") or info.get("previousClose")
                mc = info.get("marketCap")
                mcap = mc * stats["price"] / p_info if (mc and p_info) else mc
            if not mcap:
                continue
            uit.append({"ticker": a["ticker"], "name": a["name"], "kind": a["kind"], "icon": a["icon"],
                        "marketCap": int(mcap), **stats})
            print(f"  asset {a['name']}: ${mcap / 1e12:.2f} bln")
        except Exception as e:  # noqa: BLE001
            print(f"  asset {a['ticker']}: overgeslagen ({e})")
    return uit


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


_RECHTSVORM = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|ag|se|sa|nv|n v|ab|asa|as|"
                         r"spa|s p a|holdings?|group|groep|the|class [a-z]|adr|ads)\b")


def bedrijfssleutel(naam):
    """Naam zonder rechtsvorm/leestekens: om dubbele noteringen van hetzelfde bedrijf te herkennen."""
    n = re.sub(r"[^a-z0-9 ]", " ", (naam or "").lower())
    return " ".join(_RECHTSVORM.sub(" ", n).split())


def cmc_top(n=CMC_TOP):
    """[(ticker, naam, beurswaarde USD, land)] van de n grootste beursbedrijven volgens companiesmarketcap.com.
    Mislukt ophalen of is de lijst onlogisch: de vorige lijst."""
    try:
        req = urllib.request.Request(CMC_URL, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rijen = list(csv.DictReader(io.StringIO(r.read().decode("utf-8-sig"))))
        top = []
        for x in rijen:
            sym, cap = (x.get("Symbol") or "").strip(), float(x.get("marketcap") or 0)
            if sym and cap > 0:
                top.append([CMC_TICKER.get(sym, sym), html_lib.unescape((x.get("Name") or sym).strip()), cap,
                            (x.get("country") or "").strip() or None])
        top.sort(key=lambda x: -x[2])
        if len(top) >= 1000 and top[n - 1][2] > 20e9:
            top = top[:n]
            CMC_FILE.write_text(json.dumps(top, ensure_ascii=False, indent=0) + "\n")
            print(f"companiesmarketcap: top {n} opgehaald (nr. {n}: {top[-1][1]}, ${top[-1][2] / 1e9:.0f} mld)")
            return top
        print(f"companiesmarketcap: onlogische lijst ({len(top)} bedrijven), vorige gebruikt")
    except Exception as e:  # noqa: BLE001
        print(f"companiesmarketcap ophalen mislukt ({e}), vorige lijst gebruikt")
    try:
        return json.loads(CMC_FILE.read_text())[:n]
    except Exception:  # noqa: BLE001
        return []


# Beurscode van Yahoo (info["exchange"]) -> leesbare naam
BEURS_CODE = {
    "NMS": "Nasdaq", "NGM": "Nasdaq", "NCM": "Nasdaq", "NAS": "Nasdaq",
    "NYQ": "NYSE", "NYS": "NYSE", "ASE": "NYSE American", "PCX": "NYSE Arca", "BTS": "Cboe",
    "AMS": "Amsterdam", "PAR": "Parijs", "BRU": "Brussel", "LIS": "Lissabon", "MCE": "Madrid", "MIL": "Milaan",
    "GER": "Xetra", "ETR": "Xetra", "FRA": "Frankfurt", "EBS": "Zürich", "VTX": "Zürich", "LSE": "Londen",
    "CPH": "Kopenhagen", "STO": "Stockholm", "HEL": "Helsinki", "OSL": "Oslo", "VIE": "Wenen",
    "HKG": "Hongkong", "SHH": "Shanghai", "SHZ": "Shenzhen", "KSC": "Seoel", "KOE": "Seoel", "TAI": "Taiwan",
    "JPX": "Tokio", "TYO": "Tokio", "NSI": "India (NSE)", "BSE": "India (BSE)", "SAU": "Saoedi-Arabië",
    "ASX": "Sydney", "TOR": "Toronto", "SAO": "São Paulo", "ADX": "Abu Dhabi",
}
# Terugval op het achtervoegsel van de ticker (geen achtervoegsel = VS, beurs onbekend)
BEURS_SUFFIX = {
    "AS": "Amsterdam", "PA": "Parijs", "BR": "Brussel", "LS": "Lissabon", "MC": "Madrid", "MI": "Milaan",
    "DE": "Xetra", "F": "Frankfurt", "SW": "Zürich", "L": "Londen", "CO": "Kopenhagen", "ST": "Stockholm",
    "HE": "Helsinki", "OL": "Oslo", "VI": "Wenen", "HK": "Hongkong", "SS": "Shanghai", "SZ": "Shenzhen",
    "KS": "Seoel", "TW": "Taiwan", "T": "Tokio", "NS": "India (NSE)", "BO": "India (BSE)",
    "SR": "Saoedi-Arabië", "AX": "Sydney", "TO": "Toronto", "SA": "São Paulo", "AE": "Abu Dhabi",
}


def beurs_naam(ticker, info):
    """Leesbare naam van de beurs waar deze notering handelt (bv. 'Amsterdam', 'Nasdaq')."""
    naam = BEURS_CODE.get((info or {}).get("exchange") or "")
    if naam:
        return naam
    if "." in ticker:
        return BEURS_SUFFIX.get(ticker.rsplit(".", 1)[1].upper())
    return "VS"


def usd_beurswaarde(info, fx):
    """Beurswaarde in USD op basis van de (dagelijks opgehaalde) info."""
    p = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    mc, usd = fund.market_cap_quote(info, p), fund.usd_rate(info, fx)
    return mc * usd if (mc and usd) else None


def sp500_tickers():
    """Huidige S&P 500-leden (Yahoo-notatie: BRK.B -> BRK-B). Lukt ophalen niet, dan het vorige bestand."""
    try:
        req = urllib.request.Request(SP500_URL, headers={"User-Agent": "investmarket/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rijen = list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
        sym = sorted({(x.get("Symbol") or "").strip().replace(".", "-") for x in rijen} - {""})
        sectoren = {(x.get("Symbol") or "").strip().replace(".", "-"): GICS_NAAR_YAHOO.get((x.get("GICS Sector") or "").strip())
                    for x in rijen}
        if len(sym) >= 480:  # anders onvolledig antwoord: niet gebruiken
            SP500_SECTOR_FILE.write_text(json.dumps({k: v for k, v in sorted(sectoren.items()) if k and v},
                                                    indent=0) + "\n")
            SP500_FILE.write_text("# S&P 500-leden, bron: github.com/datasets/s-and-p-500-companies "
                                  f"(opgehaald {datetime.now(timezone.utc):%Y-%m-%d})\n" + "\n".join(sym) + "\n")
            print(f"S&P 500: {len(sym)} leden opgehaald")
            return sym
        print(f"S&P 500: onvolledige lijst ({len(sym)}), vorige gebruikt")
    except Exception as e:  # noqa: BLE001
        print(f"S&P 500 ophalen mislukt ({e}), vorige lijst gebruikt")
    return lees_tickers(SP500_FILE) if SP500_FILE.exists() else []


# Samenstelling van indexen voor "Stijgers & dalers per index" (Wikipedia houdt deze tabellen bij).
INDEX_BRONNEN = {
    "Nasdaq 100": {"url": "https://en.wikipedia.org/wiki/Nasdaq-100", "file": ROOT / "nasdaq100.json", "min": 95,
                   "max": 110, "suffix": "",
                   # officiële lijst van Nasdaq zelf; Wikipedia als reserve
                   "api": "https://api.nasdaq.com/api/quote/list-type/nasdaq100"},
    "AEX": {"url": "https://en.wikipedia.org/wiki/AEX_index", "file": ROOT / "aex.json", "min": 20, "max": 30,
            "suffix": ".AS"},
}


def index_leden(naam):
    """{ticker: bedrijfsnaam} van een index. Lukt ophalen niet of is de lijst onlogisch: vorige lijst."""
    b = INDEX_BRONNEN[naam]
    if b.get("api"):
        try:
            req = urllib.request.Request(b["api"], headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
                "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
                "Referer": "https://www.nasdaq.com/"})
            with urllib.request.urlopen(req, timeout=30) as r:
                js = json.loads(r.read().decode("utf-8"))
            rows = ((js.get("data") or {}).get("data") or {}).get("rows") or []
            leden = {str(x.get("symbol", "")).strip().replace(".", "-").replace("/", "-"): str(x.get("companyName", "")).strip()
                     for x in rows if x.get("symbol")}
            if b["min"] <= len(leden) <= b["max"]:
                b["file"].write_text(json.dumps(leden, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
                print(f"{naam}: {len(leden)} leden opgehaald (Nasdaq)")
                return leden
            print(f"{naam}: Nasdaq-lijst onvolledig ({len(leden)})")
        except Exception as e:  # noqa: BLE001
            print(f"{naam}: Nasdaq-lijst mislukt ({e})")
    try:
        req = urllib.request.Request(b["url"], headers={"User-Agent": "investmarket/1.0 (koersoverzicht)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8")
        tabellen = pd.read_html(io.StringIO(html))
        for tab in tabellen:
            if isinstance(tab.columns, pd.MultiIndex):
                tab.columns = [" ".join(str(x) for x in c) for c in tab.columns]
            cols = [str(c) for c in tab.columns]
            tc = next((c for c in cols if "ticker" in c.lower() or c.lower() == "symbol"), None)
            nc = next((c for c in cols if any(w in c.lower() for w in ("company", "security", "name"))), None)
            if not tc or not nc or not (b["min"] <= len(tab) <= b["max"]):
                continue
            leden = {}
            for _, rij in tab.iterrows():
                t = str(rij[tc]).strip().split()[0] if str(rij[tc]).strip() else ""
                if not t or t == "nan":
                    continue
                if b["suffix"]:   # bv. AEX: "ABN.AS" staat er al zo; "ABN" krijgt ".AS"
                    t = t if t.upper().endswith(b["suffix"].upper()) else t.replace(".", "-") + b["suffix"]
                else:             # VS: BRK.B -> BRK-B (Yahoo-notatie)
                    t = t.replace(".", "-")
                leden[t] = str(rij[nc]).strip()
            if b["min"] <= len(leden) <= b["max"]:
                b["file"].write_text(json.dumps(leden, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
                print(f"{naam}: {len(leden)} leden opgehaald")
                return leden
        print(f"{naam}: geen passende tabel gevonden, vorige lijst gebruikt. Tabellen: "
              + "; ".join(f"{len(t)} rijen {list(map(str, t.columns))[:6]}" for t in tabellen if len(t) >= 10))
    except Exception as e:  # noqa: BLE001
        print(f"{naam} ophalen mislukt ({e}), vorige lijst gebruikt")
    try:
        return json.loads(b["file"].read_text())
    except Exception:  # noqa: BLE001
        return {}


def main():
    sp500 = sp500_tickers()
    try:
        gics = json.loads(SP500_SECTOR_FILE.read_text())
    except Exception:  # noqa: BLE001
        gics = {}
    # De vier lijsten: Wereld (top 100 companiesmarketcap), S&P 500, Nasdaq 100 en AEX, elk compleet.
    leden = {naam: index_leden(naam) for naam in INDEX_BRONNEN}
    top = cmc_top()
    # Staat een bedrijf uit de top 100 ook in de AEX of Nasdaq 100 (bv. ASML), gebruik dan die notering
    via_naam = {bedrijfssleutel(nm): t for naam in ("AEX", "Nasdaq 100") for t, nm in leden[naam].items()}
    cmc = {}
    for t, nm, cap, land in top:
        t = via_naam.get(bedrijfssleutel(nm), t) if t not in sp500 else t
        cmc.setdefault(t, {"name": nm, "cap": cap, "country": land})
    lijst_def = {"Wereld": list(cmc), "S&P 500": list(sp500)}
    for naam in INDEX_BRONNEN:
        lijst_def[naam] = list(leden[naam])
    namen = {t: nm for naam in INDEX_BRONNEN for t, nm in leden[naam].items()}
    tickers = list(dict.fromkeys(t for lijst in lijst_def.values() for t in lijst))
    ai = set(lees_tickers(AI_FILE))
    print(f"{len(tickers)} aandelen (" + ", ".join(f"{k} {len(v)}" for k, v in lijst_def.items()) + ")")

    cache = fund.load_cache()
    fund.refresh(cache, [], info_only=tickers)
    rf, fx = fund.market_data(cache)
    data = download(tickers)
    fund.refresh(cache, tickers)
    # Geen sector van Yahoo? Dan de officiële GICS-sector uit de S&P 500-lijst (ook voor de waarderingsengine)
    for t, c in cache.items():
        i = (c or {}).get("info")
        if i is not None and not i.get("sector") and gics.get(t):
            i["sector"] = gics[t]

    lid = {k: set(v) for k, v in lijst_def.items()}
    rijen, prijzen, alle_closes = [], {}, {}
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
            info = (cache.get(t) or {}).get("info") or {}
            usd = fund.usd_rate(info, fx) if info else None
            if not usd:
                cur = "EUR" if t.endswith(".AS") else ("USD" if "." not in t else None)
                usd = 1.0 if cur == "USD" else (fx.get("EURUSD=X") if cur == "EUR" else None)
            if not usd:
                print(f"  {t}: valuta onbekend")
                continue
            # Beurswaarde: voor de top 100 die van companiesmarketcap, anders van Yahoo (meegeschaald met de koers)
            c = cmc.get(t)
            if c:
                cap = c["cap"]
            else:
                mcap_q = fund.market_cap_quote(info, stats["price"]) if info.get("marketCap") else None
                cap = mcap_q * usd if mcap_q else None
            if not cap:
                print(f"  {t}: beurswaarde onbekend")
                continue
            prijzen[t] = stats["price"]
            alle_closes[t] = df["Close"].dropna()
            p_info = info.get("currentPrice") or info.get("regularMarketPrice")
            schaal = stats["price"] / p_info if (p_info and stats["price"]) else 1.0
            pe = schoon((info.get("trailingPE") or 0) * schaal, 1)
            rij = {
                "ticker": t,
                "name": (c or {}).get("name") or info.get("shortName") or info.get("longName") or namen.get(t) or t,
                "country": (c or {}).get("country") or info.get("country"),
                "sector": info.get("sector") or gics.get(t) or ("Financial Services" if t == "BRK-B" else "Overig"),
                "marketCap": int(cap),
                "currency": info.get("currency") or ("EUR" if t.endswith(".AS") else "USD"),
                "beurs": beurs_naam(t, info),
                "usd": schoon(usd, 8),  # koers (beursvaluta) -> USD, voor de portfolio
                "pe": pe if pe and pe > 0 else None,
                "ai": t in ai,
                **stats,
            }
            for k, naam in (("w", "Wereld"), ("sp", "S&P 500"), ("nq", "Nasdaq 100"), ("aex", "AEX")):
                if t in lid[naam]:
                    rij[k] = True
            rijen.append(rij)
        except Exception as e:  # noqa: BLE001
            print(f"  {t}: overgeslagen ({e})")

    if not rijen:
        raise SystemExit("Geen enkele ticker gelukt; data.json niet overschreven.")
    # Rangschikking op beurswaarde (zoals companiesmarketcap)
    rijen.sort(key=lambda r: r["marketCap"], reverse=True)
    for i, r in enumerate(rijen, 1):
        r["rank"] = i
    bekend = {r["ticker"] for r in rijen}
    lijsten = {k: [t for t in v if t in bekend] for k, v in lijst_def.items()}
    ontbreekt = {k: [t for t in v if t not in bekend] for k, v in lijst_def.items()}
    print(f"{len(rijen)} aandelen met koers. Lijsten: " + ", ".join(f"{k} {len(v)}/{len(lijst_def[k])}"
                                                                for k, v in lijsten.items()))
    for k, v in ontbreekt.items():
        if v:
            print(f"  {k} zonder koers: {', '.join(v)}")
    asof = max(r["_date"] for r in rijen)
    for r in rijen:
        r.pop("_date")

    uit = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": pd.Timestamp(asof).strftime("%Y-%m-%d"),
        "rows": rijen,
    }
    extras, extra_closes = haal_extras()
    bewaar_markt_hist(extras)
    uit["extras"] = extras
    uit["lijsten"], uit["lijst_koersen"] = lijsten, {}
    try:
        intraday_alle([r["ticker"] for r in rijen] + INTRA_GROND)
    except Exception as e:  # noqa: BLE001
        print(f"intraday mislukt: {e}")
    try:
        indices, index_closes = reeksen(INDICES, index=True)
        uit["indices"] = indices
        extra_closes.update(index_closes)
    except Exception as e:  # noqa: BLE001
        print(f"indexen mislukt: {e}")
    uit["assets"] = haal_assets()
    try:
        uit["commodities"], g_hist = grondstoffen.haal_grondstoffen(bereken, spark)
        if g_hist:
            GROND_HIST.write_text(json.dumps(g_hist, separators=(",", ":")) + "\n")
    except Exception as e:  # noqa: BLE001
        print(f"grondstoffen mislukt: {e}")
        try:
            uit["commodities"] = json.loads(OUT.read_text()).get("commodities") or []
        except Exception:  # noqa: BLE001
            pass
    uit["eurusd"] = schoon(fx.get("EURUSD=X"), 6)  # 1 euro in dollar, voor de portfolio in euro's
    try:
        vorige = json.loads(OUT.read_text()).get("macro") if OUT.exists() else None
    except Exception:  # noqa: BLE001
        vorige = None
    try:
        uit["macro"] = macro.haal_macro(vorige)
        if rf:
            uit["macro"]["us10y"] = {"value": round(rf * 100, 3)}
    except Exception as e:  # noqa: BLE001
        print(f"macro mislukt: {e}")
        if vorige:
            uit["macro"] = vorige

    try:
        vorig_nieuws = json.loads(OUT.read_text()).get("nieuws") if OUT.exists() else None
    except Exception:  # noqa: BLE001
        vorig_nieuws = None
    try:
        uit["nieuws"] = nieuws.haal_nieuws(vorig_nieuws)
    except Exception as e:  # noqa: BLE001
        print(f"nieuws mislukt: {e}")
        uit["nieuws"] = vorig_nieuws or []

    # Waarderingsengine: analyseert het hele universum (voor sectorvergelijking); op de site alleen het advies
    analyse = None
    try:
        analyse = fund.run_engine(cache, prijzen, alle_closes, pd.Timestamp(asof).date(), rf, fx)
    except Exception as e:  # noqa: BLE001
        print(f"waarderingsengine mislukt: {e}")
    for r in rijen:
        r["rating"] = (analyse or {}).get(r["ticker"], {}).get("rating", "NO RATING")
        try:
            uitleg = waarom((analyse or {}).get(r["ticker"]))
        except Exception as e:  # noqa: BLE001
            print(f"  uitleg {r['ticker']}: {e}")
            uitleg = None
        if uitleg:
            r["why"] = uitleg  # waarom BUY: reden in gewone taal, uit de berekende cijfers
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
