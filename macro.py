"""Rentes, inflatie en woningprijzen uit officiële, gratis bronnen (geen API-sleutel):

- ECB Data Portal (data-api.ecb.europa.eu): ECB-rentes, Euribor, 10-jaars staatsrente NL,
  hypotheekrente NL (nieuwe leningen per rentevaste periode, MIR) en zakelijke leningen NL.
- Eurostat (ec.europa.eu/eurostat): HICP-inflatie (NL, eurozone, EU) en woningprijsindex NL.

Alles is optioneel: lukt een bron niet, dan blijft de vorige waarde staan (of ontbreekt het onderdeel).
"""
import csv
import io
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

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
            req = urllib.request.Request(url, headers={"User-Agent": "investmarket/1.0", "Accept": "*/*"})
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


def ecb_link(key):
    """Officiële pagina van een ECB-reeks in het ECB Data Portal (om het cijfer zelf te controleren)."""
    ds, rest = key.split("/", 1)
    return f"https://data.ecb.europa.eu/data/datasets/{ds}/{ds}.{rest}"


EUROSTAT_LINK = "https://ec.europa.eu/eurostat/databrowser/view/{}/default/table"
ECB_STRUCT = "https://data-api.ecb.europa.eu/service/"


def _tag(el):
    return el.tag.rsplit("}", 1)[-1]


