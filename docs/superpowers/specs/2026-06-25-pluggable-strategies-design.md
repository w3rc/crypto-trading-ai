# Pluggable Strategies — Design

**Date:** 2026-06-25
**Status:** Approved
**Sub-project:** 1 of 5 in the v2 roadmap (strategies → backtesting → news/sentiment → shorting/margin → live execution). Foundation-first, real-money-last.

## Goal

Extract the bot's single hardcoded decision path (`llm.decide`) into a small
**strategy seam** so the brain is selectable by config, and ship one concrete
deterministic strategy alongside the existing hybrid one. This is the
foundation the later sub-projects plug into: backtesting replays a strategy
over history, sentiment becomes a strategy input, and so on.

Non-goal: a plugin-discovery framework. One strategy per bot, selected by a
config string, looked up in a dict. Room for ~2-3 strategies, not infinity.

## Current state

`bot.run_once()` computes indicators per symbol and calls
`llm.decide(feats, pos, st.cash, cfg.llm) -> Decision` directly. `broker`
clamps every decision into an executable order (authoritative risk gate) and
simulates the fill. That structure is unchanged by this work — we only swap
*which function* produces the `Decision`.

## Design

### 1. The seam — `engine/strategies.py` (new)

A strategy is a plain callable with a uniform signature:

```python
def strategy(features: dict, position: Position, cash: float, cfg) -> Decision
```

Every strategy receives the whole `cfg` and reads only what it needs
(`cfg.llm` for the hybrid, `cfg.rules` for the deterministic one). This keeps
the dispatch in `bot.run_once` free of per-strategy plumbing.

```python
def hybrid(features, position, cash, cfg):
    return llm.decide(features, position, cash, cfg.llm)   # today's behavior, unchanged

def indicator_rule(features, position, cash, cfg):
    # deterministic rules over features -> Decision (see §3)
    ...

STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule}

def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
```

### 2. Dispatch — `engine/bot.py`

Resolve the strategy **once** before the symbol loop (so a bad name fails fast,
before any market calls):

```python
strategy = strategies.get(cfg.strategy)
...
# inside the per-symbol branch, replacing the direct llm.decide call:
decision = strategy(feats, pos, st.cash, cfg)
```

The stop-loss override, risk gate, fill simulation, decision logging, and
state persistence are all untouched.

### 3. Deterministic `indicator_rule` strategy

Long-only, spot. Operates on the existing feature set
(`price, rsi, macd, macd_signal, ma_fast, ma_slow, atr`).

- **bullish** if `rsi < rsi_buy` **or** (`macd > macd_signal` **and** `ma_fast > ma_slow`)
- **bearish** if `rsi > rsi_sell` **or** (`macd < macd_signal` **and** `ma_fast < ma_slow`)
- Decision:
  - **buy** with `size = buy_size` when `bullish and not bearish`
  - **sell** with `size = 1.0` (full exit) when `bearish`
  - **hold** otherwise
- `stop = None` — the broker derives the stop from `stop_loss_pct` on fill.
- `reason` is a short human string naming which rule fired (for the decision log / dashboard).

Conflicting signals (both bullish and bearish) resolve to **hold** — the
`buy` branch requires `not bearish`, and a held position with a bearish signal
still sells. This precedence is explicit and tested.

The strategy emits the raw `Decision` without checking holdings — a `sell` on
a bearish signal while flat is a no-op at the gate (`broker.plan_order`
returns `None` for zero quantity), exactly as it already does for an LLM that
says "sell" while flat. The strategy does not duplicate that guard.

Knobs live in config (calibration values, not constants — trading thresholds
need real-world tuning):

| knob | default | meaning |
|---|---|---|
| `rsi_buy` | 30 | oversold threshold → bullish |
| `rsi_sell` | 70 | overbought threshold → bearish |
| `buy_size` | 0.5 | fraction of equity to deploy on a buy (risk gate still clamps) |

### 4. Config — `engine/config.py` + `engine/config.yaml`

- New top-level `strategy: hybrid` key. **Default `hybrid` makes existing live
  behavior byte-for-byte unchanged** — the running bot is unaffected until the
  operator opts into a different strategy.
- New `rules:` block (`rsi_buy`, `rsi_sell`, `buy_size`) → a `RulesConfig`
  dataclass, attached to `Config.rules`.

```yaml
strategy: hybrid
rules:
  rsi_buy: 30
  rsi_sell: 70
  buy_size: 0.5
```

## Safety properties (preserved)

- `broker.plan_order` remains the authoritative gate: no strategy can exceed
  the per-position cap or available cash, and spot long-only invariants hold.
- Fail-safe HOLD: `hybrid` keeps its try/except → HOLD on any LLM error;
  `indicator_rule` is pure arithmetic over already-validated features and
  cannot throw on a valid feature dict.
- A typo'd strategy name raises before any market/LLM/network call.

## Testing

`tests/test_strategies.py`:
- `indicator_rule`: oversold→buy, overbought→sell (when holding), neutral→hold,
  conflicting-signals→hold, buy size honors `buy_size`.
- `get()`: returns the registered callable; raises `ValueError` (listing valid
  names) on an unknown name.

Plus minimal updates:
- `tests/test_bot.py`: assert the loop dispatches through the configured
  strategy (default `hybrid` still calls the LLM path).
- `tests/test_config.py`: `strategy` defaults to `hybrid`; `rules` parses.

## Files

| file | change |
|---|---|
| `engine/strategies.py` | **new** — `hybrid`, `indicator_rule`, `STRATEGIES`, `get` |
| `engine/bot.py` | resolve + dispatch via `strategies.get(cfg.strategy)` |
| `engine/config.py` | `strategy` field + `RulesConfig` |
| `engine/config.yaml` | `strategy: hybrid` + `rules:` block |
| `tests/test_strategies.py` | **new** |
| `tests/test_bot.py`, `tests/test_config.py` | minimal updates |

## Out of scope (future, each its own small follow-up if wanted)

- Per-symbol strategy selection.
- Surfacing the active strategy name in the Electron dashboard.
- Strategy auto-switching / ensembles.
