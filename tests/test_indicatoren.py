"""EMA 50/200 voor de grafieken (met nagemaakte koersen, geen netwerk)."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grondstoffen as g  # noqa: E402
import update  # noqa: E402
from indicatoren import ema  # noqa: E402


def test_ema_standaard():
    c = pd.Series([1.0, 2, 3, 4, 5, 6], index=pd.bdate_range("2026-01-05", periods=6))
    e = ema(c, 3)
    assert e.iloc[:2].isna().all()
    assert e.iloc[2] == 2.0                      # start: gewoon gemiddelde van de eerste 3
    assert abs(e.iloc[3] - (0.5 * 4 + 0.5 * 2)) < 1e-12   # k = 2/(3+1) = 0,5
    assert abs(e.iloc[5] - 5.0) < 1e-12
    assert ema(c, 10).isna().all()               # te weinig koersen: geen EMA
    vast = pd.Series(7.0, index=pd.bdate_range("2021-01-01", periods=300))
    assert (abs(ema(vast, 200).dropna() - 7.0) < 1e-9).all() and ema(vast, 200).notna().sum() == 101


def test_historie_met_ema(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "HIST", tmp_path / "history.json")
    idx = pd.bdate_range(end="2026-11-06", periods=5 * 260)
    close = pd.Series(np.linspace(50, 150, len(idx)), index=idx)
    kort = close.iloc[-120:]                      # nieuw aandeel: 120 koersen → wel EMA 50, geen EMA 200
    update.schrijf_historie(idx, {"A": close, "B": kort}, pd.Timestamp("2026-11-06"))
    h = json.loads((tmp_path / "history.json").read_text())
    a, b = h["series"]["A"], h["series"]["B"]
    for k in ("d50", "d200"):
        assert len(a[k]) == len(h["days"]) and None not in a[k]
    for k in ("w50", "w200"):
        assert len(a[k]) == len(h["weeks"])
    e50 = ema(close, 50)
    assert a["d50"][-1] == round(e50.iloc[-1], 2) and a["w50"][-1] == round(e50.iloc[-1], 2)
    assert a["w200"][0] is None and a["w200"][-1] is not None   # eerste 200 dagen: nog geen EMA 200
    assert "d200" not in b and b["d50"][-1] is not None and b["d50"][0] is None


def test_grondstof_historie_ema():
    idx = pd.bdate_range(end="2026-11-06", periods=1300)
    close = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    h = g.historie(close)
    assert len(h["d50"]) == len(h["days"]) and len(h["w200"]) == len(h["weeks"])
    assert h["d200"][-1] == round(ema(close, 200).iloc[-1], 4) == h["w200"][-1]
    assert h["w50"][0] is None
