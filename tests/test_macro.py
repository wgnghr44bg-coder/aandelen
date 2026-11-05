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


STRUCT_XML = """<?xml version="1.0"?>
<m:Structure xmlns:m="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
 xmlns:s="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
 xmlns:c="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"><m:Structures>
<s:Codelists>
 <s:Codelist id="CL_AMOUNT_CAT"><s:Code id="A"><c:Name xml:lang="en">Total</c:Name></s:Code>
  <s:Code id="0"><c:Name xml:lang="en">Up to and including EUR 1 million</c:Name></s:Code>
  <s:Code id="1"><c:Name xml:lang="en">Over EUR 1 million</c:Name></s:Code>
  <s:Code id="2"><c:Name xml:lang="en">Up to and including EUR 0.25 million</c:Name></s:Code></s:Codelist>
 <s:Codelist id="CL_MAT"><s:Code id="A"><c:Name xml:lang="en">Total</c:Name></s:Code>
  <s:Code id="F"><c:Name xml:lang="en">Floating rate and up to 1 year</c:Name></s:Code>
  <s:Code id="P"><c:Name xml:lang="en">Over 10 years</c:Name></s:Code>
  <s:Code id="J"><c:Name xml:lang="en">Over 5 years</c:Name></s:Code></s:Codelist>
 <s:Codelist id="CL_X"><s:Code id="M"><c:Name xml:lang="en">Monthly</c:Name></s:Code></s:Codelist>
</s:Codelists>
<s:DataStructures><s:DataStructure id="ECB_MIR1"><s:DataStructureComponents><s:DimensionList>
""" + "".join(
    f'<s:Dimension id="{d}" position="{i + 1}"><s:LocalRepresentation><s:Enumeration><Ref id="{cl}"/>'
    f'</s:Enumeration></s:LocalRepresentation></s:Dimension>'
    for i, (d, cl) in enumerate([("FREQ", "CL_X"), ("REF_AREA", "CL_X"), ("BS_REP_SECTOR", "CL_X"),
                                 ("BS_ITEM", "CL_X"), ("MATURITY_NOT_IRATE", "CL_MAT"), ("DATA_TYPE_MIR", "CL_X"),
                                 ("AMOUNT_CAT", "CL_AMOUNT_CAT"), ("BS_COUNT_SECTOR", "CL_X"),
                                 ("CURRENCY_TRANS", "CL_X"), ("IR_BUS_COV", "CL_X")])) + """
<s:TimeDimension id="TIME_PERIOD" position="11"/></s:DimensionList></s:DataStructureComponents>
</s:DataStructure></s:DataStructures></m:Structures></m:Structure>"""
NFC_CSV = """KEY,TIME_PERIOD,OBS_VALUE,TITLE
MIR.M.NL.B.A2A.F.R.1.2240.EUR.N,2026-08,3.30,x
MIR.M.NL.B.A2A.F.R.1.2240.EUR.N,2026-09,3.20,x
MIR.M.NL.B.A2A.P.R.0.2240.EUR.N,2026-09,4.05,x
MIR.M.NL.B.A2A.J.R.0.2240.EUR.N,2026-09,4.10,dubbel met P
MIR.M.NL.B.A2A.J.R.1.2240.EUR.N,2026-09,3.80,alleen J
MIR.M.NL.B.A2A.A.R.A.2240.EUR.N,2026-09,3.16,x
MIR.M.NL.B.A2A.F.R.2.2240.EUR.N,2026-09,4.40,deelbucket
MIR.M.NL.B.A2A.P.R.1.2240.EUR.N,2025-12,3.90,gestopt
MIR.M.NL.B.A2A.Z.R.1.2240.EUR.N,2026-09,9.99,onbekende code
"""


def test_zakelijk_per_bedrag(monkeypatch):
    monkeypatch.setattr(macro, "_get", lambda url, tries=3: STRUCT_XML if "references" in url
                        else NFC_CSV if "A2A" in url else None)
    rij = macro.zakelijk_nl()
    sleutels = [(r["amount"], r["fix"]) for r in rij]
    assert sleutels == [("0", "P"), ("1", "F"), ("1", "J"), ("A", "A")]  # gestopt/onbekend/deelbucket/dubbel weg
    groot = rij[1]
    assert groot["amount_label"] == "boven €1 mln" and groot["fix_label"] == "variabel tot 1 jaar"
    assert groot["value"] == 3.20 and groot["prev"] == 3.30
    assert rij[0]["amount_label"] == "tot en met €1 mln" and rij[0]["fix_label"] == "boven 10 jaar"
    assert groot["src"].endswith("MIR.M.NL.B.A2A.F.R.1.2240.EUR.N")


def test_zakelijk_zonder_codelijst_toont_niets(monkeypatch):
    monkeypatch.setattr(macro, "_get", lambda url, tries=3: None if "references" in url else NFC_CSV)
    assert macro.zakelijk_nl() is None
    assert macro.nl_label("Over EUR 0.25 million and up to and including EUR 1 million") == "boven €0,25 mln – €1 mln"
