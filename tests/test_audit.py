"""Audit: SDMX-JSON lezen en vergelijken (met nagemaakte antwoorden)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit  # noqa: E402

SDMX = {"structure": {"dimensions": {"observation": [{"values": [{"id": "2026-08"}, {"id": "2026-09"}]}]},
                      "attributes": {"series": [{"id": "TITLE", "values": [{"name": "Bank interest rates"}]}]}},
        "dataSets": [{"series": {"0:0": {"attributes": [0], "observations": {"0": [4.4], "1": [4.36]}}}}]}


def test_ecb_json_en_vergelijk(monkeypatch):
    monkeypatch.setattr(audit, "get", lambda url, tries=3: json.dumps(SDMX))
    obs, titel = audit.ecb_json("MIR/X", 2)
    assert obs == [["2026-08", 4.4], ["2026-09", 4.36]] and titel == "Bank interest rates"
    audit.rijen.clear()
    audit.vergelijk("goed", {"value": 4.36, "date": "2026-09", "prev": 4.4, "prev_date": "2026-08"}, obs, "ECB")
    audit.vergelijk("fout", {"value": 4.30, "date": "2026-09", "prev": 4.4, "prev_date": "2026-08"}, obs, "ECB")
    audit.vergelijk("oud", {"value": 4.4, "date": "2026-08"}, obs, "ECB")
    uit = {r[0]: r[4] for r in audit.rijen}
    assert uit["goed"].startswith("✅")
    assert "waarde 4.3 ≠ bron 4.36" in uit["fout"] and "pp-verschil" in uit["fout"]
    assert "niet actueel" in uit["oud"]
    assert audit.key_uit_link("https://data.ecb.europa.eu/data/datasets/MIR/MIR.M.NL.B.A2C.F.R.A.2250.EUR.N") == \
        "MIR/M.NL.B.A2C.F.R.A.2250.EUR.N"
