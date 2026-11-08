"""Rendement per kalenderjaar in bereken() (nagemaakte koersen, geen netwerk)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import bereken  # noqa: E402


def _df(punten):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in punten])
    v = [x for _, x in punten]
    return pd.DataFrame({"Close": v, "High": v}, index=idx)


def test_jaren_volledige_kalenderjaren():
    df = _df([("2023-12-29", 100.0), ("2024-06-28", 150.0), ("2024-12-31", 120.0),
              ("2025-12-31", 90.0), ("2026-11-06", 95.0)])
    j = bereken(df)["jaren"]
    assert j == {"2024": 20.0, "2025": -25.0}  # 2023 en 2026 zijn geen volledige jaren


def test_jaren_niet_als_notering_pas_later_begon():
    # eerste koers medio 2024: 2024 telt niet (geen slotkoers eind 2023), 2025 wel
    df = _df([("2024-06-03", 50.0), ("2024-12-31", 60.0), ("2025-12-31", 66.0), ("2026-11-06", 70.0)])
    assert bereken(df)["jaren"] == {"2025": 10.0}
