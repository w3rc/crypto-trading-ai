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


def ma_cross(features, position, cash, cfg) -> Decision:
    """MA20/MA50 crossover trend-following. Long-only spot."""
    fast, slow = features["ma_fast"], features["ma_slow"]
    if fast > slow:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"ma:golden fast={fast:.2f} slow={slow:.2f}")
    if fast < slow:
        return Decision(action="sell", size=1.0,
                        reason=f"ma:death fast={fast:.2f} slow={slow:.2f}")
    return Decision(action="hold", reason=f"ma:flat fast={fast:.2f} slow={slow:.2f}")


def macd_cross(features, position, cash, cfg) -> Decision:
    """MACD/signal-line crossover momentum. Long-only spot."""
    macd, sig = features["macd"], features["macd_signal"]
    if macd > sig:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"macd:bull macd={macd:.4f} sig={sig:.4f}")
    if macd < sig:
        return Decision(action="sell", size=1.0,
                        reason=f"macd:bear macd={macd:.4f} sig={sig:.4f}")
    return Decision(action="hold", reason=f"macd:flat macd={macd:.4f} sig={sig:.4f}")


def rsi_reversion(features, position, cash, cfg) -> Decision:
    """RSI mean-reversion: buy oversold, sell overbought. Long-only spot."""
    rsi = features["rsi"]
    r = cfg.rules
    if rsi < r.rsi_buy:
        return Decision(action="buy", size=r.buy_size, reason=f"rsi:oversold rsi={rsi:.0f}")
    if rsi > r.rsi_sell:
        return Decision(action="sell", size=1.0, reason=f"rsi:overbought rsi={rsi:.0f}")
    return Decision(action="hold", reason=f"rsi:neutral rsi={rsi:.0f}")


def bollinger(features, position, cash, cfg) -> Decision:
    """Bollinger-band mean-reversion: buy at/below lower band, sell at/above upper. Long-only spot."""
    price, lower, upper = features["price"], features["bb_lower"], features["bb_upper"]
    if price <= lower:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"bb:lower price={price:.2f} lower={lower:.2f}")
    if price >= upper:
        return Decision(action="sell", size=1.0,
                        reason=f"bb:upper price={price:.2f} upper={upper:.2f}")
    return Decision(action="hold", reason=f"bb:inside price={price:.2f}")


STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule,
              "sentiment_rule": sentiment_rule, "ma_cross": ma_cross,
              "macd_cross": macd_cross, "rsi_reversion": rsi_reversion,
              "bollinger": bollinger}


def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
