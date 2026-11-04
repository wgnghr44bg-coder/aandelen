"""Unit tests voor de waarderingsengine. Draaien met: python -m pytest -q"""
import copy
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import analyze_universe  # noqa: E402
from engine import dcf, growth, health, valuation  # noqa: E402
from engine.data import normalize  # noqa: E402
from engine.run import analyze, build_context  # noqa: E402
from engine.util import cagr, div, lin, score_category  # noqa: E402

TODAY = date.today()


def make_fin(profile="tech", mcap=3000.0, n=4, **over):
    """Een gezond, groeiend, goedkoop bedrijf (bedragen in miljoenen, nieuwste jaar eerst)."""
    rev = [1200.0, 1090.0, 990.0, 900.0, 820.0][:n]
    s = {
        "revenue": rev,
        "gross_profit": [r * 0.60 for r in rev],
        "operating_income": [r * 0.30 for r in rev],
        "ebit": [r * 0.30 for r in rev],
        "ebitda": [r * 0.35 for r in rev],
        "net_income": [r * 0.22 for r in rev],
        "interest_expense": [10.0] * n,
        "diluted_eps": [r * 0.22 / 100 for r in rev],
        "diluted_shares": [100.0] * n,
        "tax_rate": [0.20] * n,
        "pretax_income": [r * 0.28 for r in rev],
        "tax_provision": [r * 0.056 for r in rev],
        "total_debt": [200.0] * n,
        "cash": [300.0] * n,
        "equity": [800.0, 760.0, 720.0, 680.0, 650.0][:n],
        "total_assets": [1500.0, 1450.0, 1400.0, 1350.0, 1300.0][:n],
        "current_assets": [600.0] * n,
        "current_liabilities": [300.0] * n,
        "inventory": [50.0] * n,
        "minority_interest": [None] * n,
        "ocf": [r * 0.30 for r in rev],
        "capex": [-r * 0.05 for r in rev],
        "fcf": [r * 0.25 for r in rev],
        "sbc": [10.0] * n,
        "dividends_paid": [-50.0, -45.0, -40.0, -36.0, -33.0][:n],
        "da": [r * 0.05 for r in rev],
    }
    s.update(over.pop("s", {}))
    years = [str(TODAY.replace(year=TODAY.year - i) - timedelta(days=60)) for i in range(n)]
    ni0 = s["net_income"][0]
    fin = {
        "ticker": over.pop("ticker", "TEST"), "sector": "Technology", "industry": "Software",
        "profile": profile, "price": mcap / 100, "mcap": mcap, "currency": "USD", "fin_currency": "USD",
        "fx": 1.0, "beta": 1.0, "rf": 0.0425, "years": years, "s": s,
        "est": {"fwd_rev": 0.09, "fwd_eps": 0.10},
        "info": {"trailing_pe": mcap / ni0 if ni0 > 0 else None, "forward_pe": mcap / (ni0 * 1.1) if ni0 > 0 else None,
                 "trailing_eps": ni0 / 100, "forward_eps": ni0 * 1.1 / 100},
        "hist_mcap": [mcap * (r / rev[0]) for r in rev],
        "dates": {"price": str(TODAY), "fundamentals_fetched": str(TODAY), "info_fetched": str(TODAY),
                  "statements": years[0]},
        "issues": [], "notes": [], "shares_ok": True, "diluted_shares": 100.0,
    }
    fin.update(over)
    return fin


def run_one(fin, peers=None):
    fins = {fin["ticker"]: fin}
    for p in peers or []:
        fins[p["ticker"]] = p
    return analyze_universe(fins)[fin["ticker"]]


# ------------------------------------------------------------------ hulpfuncties

def test_util_safe_math():
    assert div(1, 0) is None and div(None, 2) is None
    assert cagr(100, 0, 3) is None and cagr(-5, 10, 3) is None
    assert math.isclose(cagr(121, 100, 2), 0.1)
    assert lin(5, 0, 10) == 50 and lin(20, 0, 10) == 100 and lin(-1, 0, 10) == 0
    assert lin(5, 10, 0) == 50  # omgekeerde richting
    assert lin(None, 0, 1) is None


