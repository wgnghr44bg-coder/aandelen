"""Beursnaam per notering (om bv. ASML.AS en ASML uit elkaar te houden)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import beurs_naam  # noqa: E402


def test_beurs_uit_yahoo_code():
    assert beurs_naam("ASML", {"exchange": "NMS"}) == "Nasdaq"
    assert beurs_naam("JPM", {"exchange": "NYQ"}) == "NYSE"
    assert beurs_naam("ASML.AS", {"exchange": "AMS"}) == "Amsterdam"


def test_beurs_terugval_op_ticker():
    assert beurs_naam("ASML.AS", {}) == "Amsterdam"
    assert beurs_naam("0700.HK", None) == "Hongkong"
    assert beurs_naam("BRK-B", {}) == "VS"
    assert beurs_naam("XYZ.QQ", {}) is None
