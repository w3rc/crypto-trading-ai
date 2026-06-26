from engine import llm
from engine.models import Decision


def hybrid(features, position, cash, cfg) -> Decision:
    """Indicators + LLM judgment — the v1 behavior, unchanged."""
    return llm.decide(features, position, cash, cfg.llm)


def indicator_rule(features, position, cash, cfg) -> Decision:
    """Deterministic RSI/MACD/MA crossover rules. Long-only, no LLM."""
    r = cfg.rules
    rsi = features["rsi"]
    bullish = rsi < r.rsi_buy or (
        features["macd"] > features["macd_signal"]
        and features["ma_fast"] > features["ma_slow"])
    bearish = rsi > r.rsi_sell or (
        features["macd"] < features["macd_signal"]
        and features["ma_fast"] < features["ma_slow"])
    if bullish and not bearish:
        return Decision(action="buy", size=r.buy_size, reason=f"rule:bullish rsi={rsi:.0f}")
    if bearish and not bullish:
        return Decision(action="sell", size=1.0, reason=f"rule:bearish rsi={rsi:.0f}")
    return Decision(action="hold", reason=f"rule:neutral rsi={rsi:.0f}")


STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule}


def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
