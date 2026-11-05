"""Tests voor het inlezen van ECB- en Eurostat-data (met nagemaakte antwoorden)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import macro  # noqa: E402

ECB_CSV = """KEY,FREQ,TIME_PERIOD,OBS_VALUE,TITLE
FM.D.U2.EUR.4F.KR.DFR.LEV,D,2025-06-10,2.25,Deposit facility
FM.D.U2.EUR.4F.KR.DFR.LEV,D,2025-06-11,2.0,Deposit facility
FM.D.U2.EUR.4F.KR.DFR.LEV,D,2025-06-12,2.0,Deposit facility
"""
MIR_CSV = """KEY,FREQ,TIME_PERIOD,OBS_VALUE,TITLE
MIR.M.NL.B.A2C.P.R.A.2250.EUR.N,M,2026-08,3.70,x
MIR.M.NL.B.A2C.P.R.A.2250.EUR.N,M,2026-09,3.65,x
MIR.M.NL.B.A2C.F.R.A.2250.EUR.N,M,2026-09,4.10,x
MIR.M.NL.B.A2C.A.R.A.2250.EUR.N,M,2026-09,3.80,totaal
"""
STAT = {"id": ["freq", "unit", "coicop", "geo", "time"], "size": [1, 1, 1, 2, 2],
        "dimension": {"freq": {"category": {"index": {"M": 0}}}, "unit": {"category": {"index": {"RCH_A": 0}}},
                      "coicop": {"category": {"index": {"CP00": 0}}},
                      "geo": {"category": {"index": {"EA20": 0, "NL": 1}}},
                      "time": {"category": {"index": {"2026-08": 0, "2026-09": 1}}}},
        "value": {"0": 2.1, "1": 2.2, "2": 3.0, "3": 2.9}}


def fake_get(url, tries=3):
    if "DFR" in url or "MRR" in url:
        return ECB_CSV
    if "A2C" in url:
        return MIR_CSV
    if "prc_hicp" in url:
        return json.dumps(STAT)
    if "ICP/M.NL" in url:
        return "KEY,TIME_PERIOD,OBS_VALUE\nICP.M.NL.N.000000.4.ANR,2026-10,2.8\nICP.M.NL.N.000000.4.ANR,2026-09,2.9\n"
    return None  # overige bronnen 'falen'


def test_macro_parsing(monkeypatch):
    monkeypatch.setattr(macro, "_get", fake_get)
    m = macro.haal_macro({"euribor3m": {"value": 2.0}})
    assert m["ecb_deposit"]["value"] == 2.0 and m["ecb_deposit"]["prev"] == 2.25
    assert m["ecb_deposit"]["since"] == "2025-06-11"
    hyp = {h["code"]: h for h in m["mortgage_nl"]}
    assert set(hyp) == {"F", "P"}                      # 'A' (totaal) niet als vaste periode
    assert hyp["P"]["value"] == 3.65 and hyp["P"]["prev"] == 3.70
    assert m["hicp"]["NL"] == [["2026-09", 2.9], ["2026-10", 2.8]]   # ECB (actueler) wint
    assert m["hicp"]["EA20"][-1] == ["2026-09", 2.2]
    assert m["euribor3m"] == {"value": 2.0}            # bron faalde -> vorige waarde
    assert "nl10y" not in m                            # geen vorige -> ontbreekt (niet verzonnen)


def test_markt_archief_wist_niets(tmp_path, monkeypatch):
    import update
    monkeypatch.setattr(update, "MARKT_HIST", tmp_path / "m.json")
    update.bewaar_markt_hist([{"ticker": "X", "h": [["2020-12-31", 1.0], ["2021-12-31", 2.0]]}])
    # later geeft de bron alleen recente jaren terug
    ex = [{"ticker": "X", "h": [["2027-01-04", 3.0], ["2021-12-31", 2.5]]}]
    update.bewaar_markt_hist(ex)
    assert ex[0]["h"] == [["2020-12-31", 1.0], ["2021-12-31", 2.5], ["2027-01-04", 3.0]]


def test_eerst_gezien(monkeypatch):
    from datetime import date
    assert macro.eerst_gezien("2026-09", None) is None                                   # niets bekend
    assert macro.eerst_gezien("2026-09", {"date": "2026-09"}) is None                    # al aanwezig, datum onbekend
    assert macro.eerst_gezien("2026-09", {"date": "2026-09", "upd": "2026-10-30"}) == "2026-10-30"
    assert macro.eerst_gezien("2026-10", {"date": "2026-09"}) == date.today().isoformat()  # nieuwe maand: vandaag


def test_cbs_woningprijzen(monkeypatch):
    antwoorden = {
        "/DataProperties": {"value": [{"Type": "TimeDimension", "Key": "Perioden"},
                                      {"Type": "Topic", "Key": "PrijsindexVerkoopprijzen_1", "Title": "Prijsindex verkoopprijzen"},
                                      {"Type": "Topic", "Key": "OntwikkelingTOVEenJaarEerder_3",
                                       "Title": "Ontwikkeling t.o.v. een jaar eerder"}]},
        "/TypedDataSet": {"value": [{"Perioden": "2026MM09", "OntwikkelingTOVEenJaarEerder_3": 4.1},
                                    {"Perioden": "2026MM08", "OntwikkelingTOVEenJaarEerder_3": 4.5},
                                    {"Perioden": "2025JJ00", "OntwikkelingTOVEenJaarEerder_3": 8.0}]},
        "/TableInfos": {"value": [{"Modified": "2026-10-22T02:00:00", "Title": "Bestaande koopwoningen"}]},
    }
    monkeypatch.setattr(macro, "_get", lambda url, tries=3: json.dumps(next(v for k, v in antwoorden.items() if k in url)))
    r = macro.cbs_woningprijzen()
    assert r["series"] == [["2026-08", 4.5], ["2026-09", 4.1]] and r["updated"] == "2026-10-22"
