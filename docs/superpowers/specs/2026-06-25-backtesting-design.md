# Backtesting — Design

**Date:** 2026-06-25
**Status:** Approved
**Sub-project:** 2 of 5 in the v2 roadmap (strategies → **backtesting** → news/sentiment → shorting/margin → live execution).
**Depends on:** the strategy seam from sub-project #1 (`engine/strategies.py`, branch `feat/pluggable-strategies` / PR #2). This work stacks on that branch.

## Goal

Replay a strategy over historical candles to answer one question: **does it beat
just holding?** Same fees, slippage, stops, and risk gate as the live bot, so
the result is realistic rather than idealized. Single symbol or a multi-symbol
portfolio sharing one cash balance — configurable by passing 1 or N symbols
through one code path.

Non-goals (later, if wanted): parameter sweeps / optimization, walk-forward
analysis, Sharpe/Sortino, wiring the equity curve into the dashboard, gap-only
cache fetches.

## Architecture

A replay harness that **reuses the engine's existing pure functions** and does
**not** modify the live bot — the running bot stays untouched.

```
engine/datafeed.py   historical OHLCV fetch (paginated ccxt) + disk cache
engine/metrics.py    return %, equal-weight buy-and-hold %, max drawdown
engine/backtest.py   the replay loop + CLI (python -m engine.backtest)
```

Reused unchanged: `indicators.compute_indicators`, `strategies.get`,
`broker.plan_order` / `apply_fill` / `stop_triggered`, `models.Position` / `Order`,
`config.load_config`. The replay loop is the bot's per-symbol logic stepped over
historical time instead of one live tick.

## 1. Data layer — `engine/datafeed.py`

```python
def load_ohlcv(exchange, symbol, timeframe, since_ms, until_ms,
               cache_dir="data/cache") -> pd.DataFrame
```
Returns columns `[ts, open, high, low, close, volume]`, `ts` ascending (epoch ms),
restricted to `[since_ms, until_ms]`.

- **Cache file** per `{exchange_name}_{symbol_sanitized}_{timeframe}.csv` under
  `cache_dir` (symbol `BTC/USDT` → `BTC-USDT`).
- **Coverage check:** if a cache file exists and
  `cached.ts.min() <= since_ms and cached.ts.max() >= until_ms`, slice and return
  — no network.
- **On miss:** fetch `[since_ms, until_ms]` from ccxt (paginated), union with the
  cached rows (concat → drop duplicate `ts` → sort), write back, return the slice.
  `# ponytail: re-fetches the whole requested range on a partial-coverage miss,
  not just the missing gap; gap-only fetch is the upgrade path.`
- **Pagination** (`fetch_ohlcv` caps ~500-1000 rows/call): loop from `since_ms`,
  advancing the cursor to `last_ts + timeframe_ms` (using
  `exchange.parse_timeframe(timeframe) * 1000`), stop at `until_ms` or a short
  batch.

The exchange object is passed in (constructed by the caller), so tests inject a
fake exchange — no network in tests.

## 2. Metrics — `engine/metrics.py`

```python
def max_drawdown(curve: list[float]) -> float      # most negative peak-to-trough, e.g. -0.23
def summarize(equity: list[float], buy_hold: list[float], n_trades: int) -> dict
```
`summarize` returns:
`{final_equity, total_return, buy_hold_return, max_drawdown, n_trades, beats_hold}`
where `total_return = equity[-1]/equity[0] - 1`,
`buy_hold_return = buy_hold[-1]/buy_hold[0] - 1`,
`beats_hold = total_return > buy_hold_return`.

**Buy-and-hold benchmark (equal-weight):** both curves start at `capital`
(`equity[0] = buy_hold[0] = cfg.paper_capital`) so returns are measured from the
same baseline. Split the starting capital equally across the N symbols; at the
**first post-warmup bar** buy `qty_i = (capital/N)/price_i`, applying the same
one-time entry fee + slippage the strategy would pay (so the baseline isn't
unfairly frictionless); hold to the end. `buy_hold[t] = Σ qty_i · price_i[t]`.

## 3. Replay loop — `engine/backtest.py`

```python
def run_backtest(symbols, timeframe, since_ms, until_ms, strategy_name, cfg,
                 feed=datafeed.load_ohlcv, exchange=None) -> dict
```

1. Load each symbol's candles via `feed`. Build the **timeline** = the sorted
   intersection of all symbols' timestamps (same exchange+timeframe candles share
   boundaries; intersection keeps every step fully priced). For one symbol this is
   just its timestamps.
