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


def compute_indicators(df: pd.DataFrame) -> dict:
    if len(df) < MIN_ROWS:
        raise ValueError(f"need >= {MIN_ROWS} rows, got {len(df)}")
    close = df["close"]
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    bb_mid = close.rolling(20).mean().iloc[-1]
    bb_std = close.rolling(20).std().iloc[-1]     # ddof=1 (pandas default)
    return {
        "price": float(close.iloc[-1]),
        "rsi": float(_rsi(close).iloc[-1]),
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(signal.iloc[-1]),
        "ma_fast": float(close.rolling(20).mean().iloc[-1]),
        "ma_slow": float(close.rolling(50).mean().iloc[-1]),
        "atr": float(_atr(df).iloc[-1]),
        "bb_mid": float(bb_mid),
        "bb_upper": float(bb_mid + 2 * bb_std),
        "bb_lower": float(bb_mid - 2 * bb_std),
    }
