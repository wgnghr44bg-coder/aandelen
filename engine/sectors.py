"""Sectorprofielen: elke sector heeft eigen normen, eigen gewichten en een passend waarderingsmodel.

Normen zijn (slecht, goed): de waarde die 0 punten geeft en de waarde die 100 punten geeft.
"""

# Financials die als bank/verzekeraar/vermogensbeheerder worden gewaardeerd (P/B, ROE, residual income).
# Betaalnetwerken (Visa, Mastercard), beurzen en ratingbureaus zijn asset-light en vallen hier niet onder.
BANKLIKE_INDUSTRY_PREFIXES = (
    "Banks", "Insurance - Life", "Insurance - Property", "Insurance - Diversified",
    "Insurance - Specialty", "Insurance - Reinsurance", "Capital Markets",
    "Asset Management", "Financial Conglomerates", "Mortgage Finance",
)
# Kredietverstrekkers met een bankbalans, door Yahoo ingedeeld als "Credit Services".
LENDERS = {"AXP", "COF", "SYF", "DFS", "ALLY"}


def profile_for(sector, industry, ticker):
    ind = industry or ""
    if sector == "Financial Services":
        if ticker in LENDERS or ind.startswith(BANKLIKE_INDUSTRY_PREFIXES):
            return "bank"
        return "fin_light"
    if sector == "Real Estate":
        return "reit"
    if sector == "Utilities":
        return "utility"
    if sector == "Communication Services" and ind.startswith("Telecom"):
        return "telecom"
    if sector in ("Technology", "Communication Services"):
        return "tech"
    return {
        "Healthcare": "health",
        "Consumer Defensive": "cons_def",
        "Consumer Cyclical": "cons_cyc",
        "Industrials": "industrial",
        "Energy": "cyclical",
        "Basic Materials": "cyclical",
    }.get(sector, "generic")


# Welk intrinsieke-waardemodel per profiel:
#   fcf = DCF op vrije kasstroom (EV - netto schuld)
#   ddm = dividend discount (nutsbedrijven/vastgoed: FCF structureel negatief door investeringen)
#   ri  = residual income (banken/verzekeraars: geen zinvolle vrije kasstroom of netto schuld)
MODEL = {"bank": "ri", "reit": "ddm", "utility": "ddm"}

# Cyclische sectoren: vrije kasstroom normaliseren over meerdere jaren.
CYCLICAL = {"cyclical"}

BASE_NORMS = {
    # Financial Health
    "de": (2.0, 0.3), "current": (0.8, 2.0), "quick": (0.5, 1.5), "int_cov": (2.0, 15.0),
    "nd_ebitda": (4.0, 0.0), "debt_assets": (0.6, 0.1), "cash_debt": (0.1, 1.0),
    "debt_dev": (0.15, -0.05), "equity_assets": (0.05, 0.12), "loss_years": (2, 0),
    "roa_min": (0.002, 0.01),
    # Profitability
    "roic": (0.05, 0.20), "roe": (0.05, 0.25), "roa": (0.02, 0.12), "gm": (0.20, 0.60),
    "om": (0.05, 0.30), "nm": (0.02, 0.20), "fcfm": (0.02, 0.20), "roic_trend": (-0.05, 0.03),
    "roe_trend": (-0.04, 0.02), "ffo_margin": (0.25, 0.60),
    # Growth
    "rev3": (0.0, 0.12), "rev5": (0.0, 0.12), "eps3": (-0.02, 0.15), "eps5": (-0.02, 0.15),
    "fcf_g": (-0.02, 0.15), "opinc_g": (-0.02, 0.15), "fwd_rev": (0.0, 0.12),
    "fwd_eps": (0.0, 0.15), "consistency": (0.4, 1.0), "bv_g": (0.0, 0.10),
    "ffo_g": (0.0, 0.08), "div_g": (0.0, 0.08),
    # Valuation
    "pe": (40.0, 12.0), "fpe": (35.0, 11.0), "peg": (3.0, 1.0), "ps": (10.0, 1.5),
    "pb": (8.0, 1.5), "pfcf": (45.0, 12.0), "ev_ebitda": (30.0, 8.0), "ev_ebit": (40.0, 10.0),
    "div_yield": (0.0, 0.04), "hist_rel": (1.5, 0.75), "sector_rel": (1.6, 0.7),
    "pb_just": (1.6, 0.8), "p_ffo": (26.0, 12.0),
    # Competitive Advantage
    "gm_level": (0.25, 0.65), "gm_stab": (0.08, 0.01), "om_stab": (0.08, 0.01),
    "roic_min": (0.06, 0.20), "roic_stab": (0.10, 0.02), "rev_stab": (0.15, 0.03),
    "rev_decl": (2, 0), "pricing": (-0.05, 0.03), "market_pos": (0.2, 0.9),
    "roe_min": (0.05, 0.14), "roe_stab": (0.06, 0.01), "nm_stab": (0.08, 0.02),
    "ffo_stab": (0.08, 0.02),
}

