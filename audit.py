"""Data-audit: controleert ieder rente-, inflatie- en woningprijscijfer op de site (docs/data.json) tegen
de originele bron. Haalt alles opnieuw op via een ándere route dan de site zelf (ECB: SDMX-JSON in plaats
van CSV; Eurostat/CBS: per land/kolom apart) en schrijft audit/rapport.md.

Draaien: python audit.py   (in GitHub Actions: workflow 'Data-audit')
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "docs" / "data.json"
OUT = ROOT / "audit" / "rapport.md"
ECB = "https://data-api.ecb.europa.eu/service/data/"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
CBS = "https://opendata.cbs.nl/ODataApi/odata/85773NED"
TOL = 0.0051  # bronnen publiceren 2 decimalen


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "investmarket-audit/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"  {url[:100]}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  {url[:100]}: {e}")
        time.sleep(3 * (i + 1))
    return None


def ecb_json(key, n):
    """SDMX-JSON van de ECB -> [[periode, waarde], …] (oud -> nieuw) + titel. Eén reeks."""
    txt = get(f"{ECB}{key}?lastNObservations={n}&format=jsondata")
    if not txt:
        return None, None
    js = json.loads(txt)
    tijden = [v["id"] for v in js["structure"]["dimensions"]["observation"][0]["values"]]
    reeksen = js["dataSets"][0]["series"]
    if len(reeksen) != 1:
        return None, f"{len(reeksen)} reeksen"
    reeks = next(iter(reeksen.values()))
    obs = sorted([tijden[int(i)], round(float(v[0]), 4)] for i, v in reeks["observations"].items() if v[0] is not None)
    attrs = js["structure"].get("attributes", {}).get("series", [])
    titel = next((a["values"][reeks["attributes"][i]]["name"] for i, a in enumerate(attrs)
                  if a["id"] == "TITLE" and i < len(reeks.get("attributes", [])) and reeks["attributes"][i] is not None),
                 "")
    return obs, titel


def key_uit_link(src):
    """https://data.ecb.europa.eu/data/datasets/MIR/MIR.M.NL… -> MIR/M.NL…"""
    deel = src.rstrip("/").split("/datasets/")[1].split("/", 1)[1]
    ds, rest = deel.split(".", 1)
    return f"{ds}/{rest}"


def eurostat_een(dataset, params, n):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    txt = get(f"{EUROSTAT}{dataset}?{q}&lastTimePeriod={n}")
    if not txt:
        return None, None
    js = json.loads(txt)
    tijd = js["dimension"]["time"]["category"]["index"]
    for d, size in zip(js["id"], js["size"]):
        if d != "time" and size != 1:
            return None, f"dimensie {d} heeft {size} waarden"
    obs = sorted([t, round(float(js["value"][str(i)]), 4)] for t, i in tijd.items() if str(i) in js["value"])
    return obs, str(js.get("updated") or "")[:10]


rijen, ontbreekt = [], []


def vergelijk(naam, site, bron_obs, bron_label, extra=""):
    """site: {"value","date","prev","prev_date"}; bron_obs: [[periode, waarde], …]."""
    if not site:
        rijen.append((naam, "–", "–", bron_label, "❔ niet op de site"))
        return
    if not bron_obs:
        rijen.append((naam, f"{site.get('value')} ({site.get('date')})", "bron gaf geen antwoord", bron_label,
                      "⚠️ niet te controleren"))
        return
    bron = dict(map(tuple, bron_obs))
    laatste = bron_obs[-1]
    fouten = []
    if site.get("date") not in bron:
        fouten.append(f"periode {site.get('date')} niet in bron")
    elif abs(bron[site["date"]] - site["value"]) > TOL:
        fouten.append(f"waarde {site['value']} ≠ bron {bron[site['date']]}")
    if laatste[0] != site.get("date"):
        fouten.append(f"niet actueel: bron heeft al {laatste[0]} ({laatste[1]})")
    if site.get("prev") is not None:
        pd_ = site.get("prev_date")
        if pd_ and pd_ in bron and abs(bron[pd_] - site["prev"]) > TOL:
            fouten.append(f"vorige {site['prev']} ≠ bron {bron[pd_]}")
        if pd_ and site.get("date") in bron and pd_ in bron:
            pp_site = round(site["value"] - site["prev"], 4)
            pp_bron = round(bron[site["date"]] - bron[pd_], 4)
            if abs(pp_site - pp_bron) > 2 * TOL:
                fouten.append(f"pp-verschil {pp_site} ≠ bron {pp_bron}")
    tekst_site = f"{site['value']}% ({site.get('date')})"
    if site.get("prev") is not None:
        tekst_site += f", vorige {site['prev']}% ({site.get('prev_date') or '?'})"
    tekst_bron = f"{bron.get(site.get('date'), '–')}% ({site.get('date')})"
    if site.get("prev_date") in bron:
        tekst_bron += f", vorige {bron[site['prev_date']]}% ({site['prev_date']})"
    rijen.append((naam, tekst_site, tekst_bron + extra, bron_label,
                  "✅ klopt" if not fouten else "❌ " + "; ".join(fouten)))


