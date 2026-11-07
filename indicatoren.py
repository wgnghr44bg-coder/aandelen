"""Technische lijnen voor de koersgrafieken (EMA 50 en EMA 200)."""
import numpy as np
import pandas as pd

EMA_PERIODES = (50, 200)


def ema(close, n):
    """Exponentieel voortschrijdend gemiddelde over n slotkoersen (standaard, zoals TradingView/Yahoo):
    start = gewoon gemiddelde van de eerste n koersen, daarna EMA = k*koers + (1-k)*vorige EMA met k = 2/(n+1).
    Vóór de n-de koers is er nog geen EMA (NaN): dan tekenen we niets i.p.v. een geschatte waarde."""
    c = pd.Series(close, dtype="float64").dropna()
    uit = pd.Series(np.nan, index=c.index, dtype="float64")
    if len(c) < n:
        return uit
    k = 2.0 / (n + 1)
    v = c.iloc[:n].mean()
    waarden = c.to_numpy()
    res = uit.to_numpy().copy()
    res[n - 1] = v
    for i in range(n, len(waarden)):
        v = k * waarden[i] + (1 - k) * v
        res[i] = v
    return pd.Series(res, index=c.index)