def test_missing_data_is_never_zero_or_positive():
    res = score_category({"a": None, "b": 0.5}, {}, {"a": 1, "b": 1}, {"a": (0, 1), "b": (0, 1)})
    assert res["metrics"]["a"]["score"] is None
    assert res["score"] == 50.0 and res["coverage"] == 0.5
    res = score_category({"a": None, "b": None}, {}, {"a": 1, "b": 1}, {"a": (0, 1), "b": (0, 1)})
    assert res["score"] is None


# ------------------------------------------------------------------ adviezen

def test_quality_company_cheap_is_buy():
    r = run_one(make_fin())
    assert r["rating"] == "BUY", r["reasons"]
    assert r["dcf"]["scenarios"]["neutral"]["margin_of_safety"] >= 0.20


def test_strong_company_overvalued_is_hold_not_sell():
    r = run_one(make_fin(mcap=6500.0))
    assert r["rating"] == "HOLD", (r["reasons"], r["dcf"]["scenarios"]["neutral"])
    assert r["dcf"]["scenarios"]["neutral"]["upside"] < 0


def test_extreme_overvaluation_is_sell():
    # middelmatig bedrijf (lage marges, lage groei) tegen een absurde prijs
    slow = [1000.0, 990.0, 985.0, 980.0]
    f = make_fin(mcap=60000.0, s={"revenue": slow, "net_income": [r * 0.04 for r in slow],
                                  "diluted_eps": [r * 0.0004 for r in slow], "fcf": [r * 0.04 for r in slow],
                                  "operating_income": [r * 0.07 for r in slow], "ebit": [r * 0.07 for r in slow],
                                  "ebitda": [r * 0.10 for r in slow], "gross_profit": [r * 0.22 for r in slow],
                                  "equity": [900.0] * 4, "total_assets": [2500.0] * 4})
    f["est"] = {"fwd_rev": 0.01, "fwd_eps": 0.01}
    r = run_one(f)
    assert r["rating"] == "SELL", r["reasons"]
    assert any("extreem overgewaardeerd" in x for x in r["reasons"])


def test_debt_heavy_but_solvent_is_not_sell():
    # veel schuld, maar rente ruim te betalen (geen financiële nood) -> geen SELL op gezondheid
    f = make_fin(s={"total_debt": [1400.0] * 4, "cash": [20.0] * 4, "equity": [100.0] * 4,
                    "current_assets": [250.0] * 4, "current_liabilities": [400.0] * 4})
    r = run_one(f)
    assert not any("gezondheid" in x for x in r["reasons"]), r["reasons"]


def test_debt_free_company_rated():
    raw = fake_raw()
    del raw["balance"]["rows"]["Total Debt"]
    fin = normalize("NODEBT", fake_info(), raw, 30.0, lambda d: 25.0, TODAY, 1.0, 0.04, str(TODAY), str(TODAY))
    assert fin["s"]["total_debt"] == [0.0] * 4
    res = analyze_universe({"NODEBT": fin})["NODEBT"]
    assert res["categories"]["health"]["score"] is not None
    raw2 = fake_raw()
    raw2["balance"]["rows"]["Total Debt"] = [None] * 4  # rij aanwezig maar leeg
    fin2 = normalize("EMPTY", fake_info(), raw2, 30.0, None, TODAY, 1.0, 0.04, str(TODAY), str(TODAY))
    assert fin2["s"]["total_debt"] == [0.0] * 4


def test_cyclical_decline_not_structural():
    from engine.decision import deterioration_flags
    rev = [900.0, 1000.0, 1200.0, 1000.0]
    f = make_fin(profile="cyclical", s={"revenue": rev})
    f["est"]["fwd_eps"] = -0.2
    assert deterioration_flags(f, {}) == []
    g = make_fin(profile="industrial", s={"revenue": rev})
    g["est"]["fwd_eps"] = -0.2
    assert "omzet krimpt al twee jaar" in deterioration_flags(g, {})


