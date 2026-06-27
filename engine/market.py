import ccxt
import pandas as pd


_DERIVATIVE_TYPES = {"swap", "future", "margin", "delivery"}


def supports_short(exchange) -> bool:
    """Whether the exchange's default market type permits shorting (offline)."""
    # ponytail: defaultType heuristic; the precise check is load_markets + market.type.
    options = getattr(exchange, "options", {}) or {}
    return options.get("defaultType", "spot") in _DERIVATIVE_TYPES


def make_exchange(name: str):
    return getattr(ccxt, name)({"enableRateLimit": True})


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_price(exchange, symbol: str) -> float:
    return float(exchange.fetch_ticker(symbol)["last"])
