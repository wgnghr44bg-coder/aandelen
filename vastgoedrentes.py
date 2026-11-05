"""Vastgoedfinancieringen box 3: actuele, door geldverstrekkers zelf gepubliceerde rentes voor verhuurd /
belegd vastgoed. Draait dagelijks (workflow 'Vastgoedrentes') met een echte browser, omdat een deel van de
aanbieders hun tabellen met JavaScript laadt.

Regels:
- Alleen pagina's die robots.txt toestaat. Geen tarief gevonden of niet leesbaar -> 'Tarief op aanvraag'.
- Een tabel wordt alleen gebruikt als hij volledig klopt (elke rij evenveel rentes als LTV-kolommen,
  rentes tussen 2% en 15%). Anders wordt niets getoond (niets gokken).
- Vaste kenmerken (kosten, min./max. financiering) staan hieronder met de zin waarop ze gecontroleerd worden;
  staat die zin niet meer op de bronpagina, dan verdwijnt het kenmerk van de site.
- Historie: docs/vastgoedrentes_hist.json krijgt elke dag een momentopname (alleen bij wijzigingen),
  plus de historische tabellen die NIBC zelf publiceert.
Uitvoer: docs/vastgoedrentes.json
"""
import json
import re
import socket
import sys
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "vastgoedrentes.json"
HIST = ROOT / "docs" / "vastgoedrentes_hist.json"
UA = "Mozilla/5.0 (compatible; InvestMarket/1.0; +https://github.com/wgnghr44bg-coder/aandelen)"
socket.setdefaulttimeout(20)

PCT = re.compile(r"^(\d{1,2},\d{2})\s?%\*?$")
LABEL = re.compile(r"^(variabel|1 maand|\d{1,2}\s*(jaar|jr)\b.*)$", re.I)
HEAD = re.compile(r"(\d{2})\s?%")

