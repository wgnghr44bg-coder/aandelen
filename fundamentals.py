"""Ophalen en cachen van fundamentele data + aansturen van de waarderingsengine.

Cache (.cache/fundamentals.json, bewaard via de GitHub Actions-cache, niet in de repo):
  {ticker: {"info": {...}, "info_fetched": iso-tijd,
            "raw": {...jaarcijfers + verwachtingen...}, "raw_fetched": iso-tijd}}

- Info (naam, sector, beurswaarde, K/W) wordt max. 1× per dag per aandeel opgehaald.
- Jaarcijfers en verwachtingen max. 1× per week per aandeel, binnen een tijdsbudget per run.
- Elk uur wordt het advies opnieuw berekend met de actuele koers, zonder extra API-aanroepen.
"""
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from engine import ENGINE_VERSION, analyze_universe
from engine.data import extract_info, extract_raw, normalize

ROOT = Path(__file__).parent
CACHE = ROOT / ".cache" / "fundamentals.json"
ANALYSIS = ROOT / "analyse" / "analysis.json"
INFO_MAX_AGE = timedelta(hours=23)
RAW_MAX_AGE = timedelta(days=7)
RAW_BUDGET_S = 540  # max. 9 minuten jaarcijfers ophalen per run


def now():
    return datetime.now(timezone.utc)


def _age(ts):
    try:
        return now() - datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return timedelta(days=9999)


def load_cache():
    try:
        return json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, separators=(",", ":")))
    tmp.replace(CACHE)


def _retry(fn, label, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            print(f"  {label} poging {i + 1} mislukt: {e}")
            time.sleep(2 * (i + 1))
    return None


def refresh(cache, tickers):
    """Werkt de cache bij: eerst ontbrekende/verouderde info (nodig voor de top 100), dan jaarcijfers."""
    n_info = 0
    for t in tickers:
        c = cache.setdefault(t, {})
        if c.get("info") and _age(c.get("info_fetched")) < INFO_MAX_AGE:
            continue
        info = _retry(lambda: yf.Ticker(t).info or {}, f"info {t}")
        if info and info.get("marketCap"):
            c["info"] = extract_info(info)
            c["info_fetched"] = now().isoformat()
            n_info += 1
        time.sleep(0.3)
    if n_info:
        save_cache(cache)
    print(f"info bijgewerkt: {n_info}")

    todo = [t for t in tickers if cache.get(t, {}).get("info")
            and (not cache[t].get("raw") or _age(cache[t].get("raw_fetched")) >= RAW_MAX_AGE)]
    todo.sort(key=lambda t: (cache[t].get("raw") is not None, cache[t].get("raw_fetched") or ""))
    start, n_raw = time.time(), 0
    for t in todo:
        if time.time() - start > RAW_BUDGET_S:
            print(f"tijdsbudget jaarcijfers op; nog {len(todo) - n_raw} te gaan (volgende run)")
            break
        raw = _retry(lambda: extract_raw(yf.Ticker(t)), f"jaarcijfers {t}")
        if raw and raw.get("income"):
            cache[t]["raw"] = raw
            cache[t]["raw_fetched"] = now().isoformat()
        else:
            print(f"  jaarcijfers {t}: niet beschikbaar")
        n_raw += 1
        if n_raw % 10 == 0:
            save_cache(cache)
        time.sleep(0.5)
    save_cache(cache)
    print(f"jaarcijfers bijgewerkt: {n_raw}")


def market_data(cache):
    """Risicovrije rente (10-jaars VS, ^TNX) en wisselkoersen voor bedrijven die in een andere valuta
    rapporteren dan hun koers (ADR's). Eén download voor alles."""
    pairs = set()
    for c in cache.values():
        i = c.get("info") or {}
        cur, fcur = i.get("currency"), i.get("financialCurrency") or i.get("currency")
        if cur and fcur and cur != fcur:
            pairs.add(f"{fcur}{cur}=X")
    symbols = ["^TNX"] + sorted(pairs)
    rf, fx = None, {}
    try:
        d = yf.download(symbols, period="10d", interval="1d", auto_adjust=False,
                        group_by="ticker", progress=False)
        for s in symbols:
            try:
                close = d[s]["Close"].dropna()
                if close.empty:
                    continue
                v = float(close.iloc[-1])
                if s == "^TNX":
                    rf = v / 100.0 if 0.5 < v < 15 else None
                else:
                    fx[s] = v
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        print(f"rente/valuta download mislukt: {e}")
    print(f"rente 10j: {rf}, wisselkoersen: {len(fx)}/{len(pairs)}")
    return rf, fx


def fx_rate(info, fx):
    cur, fcur = info.get("currency"), info.get("financialCurrency") or info.get("currency")
    if not cur:
        return None
    if cur == fcur:
        return 1.0
    return fx.get(f"{fcur}{cur}=X")


def _price_lookup(close):
    if close is None or close.empty:
        return None
    idx = pd.DatetimeIndex(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(close.values, index=idx).sort_index()

    def on(d):
        part = s[s.index <= pd.Timestamp(d)]
        return float(part.iloc[-1]) if not part.empty else None
    return on


def run_engine(cache, prices, closes, asof, rf, fx):
    """prices: {ticker: huidige koers}, closes: {ticker: Series slotkoersen}.
    Geeft {ticker: analyse} voor alle aandelen met info (het hele universum, voor sectorvergelijking)."""
    fins = {}
    for t, price in prices.items():
        c = cache.get(t) or {}
        if not c.get("info"):
            continue
        raw_day = (c.get("raw_fetched") or "")[:10] or None
        fins[t] = normalize(t, c["info"], c.get("raw"), price, _price_lookup(closes.get(t)), asof,
                            fx_rate(c["info"], fx), rf, raw_day, (c.get("info_fetched") or "")[:10] or None)
    return analyze_universe(fins)


def write_analysis(results, asof):
    """Interne, volledige analyse (alle ratio's, scores, DCF-aannames, datums). Niet op de site."""
    ANALYSIS.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"engine_version": ENGINE_VERSION, "generated": now().isoformat(timespec="seconds"),
                         "price_date": str(asof)})]
    lines += [json.dumps(results[t], ensure_ascii=False, separators=(",", ":")) for t in sorted(results)]
    ANALYSIS.write_text("\n".join(lines) + "\n")
    counts = {}
    for r in results.values():
        counts[r["rating"]] = counts.get(r["rating"], 0) + 1
    print(f"analyse geschreven: {counts}")


def today():
    return date.today()
