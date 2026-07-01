import pandas as pd

MIN_ROWS = 50

# ponytail: indicators computed directly in pandas instead of pandas-ta.
# ~30 lines of standard formulas, fully tested, and avoids pandas-ta's
# numpy-version fragility. Upgrade path: swap to pandas-ta if more indicators
# are needed than is worth hand-rolling.


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    """Causal indicator series, one row per candle (rolling/ewm only look backward,
    so row i uses only df[:i+1]). Warmup rows carry NaN. Shared by the scalar (live)
    and series (backtest) paths so the two can never drift."""
    close = df["close"]
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()               # ddof=1 (pandas default)
    return pd.DataFrame({
        "price": close,
        "rsi": _rsi(close),
        "macd": macd,
        "macd_signal": macd.ewm(span=9, adjust=False).mean(),
        "ma_fast": sma20,
        "ma_slow": close.rolling(50).mean(),
        "atr": _atr(df),
        "bb_mid": sma20,
        "bb_upper": sma20 + 2 * std20,
        "bb_lower": sma20 - 2 * std20,
    })


def compute_indicators(df: pd.DataFrame) -> dict:
    if len(df) < MIN_ROWS:
        raise ValueError(f"need >= {MIN_ROWS} rows, got {len(df)}")
    return {k: float(v) for k, v in _frame(df).iloc[-1].items()}


def compute_indicators_series(df: pd.DataFrame) -> pd.DataFrame:
    """Full causal indicator series — series.iloc[i] equals compute_indicators(df[:i+1])
    for i >= MIN_ROWS-1. Lets a backtest precompute indicators once (O(n)) instead of
    recomputing the whole trailing window every step (O(n^2))."""
    return _frame(df)