# Per aanbieder: pagina('s) met tabel, begin- en eindtekst van het blok, soort vastgoed.
AANBIEDERS = [
    {"id": "rnhb", "naam": "RNHB", "url": "https://www.rnhb.nl/rente", "tabellen": []},
    {"id": "nibc", "naam": "NIBC", "url": "https://nibc.nl/vastgoed-hypotheek/rentes-vastgoed-hypotheek",
     "tabellen": [{"seg": "residentieel", "url": "https://nibc.nl/vastgoed-hypotheek/rentes-vastgoed-hypotheek",
                   "start": "Actuele rentes sinds", "end": "Let op: deze rentes", "klik": k, "naam": n}
                  for k, n in (("Tot 1 miljoen", "saldo tot € 1 mln"), ("Tussen 1 en 2,5 miljoen", "saldo € 1–2,5 mln"),
                               ("Boven 2,5 miljoen", "saldo boven € 2,5 mln"))],
     "datum": r"Actuele rentes sinds (\d{1,2} \w+\.?)",
     "feiten": [{"t": "Tarieven hangen ook af van het totale saldo bij NIBC (tot € 1 mln, € 1–2,5 mln, boven € 2,5 mln); "
                      "hier: saldo tot € 1 mln.", "check": "Tussen 1 en 2,5 miljoen"},
                {"t": "Indicatieve rentes; renteopslag als de lening (deels) op niet-woningen rust.",
                 "check": "renteopslag worden toegepast"}]},
    {"id": "domivest", "naam": "Domivest", "url": "https://www.domivest.nl/", "tabellen": []},
    {"id": "nestr", "naam": "Nestr", "url": "https://www.nestr.nl/rente",
     "tabellen": [{"seg": "residentieel", "url": "https://www.nestr.nl/rente",
                   "start": "Rentetarieven Verhuurde Woningen", "end": "* Het variabel tarief", "naam": "verhuurde woningen"},
                  {"seg": "combinatie", "url": "https://www.nestr.nl/rente",
                   "start": "Rentetarieven Combinatiepanden", "end": "* Het variabel tarief", "naam": "combinatiepanden"},
                  {"seg": "commercieel", "url": "https://www.nestr.nl/rente",
                   "start": "Rentetarieven Commercieel Vastgoed", "end": "- Bovenstaande tarieven", "naam": "commercieel"}],
     "feiten": [{"t": "Rentekorting mogelijk door 1%, 2% of 3% afsluitvergoeding te betalen.",
                 "check": "Je kunt rentekorting inkopen door 1%, 2% of 3% afsluitvergoeding"},
                {"t": "Commerciële tarieven gelden tot max. € 3.000.000.", "check": "tot maximaal EUR 3.000.000"},
                {"t": "Energielabel A of B: 0,10% korting.", "check": "korting van 0,10%"}]},
    {"id": "dcmf", "naam": "DCMF", "url": "https://dcmf.nl/verhuurhypotheek/",
     "tabellen": [{"seg": "residentieel", "url": "https://dcmf.nl/verhuurhypotheek/", "start": "Onze rentetarieven",
                   "end": "De tariefklasse", "naam": "verhuurhypotheek"}],
     "datum": r"gelden per (\d{2}-\d{2}-\d{4})",
     "feiten": [{"t": "Financiering tot 85% van de waarde.", "check": "Financiering tot 85% van de waarde"},
                {"t": "Tarieven zonder renteopslagen; kunnen wijzigen tijdens het aanvraagproces.",
                 "check": "zonder renteopslagen"}]},
    {"id": "solidbriq", "naam": "SolidBriq", "url": "https://www.solidbriq.nl/actuele-rentetarieven/",
     "tabellen": [{"seg": "residentieel", "url": "https://www.solidbriq.nl/actuele-rentetarieven/",
                   "frame": ("interests-page", "Basiq Select"), "start": "Rentevaste periode", "end": "\n*",
                   "naam": "BasiQ Select (nieuwe leningen sinds 1 okt 2026)"},
                  {"seg": "commercieel", "url": "https://www.solidbriq.nl/actuele-rentetarieven/",
                   "frame": ("interests-page", "Generiq"), "start": "Rentevaste periode", "end": "\n*",
                   "naam": "GeneriQ (commercieel)"}],
     "datum": r"Actuele rentetarieven per (\d{2}-\d{2}-\d{4})",
     "feiten": [{"t": "Variabele rente = 1-maands Euribor + opslag: woningen 2,90% (t/m 65% LTV) tot 4,00% (t/m 85% LTV); "
                      "commercieel 3,75–3,85%.", "check": "t/m 85% LTV: 4,00%",
                 "url": "https://www.solidbriq.nl/vaststelling-variabele-rente/"},
                {"t": "Anti-speculatieboete bij aflossen binnen 3 jaar: 3% / 2% / 1%.", "check": "anti-speculatie boete",
                 "url": "https://www.solidbriq.nl/hoe-financieren/flexibel-in-de-toekomst/"}]},
    {"id": "mogelijk", "naam": "Mogelijk", "url": "https://www.mogelijk.nl/verhuurhypotheek",
     "tabellen": [{"seg": "residentieel", "url": "https://www.mogelijk.nl/verhuurhypotheek", "start": "Rente vanaf",
                   "end": "Let op: Deze rentes", "naam": "verhuurhypotheek", "laatste_start": True}],
     "feiten": [{"t": "Kosten: eenmalig 1% van de leensom, minimaal € 2.250 (via een intermediair geen afsluitprovisie).",
                 "check": "eenmalig 1% over de leensom, met een minimum bedrag van € 2.250"},
                {"t": "Financiering vanaf € 50.000.", "check": "vanaf € 50.000",
                 "url": "https://www.mogelijk.nl/verhuurhypotheek"},
                {"t": "Maximale LTV 85%; tot 75% aflossingsvrij.", "check": "Maximale LTV 85%"}]},
    {"id": "build", "naam": "Build", "url": "https://build-finance.com/rentes",
     "tabellen": [{"seg": "residentieel", "url": "https://build.quantleap.nl/widgets/rates", "start": "Looptijd",
                   "end": "* Commercieel", "klik": ["Build GO!", "Zelfstandige woonruimtes"],
                   "naam": "Build GO! · zelfstandige woonruimtes"}],
     "datum": r"Rentetarieven per (\d{2}-\d{2}-\d{4})",
     "feiten": [{"t": "Bij leningen tot € 1.000.000 geldt een opslag van 0,2%.", "check": "leningen tot € 1.000.000 geldt een opslag",
                 "url": "https://build.quantleap.nl/widgets/rates"},
                {"t": "Financieringen van € 250.000 tot € 15 miljoen.", "check": "van € 250.000 tot € 15 miljoen",
                 "url": "https://build-finance.com/vastgoed-financieren/"}]},
    {"id": "hyra", "naam": "Hyra", "url": "https://hyra.nl/", "tabellen": [],
     "reden": "geen website met tarieven gevonden (hyra.nl staat te koop)"},
    {"id": "casarion", "naam": "Casarion", "url": "https://www.casarion.com/rente-residentieel",
     "tabellen": [{"seg": "residentieel", "url": "https://www.casarion.com/rente-residentieel",
                   "start": "Actuele rente residentieel vastgoed", "end": "Het is mogelijk", "naam": "residentieel"},
                  {"seg": "commercieel", "url": "https://www.casarion.com/rente-commercieel",
                   "start": "Actuele rente commercieel vastgoed", "end": "Het is mogelijk", "naam": "commercieel"}],
     "feiten": [{"t": "Geen kortingen verwerkt: energielabel A/B 0,10% korting.", "check": "korting van 0,10%",
                 "url": "https://www.casarion.com/rente-residentieel"},
                {"t": "Lagere rente mogelijk met disagio (1–4% van de leensom, vanaf 5 jaar vast).",
                 "check": "disagio van 1%, 2%, 3% of 4%", "url": "https://www.casarion.com/rente-residentieel"},
                {"t": "1 jaar vast = '1 jr + Switch' (voorwaarden Casarion SWITCH).", "check": "1 jr + Switch",
                 "url": "https://www.casarion.com/rente-residentieel"}]},
]