def test_exceptional_company_extremely_priced_is_hold():
    r = run_one(make_fin(mcap=60000.0))
    assert r["categories"]["growth"]["score"] >= 60
    assert r["rating"] == "HOLD", r["reasons"]


def test_negative_earnings_no_buy_and_pe_zero():
    rev = [1200.0, 1090.0, 990.0, 900.0]
    f = make_fin(s={"net_income": [-50.0, 100.0, 120.0, 110.0],
                    "diluted_eps": [-0.5, 1.0, 1.2, 1.1]})
    f["info"]["trailing_pe"] = None
    r = run_one(f)
    assert r["rating"] != "BUY"
    assert r["categories"]["valuation"]["metrics"]["pe"]["score"] == 0.0
    assert "omgeslagen naar verlies" in r["flags"]
    assert rev  # noqa


def test_negative_fcf_dcf_invalid():
    f = make_fin(s={"fcf": [-100.0, -80.0, -50.0, -20.0]})
    r = run_one(f)
    assert r["dcf"]["valid"] is False
    assert r["rating"] in ("NO RATING", "SELL")
    assert r["rating"] != "BUY"


def test_high_debt_hurts_health_and_blocks_buy():
    f = make_fin(s={"total_debt": [6000.0, 4000.0, 3000.0, 2000.0], "cash": [50.0] * 4,
                    "interest_expense": [300.0, 200.0, 150.0, 100.0],
                    "current_assets": [200.0] * 4, "current_liabilities": [500.0] * 4})
    r = run_one(f)
    assert r["categories"]["health"]["score"] < 40
    assert r["rating"] != "BUY"


def test_missing_financial_data_no_rating():
    f = make_fin()
    for k in ("total_debt", "cash", "equity", "total_assets", "current_assets", "current_liabilities",
              "inventory", "interest_expense", "ebitda", "ebit"):
        f["s"][k] = [None] * 4
    r = run_one(f)
    assert r["rating"] == "NO RATING"


def test_unrealistic_growth_is_capped():
    f = make_fin()
    f["est"] = {"fwd_rev": 3.0, "fwd_eps": 5.0}
    f["s"]["fcf"] = [1200.0, 300.0, 100.0, 10.0]  # +390%/jaar
    d = dcf.run(f)
    neu = d["scenarios"]["neutral"]
    assert neu["growth_y1"] <= 0.25
    assert d["scenarios"]["optimistic"]["growth_y1"] <= 0.30
    assert math.isfinite(neu["equity_value"])


def test_negative_intrinsic_value():
    f = make_fin(s={"total_debt": [50000.0] * 4, "cash": [10.0] * 4})
    d = dcf.run(f)
    assert d["valid"] is False and "negatieve intrinsieke waarde" in d["reason"]
    assert d["scenarios"]["neutral"]["margin_of_safety"] is None
    assert run_one(f)["rating"] != "BUY"


def test_division_by_zero_everywhere():
    zeros = {k: [0.0] * 4 for k in ("revenue", "gross_profit", "operating_income", "ebit", "ebitda",
                                     "net_income", "interest_expense", "equity", "total_assets",
                                     "current_liabilities", "total_debt", "cash", "fcf", "ocf")}
    f = make_fin(s=zeros, mcap=1000.0)
    f["info"] = {"trailing_pe": None, "forward_pe": None, "trailing_eps": 0.0, "forward_eps": 0.0}
    r = run_one(f)  # mag niet crashen
    assert r["rating"] in ("NO RATING", "SELL", "HOLD")


def test_extreme_pe_scores_zero():
    f = make_fin(mcap=3000.0)
    f["info"]["trailing_pe"] = 500.0
    vals = valuation.evaluate(f, {})["metrics"]
    assert vals["pe"]["score"] == 0.0


