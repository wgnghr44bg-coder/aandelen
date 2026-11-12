"""Avondkoers als slot van afgelopen dagen (zoals de broker-app 'vandaag' rekent; geen netwerk)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from update import avond_bijwerken, met_avond  # noqa: E402


def test_avond_onthouden_nieuwste_wint():
    av = {}
    avond_bijwerken(av, [{"ticker": "WEBN.DE", "na": {"p": 13.19}, "i": {"date": "2026-11-12"}}])
    avond_bijwerken(av, [{"ticker": "WEBN.DE", "na": {"p": 13.21}, "i": {"date": "2026-11-12"}},
                         {"ticker": "VALL.AS", "i": {"date": "2026-11-12"}}])  # zonder avondkoers: niets
    assert av == {"WEBN.DE@avond": {"2026-11-12": 13.21}}


def test_avond_alleen_voor_afgelopen_dagen():
    oud = {"2026-11-11": 13.176, "2026-11-12": 13.30}
    uit = met_avond(dict(oud), {"2026-11-11": 13.21, "2026-11-12": 13.25, "2026-11-01": 12.0}, "2026-11-12")
    assert uit == {"2026-11-11": 13.21, "2026-11-12": 13.30}  # vandaag blijft de koers van nu; geen nieuwe dagen