MAAND = {m: i + 1 for i, m in enumerate(["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"])}


def bron_dag(d, vandaag):
    """Datum die de aanbieder zelf noemt ('22-10-2026' of '28 okt.') -> 'JJJJ-MM-DD'; anders vandaag."""
    if d:
        m = re.match(r"(\d{2})-(\d{2})-(\d{4})$", d)
        if m:
            iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            return iso if iso <= vandaag else vandaag
        m = re.match(r"(\d{1,2}) (\w{3})", d)
        if m and m.group(2).lower() in MAAND:
            j = int(vandaag[:4])
            iso = f"{j}-{MAAND[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
            if iso > vandaag:
                iso = f"{j - 1}{iso[4:]}"
            return iso
    return vandaag


def norm_fix(label):
    t = label.lower()
    if t.startswith("variabel") or t == "1 maand":  # 1 maand vast = maandelijks herziene (variabele) rente
        return "var"
    m = re.match(r"(\d{1,2})", t)
    return m.group(1) if m else None


def parse_grid(tekst):
    """Tekst van één rentetabel -> {"ltv": [..], "rows": [{"fix", "label", "rates"}]} of None (niet volledig)."""
    tokens = [t.strip() for regel in tekst.splitlines() for t in regel.split("\t") if t.strip()]
    ltv, labels, rows, cur = [], [], [], []
    for t in tokens:
        m = PCT.match(t)
        if m:
            if not ltv:
                continue  # percentage buiten de tabel (bv. "Rente vanaf 5,95%")
            cur.append(float(m.group(1).replace(",", ".")))
            if len(cur) == len(ltv):
                if not labels:
                    return None
                lab = labels.pop(0)
                rows.append({"fix": norm_fix(lab), "label": lab, "rates": cur})
                cur = []
        elif LABEL.match(t):
            if cur:
                return None  # onvolledige rij
            labels.append(t)
        elif not rows and not cur and len(t) <= 22 and HEAD.search(t) and "," not in t:
            v = int(HEAD.findall(t)[-1])
            if v not in ltv:
                ltv.append(v)
    if cur or labels or not rows or ltv != sorted(ltv):
        return None
    if any(not (2 <= r <= 15) for row in rows for r in row["rates"]) or any(row["fix"] is None for row in rows):
        return None
    return {"ltv": ltv, "rows": rows}


def blok(tekst, start, end, laatste=False):
    i = tekst.rfind(start) if laatste else tekst.find(start)
    if i < 0:
        return None
    j = tekst.find(end, i + len(start))
    return tekst[i + len(start): j if j > 0 else None]


def mag(url, cache={}):  # noqa: B006
    host = "/".join(url.split("/")[:3])
    if host not in cache:
        rp = urllib.robotparser.RobotFileParser(host + "/robots.txt")
        try:
            rp.read()
            cache[host] = rp
        except Exception as e:  # noqa: BLE001
            print(f"  robots.txt {host}: {e}")
            cache[host] = None
    rp = cache[host]
    if rp is None:
        return None  # robots.txt niet bereikbaar (site reageert niet)
    return rp.can_fetch(UA, url)