def test_insufficient_history_no_rating():
    f = make_fin(n=2)
    f["issues"].append("te weinig historie (2 jaar, minimaal 3)")
    assert run_one(f)["rating"] == "NO RATING"


def test_stale_and_missing_inputs_no_rating_via_normalize():
    raw = fake_raw(years_ago_latest=3)
    fin = normalize("OLD", fake_info(), raw, 30.0, None, TODAY, 1.0, 0.04, str(TODAY), str(TODAY))
    assert any("verouderd" in i for i in fin["issues"])
    fin2 = normalize("NOFX", fake_info(fin_cur="TWD"), fake_raw(), 30.0, None, TODAY, None, 0.04,
                     str(TODAY), str(TODAY))
    assert any("wisselkoers" in i for i in fin2["issues"])
    for f in (fin, fin2):
        assert analyze(f, build_context({f["ticker"]: f}))["rating"] == "NO RATING"


@pytest.mark.parametrize("profile,model", [("tech", "fcf"), ("industrial", "fcf"), ("cyclical", "fcf"),
                                           ("bank", "ri"), ("utility", "ddm"), ("reit", "ddm")])
def test_sector_models(profile, model):
    f = make_fin(profile=profile)
    if profile == "reit":
        f["s"]["ffo"] = [ni + d for ni, d in zip(f["s"]["net_income"], f["s"]["da"])]
    d = dcf.run(f)
    assert d["model"] == model
    r = run_one(f)
    assert r["rating"] in ("BUY", "HOLD", "SELL", "NO RATING")


def test_sector_norms_differ():
    f_tech, f_util = make_fin(profile="tech", mcap=5000.0), make_fin(profile="utility", mcap=5000.0)
    v_tech = valuation.evaluate(f_tech, {})["metrics"]["pe"]["score"]
    v_util = valuation.evaluate(f_util, {})["metrics"]["pe"]["score"]
    assert v_tech != v_util
    assert "pfcf" not in valuation.evaluate(f_util, {})["metrics"]
    bank = health.evaluate(make_fin(profile="bank"), {})["metrics"]
    assert "current" not in bank and "equity_assets" in bank


def test_temporary_revenue_growth_scores_lower_than_structural():
    good = growth.evaluate(make_fin(), {})["score"]
    bumpy = make_fin(s={"net_income": [150.0, 300.0, 120.0, 250.0], "diluted_eps": [1.5, 3.0, 1.2, 2.5]})
    assert growth.evaluate(bumpy, {})["score"] < good


def test_sector_comparison_used():
    peers = [make_fin(ticker=f"P{i}", mcap=6000.0) for i in range(5)]
    r = run_one(make_fin(), peers)
    sr = r["categories"]["valuation"]["metrics"]["sector_rel"]
    assert sr["value"] is not None and sr["value"] < 1  # goedkoper dan de sector


def test_deterministic():
    a = run_one(make_fin())
    b = run_one(copy.deepcopy(make_fin()))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_rating_values_only():
    for m in (1500.0, 3000.0, 6000.0, 60000.0):
        assert run_one(make_fin(mcap=m))["rating"] in ("BUY", "HOLD", "SELL", "NO RATING")


# ------------------------------------------------------------------ normaliseren van ruwe data

def fake_info(fin_cur="USD"):
    return {"shortName": "Test", "sector": "Technology", "industry": "Software", "marketCap": 3000.0,
            "currentPrice": 30.0, "trailingPE": 11.0, "forwardPE": 10.0, "beta": 1.1, "currency": "USD",
            "financialCurrency": fin_cur, "trailingEps": 2.6, "forwardEps": 2.9}


