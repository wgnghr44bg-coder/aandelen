"""Fundamental Score (0–100) = Health×0,20 + Profitability×0,20 + Growth×0,20 + Valuation×0,25 + Moat×0,15."""
WEIGHTS = {"health": 0.20, "profitability": 0.20, "growth": 0.20, "valuation": 0.25, "moat": 0.15}


def fundamental_score(categories):
    """None als één van de categorieën ontbreekt: een gat wordt nooit als 0 of als gemiddelde ingevuld."""
    total = 0.0
    for cat, w in WEIGHTS.items():
        sc = (categories.get(cat) or {}).get("score")
        if sc is None:
            return None
        total += sc * w
    return round(total, 2)
