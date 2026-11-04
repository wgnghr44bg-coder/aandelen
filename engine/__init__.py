"""Fundamentele waarderingsengine voor StockHunter.

Opbouw (elke stap is een eigen module):
  data.py          – financiële data verwerken (normaliseren, valuta, kwaliteit)
  health.py        – Financial Health
  profitability.py – Profitability
  growth.py        – Growth
  valuation.py     – Valuation (absoluut, historisch en t.o.v. sector)
  moat.py          – Competitive Advantage
  dcf.py           – DCF (en DDM / residual income voor sectoren waar FCF-DCF niet past)
  scoring.py       – Fundamental Score (gewogen 0–100)
  decision.py      – BUY / HOLD / SELL / NO RATING
  run.py           – alles samen voor het hele universum (sectorvergelijking)

Alle berekeningen zijn deterministisch: dezelfde input geeft altijd hetzelfde advies.
"""
from .run import analyze_universe  # noqa: F401

ENGINE_VERSION = "1.0"
