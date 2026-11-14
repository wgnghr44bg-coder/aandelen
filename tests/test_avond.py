"""Avondkoers als slot van afgelopen dagen (zoals de broker-app 'vandaag' rekent; geen netwerk)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd  # noqa: E402
from update import TZ_NL, avond_bijwerken, avond_venster, met_avond  # noqa: E402


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


def test_avondkoers_alleen_op_de_avond_van_de_handelsdag():
    def nu(x):
        return pd.Timestamp(x, tz=TZ_NL)
    assert avond_venster("2026-11-13", nu("2026-11-13 19:30"))          # vrijdagavond: avondkoers
    assert not avond_venster("2026-11-13", nu("2026-11-13 16:00"))      # overdag: Xetra
    assert not avond_venster("2026-11-13", nu("2026-11-13 23:10"))      # na de avondhandel: officiële slot
    assert not avond_venster("2026-11-13", nu("2026-11-14 12:30"))      # zaterdag: officiële slot (zoals IBKR)
