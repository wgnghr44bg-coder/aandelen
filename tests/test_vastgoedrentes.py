"""Vastgoedrentes: tabellen lezen zoals ze op de bronpagina's staan (tekst uit de echte pagina's, nov 2026)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vastgoedrentes as v  # noqa: E402

NIBC = """Periode
Actuele rentes sinds 28 okt.
30-09-2026
16-09-2026
1 jaar
2 jaar
3 jaar
5 jaar
7 jaar
10 jaar
15 jaar
t/m
50% MW\tt/m
60% MW\tt/m
70% MW\tt/m
75% MW\tt/m
80% MW\tt/m
85% MW
\t6,15%\t6,15%\t6,20%\t6,30%\t6,50%\t6,85%
\t5,95%\t5,95%\t6,10%\t6,10%\t6,30%\t6,80%
\t5,90%\t5,90%\t6,05%\t6,05%\t6,25%\t6,75%
\t6,05%\t6,05%\t6,10%\t6,20%\t6,40%\t6,90%
\t6,30%\t6,30%\t6,35%\t6,45%\t6,65%\t7,15%
\t6,35%\t6,45%\t6,65%\t6,75%\t6,95%\t7,60%
\t6,60%\t6,70%\t6,90%\t7,00%\t7,20%\t7,65%
Let op: deze rentes zijn indicatief."""

DCMF = """Rentevast-periode
≤ 50% LTV
≤ 60% LTV
≤ 65% LTV
≤ 70% LTV
≤ 75% LTV
≤ 80% LTV
≤ 85% LTV
Rentevast-periode
≤ 50% LTV
≤ 60% LTV
≤ 65% LTV
≤ 70% LTV
≤ 75% LTV
≤ 80% LTV
≤ 85% LTV
1 jaar\t6,90%\t6,90%\t7,05%\t7,30%\t7,35%\t7,60%\t8,10%
3 jaar\t6,00%\t6,00%\t6,00%\t6,15%\t6,15%\t6,15%\t6,65%
5 jaar\t5,85%\t5,90%\t5,90%\t5,95%\t5,95%\t6,10%\t6,60%"""

MOGELIJK = """Rente vanaf 5,95%
LTV < 50%\tLTV >50% - 60%\tLTV >60% - 65%\tLTV >65% - 70%\tLTV >70% - 75%\tLTV >75% - 80%\tLTV 80% - 85%
3 jaar vast\t6,05%\t6,10%\t6,20%\t6,20%\t6,25%\t6,45%\t7,35%
5 jaar vast\t5,95%\t6,00%\t6,10%\t6,10%\t6,15%\t6,35%\t7,25%"""

CASARION = "\n".join(["50%", "55%", "60%", "65%", "70%", "75%", "80%", "85%", "Variabel"] + ["6,37%"] * 5 +
                     ["6,62%", "6,87%", "6,87%", "1 jr + Switch", "5,95%", "5,95%", "5,95%", "6,00%", "6,05%", "6,10%",
                      "6,30%", "7,05%"])


def test_nibc_labels_eerst():
    g = v.parse_grid(v.blok(NIBC, "Actuele rentes sinds", "Let op: deze rentes"))
    assert g["ltv"] == [50, 60, 70, 75, 80, 85]
    assert [r["fix"] for r in g["rows"]] == ["1", "2", "3", "5", "7", "10", "15"]
    assert g["rows"][3]["rates"] == [6.05, 6.05, 6.10, 6.20, 6.40, 6.90]


def test_dcmf_dubbele_kop_en_mogelijk_bandbreedte():
    g = v.parse_grid(DCMF)
    assert g["ltv"] == [50, 60, 65, 70, 75, 80, 85] and g["rows"][2]["rates"][0] == 5.85
    m = v.parse_grid(MOGELIJK)
    assert m["ltv"] == [50, 60, 65, 70, 75, 80, 85]          # bovengrens van elke LTV-klasse
    assert m["rows"][1]["fix"] == "5" and m["rows"][1]["rates"][-1] == 7.25


def test_casarion_en_onvolledig():
    g = v.parse_grid(CASARION)
    assert [r["fix"] for r in g["rows"]] == ["var", "1"] and g["rows"][1]["label"] == "1 jr + Switch"
    assert v.parse_grid(CASARION.rsplit("\n", 1)[0]) is None     # laatste rente ontbreekt -> niets gebruiken
    assert v.parse_grid("50%\n60%\n1 jaar\n45,00%\n6,00%") is None  # onlogische rente -> niets


def test_bron_dag():
    assert v.bron_dag("22-10-2026", "2026-11-05") == "2026-10-22"
    assert v.bron_dag("28 okt.", "2026-11-05") == "2026-10-28"
    assert v.bron_dag("28 dec.", "2027-01-03") == "2026-12-28"     # jaarwisseling
    assert v.bron_dag(None, "2026-11-05") == "2026-11-05"


def test_solidbriq_1_maand_is_variabel():
    g = v.parse_grid("Rentevaste periode\t≤ 50%\t≤ 55%\n1 maand\t5,30%\t5,30%\n5 jaar\t6,05%\t6,05%")
    assert [r["fix"] for r in g["rows"]] == ["var", "5"] and g["ltv"] == [50, 55]