def main():
    data = json.loads(DATA.read_text())
    m = data.get("macro") or {}

    # ECB-beleidsrentes: huidig niveau, vorig niveau en ingangsdatum
    for naam, label, key in (("ecb_deposit", "ECB depositorente", "FM/D.U2.EUR.4F.KR.DFR.LEV"),
                             ("ecb_mro", "ECB herfinancieringsrente", "FM/D.U2.EUR.4F.KR.MRR_FR.LEV")):
        obs, _ = ecb_json(key, 500)
        s = m.get(naam)
        if not obs or not s:
            rijen.append((label, str(s and s.get("value")), "–", "ECB", "⚠️ niet te controleren"))
            continue
        cur = obs[-1][1]
        i = next((j for j in range(len(obs) - 1, -1, -1) if obs[j][1] != cur), None)
        prev, since = (obs[i][1], obs[i + 1][0]) if i is not None else (None, None)
        f = []
        if abs(cur - s["value"]) > TOL:
            f.append(f"niveau {s['value']} ≠ {cur}")
        if prev is not None and s.get("prev") is not None and abs(prev - s["prev"]) > TOL:
            f.append(f"vorig niveau {s['prev']} ≠ {prev}")
        if since and s.get("since") != since:
            f.append(f"ingangsdatum {s.get('since')} ≠ {since}")
        rijen.append((label, f"{s['value']}% sinds {s.get('since')}, vorig {s.get('prev')}%",
                      f"{cur}% sinds {since}, vorig {prev}%", f"ECB ({key})", "✅ klopt" if not f else "❌ " + "; ".join(f)))

    for naam, label in (("euribor3m", "Euribor 3 maanden (maandgem.)"), ("nl10y", "Staatsrente NL 10 jaar (maandgem.)"),
                        ("nfc_loans_nl", "Zakelijke leningen NL, totaal")):
        s = m.get(naam)
        key = key_uit_link(s["src"]) if s and s.get("src") else None
        obs, titel = ecb_json(key, 6) if key else (None, None)
        vergelijk(label, s, obs, f"ECB ({key})", f" – “{titel}”" if titel else "")

    for h in m.get("mortgage_nl") or []:
        key = key_uit_link(h["src"])
        obs, titel = ecb_json(key, 6)
        vergelijk(f"Hypotheek {h['label']}", h, obs, f"DNB via ECB ({key})", f" – “{titel}”" if titel else "")

    for b in m.get("business_nl") or []:
        key = key_uit_link(b["src"])
        obs, titel = ecb_json(key, 6)
        vergelijk(f"Zakelijk {b['amount_label']} / {b['fix_label']}", b, obs, f"DNB via ECB ({key})")

    # HICP per land apart
    h = m.get("hicp") or {}
    for geo, label in (("NL", "Inflatie NL (HICP)"), ("EA20", "Inflatie eurozone (HICP)"), ("EU27_2020", "Inflatie EU")):
        serie = h.get(geo)
        if not serie:
            continue
        obs, upd = eurostat_een("prc_hicp_minr", {"geo": geo, "coicop18": "TOTAL", "unit": "RCH_A", "freq": "M"}, 6)
        site = {"value": serie[-1][1], "date": serie[-1][0], "prev": serie[-2][1] if len(serie) > 1 else None,
                "prev_date": serie[-2][0] if len(serie) > 1 else None}
        vergelijk(label, site, obs, "Eurostat prc_hicp_minr", f" (Eurostat bijgewerkt {upd})" if upd else "")

    # Woningprijzen: Eurostat (kwartaal, alle woningen) en CBS (maand, bestaande koopwoningen)
    hp = m.get("house_prices_nl")
    euro = None
    if hp:
        euro, upd = eurostat_een("prc_hpi_q", {"geo": "NL", "purchase": "TOTAL", "unit": "RCH_A", "freq": "Q"}, 6)
        site = {"value": hp[-1][1], "date": hp[-1][0], "prev": hp[-2][1], "prev_date": hp[-2][0]}
        vergelijk("Woningprijzen NL (Eurostat, kwartaal)", site, euro, "Eurostat prc_hpi_q",
                  f" (Eurostat bijgewerkt {upd})" if upd else "")
    cbs_site = m.get("house_prices_cbs")
    cbs_obs = None
    try:
        props = json.loads(get(CBS + "/DataProperties?$format=json") or "{}").get("value") or []
        kol = next((p["Key"] for p in props if p.get("Type") == "Topic" and "jaar eerder" in p.get("Title", "").lower()), None)
        if kol:
            q = urllib.parse.quote("substringof('MM',Perioden)")
            rows = json.loads(get(f"{CBS}/TypedDataSet?$format=json&$filter={q}") or "{}").get("value") or []
            cbs_obs = sorted([f"{r['Perioden'][:4]}-{r['Perioden'][6:8]}", round(float(r[kol]), 4)]
                             for r in rows if r.get(kol) is not None)
    except Exception as e:  # noqa: BLE001
        print(f"  cbs: {e}")
    if cbs_site:
        s = cbs_site["series"]
        vergelijk("Woningprijzen NL (CBS, maand)", {"value": s[-1][1], "date": s[-1][0], "prev": s[-2][1],
                                                   "prev_date": s[-2][0]}, cbs_obs, "CBS 85773NED")
    elif cbs_obs:
        ontbreekt.append(f"CBS-woningprijzen staan nog niet op de site (bron heeft {cbs_obs[-1]}).")
    # Eurostat-kwartaal naast het CBS-kwartaalgemiddelde (andere definitie: Eurostat = alle woningen incl. nieuwbouw)
    if euro and cbs_obs:
        q = euro[-1][0]  # bv. 2026-Q2
        jaar, kw = q.split("-Q")
        maanden = [f"{jaar}-{int(kw) * 3 - 2 + i:02d}" for i in range(3)]
        cb = dict(map(tuple, cbs_obs))
        if all(mm in cb for mm in maanden):
            gem = round(sum(cb[mm] for mm in maanden) / 3, 2)
            ontbreekt.append(f"Ter vergelijking {q}: Eurostat {euro[-1][1]}% (alle woningen) vs. CBS gemiddeld "
                             f"{gem}% (bestaande koopwoningen, maanden {', '.join(maanden)}). Verschil komt door de "
                             f"definitie (nieuwbouw wel/niet) en de methode, niet door een fout.")

    # Rapport
    OUT.parent.mkdir(parents=True, exist_ok=True)
    nu = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    goed = sum(r[4].startswith("✅") for r in rijen)
    fout = sum(r[4].startswith("❌") for r in rijen)
    regels = [f"# Data-audit InvestMarket – {nu}", "",
              f"Gecontroleerd: {len(rijen)} cijfers · ✅ {goed} kloppen · ❌ {fout} wijken af · "
              f"⚠️ {len(rijen) - goed - fout} niet te controleren.", "",
              f"Site-data van {data.get('updated')}.", "",
              "| Cijfer | Op de site | In de bron | Bron | Uitkomst |", "|---|---|---|---|---|"]
    regels += [f"| {' | '.join(str(c).replace('|', '/') for c in r)} |" for r in rijen]
    if ontbreekt:
        regels += ["", "## Opmerkingen", ""] + [f"- {o}" for o in ontbreekt]
    OUT.write_text("\n".join(regels) + "\n")
    print("\n".join(regels))


if __name__ == "__main__":
    main()
