"""Avondkoers van WEBN op een andere beurs na de Xetra-slotveiling (nagemaakte koersen, geen netwerk)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import kies_na_koers  # noqa: E402


def _r(*punten):
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="Europe/Amsterdam") for t, _ in punten]).tz_convert("UTC")
    return pd.Series([v for _, v in punten], index=idx)


def test_nieuwste_avondkoers_wint():
    r = kies_na_koers("2026-11-11", "17:25", {
        "WEBN.MU": _r(("2026-11-11 18:30", 13.22), ("2026-11-11 18:36", 13.228)),
        "WEBN.DU": _r(("2026-11-11 17:45", 13.19), ("2026-11-11 19:46", 13.204)),
    })
    assert r == {"p": 13.204, "t": "19:46", "beurs": "Düsseldorf"}


def test_overdag_of_andere_dag_niet():
    assert kies_na_koers("2026-11-11", "15:10", {"WEBN.MU": _r(("2026-11-11 15:30", 13.1))}) is None
    assert kies_na_koers("2026-11-11", "17:25", {"WEBN.MU": _r(("2026-11-10 21:50", 13.0))}) is None
    assert kies_na_koers("2026-11-11", "17:25", {"WEBN.MU": _r(("2026-11-11 17:30", 13.0))}) is None
    assert kies_na_koers("2026-11-11", "17:25", {"WEBN.MU": pd.Series(dtype=float)}) is None


def test_midden_van_bied_en_laat():
    from update import kies_mid
    # kleinste spread wint; te grote spread of ontbrekende prijzen tellen niet
    assert kies_mid({"WEBN.MU": (13.172, 13.208), "WEBN.DU": (13.18, 13.20)}) == (13.19, "Düsseldorf")
    assert kies_mid({"WEBN.MU": (13.0, 13.5), "WEBN.DU": (None, 13.2)}) is None
    assert kies_mid({"WEBN.MU": (13.3, 13.2)}) is None