def t_frame(pg, spec):
    """Tekst van een tabblad in een iframe: spec = (deel van frame-url, alt-tekst van de tabknop)."""
    deel, tab = spec
    f = next((f for f in pg.frames if deel in f.url), None)
    if not f:
        raise RuntimeError(f"frame {deel} niet gevonden")
    knop = f.locator(f'button:has(img[alt="{tab}"])').first
    if knop.get_attribute("disabled") is None:  # niet al gekozen: aanklikken
        knop.click(timeout=5000)
        pg.wait_for_timeout(1200)
    if knop.get_attribute("disabled") is None:
        raise RuntimeError(f"tabblad {tab} niet actief geworden")
    print(f"  frame-tabblad {tab!r} actief")
    txt = f.inner_text("body")
    return txt


def nibc_historie(pg):
    """NIBC publiceert oude rentetabellen via een periodekeuze. Geeft [[datum, grid], …] (oud -> nieuw)."""
    uit = []
    try:
        sel = next((s for s in pg.locator("select").all()
                    if re.search(r"\d{2}-\d{2}-\d{4}", s.inner_text() or "")), None)
        if not sel:
            print("  nibc historie: geen periodekeuze gevonden")
            return uit
        opties = [o for o in sel.locator("option").all()]
        waarden = [(o.get_attribute("value"), (o.inner_text() or "").strip()) for o in opties]
        for val, txt in waarden:
            m = re.search(r"(\d{2})-(\d{2})-(\d{4})", txt)
            if not m:
                continue
            sel.select_option(value=val)
            pg.wait_for_timeout(700)
            g = parse_grid(blok(pg.inner_text("body"), "Periode", "Let op: deze rentes") or "")
            if g:
                uit.append([f"{m.group(3)}-{m.group(2)}-{m.group(1)}", g])
        print(f"  nibc historie: {len(uit)} van {len(waarden)} periodes gelezen")
    except Exception as e:  # noqa: BLE001
        print(f"  nibc historie: {e}")
    return sorted(uit)


