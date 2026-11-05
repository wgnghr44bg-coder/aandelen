"""Rentes, inflatie en woningprijzen uit officiële, gratis bronnen (geen API-sleutel):

- ECB Data Portal (data-api.ecb.europa.eu): ECB-rentes, Euribor, 10-jaars staatsrente NL,
  hypotheekrente NL (nieuwe leningen per rentevaste periode, MIR).
- Eurostat (ec.europa.eu/eurostat): HICP-inflatie (NL, eurozone, EU) en woningprijsindex NL (kwartaal).
- CBS open data (opendata.cbs.nl, CC BY 4.0): prijsindex bestaande koopwoningen (maand).

De MIR-rentecijfers voor Nederland worden door DNB aan de ECB geleverd; het ECB Data Portal is de open,
sleutelvrije bron van dezelfde DNB-cijfers.

Per cijfer bewaren we ook: meetperiode (`date`), vorige periode (`prev`, `prev_date`), frequentie (`freq`),
soort cijfer (`kind`) en de datum waarop de bron het cijfer heeft bijgewerkt (`upd`, zie `eerst_gezien`; Eurostat/CBS: hun eigen update-datum).

Alles is optioneel: lukt een bron niet, dan blijft de vorige waarde staan (of ontbreekt het onderdeel).
"""
import csv
import io
from datetime import date
import json
import time
import urllib.error
import urllib.parse
import urllib.request

ECB = "https://data-api.ecb.europa.eu/service/data/"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"

HYP_KEY = "MIR/M.NL.B.A2C..R.A.2250.EUR.N"   # hypotheken NL, nieuwe leningen, per rentevaste periode
# Rentevaste periode in de MIR-statistiek (nieuwe hypotheken)
FIXATIE = {
    "F": "variabel / tot 1 jaar vast",
    "I": "1 tot 5 jaar vast",
    "O": "5 tot 10 jaar vast",
    "P": "meer dan 10 jaar vast",
}


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "investmarket/1.0", "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"  macro {url[:90]}… poging {i + 1} mislukt: {e}")
            time.sleep(2 * (i + 1))
    return None


def eerst_gezien(periode, vorige):
    """Dag waarop InvestMarket deze meetperiode voor het eerst in de bron zag (de site kijkt elke 30 min.,
    dus dit is de publicatiedatum op ±30 minuten). Bij een periode die er al was vóór we dit bijhielden: None.
    De ECB-API geeft zelf geen betrouwbare publicatiedatum per waarneming."""
    vorige = vorige or {}
    if vorige.get("date") == periode:
        return vorige.get("upd")
    return date.today().isoformat() if vorige.get("date") else None


def _num(x):
    try:
        return round(float(x), 4)
    except (TypeError, ValueError):
        return None


def ecb_series(key, n=2):
    """ECB-reeks(en) als {series_key: {"title":…, "obs": [[periode, waarde], …]}} (oud -> nieuw)."""
    txt = _get(f"{ECB}{key}?lastNObservations={n}&format=csvdata")
    if not txt:
        return {}
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        k = row.get("KEY") or key
        s = out.setdefault(k, {"title": row.get("TITLE") or row.get("TITLE_COMPL") or "", "row": row, "obs": []})
        v = _num(row.get("OBS_VALUE"))
        if v is not None:
            s["obs"].append([row.get("TIME_PERIOD"), v])
    for s in out.values():
        s["obs"].sort(key=lambda x: x[0])
    return out


def _last(series):
    if not series or not series.get("obs"):
        return None
    obs = series["obs"]
    cur = obs[-1]
    prev = obs[-2] if len(obs) > 1 else None
    return {"value": cur[1], "date": cur[0], "prev": prev[1] if prev else None,
            "prev_date": prev[0] if prev else None}


def ecb_one(key, n=2):
    s = ecb_series(key, n)
    return _last(next(iter(s.values()))) if s else None