def fake_raw(years_ago_latest=0):
    d = [str(TODAY.replace(year=TODAY.year - years_ago_latest - i) - timedelta(days=60)) for i in range(4)]
    rev = [1200.0, 1090.0, 990.0, 900.0]
    return {
        "income": {"dates": d, "rows": {
            "Total Revenue": rev, "Gross Profit": [r * .6 for r in rev], "Operating Income": [r * .3 for r in rev],
            "EBIT": [r * .3 for r in rev], "EBITDA": [r * .35 for r in rev], "Net Income": [r * .22 for r in rev],
            "Interest Expense": [10.0] * 4, "Diluted EPS": [r * .0022 for r in rev],
            "Diluted Average Shares": [100.0] * 4, "Tax Rate For Calcs": [0.2] * 4}},
        # balans met iets afwijkende datums (moet toch uitgelijnd worden)
        "balance": {"dates": [str(TODAY.replace(year=TODAY.year - years_ago_latest - i) - timedelta(days=55))
                              for i in range(4)], "rows": {
            "Total Debt": [200.0] * 4, "Cash Cash Equivalents And Short Term Investments": [300.0] * 4,
            "Stockholders Equity": [800.0, 760.0, 720.0, 680.0], "Total Assets": [1500.0] * 4,
            "Current Assets": [600.0] * 4, "Current Liabilities": [300.0] * 4}},
        "cashflow": {"dates": d, "rows": {
            "Operating Cash Flow": [r * .3 for r in rev], "Capital Expenditure": [-r * .05 for r in rev],
            "Stock Based Compensation": [10.0] * 4, "Cash Dividends Paid": [-50.0, -45.0, -40.0, -36.0]}},
        "estimates": {"revenue": {"+1y": 0.09}, "eps": {"+1y": 0.10}},
    }


def test_normalize_alignment_fx_and_derived():
    fin = normalize("ADR", fake_info(fin_cur="TWD"), fake_raw(), 30.0, lambda d: 25.0, TODAY,
                    1 / 32.0, 0.04, str(TODAY), str(TODAY))
    assert fin["issues"] == []
    assert math.isclose(fin["s"]["revenue"][0], 1200 / 32.0)       # omgerekend naar USD
    assert fin["s"]["diluted_eps"][0] == pytest.approx(1200 * .0022)  # per-aandeel niet omgerekend
    assert fin["s"]["total_debt"][0] == pytest.approx(200 / 32.0)    # balans uitgelijnd
    assert fin["s"]["fcf"][0] == pytest.approx((360 - 60) / 32.0)     # FCF = OCF + capex
    assert fin["s"]["inventory"] == [0.0] * 4                         # geen voorraadpost
    assert fin["shares_ok"] is False                                  # andere valuta -> verhoudingsmethode
    assert fin["est"] == {"fwd_rev": 0.09, "fwd_eps": 0.10}


def test_normalize_then_full_analysis_runs():
    fin = normalize("OK", fake_info(), fake_raw(), 30.0, lambda d: 25.0, TODAY, 1.0, 0.04,
                    str(TODAY), str(TODAY))
    res = analyze_universe({"OK": fin})["OK"]
    assert res["rating"] in ("BUY", "HOLD", "SELL", "NO RATING")
    assert res["data"]["dates"]["statements"] == fin["years"][0]


# ------------------------------------------------------------------ valuta (wereldwijd)

def test_currency_conversion_helpers():
    import fundamentals as fund
    fx = {"GBPUSD=X": 1.25, "JPYUSD=X": 0.0067, "TWDUSD=X": 0.031, "USDGBP=X": 0.8}
    lse = {"currency": "GBp", "financialCurrency": "GBP", "sharesOutstanding": 1_000_000, "marketCap": 50_000}
    # koers 5000 pence = £50 -> beurswaarde 5.000.000.000 pence = $62,5 mln
    assert fund.market_cap_quote(lse, 5000.0) == 5_000_000_000
    assert fund.usd_rate(lse, fx) == pytest.approx(0.0125)
    assert fund.fx_rate(lse, fx) == 100.0                      # jaarcijfers in GBP -> pence
    lse_usd = dict(lse, financialCurrency="USD")
    assert fund.fx_rate(lse_usd, fx) == pytest.approx(80.0)    # USD -> GBP -> pence
    jp = {"currency": "JPY", "financialCurrency": "JPY", "marketCap": 1e13, "currentPrice": 1000.0}
    assert fund.fx_rate(jp, fx) == 1.0 and fund.usd_rate(jp, fx) == pytest.approx(0.0067)
    assert fund.market_cap_quote(jp, 1100.0) == pytest.approx(1.1e13)
    adr = {"currency": "USD", "financialCurrency": "TWD"}
    assert fund.fx_rate(adr, {"TWDUSD=X": 0.031}) == 0.031
    assert fund.usd_rate({"currency": "XYZ"}, fx) is None      # onbekende valuta -> overslaan


