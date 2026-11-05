"""Grondstoffen: eenheden, bandbreedte en terugval op een link (met nagemaakte koersen)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import grondstoffen as g  # noqa: E402
import update  # noqa: E402


def _df(prijs, dagen_oud=0):
    idx = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=dagen_oud), periods=300)
    c = np.linspace(prijs * 0.8, prijs, len(idx))
    return pd.DataFrame({"Close": c, "High": c * 1.01}, index=idx)


def test_grondstoffen(monkeypatch):
    frames = {"GC=F": _df(4000), "ZW=F": _df(540), "SI=F": _df(4000), "PL=F": _df(1000, dagen_oud=40)}
    data = pd.concat(frames, axis=1)
    monkeypatch.setattr(g.yf, "download", lambda *a, **k: data)
    uit, hist = g.haal_grondstoffen(update.bereken, update.spark)
    items = {it["id"]: it for grp in uit for it in grp["items"]}
    assert [grp["group"] for grp in uit][0] == "Edelmetalen" and len(items) == 31
    assert items["gold"]["price"] == 4000 and items["gold"]["src"].endswith("GC=F/")
    assert items["wheat"]["price"] == 5.4 and items["wheat"]["unit"] == "$/bushel"   # dollarcent -> dollar
    assert "price" not in items["silver"] and items["silver"]["link"]                 # buiten bandbreedte
    assert "price" not in items["platinum"]                                            # verouderd
    assert items["nickel"]["link"].endswith("/nickel") and "price" not in items["nickel"]
    assert items["wti"].get("link", "").endswith("/crude-oil")
    assert len(items["gold"]["spark"]) == 30 and items["gold"]["y1"] is not None
    h = hist["ZW=F"]
    assert set(hist) == {"GC=F", "ZW=F"} and len(h["days"]) == len(h["d"]) and len(h["weeks"]) == len(h["w"])
    assert h["d"][-1] == 5.4 and h["w"][-1] == 5.4 and h["weeks"][-1] == h["days"][-1]
