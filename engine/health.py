"""Financial Health (20%): schuld, liquiditeit, rentedekking en schuldontwikkeling."""
from .sectors import norms_for, weights_for
from .series import ser, span_cagr
from .util import at, cagr, div, num, score_category


def values(fin):
    vals, forced, notes = {}, {}, []
    s = lambda k: ser(fin, k)  # noqa: E731
    debt, cash, eq = at(s("total_debt"), 0), at(s("cash"), 0), at(s("equity"), 0)
    ebitda, ebit, ie = at(s("ebitda"), 0), at(s("ebit"), 0), at(s("interest_expense"), 0)
    assets = at(s("total_assets"), 0)

    # Debt-to-Equity (negatief eigen vermogen door inkoop eigen aandelen: niet zinvol)
    if debt is not None and eq is not None:
        if eq > 0:
            vals["de"] = debt / eq
        else:
            notes.append("negatief eigen vermogen: D/E niet zinvol")
    vals["current"] = div(at(s("current_assets"), 0), at(s("current_liabilities"), 0))
    ca, cl, inv = at(s("current_assets"), 0), at(s("current_liabilities"), 0), at(s("inventory"), 0)
    if ca is not None and cl and inv is not None:
        vals["quick"] = (ca - inv) / cl
    # Interest Coverage
    if fin["profile"] in ("reit", "utility") and ebitda is not None:
        ebit = ebitda  # vastgoed/nuts: dekking op EBITDA (zware afschrijvingen)
    if ebit is not None:
        if ie is not None and abs(ie) > 0:
            vals["int_cov"] = ebit / abs(ie)
        elif debt == 0:
            forced["int_cov"] = 100.0
            notes.append("geen schuld: rentedekking maximaal")
    # Net Debt / EBITDA
    if debt is not None and cash is not None:
        nd = debt - cash
        if ebitda is not None and ebitda > 0:
            vals["nd_ebitda"] = nd / ebitda
        elif ebitda is not None and ebitda <= 0:
            forced["nd_ebitda"] = 0.0 if nd > 0 else None
            notes.append("EBITDA niet positief")
    vals["debt_assets"] = div(debt, assets)
    if debt is not None and cash is not None:
        if debt == 0:
            forced["cash_debt"] = 100.0
        else:
            vals["cash_debt"] = cash / debt
    # Schuldontwikkeling: groei schuld minus groei EBITDA (over de langste beschikbare periode, 3–4 jaar)
    for yrs in (4, 3):
        dg = span_cagr(s("total_debt"), yrs)
        eg = span_cagr(s("ebitda"), yrs)
        if dg is not None and eg is not None:
            vals["debt_dev"] = dg - eg
            break
    # Bankachtig: eigen vermogen / activa (buffer), verliesjaren, laagste ROA
    vals["equity_assets"] = div(eq, assets) if (eq is not None and eq > 0) else None
    ni = s("net_income")
    known = [x for x in ni[:4] if x is not None]
    vals["loss_years"] = sum(1 for x in known if x < 0) if len(known) >= 3 else None
    roas = [div(n, a) for n, a in zip(ni, s("total_assets")) if n is not None and a]
    vals["roa_min"] = min(roas) if len(roas) >= 3 else None
    return vals, forced, notes


def evaluate(fin, ctx=None):
    prof = fin["profile"]
    vals, forced, notes = values(fin)
    res = score_category(vals, forced, weights_for(prof)["health"], norms_for(prof))
    res["notes"] = notes
    return res
