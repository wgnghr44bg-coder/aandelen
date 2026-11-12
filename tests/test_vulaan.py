"""Ontbrekende laatste beursdag bij Yahoo aanvullen uit het archief (geen netwerk)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import lege_dag, vul_aan, vul_lege_dag  # noqa: E402


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


def test_lege_dag_uit_intraday():
    df = _df([("2026-11-09", 350.69), ("2026-11-10", 348.51), ("2026-11-11", float("nan"))])
    idx = pd.DatetimeIndex(["2026-11-10 15:55", "2026-11-11 15:50", "2026-11-11 15:55"]).tz_localize("America/New_York")
    intra = pd.Series([348.5, 355.7, 355.79], index=idx)
    uit = vul_lege_dag(df, intra)
    assert uit["Close"].iloc[-1] == 355.79 and len(uit["Close"].dropna()) == 3


def test_lege_dag_niets_als_geen_lege_rij_of_geen_intraday():
    df = _df([("2026-11-10", 348.51), ("2026-11-11", 355.63)])
    assert lege_dag(df) == []
    leeg = _df([("2026-11-10", 348.51), ("2026-11-11", float("nan"))])
    assert vul_lege_dag(leeg, None) is leeg
    oud = pd.Series([348.5], index=pd.DatetimeIndex(["2026-11-10 15:55"]).tz_localize("America/New_York"))
    assert pd.isna(vul_lege_dag(leeg, oud)["Close"].iloc[-1])  # geen koers van die dag: niets verzinnen


def test_lege_dag_ook_als_andere_beurs_al_verder_is():
    # download van veel beurzen: rij 12 nov bestaat (Azië), maar is leeg voor AAPL; 11 nov ook leeg
    df = _df([("2026-11-10", 348.51), ("2026-11-11", float("nan")), ("2026-11-12", float("nan"))])
    idx = pd.DatetimeIndex(["2026-11-11 15:50", "2026-11-11 15:55"]).tz_localize("America/New_York")
    uit = vul_lege_dag(df, pd.Series([355.7, 355.79], index=idx))
    c = uit["Close"].dropna()
    assert str(c.index[-1].date()) == "2026-11-11" and c.iloc[-1] == 355.79
