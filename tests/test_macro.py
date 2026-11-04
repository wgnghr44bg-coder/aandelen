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
    return None  # overige bronnen 'falen'


def test_macro_parsing(monkeypatch):
    monkeypatch.setattr(macro, "_get", fake_get)
    m = macro.haal_macro({"euribor3m": {"value": 2.0}})
    assert m["ecb_deposit"]["value"] == 2.0 and m["ecb_deposit"]["prev"] == 2.25
    hyp = {h["code"]: h for h in m["mortgage_nl"]}
    assert set(hyp) == {"F", "P"}                      # 'A' (totaal) niet als vaste periode
    assert hyp["P"]["value"] == 3.65 and hyp["P"]["prev"] == 3.70
    assert m["hicp"]["NL"] == [["2026-08", 3.0], ["2026-09", 2.9]]
    assert m["hicp"]["EA20"][-1] == ["2026-09", 2.2]
    assert m["euribor3m"] == {"value": 2.0}            # bron faalde -> vorige waarde
    assert "nl10y" not in m                            # geen vorige -> ontbreekt (niet verzonnen)