PROFILE_NORMS = {
    "tech": {"pe": (50, 18), "fpe": (40, 15), "ps": (14, 3), "pfcf": (50, 18), "ev_ebitda": (40, 12),
             "ev_ebit": (50, 15), "gm": (0.35, 0.70), "gm_level": (0.35, 0.75), "rev3": (0.03, 0.18),
             "fwd_rev": (0.02, 0.15), "eps3": (0.0, 0.18)},
    "health": {"pe": (40, 14), "fpe": (32, 12), "gm": (0.40, 0.75), "gm_level": (0.40, 0.75),
               "rev3": (0.0, 0.10)},
    "cons_def": {"pe": (35, 15), "fpe": (30, 14), "ps": (5, 1), "gm": (0.20, 0.50),
                 "gm_level": (0.20, 0.50), "rev3": (0.0, 0.07), "eps3": (0.0, 0.10),
                 "fwd_rev": (0.0, 0.06), "fwd_eps": (0.0, 0.10), "om": (0.04, 0.20)},
    "cons_cyc": {"pe": (40, 14), "gm": (0.20, 0.50), "gm_level": (0.20, 0.50), "om": (0.04, 0.20)},
    "industrial": {"pe": (35, 14), "ev_ebitda": (25, 9), "gm": (0.15, 0.40), "gm_level": (0.15, 0.40),
                   "om": (0.05, 0.20), "rev3": (0.0, 0.08)},
    "cyclical": {"pe": (25, 8), "fpe": (22, 8), "ev_ebitda": (12, 4), "ev_ebit": (18, 6), "pfcf": (25, 8),
                 "gm": (0.10, 0.40), "gm_level": (0.10, 0.40), "om": (0.03, 0.20), "rev3": (-0.05, 0.08),
                 "de": (1.5, 0.2), "nd_ebitda": (3.0, 0.0), "rev_stab": (0.30, 0.08)},
    "telecom": {"pe": (25, 10), "fpe": (22, 9), "ev_ebitda": (12, 6), "de": (2.5, 0.8),
                "nd_ebitda": (4.5, 2.0), "rev3": (-0.01, 0.05), "fwd_rev": (-0.01, 0.04),
                "div_yield": (0.01, 0.06)},
    "utility": {"de": (2.5, 0.8), "nd_ebitda": (6.5, 3.5), "int_cov": (1.5, 5.0), "current": (0.5, 1.2),
                "quick": (0.3, 1.0), "debt_assets": (0.55, 0.30), "pe": (28, 14), "fpe": (24, 13),
                "ev_ebitda": (16, 9), "roe": (0.05, 0.12), "roa": (0.01, 0.04), "om": (0.10, 0.30),
                "rev3": (0.0, 0.06), "eps3": (0.0, 0.08), "fwd_rev": (0.0, 0.05), "fwd_eps": (0.0, 0.08),
                "div_yield": (0.02, 0.05), "roic": (0.03, 0.08), "roic_min": (0.02, 0.07)},
    "reit": {"nd_ebitda": (8.0, 4.5), "de": (2.0, 0.7), "int_cov": (1.5, 4.0), "debt_assets": (0.6, 0.3),
             "om": (0.15, 0.45), "roe": (0.02, 0.10), "roa": (0.01, 0.05), "rev3": (0.0, 0.08),
             "fwd_rev": (0.0, 0.06), "ev_ebitda": (28, 15), "div_yield": (0.02, 0.05), "pb": (3.0, 1.0)},
    "bank": {"pe": (18, 8), "fpe": (16, 7), "pb": (2.5, 0.9), "roe": (0.06, 0.16), "roa": (0.004, 0.015),
             "nm": (0.10, 0.30), "rev3": (0.0, 0.08), "eps3": (0.0, 0.10), "fwd_rev": (0.0, 0.06),
             "fwd_eps": (0.0, 0.10), "div_yield": (0.01, 0.04), "rev_stab": (0.15, 0.04)},
    "fin_light": {"pe": (45, 18), "fpe": (38, 16), "pfcf": (45, 18), "ev_ebitda": (35, 14),
                  "gm_level": (0.40, 0.80), "om": (0.15, 0.45)},
}