EUROSTAT_UPDATED = {}  # dataset -> datum laatste update (uit het JSON-stat-veld "updated")


def eurostat(dataset, params, n):
    """JSON-stat van Eurostat -> {geo: [[periode, waarde], …]} (oud -> nieuw)."""
    q = "&".join(f"{k}={v}" for k, vals in params.items() for v in (vals if isinstance(vals, list) else [vals]))
    txt = _get(f"{EUROSTAT}{dataset}?{q}&lastTimePeriod={n}")
    if not txt:
        return {}
    try:
        js = json.loads(txt)
        if js.get("updated"):
            EUROSTAT_UPDATED[dataset] = str(js["updated"])[:10]
        ids, sizes, dims = js["id"], js["size"], js["dimension"]
        idx = {d: dims[d]["category"]["index"] for d in ids}
        geos = sorted(idx["geo"], key=lambda g: idx["geo"][g])
        times = sorted(idx["time"], key=lambda t: idx["time"][t])
        out = {}
        for g in geos:
            series = []
            for t in times:
                pos = {d: 0 for d in ids}
                pos["geo"], pos["time"] = idx["geo"][g], idx["time"][t]
                flat = 0
                for d, size in zip(ids, sizes):
                    flat = flat * size + pos[d]
                v = js["value"].get(str(flat))
                if v is not None:
                    series.append([t, _num(v)])
            out[g] = series
        return out
    except Exception as e:  # noqa: BLE001
        print(f"  eurostat {dataset}: niet te lezen ({e})")
        return {}


def ecb_link(key):
    """Officiële pagina van een ECB-reeks in het ECB Data Portal (om het cijfer zelf te controleren)."""
    ds, rest = key.split("/", 1)
    return f"https://data.ecb.europa.eu/data/datasets/{ds}/{ds}.{rest}"


EUROSTAT_LINK = "https://ec.europa.eu/eurostat/databrowser/view/{}/default/table"


CBS_OData = "https://opendata.cbs.nl/ODataApi/odata/85773NED"
CBS_LINK = "https://opendata.cbs.nl/statline/#/CBS/nl/dataset/85773NED/table"


def cbs_woningprijzen(n=400):
    """CBS 85773NED (bestaande koopwoningen): per maand de verandering t.o.v. een jaar eerder (%).
    Kolommen worden op hun officiële titel gezocht (niet op een vermoede naam).
    Geeft {"series": [[JJJJ-MM, %], …], "updated": JJJJ-MM-DD, "title": …} of None."""
    try:
        props = json.loads(_get(CBS_OData + "/DataProperties?$format=json") or "{}").get("value") or []
        topics = [p for p in props if p.get("Type") == "Topic"]
        sleutel = next((p for p in topics if "jaar eerder" in (p.get("Title") or "").lower()), None)
        if not sleutel:
            print(f"  cbs: kolom 'jaar eerder' niet gevonden ({[p.get('Title') for p in topics]})")
            return None
        dims = [p["Key"] for p in props if p.get("Type") in ("Dimension", "GeoDimension")]
        filt = "substringof('MM',Perioden)"
        for d in dims:  # andere dimensies (bv. regio): kies 'Nederland' / 'Totaal'
            vals = json.loads(_get(f"{CBS_OData}/{d}?$format=json") or "{}").get("value") or []
            keuze = next((v for v in vals if (v.get("Title") or "").strip().lower() in ("nederland", "totaal")), None)
            if not keuze:
                print(f"  cbs: dimensie {d} zonder 'Nederland/Totaal'")
                return None
            filt += f" and {d} eq '{keuze['Key']}'"
        url = (f"{CBS_OData}/TypedDataSet?$format=json&$select=Perioden,{sleutel['Key']}"
               f"&$filter={urllib.parse.quote(filt)}")
        rows = json.loads(_get(url) or "{}").get("value") or []
        serie = []
        for r in rows:
            p, v = (r.get("Perioden") or "").strip(), _num(r.get(sleutel["Key"]))
            if len(p) == 8 and p[4:6] == "MM" and v is not None:
                serie.append([f"{p[:4]}-{p[6:]}", v])
        serie.sort()
        info = (json.loads(_get(CBS_OData + "/TableInfos?$format=json") or "{}").get("value") or [{}])[0]
        if not serie:
            return None
        print(f"  cbs woningprijzen: {sleutel.get('Title')!r} -> {serie[-1]} (tabel bijgewerkt {info.get('Modified')})")
        return {"series": serie[-n:], "updated": (info.get("Modified") or "")[:10] or None,
                "title": sleutel.get("Title"), "table": info.get("Title"), "src": CBS_LINK}
    except Exception as e:  # noqa: BLE001
        print(f"  cbs woningprijzen: mislukt ({e})")
        return None


