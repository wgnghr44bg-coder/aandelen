"""Rentes, inflatie en woningprijzen uit officiële, gratis bronnen (geen API-sleutel):

- ECB Data Portal (data-api.ecb.europa.eu): ECB-rentes, Euribor, 10-jaars staatsrente NL,
  hypotheekrente NL (nieuwe leningen per rentevaste periode, MIR) en zakelijke leningen NL.
- Eurostat (ec.europa.eu/eurostat): HICP-inflatie (NL, eurozone, EU) en woningprijsindex NL.

Alles is optioneel: lukt een bron niet, dan blijft de vorige waarde staan (of ontbreekt het onderdeel).
"""
import csv
import io
import json
import time
import urllib.request

ECB = "https://data-api.ecb.europa.eu/service/data/"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"

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
            req = urllib.request.Request(url, headers={"User-Agent": "stockhunter/1.0", "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"  macro {url[:90]}… poging {i + 1} mislukt: {e}")
            time.sleep(2 * (i + 1))
    return None


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


def eurostat(dataset, params, n):
    """JSON-stat van Eurostat -> {geo: [[periode, waarde], …]} (oud -> nieuw)."""
    q = "&".join(f"{k}={v}" for k, vals in params.items() for v in (vals if isinstance(vals, list) else [vals]))
    txt = _get(f"{EUROSTAT}{dataset}?{q}&lastTimePeriod={n}")
    if not txt:
        return {}
    try:
        js = json.loads(txt)
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
            zet(naam, {"value": cur[1], "date": cur[0], "prev": prev[1] if prev else None, "since": since})
        else:
            zet(naam, None)

    zet("euribor3m", ecb_one("FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"))
    zet("nl10y", ecb_one("IRS/M.NL.L.L40.CI.0000.EUR.N.Z"))
    zet("nfc_loans_nl", ecb_one("MIR/M.NL.B.A2A.A.R.A.2240.EUR.N"))

    # Hypotheekrente NL, nieuwe leningen per rentevaste periode
    hyp = []
    for k, s in sorted(ecb_series("MIR/M.NL.B.A2C..R.A.2250.EUR.N", 2).items()):
        parts = k.split(".")
        code = parts[parts.index("A2C") + 1] if "A2C" in parts and parts.index("A2C") + 1 < len(parts) else ""
        last = _last(s)
        if last and code in FIXATIE:
            hyp.append({"code": code, "label": FIXATIE[code], **last})
    order = list(FIXATIE)
    hyp.sort(key=lambda h: order.index(h["code"]))
    zet("mortgage_nl", hyp)

    # Inflatie (HICP, jaar op jaar) – 25 maanden voor een grafiek. Eerst via de ECB (actueel),
    # anders Eurostat. Eurozone = U2 (wisselende samenstelling, zoals de ECB zelf rapporteert).
    hicp = {}
    for geo, key in (("NL", "ICP/M.NL.N.000000.4.ANR"), ("EA20", "ICP/M.U2.N.000000.4.ANR")):
        st = next(iter(ecb_series(key, 25).values()), None)
        if st and st["obs"]:
            hicp[geo] = st["obs"]
    es = eurostat("prc_hicp_manr", {"geo": ["NL", "EA20", "EU27_2020"], "coicop": "CP00"}, 25)
    for geo, serie in es.items():
        if serie and (geo not in hicp or serie[-1][0] > hicp[geo][-1][0]):
            hicp[geo] = serie
    # EU alleen tonen als die net zo actueel is als NL (anders misleidend)
    if "EU27_2020" in hicp and "NL" in hicp and hicp["EU27_2020"][-1][0] < hicp["NL"][-1][0]:
        hicp.pop("EU27_2020")
    zet("hicp", hicp if any(hicp.values()) else None)

    # Woningprijzen NL (jaar op jaar, per kwartaal)
    hpi = eurostat("prc_hpi_q", {"geo": "NL", "purchase": "TOTAL", "unit": "RCH_A"}, 12).get("NL")
    zet("house_prices_nl", hpi)

    ok = sorted(m)
    print(f"macro: {len(ok)} onderdelen ({', '.join(ok)})")
    return m