_GENERIC = {
    "health": {"de": 1.5, "current": 1, "quick": 1, "int_cov": 1.5, "nd_ebitda": 2,
               "debt_assets": 1, "cash_debt": 1, "debt_dev": 1},
    "profitability": {"roic": 2.5, "roe": 1.5, "roa": 1, "gm": 1, "om": 1.5, "nm": 1,
                      "fcfm": 1.5, "roic_trend": 1},
    "growth": {"rev3": 1.5, "rev5": 0.5, "eps3": 1.5, "eps5": 0.5, "fcf_g": 1, "opinc_g": 1,
               "fwd_rev": 1, "fwd_eps": 1, "consistency": 1.5},
    "valuation": {"pe": 1.5, "fpe": 1.5, "peg": 1, "ps": 0.5, "pb": 0.5, "pfcf": 2,
                  "ev_ebitda": 1.5, "ev_ebit": 1, "hist_rel": 1.5, "sector_rel": 1.5},
    "moat": {"gm_level": 1, "gm_stab": 1, "om_stab": 1.5, "roic_min": 2, "roic_stab": 1,
             "rev_stab": 1, "rev_decl": 1, "pricing": 1, "market_pos": 0.5},
}


def _merge(base, **changes):
    out = {k: dict(v) for k, v in base.items()}
    for cat, upd in changes.items():
        if isinstance(upd, dict) and upd.get("__replace__"):
            out[cat] = {k: v for k, v in upd.items() if k != "__replace__"}
        else:
            for k, v in upd.items():
                if v is None:
                    out[cat].pop(k, None)
                else:
                    out[cat][k] = v
    return out


WEIGHTS = {
    "generic": _GENERIC,
    "tech": _merge(_GENERIC, valuation={"peg": 1.5, "ps": 1, "pb": 0.25},
                   growth={"fwd_rev": 1.5, "fwd_eps": 1.5}),
    "health": _merge(_GENERIC),
    "cons_def": _merge(_GENERIC, valuation={"div_yield": 0.75}),
    "cons_cyc": _merge(_GENERIC),
    "industrial": _merge(_GENERIC, valuation={"ev_ebitda": 2}),
    "cyclical": _merge(_GENERIC, valuation={"ev_ebitda": 2, "peg": None, "div_yield": 0.5}),
    "telecom": _merge(_GENERIC, valuation={"div_yield": 1, "ev_ebitda": 2, "peg": 0.5}),
    "fin_light": _merge(_GENERIC),
    "utility": _merge(
        _GENERIC,
        health={"current": 0.5, "quick": 0.5},
        profitability={"fcfm": None, "roic": 1.5, "roe": 2},
        growth={"fcf_g": None, "div_g": 1},
        valuation={"pfcf": None, "peg": 0.5, "div_yield": 1, "ev_ebitda": 2},
    ),
    "bank": {
        "health": {"equity_assets": 3, "loss_years": 1.5, "roa_min": 1.5},
        "profitability": {"roe": 3, "roa": 2, "nm": 1, "roe_trend": 1},
        "growth": {"rev3": 1.5, "rev5": 0.5, "eps3": 1.5, "eps5": 0.5, "bv_g": 1.5,
                   "fwd_rev": 1, "fwd_eps": 1, "consistency": 1.5},
        "valuation": {"pe": 1.5, "fpe": 1.5, "pb": 1, "pb_just": 2.5, "div_yield": 0.75,
                      "hist_rel": 1, "sector_rel": 1.5},
        "moat": {"roe_min": 2, "roe_stab": 1.5, "rev_stab": 1, "rev_decl": 1, "nm_stab": 1,
                 "market_pos": 0.5},
    },
    "reit": {
        "health": {"nd_ebitda": 2, "de": 1, "int_cov": 1.5, "debt_assets": 1, "debt_dev": 1},
        "profitability": {"ffo_margin": 2, "om": 1, "roe": 1, "roa": 1},
        "growth": {"rev3": 1.5, "rev5": 0.5, "ffo_g": 1.5, "div_g": 1, "fwd_rev": 1, "consistency": 1},
        "valuation": {"p_ffo": 2.5, "ev_ebitda": 1.5, "div_yield": 1, "pb": 0.5, "hist_rel": 1,
                      "sector_rel": 1.5},
        "moat": {"om_stab": 1.5, "rev_stab": 1.5, "rev_decl": 1, "ffo_stab": 1, "gm_stab": 0.5,
                 "market_pos": 0.5},
    },
}

# Metrics voor de sectorvergelijking per profiel (multiples waarbij lager = goedkoper).
SECTOR_MULTIPLES = {
    "bank": ("pe", "pb"),
    "reit": ("p_ffo", "ev_ebitda"),
    "utility": ("pe", "ev_ebitda"),
}
DEFAULT_SECTOR_MULTIPLES = ("pe", "ev_ebitda", "pfcf")


def norms_for(profile):
    n = dict(BASE_NORMS)
    n.update(PROFILE_NORMS.get(profile, {}))
    return n


def weights_for(profile):
    return WEIGHTS.get(profile, WEIGHTS["generic"])