def haal_macro(vorige=None):
    """Alle macro-cijfers. `vorige` = macro van de vorige run (terugval per onderdeel)."""
    vorige = vorige or {}
    m = {}

    def zet(naam, waarde):
        if waarde:
            m[naam] = waarde
        elif vorige.get(naam):
            m[naam] = vorige[naam]
            print(f"  macro {naam}: vorige waarde gebruikt")

    # ECB-rentes (dagreeksen; vorige waarde = vorige wijziging)
    for naam, key in (("ecb_deposit", "FM/D.U2.EUR.4F.KR.DFR.LEV"), ("ecb_mro", "FM/D.U2.EUR.4F.KR.MRR_FR.LEV")):
        s = ecb_series(key, 400)
        st = next(iter(s.values()), None)
        if st and st["obs"]:
            obs = st["obs"]
            cur = obs[-1]
            idx = next((i for i in range(len(obs) - 1, -1, -1) if obs[i][1] != cur[1]), None)
            prev = obs[idx] if idx is not None else None
            since = obs[idx + 1][0] if idx is not None else None  # eerste dag van de huidige rente
            zet(naam, {"value": cur[1], "date": cur[0], "prev": prev[1] if prev else None, "since": since,
                       "prev_until": prev[0] if prev else None, "kind": "beleidsrente (geldend niveau)",
                       "freq": "wijzigt bij een ECB-rentebesluit (±elke 6 weken een vergadering)",
                       "src": ecb_link(key)})
        else:
            zet(naam, None)

    MAAND = "maandelijks"
    for naam, key, kind in (("euribor3m", "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", "maandgemiddelde"),
                            ("nl10y", "IRS/M.NL.L.L40.CI.0000.EUR.N.Z", "maandgemiddelde rendement")):
        st = next(iter(ecb_series(key, 2).values()), None)
        last = _last(st)
        if last:
            last.update({"src": ecb_link(key), "title": st.get("title") or "", "kind": kind, "freq": MAAND,
                         "upd": eerst_gezien(last["date"], vorige.get(naam)), "upd_how": "gezien"})
            print(f"  {naam}: {last['title']!r} -> {last['value']} ({last['date']}, bijgewerkt {last['upd']})")
        zet(naam, last)

    # Hypotheekrente NL, nieuwe leningen per rentevaste periode
    hyp = []
    hyp_hist = {}
    for k, s in sorted(ecb_series(HYP_KEY, 241).items()):  # ±20 jaar maandcijfers voor de grafiek
        parts = k.split(".")
        code = parts[parts.index("A2C") + 1] if "A2C" in parts and parts.index("A2C") + 1 < len(parts) else ""
        last = _last(s)
        if last and code in FIXATIE:
            hyp_hist[code] = s["obs"]
            hyp.append({"code": code, "label": FIXATIE[code], "title": s.get("title") or "",
                        "src": ecb_link("MIR/" + ".".join(parts[parts.index("M"):]) if "M" in parts else "MIR/" + k), **last})
            print(f"  hypotheek {code}: {s.get('title')!r} -> {last['value']} ({last['date']})")
    order = list(FIXATIE)
    hyp.sort(key=lambda h: order.index(h["code"]))
    if hyp:
        upd = eerst_gezien(hyp[0]["date"], (vorige.get("mortgage_nl") or [None])[0])
        for h in hyp:
            h.update({"kind": "maandgemiddelde nieuw afgesloten hypotheken", "freq": MAAND, "upd": upd, "upd_how": "gezien"})
    zet("mortgage_nl", hyp)
    zet("mortgage_hist", hyp_hist if len(hyp_hist) == len(hyp) and hyp else None)

    # Inflatie (HICP, jaar op jaar) – 25 maanden voor een grafiek. Sinds 2026 publiceert Eurostat de HICP
    # volgens COICOP 2018 in nieuwe datasets; we proberen nieuw én oud (Eurostat en ECB) en nemen per land
    # de meest actuele reeks.
    kandidaten = []
    geos = ["NL", "EA20", "EU27_2020"]
    for ds, extra in (("prc_hicp_minr", {"coicop18": "TOTAL", "unit": "RCH_A"}),
                      ("prc_hicp_minr", {"coicop18": "CP00", "unit": "RCH_A"}),
                      ("prc_hicp_manr", {"coicop": "CP00"})):
        res = eurostat(ds, {"geo": geos, **extra}, 25)
        if any(res.values()):
            kandidaten.append((f"eurostat {ds} {extra}", res))
    for geo, keys in (("NL", ["ICP/M.NL.N.000000.4.ANR", "ICP/M.NL.N.TOTAL.4.ANR"]),
                      ("EA20", ["ICP/M.U2.N.000000.4.ANR", "ICP/M.U2.N.TOTAL.4.ANR"])):
        for key in keys:
            st = next(iter(ecb_series(key, 25).values()), None)
            if st and st["obs"]:
                kandidaten.append((f"ecb {key}", {geo: st["obs"]}))
    hicp = {}
    for naam, res in kandidaten:
        for geo, serie in res.items():
            if serie:
                print(f"  hicp {naam} {geo}: t/m {serie[-1][0]}")
                if geo not in hicp or serie[-1][0] > hicp[geo][-1][0]:
                    hicp[geo] = serie
    # EU alleen tonen als die net zo actueel is als NL (anders misleidend)
    if "EU27_2020" in hicp and "NL" in hicp and hicp["EU27_2020"][-1][0] < hicp["NL"][-1][0]:
        hicp.pop("EU27_2020")
    heeft = any(hicp.values())
    if heeft:
        hicp.update({"src": EUROSTAT_LINK.format("prc_hicp_minr"), "upd": EUROSTAT_UPDATED.get("prc_hicp_minr"),
                     "freq": MAAND, "kind": "verandering t.o.v. dezelfde maand een jaar eerder"})
    zet("hicp", hicp if heeft else None)

    # Woningprijzen NL (jaar op jaar, per kwartaal)
    hpi = eurostat("prc_hpi_q", {"geo": "NL", "purchase": "TOTAL", "unit": "RCH_A"}, 90).get("NL")  # sinds ±2005
    zet("house_prices_nl", hpi)
    if hpi:
        m["house_prices_src"] = EUROSTAT_LINK.format("prc_hpi_q")
        m["house_prices_upd"] = EUROSTAT_UPDATED.get("prc_hpi_q")
    elif vorige.get("house_prices_src"):
        m["house_prices_src"], m["house_prices_upd"] = vorige["house_prices_src"], vorige.get("house_prices_upd")

    # Woningprijzen NL volgens CBS (bestaande koopwoningen, per maand)
    zet("house_prices_cbs", cbs_woningprijzen())

    ok = sorted(m)
    print(f"macro: {len(ok)} onderdelen ({', '.join(ok)})")
    return m