def mir_structuur():
    """Officiële betekenis van de codes in de MIR-reeksen, uit de ECB-structuur (SDMX):
    ([dimensie-id's in volgorde], {dimensie: {code: (volgnummer, Engelse naam)}})."""
    for pad in ("dataflow/ECB/MIR/latest?references=descendants", "datastructure/ECB/ECB_MIR1?references=children"):
        txt = _get(ECB_STRUCT + pad, tries=2)
        if not txt:
            continue
        try:
            root = ET.fromstring(txt.encode("utf-8"))
        except ET.ParseError as e:
            print(f"  mir-structuur {pad}: niet te lezen ({e})")
            continue
        lijsten = {}
        for cl in root.iter():
            if _tag(cl) != "Codelist":
                continue
            codes = {}
            for code in cl:
                if _tag(code) != "Code":
                    continue
                namen = [n for n in code if _tag(n) == "Name"]
                en = next((n.text for n in namen if n.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"), None)
                codes[code.get("id")] = (len(codes), (en or (namen[0].text if namen else "") or "").strip())
            lijsten[cl.get("id")] = codes
        dims = []
        for d in root.iter():
            if _tag(d) != "Dimension" or not d.get("id"):
                continue
            ref = next((r.get("id") for r in d.iter() if _tag(r) == "Ref" and r.get("id") in lijsten), None)
            dims.append((int(d.get("position") or len(dims) + 1), d.get("id"), lijsten.get(ref, {})))
        dims.sort()
        if dims and lijsten:
            return [d[1] for d in dims], {d[1]: d[2] for d in dims}
    return None, None


def nl_label(en):
    """Engelse ECB-omschrijving van een bedrag of rentevaste periode -> kort Nederlands."""
    t = (en or "").strip()
    low = t.lower()
    if low in ("total", "total amount", "all amounts", "total maturity", "total initial rate fixation"):
        return "totaal"
    t = re.sub(r"(?i)floating rate and up to", "variabel tot", t)
    t = re.sub(r"(?i)\s*and up to and including\s*", " – ", t)
    t = re.sub(r"(?i)\s*and up to\s*", " – ", t)
    t = re.sub(r"(?i)up to and including", "tot en met", t)
    t = re.sub(r"(?i)\bup to\b", "tot", t)
    t = re.sub(r"(?i)\bover\b", "boven", t)
    t = re.sub(r"(?i)\beur\s*", "€", t)
    t = re.sub(r"(?i)\s*millions?\b", " mln", t)
    t = re.sub(r"(?i)\byears?\b", "jaar", t)
    t = re.sub(r"(?i)\bmonths?\b", "maanden", t)
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:1].lower() + t[1:]


def zakelijk_nl():
    """Rente op nieuwe bedrijfsleningen NL (hieronder valt ook bancaire vastgoedfinanciering), per
    leningbedrag en rentevaste periode. De omschrijvingen komen uit de officiële ECB-codelijsten;
    zonder die lijsten tonen we niets (niets gokken)."""
    reeksen = ecb_series("MIR/M.NL.B.A2A..R..2240.EUR.N", 2)
    if not reeksen:
        return None
    dims, lijsten = mir_structuur()
    if not dims or "AMOUNT_CAT" not in dims:
        print("  zakelijk: ECB-codelijsten niet beschikbaar")
        return None
    i_bedrag = dims.index("AMOUNT_CAT")
    i_vast = next((i for i, d in enumerate(dims) if d.startswith("MATURITY")), None)
    if i_vast is None:
        return None
    rijen, nieuwste = [], max((s["obs"][-1][0] for s in reeksen.values() if s["obs"]), default="")
    for k, s in reeksen.items():
        delen = k.split(".")
        if delen and delen[0] == "MIR":
            delen = delen[1:]
        last = _last(s)
        if len(delen) != len(dims) or not last or last["date"] < nieuwste:
            continue  # verouderde/stopgezette reeks
        b, v = delen[i_bedrag], delen[i_vast]
        bi, bnaam = lijsten[dims[i_bedrag]].get(b, (None, None))
        vi, vnaam = lijsten[dims[i_vast]].get(v, (None, None))
        if bnaam is None or vnaam is None:
            continue
        rijen.append({"amount": b, "amount_label": nl_label(bnaam), "amount_en": bnaam, "amount_ord": bi,
                      "fix": v, "fix_label": nl_label(vnaam), "fix_en": vnaam, "fix_ord": vi,
                      "src": ecb_link("MIR/" + ".".join(delen)), **last})
        print(f"  zakelijk {b}/{v}: {bnaam!r} / {vnaam!r} -> {last['value']} ({last['date']})")
    # Overzichtelijke selectie (codes volgens de ECB-codelijst, gecontroleerd in de logs):
    # bedrag 0 = t/m €1 mln, 1 = boven €1 mln, A = totaal; vast A = alle, F = tot 1 jaar, I = 1-5 jaar,
    # O = 5-10 jaar, P = boven 10 jaar; J (boven 5 jaar) alleen als O/P ontbreken.
    bedragen, vast = ["0", "1", "A"], ["A", "F", "I", "O", "P", "J"]
    rijen = [r for r in rijen if r["amount"] in bedragen and r["fix"] in vast]
    heeft_op = {r["amount"] for r in rijen if r["fix"] in ("O", "P")}
    rijen = [r for r in rijen if not (r["fix"] == "J" and r["amount"] in heeft_op)]
    rijen.sort(key=lambda r: (bedragen.index(r["amount"]), vast.index(r["fix"])))
    return rijen or None


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
                       "src": ecb_link(key)})
        else:
            zet(naam, None)

    for naam, key in (("euribor3m", "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"),
                      ("nl10y", "IRS/M.NL.L.L40.CI.0000.EUR.N.Z"),
                      ("nfc_loans_nl", "MIR/M.NL.B.A2A.A.R.A.2240.EUR.N")):
        st = next(iter(ecb_series(key, 2).values()), None)
        last = _last(st)
        if last:
            last.update({"src": ecb_link(key), "title": st.get("title") or ""})
            print(f"  {naam}: {last['title']!r} -> {last['value']} ({last['date']})")
        zet(naam, last)

    # Hypotheekrente NL, nieuwe leningen per rentevaste periode
    hyp = []
    for k, s in sorted(ecb_series("MIR/M.NL.B.A2C..R.A.2250.EUR.N", 2).items()):
        parts = k.split(".")
        code = parts[parts.index("A2C") + 1] if "A2C" in parts and parts.index("A2C") + 1 < len(parts) else ""
        last = _last(s)
        if last and code in FIXATIE:
            hyp.append({"code": code, "label": FIXATIE[code], "title": s.get("title") or "",
                        "src": ecb_link("MIR/" + ".".join(parts[parts.index("M"):]) if "M" in parts else "MIR/" + k), **last})
            print(f"  hypotheek {code}: {s.get('title')!r} -> {last['value']} ({last['date']})")
    order = list(FIXATIE)
    hyp.sort(key=lambda h: order.index(h["code"]))
    zet("mortgage_nl", hyp)

    # Bedrijfsleningen NL per bedrag en rentevaste periode (basis voor bancaire vastgoedfinanciering)
    zet("business_nl", zakelijk_nl())

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
    if hicp:
        hicp["src"] = EUROSTAT_LINK.format("prc_hicp_minr")
    zet("hicp", hicp if any(v for g, v in hicp.items() if g != "src") else None)

    # Woningprijzen NL (jaar op jaar, per kwartaal)
    hpi = eurostat("prc_hpi_q", {"geo": "NL", "purchase": "TOTAL", "unit": "RCH_A"}, 12).get("NL")
    zet("house_prices_nl", hpi)
    if hpi:
        m["house_prices_src"] = EUROSTAT_LINK.format("prc_hpi_q")

    ok = sorted(m)
    print(f"macro: {len(ok)} onderdelen ({', '.join(ok)})")
    return m
