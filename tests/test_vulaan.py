"""Ontbrekende laatste beursdag bij Yahoo aanvullen uit het archief (geen netwerk)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import vul_aan  # noqa: E402


def _df(punten, tz=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in punten])
    if tz:
        idx = idx.tz_localize(tz)
    v = [x for _, x in punten]
    return pd.DataFrame({"Open": v, "Close": v, "High": v}, index=idx)


def test_ontbrekende_dag_aangevuld():
    df = _df([("2026-11-09", 12.902), ("2026-11-10", 12.924)])
    uit = vul_aan(df, [["2026-11-10", 12.924], ["2026-11-11", 13.185]])
    assert uit["Close"].iloc[-1] == 13.185
    assert str(uit.index[-1].date()) == "2026-11-11"
    assert len(uit) == 3


def test_met_tijdzone():
    df = _df([("2026-11-10", 4.33)], tz="Europe/Amsterdam")
    uit = vul_aan(df, [["2026-11-11", 4.414]])
    assert uit["Close"].iloc[-1] == 4.414 and uit.index.tz is not None


def test_niets_te_doen():
    df = _df([("2026-11-10", 12.924), ("2026-11-11", 13.1)])
    assert vul_aan(df, [["2026-11-11", 13.185]])["Close"].iloc[-1] == 13.1  # Yahoo heeft de dag: Yahoo wint
    assert vul_aan(df, None) is df
