import ccxt
import pandas as pd


def make_exchange(name: str):
    return getattr(ccxt, name)({"enableRateLimit": True})


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_price(exchange, symbol: str) -> float:
    return float(exchange.fetch_ticker(symbol)["last"])
