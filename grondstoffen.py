"""Grondstoffen (commodities): koersen van termijncontracten via Yahoo Finance (gratis, zonder sleutel).

Elke grondstof heeft een of meer kandidaat-tickers. Een koers wordt alleen getoond als:
  - er recente data is (laatste koers niet ouder dan MAX_OUD dagen), en
  - de koers binnen een ruime, logische bandbreedte valt (beschermt tegen verkeerde eenheden of
    een verkeerd contract).
Anders tonen we geen cijfer maar alleen een link naar een betrouwbare bron (niets gokken).
Prijzen in centen (zoals tarwe in dollarcent per bushel) worden omgerekend naar dollars (`div`).
"""
import pandas as pd
import yfinance as yf

MAX_OUD = 10  # dagen
TE = "https://tradingeconomics.com/commodity/"

# (groep, [items]); item: naam, eng, tickers, eenheid, div (centen -> dollar), bandbreedte (na div), link
GROEPEN = [
    ("Edelmetalen", "💎", [
        dict(id="gold", naam="Goud", en="Gold", tickers=["GC=F"], unit="$/troy ounce", band=(1000, 12000)),
        dict(id="silver", naam="Zilver", en="Silver", tickers=["SI=F"], unit="$/troy ounce", band=(10, 250)),
        dict(id="platinum", naam="Platina", en="Platinum", tickers=["PL=F"], unit="$/troy ounce", band=(400, 6000)),
        dict(id="palladium", naam="Palladium", en="Palladium", tickers=["PA=F"], unit="$/troy ounce", band=(400, 6000)),
    ]),
    ("Industriële metalen", "🔩", [
        dict(id="copper", naam="Koper", en="Copper", tickers=["HG=F"], unit="$/pound", band=(1.5, 15)),
        dict(id="aluminium", naam="Aluminium", en="Aluminium", tickers=["ALI=F"], unit="$/ton", band=(1200, 6000),
             link=TE + "aluminum"),
        dict(id="nickel", naam="Nikkel", en="Nickel", tickers=[], link=TE + "nickel"),
        dict(id="zinc", naam="Zink", en="Zinc", tickers=[], link=TE + "zinc"),
        dict(id="tin", naam="Tin", en="Tin", tickers=[], link=TE + "tin"),
        dict(id="ironore", naam="IJzererts", en="Iron Ore", tickers=["TIO=F"], unit="$/ton", band=(40, 300),
             link=TE + "iron-ore"),
    ]),
    ("Energie", "⚡", [
        dict(id="brent", naam="Brent olie", en="Brent Crude Oil", tickers=["BZ=F"], unit="$/vat", band=(20, 200)),
        dict(id="wti", naam="WTI olie", en="WTI Crude Oil", tickers=["CL=F"], unit="$/vat", band=(20, 200),
             link=TE + "crude-oil"),
        dict(id="natgas", naam="Aardgas (VS)", en="Natural Gas", tickers=["NG=F"], unit="$/MMBtu", band=(0.8, 20)),
        dict(id="uranium", naam="Uranium", en="Uranium", tickers=["UX=F"], unit="$/pound", band=(20, 300),
             link=TE + "uranium"),
        dict(id="coal", naam="Steenkool", en="Coal", tickers=["MTF=F"], unit="$/ton", band=(40, 500),
             link=TE + "coal"),
        dict(id="gasoline", naam="Benzine (VS)", en="Gasoline", tickers=["RB=F"], unit="$/gallon", band=(0.8, 6)),
    ]),
    ("Batterij- en strategische grondstoffen", "🔋", [
        dict(id="lithium", naam="Lithium", en="Lithium", tickers=[], link=TE + "lithium"),
        dict(id="cobalt", naam="Kobalt", en="Cobalt", tickers=[], link=TE + "cobalt"),
        dict(id="graphite", naam="Grafiet", en="Graphite", tickers=[],
             link="https://www.usgs.gov/centers/national-minerals-information-center/graphite-statistics-and-information"),
        dict(id="rareearths", naam="Zeldzame aardmetalen", en="Rare Earths", tickers=[],
             link=TE + "neodymium", linklabel="Neodymium (Trading Economics)"),
    ]),
    ("Landbouw", "🌾", [
        dict(id="wheat", naam="Tarwe", en="Wheat", tickers=["ZW=F"], unit="$/bushel", div=100, band=(2, 15)),
        dict(id="corn", naam="Maïs", en="Corn", tickers=["ZC=F"], unit="$/bushel", div=100, band=(2, 10)),
        dict(id="soy", naam="Sojabonen", en="Soybeans", tickers=["ZS=F"], unit="$/bushel", div=100, band=(5, 25)),
        dict(id="coffee", naam="Koffie", en="Coffee", tickers=["KC=F"], unit="$/pound", div=100, band=(0.8, 8)),
        dict(id="cocoa", naam="Cacao", en="Cocoa", tickers=["CC=F"], unit="$/ton", band=(1500, 16000)),
        dict(id="sugar", naam="Suiker", en="Sugar", tickers=["SB=F"], unit="$/pound", div=100, band=(0.06, 0.5)),
        dict(id="cotton", naam="Katoen", en="Cotton", tickers=["CT=F"], unit="$/pound", div=100, band=(0.35, 2)),
        dict(id="canola", naam="Koolzaad", en="Canola", tickers=["RS=F"], unit="C$/ton", band=(350, 1500),
             cur="CAD", link=TE + "canola"),
        dict(id="rice", naam="Rijst", en="Rice", tickers=["ZR=F"], unit="$/cwt", band=(7, 30),
             link=TE + "rough-rice"),
    ]),
    ("Vee", "🐄", [
        dict(id="cattle", naam="Rundvee", en="Live Cattle", tickers=["LE=F"], unit="$/pound", div=100, band=(1, 4)),
        dict(id="hogs", naam="Varkensvlees", en="Lean Hogs", tickers=["HE=F"], unit="$/pound", div=100, band=(0.4, 2)),
    ]),
]


