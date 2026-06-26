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


def sentiment_rule(features, position, cash, cfg) -> Decision:
    """indicator_rule signals gated by the blended sentiment score. Deterministic."""
    r = cfg.rules
    s = cfg.sentiment
    rsi = features["rsi"]
    sent = features.get("sentiment", 0.0)
    bullish = rsi < r.rsi_buy or (
        features["macd"] > features["macd_signal"]
        and features["ma_fast"] > features["ma_slow"])
    bearish = rsi > r.rsi_sell or (
        features["macd"] < features["macd_signal"]
        and features["ma_fast"] < features["ma_slow"])
    if bullish and bearish:
        return Decision(action="hold", reason=f"sent:conflict s={sent:+.2f}")
    if bullish:
        if sent >= s.buy_min:
            return Decision(action="buy", size=r.buy_size,
                            reason=f"sent:buy rsi={rsi:.0f} s={sent:+.2f}")
        return Decision(action="hold", reason=f"sent:veto-buy s={sent:+.2f}")
    if bearish:
        return Decision(action="sell", size=1.0, reason=f"sent:sell rsi={rsi:.0f}")
    if sent <= s.sell_max:
        return Decision(action="sell", size=1.0, reason=f"sent:risk-off s={sent:+.2f}")
    return Decision(action="hold", reason=f"sent:neutral s={sent:+.2f}")


STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule,
              "sentiment_rule": sentiment_rule}


def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
