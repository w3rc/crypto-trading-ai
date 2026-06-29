import ccxt
import pandas as pd

from engine.models import Fill


_DERIVATIVE_TYPES = {"swap", "future", "margin", "delivery"}


def supports_short(exchange) -> bool:
    """Whether the exchange's default market type permits shorting (offline)."""
    # ponytail: defaultType heuristic; the precise check is load_markets + market.type.
    options = getattr(exchange, "options", {}) or {}
    return options.get("defaultType", "spot") in _DERIVATIVE_TYPES


def make_exchange(name: str, mode: str = "paper", api_key: str = "", secret: str = ""):
    opts = {"enableRateLimit": True}
    if mode in ("shadow", "live"):
        opts["apiKey"] = api_key
        opts["secret"] = secret
    return getattr(ccxt, name)(opts)


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_price(exchange, symbol: str) -> float:
    return float(exchange.fetch_ticker(symbol)["last"])


def fetch_balance(exchange, symbols: list[str]) -> tuple[float, dict[str, float]]:
    """Real account balance, read-only: (free quote, {symbol: free base})."""
    bal = exchange.fetch_balance()

    def free(asset: str) -> float:
        return float((bal.get(asset) or {}).get("free", 0.0) or 0.0)

    quote = symbols[0].split("/")[1] if symbols else "USDT"
    # ponytail: assumes one shared quote across symbols (USDT); multi-quote is a later refinement.
    cash = free(quote)
    qty = {s: free(s.split("/")[0]) for s in symbols}
    return cash, qty


def create_order(exchange, symbol: str, side: str, qty: float, ref_price: float, ts: str) -> Fill:
    """Place a REAL spot market order; return the reconciled real fill.

    The ONLY order-placement call in the engine. Prefers the response's
    filled/average/fee; re-polls once via fetch_order if not yet filled;
    falls back to ref_price for a missing average and 0.0 for a missing fee.
    """
    o = exchange.create_order(symbol, "market", side, qty)
    filled = float(o.get("filled") or 0.0)
    if o.get("status") != "closed" or filled <= 0:
        # ponytail: single re-poll, no chase loop; an under-read remainder
        # self-heals next cycle (exchange = truth for balances).
        try:
            o = exchange.fetch_order(o.get("id"), symbol) or o
            filled = float(o.get("filled") or filled or 0.0)
        except Exception:
            pass
    avg = float(o.get("average") or o.get("price") or ref_price)
    fee = float((o.get("fee") or {}).get("cost") or 0.0)
    return Fill(symbol, side, filled, avg, fee, ts)