def yahoo_link(t):
    return f"https://finance.yahoo.com/quote/{t}/"


def _stats(df, div, bereken, spark):
    df = df.dropna(subset=["Close"])
    if len(df) < 5:
        return None, "te weinig data"
    df = df[["Close", "High"]] / div if "High" in df else df[["Close"]] / div
    oud = (pd.Timestamp.now(tz=df.index.tz) - df.index[-1]).days if df.index.tz else \
        (pd.Timestamp.now() - df.index[-1]).days
    if oud > MAX_OUD:
        return None, f"verouderd ({oud} dagen)"
    s = bereken(df)
    if not s:
        return None, "geen data"
    s["price"] = round(float(df["Close"].iloc[-1]), 4)  # meer decimalen (bv. suiker $0,1612/pound)
    s.pop("high52", None)
    s["date"] = pd.Timestamp(s.pop("_date")).strftime("%Y-%m-%d")
    s["spark"] = spark(df["Close"])
    return s, None


def haal_grondstoffen(bereken, spark):
    """Lijst van groepen met items. bereken/spark komen uit update.py (dezelfde berekening als aandelen)."""
    alle = sorted({t for _, _, items in GROEPEN for it in items for t in it["tickers"]})
    data = None
    try:
        data = yf.download(alle, period="2y", interval="1d", auto_adjust=False, group_by="ticker", progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"grondstoffen download mislukt: {e}")
    uit, n = [], 0
    for groep, icoon, items in GROEPEN:
        rijen = []
        for it in items:
            rij = {"id": it["id"], "name": it["naam"], "en": it["en"]}
            for t in it["tickers"]:
                try:
                    df = data[t] if data is not None else None
                    if df is None or df.empty:
                        print(f"  grondstof {it['naam']} {t}: geen data")
                        continue
                    s, fout = _stats(df, it.get("div", 1), bereken, spark)
                    if fout:
                        print(f"  grondstof {it['naam']} {t}: {fout}")
                        continue
                    lo, hi = it["band"]
                    if not lo <= s["price"] <= hi:
                        print(f"  grondstof {it['naam']} {t}: koers {s['price']} buiten {lo}–{hi}, niet getoond")
                        continue
                    rij.update({"ticker": t, "unit": it["unit"], "currency": it.get("cur", "USD"),
                                "src": yahoo_link(t), **s})
                    print(f"  grondstof {it['naam']} {t}: {s['price']} {it['unit']} ({s['date']})")
                    n += 1
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"  grondstof {it['naam']} {t}: overgeslagen ({e})")
            if "price" not in rij:
                rij["link"] = it.get("link") or TE + it["en"].lower().replace(" ", "-")
                if it.get("linklabel"):
                    rij["linklabel"] = it["linklabel"]
            rijen.append(rij)
        uit.append({"group": groep, "icon": icoon, "items": rijen})
    print(f"grondstoffen: {n} met koers")
    return uit