def main():
    from playwright.sync_api import sync_playwright

    nu = datetime.now(timezone.utc)
    vandaag = nu.strftime("%Y-%m-%d")
    try:
        hist = json.loads(HIST.read_text())
    except Exception:  # noqa: BLE001
        hist = {}
    uit = {"updated": nu.strftime("%Y-%m-%dT%H:%M:%SZ"), "lenders": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=UA, locale="nl-NL")
        paginas = {}

        def open_pagina(url, klik=None):
            key = (url, str(klik))
            if key in paginas:
                return paginas[key]
            if not mag(url):
                paginas[key] = (None, "robots")
                return paginas[key]
            pg = ctx.new_page()
            try:
                pg.goto(url, wait_until="networkidle", timeout=45000)
                pg.wait_for_timeout(2500)
                for k in ([klik] if isinstance(klik, str) else (klik or [])):
                    els = [e for e in pg.get_by_text(k, exact=True).all() if e.is_visible()]
                    if not els:
                        raise RuntimeError(f"knop {k!r} niet zichtbaar")
                    els[0].click(timeout=5000)
                    pg.wait_for_timeout(1500)
                    st = els[0].evaluate("e => (e.className||'') + ' ' + (e.getAttribute('aria-selected')||'') + ' ' + "
                                         "((e.closest('[class]')||{}).className||'')")
                    print(f"  klik {k!r} op {url}: {st[:120]}")
                paginas[key] = (pg, None)
            except Exception as e:  # noqa: BLE001
                print(f"  {url}: {e}")
                paginas[key] = (None, "fout")
            return paginas[key]

        for a in AANBIEDERS:
            r = {"id": a["id"], "name": a["naam"], "url": a["url"], "checked": vandaag, "segments": [], "facts": []}
            if a.get("reden"):
                r["status"], r["reason"] = "aanvraag", a["reden"]
            elif mag(a["url"]) is None:
                r["status"], r["reason"] = "aanvraag", "website niet bereikbaar voor automatische controle"
            elif not mag(a["url"]):
                r["status"], r["reason"] = "aanvraag", "de website staat automatisch uitlezen niet toe (robots.txt)"
            else:
                hoofd, fout = open_pagina(a["url"])
                if fout:
                    r["status"], r["reason"] = "aanvraag", "website niet bereikbaar voor automatische controle"
                hoofdtekst = (hoofd.inner_text("body") if hoofd else "").replace("\xa0", " ")
                if hoofd:  # datum kan ook in een iframe staan
                    hoofdtekst += " ".join(f.inner_text("body") for f in hoofd.frames[1:] if "interests" in f.url)
                if a.get("datum") and hoofdtekst:
                    m = re.search(a["datum"], hoofdtekst)
                    r["source_date"] = m.group(1) if m else None
                for t in a["tabellen"]:
                    pg, fout = open_pagina(t["url"], t.get("klik"))
                    if not pg:
                        continue
                    try:
                        tekst = (t_frame(pg, t["frame"]) if t.get("frame") else pg.inner_text("body")).replace("\xa0", " ")
                    except Exception as e:  # noqa: BLE001
                        print(f"  {a['naam']} {t['naam']}: {e}")
                        continue
                    if a.get("datum") and not r.get("source_date"):
                        m = re.search(a["datum"], tekst)
                        r["source_date"] = m.group(1) if m else None
                    g = parse_grid(blok(tekst, t["start"], t["end"], t.get("laatste_start")) or "")
                    if g:
                        r["segments"].append({"seg": t["seg"], "name": t["naam"], "src": t["url"], **g})
                        print(f"  {a['naam']} {t['naam']}: LTV {g['ltv']}, "
                              f"{[(row['label'], row['rates']) for row in g['rows']]}")
                    else:
                        print(f"  {a['naam']} {t['naam']}: tabel niet volledig leesbaar, niet gebruikt. Blok: "
                              f"{(blok(tekst, t['start'], t['end'], t.get('laatste_start')) or '')[:700]!r}")
                    if a["id"] == "nibc" and not hist.get("nibc_backfill"):
                        reeks = hist.setdefault("nibc|residentieel", [])
                        for d, gr in nibc_historie(pg):
                            snap = {row["fix"]: dict(zip(map(str, gr["ltv"]), row["rates"])) for row in gr["rows"]}
                            if d not in {x[0] for x in reeks}:
                                reeks.append([d, snap])
                        reeks.sort(key=lambda x: x[0])
                        hist["nibc_backfill"] = vandaag
                # vaste kenmerken alleen als de controlezin nog op de bron staat
                for f in a.get("feiten", []):
                    bron = f.get("url") or a["url"]
                    pg, _ = open_pagina(bron)
                    txt = " ".join(((pg.inner_text("body") + " " + re.sub(r"<[^>]+>", " ", pg.content())) if pg else "")
                                   .replace("\xa0", " ").split())
                    if " ".join(f["check"].split()) in txt:
                        r["facts"].append({"t": f["t"], "src": bron})
                    else:
                        print(f"  {a['naam']}: kenmerk niet meer gevonden: {f['check']!r}")
                r["status"] = "ok" if r["segments"] else "aanvraag"
                if not r["segments"] and not r.get("reason"):
                    r["reason"] = "geen leesbare rentetabel gepubliceerd"
            uit["lenders"].append(r)
            # historie: momentopname per dag, alleen bij een wijziging
            gezien = set()
            for s in r["segments"]:
                key = f"{a['id']}|{s['seg']}" + (f"|{s['name']}" if s["seg"] in gezien else "")
                gezien.add(s["seg"])
                snap = {row["fix"]: dict(zip(map(str, s["ltv"]), row["rates"])) for row in s["rows"]}
                reeks = hist.setdefault(key, [])
                dag = bron_dag(r.get("source_date"), vandaag)
                if not reeks or reeks[-1][1] != snap:
                    reeks = [x for x in reeks if x[0] != dag]
                    reeks.append([dag, snap])
                    reeks.sort(key=lambda x: x[0])
                    hist[key] = reeks
            sys.stdout.flush()
        b.close()
    OUT.write_text(json.dumps(uit, ensure_ascii=False, indent=1) + "\n")
    HIST.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")) + "\n")
    ok = [x["name"] for x in uit["lenders"] if x["status"] == "ok"]
    print(f"vastgoedrentes: {len(ok)} aanbieders met tarieven ({', '.join(ok)})")


if __name__ == "__main__":
    main()
