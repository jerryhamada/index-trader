"""Does price trend or snap back within the day? Lo-MacKinlay variance ratio."""
import numpy as np
import pandas as pd


def variance_ratio(close: pd.Series, q: int) -> tuple[float, float]:
    """Variance ratio at a horizon of q bars, and its z-score.

    Above 1 means moves tend to continue (trend-following is favoured); below 1
    means they tend to reverse. Only within-day returns are used, and the
    z-score is the version that allows volatility to change through the day.
    Beyond roughly +/-2 the result is unlikely to be chance.
    """
    r = np.log(close).groupby(close.index.normalize()).diff().dropna()
    day = r.index.normalize()
    x = r - r.mean()
    total = (x**2).sum()
    vr, var = 1.0, 0.0
    for j in range(1, q):
        lagged = x.groupby(day).shift(j)
        weight = 2 * (1 - j / q)
        vr += weight * (x * lagged).sum() / total
        var += weight**2 * (x**2 * lagged**2).sum() / total**2
    return vr, (vr - 1) / np.sqrt(var)
