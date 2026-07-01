// Single source of truth for the strategy list on the TS side (mirrors engine/strategies.py::STRATEGIES).
export const STRATEGIES: { id: string; label: string }[] = [
  { id: "hybrid", label: "AI (hybrid)" },
  { id: "indicator_rule", label: "Indicator rule" },
  { id: "sentiment_rule", label: "Sentiment rule" },
  { id: "ma_cross", label: "MA cross" },
  { id: "macd_cross", label: "MACD cross" },
  { id: "rsi_reversion", label: "RSI reversion" },
  { id: "bollinger", label: "Bollinger" },
];

export const STRATEGY_IDS = STRATEGIES.map((s) => s.id);

// The only strategy that calls the LLM — slow/costly to backtest over long ranges.
export const LLM_STRATEGIES = new Set(["hybrid"]);