2. `strat = strategies.get(strategy_name)`; `cash = cfg.paper_capital`;
   `positions = {sym: Position(sym)}`; `equity_curve = [cfg.paper_capital]` (the
   baseline before any trade, so it and the buy-hold curve share a starting point).
3. For each timestamp `t` in the timeline:
   - **Price pre-pass:** for every symbol, `window = candles[ts <= t]`; skip this
     `t` entirely until **every** symbol's window has `>= indicators.MIN_ROWS` rows
     (warmup — no magic constant, derived from what `compute_indicators` requires);
     `feats[sym] = compute_indicators(window)`, `price[sym] = feats[sym]["price"]`.
   - `equity = cash + Σ positions[s].qty · price[s]` (full portfolio equity for sizing).
   - **Per symbol:** stop-check → else `strat(feats[sym], pos, cash, cfg)` →
     `broker.plan_order(decision, pos, cash, price, equity, cfg.risk)`; if an order
     comes back, `apply_fill` against shared `cash` and update `positions[sym]`;
     append the fill to `trades`.
   - Append `cash + Σ qty·price` to the equity curve.
4. Compute the buy-and-hold curve over the same timeline; call `metrics.summarize`.
5. Return `{metrics, equity_curve, buy_hold_curve, trades, timeline}`.

`# ponytail: recomputes indicators over the whole trailing window each step
(O(n²) total); precompute rolling indicators if backtests get slow.` For
year-scale hourly data this is a few seconds — fine.

**Output / CLI** — `python -m engine.backtest`:
```
--symbols BTC/USDT,ETH/USDT   (default: cfg.symbols)
--timeframe 1h                (default: cfg.timeframe)
--since 2024-01-01            (required; parsed to epoch ms, UTC)
--until 2025-01-01            (default: now)
--strategy indicator_rule     (default: cfg.strategy)
--capital 10000               (default: cfg.paper_capital)
```
Prints a summary table (final equity, total return %, buy-and-hold return %,
beats-hold ✓/✗, max drawdown %, # trades) and writes the equity + buy-hold curves
to `data/backtest_equity.csv` (inspectable; dashboard wiring is a later YAGNI).
Fees, slippage, risk, and `rules` come from `config.yaml`.

**LLM-strategy cost guard:** the harness is strategy-agnostic, so `hybrid` works
but makes one LLM call per candle per symbol. When the chosen strategy is not a
known deterministic one, print a loud warning with the estimated call count
(`len(timeline) × len(symbols)`) before running. It proceeds — it does not block —
but the practical path is `indicator_rule`.

## Safety properties (preserved)

- Every decision still passes through the **unmodified** `broker.plan_order` risk
  gate and `apply_fill`; the backtest cannot exceed position caps or cash, and
  spot long-only invariants hold. No live-bot code is modified.
- The backtest never touches `data/state.json`, `data/trades.csv`, or the file
  lock — it is read-only with respect to live state and writes only
  `data/cache/*` and `data/backtest_equity.csv`.

## Testing

`tests/test_datafeed.py` (fake exchange, no network):
- cache hit → no fetch when the file already covers the range
- cache miss → fetch, merge (union + dedupe by `ts`), write, slice
- pagination → fake exchange returns two batches; loop stitches them, advances the cursor
- range slice → returns only `[since, until]`

`tests/test_metrics.py`:
- `total_return` / `buy_hold_return` math on a known curve
- equal-weight buy-and-hold across two symbols with the entry fee applied
- `max_drawdown` on a curve with a known peak-to-trough

`tests/test_backtest.py` (fake feed, deterministic synthetic candles):
- monotonic up-trend + `indicator_rule` → buys, equity ends > start
- warmup: no trades before `MIN_ROWS` candles exist
- two-symbol timeline alignment uses the timestamp intersection
- the run never writes `state.json` / `trades.csv` (live state untouched)

## Files

| file | change |
|---|---|
| `engine/datafeed.py` | **new** — paginated ccxt fetch + disk cache |
| `engine/metrics.py` | **new** — return %, equal-weight B&H %, max drawdown |
| `engine/backtest.py` | **new** — replay loop + CLI |
| `tests/test_datafeed.py`, `tests/test_metrics.py`, `tests/test_backtest.py` | **new** |
| `README.md` | add a "Backtesting" usage section |

No changes to `bot.py`, `broker.py`, `strategies.py`, `indicators.py`, `models.py`.