def test_normalize_pence_market_cap():
    info = dict(fake_info(fin_cur="GBP"), currency="GBp", sharesOutstanding=100.0, currentPrice=3000.0)
    fin = normalize("X.L", info, fake_raw(), 3000.0, None, TODAY, 100.0, 0.04, str(TODAY), str(TODAY))
    assert fin["mcap"] == pytest.approx(300000.0)          # 100 aandelen × 3000 pence
    assert fin["s"]["revenue"][0] == pytest.approx(120000.0)  # £1200 -> 120.000 pence


def test_growth_not_above_analyst_expectations():
    f = make_fin(s={"revenue": [1600.0, 1100.0, 800.0, 500.0], "fcf": [400.0, 260.0, 180.0, 110.0]})
    f["est"] = {"fwd_rev": 0.06, "fwd_eps": 0.08}
    assert dcf.run(f)["scenarios"]["neutral"]["growth_y1"] == pytest.approx(0.08)


def test_fcf_capped_when_far_above_earnings():
    f = make_fin(s={"fcf": [1200.0, 1100.0, 1000.0, 900.0]})  # FCF ~4,5× de winst
    neu = dcf.run(f)["scenarios"]["neutral"]
    ni_avg = sum(f["s"]["net_income"][:3]) / 3
    assert neu["base_fcf"] <= 1.5 * ni_avg + 1
    assert "begrensd" in neu["fcf_basis"]


def test_country_risk_premium_raises_discount_rate():
    dev, em = make_fin(), make_fin()
    em["fin_currency"] = "CNY"
    r_dev = dcf.run(dev)["scenarios"]["neutral"]["cost_of_equity"]
    r_em = dcf.run(em)["scenarios"]["neutral"]["cost_of_equity"]
    assert r_em == pytest.approx(r_dev + 0.01)


def test_exchange_clearing_cash_not_counted():
    f = make_fin(s={"cash": [50000.0] * 4})  # enorme kas (onderpand clearing)
    normal = dcf.run(f)["scenarios"]["neutral"]["upside"]
    f["industry"] = "Financial Data & Stock Exchanges"
    exch = dcf.run(f)["scenarios"]["neutral"]
    assert exch["net_debt"] == 200.0 and exch["upside"] < normal


def test_only_developed_countries():
    import fundamentals as fund
    assert fund.is_developed({"country": "United States"})
    assert fund.is_developed({"country": "Japan"}) and fund.is_developed({"country": "Hong Kong"})
    for c in ("China", "India", "Taiwan", "South Korea", "Brazil", "Saudi Arabia"):
        assert not fund.is_developed({"country": c})
    tickers = [l.strip() for l in open(Path(__file__).resolve().parents[1] / "tickers.txt")
               if l.strip() and not l.startswith("#")]
    assert not any(t.endswith((".SS", ".SZ", ".NS", ".SR", ".KS", ".TW")) for t in tickers)
    assert not {"TSM", "BABA", "PDD", "NTES", "INFY", "PBR"} & set(tickers)


def test_free_float():
    import fundamentals as fund
    assert fund.free_float({"floatShares": 55, "sharesOutstanding": 100}) == 0.55
    assert fund.free_float({"sharesOutstanding": 100}) == 1.0          # onbekend
    assert fund.free_float({"floatShares": 300, "sharesOutstanding": 100}) == 1.0  # onlogisch
