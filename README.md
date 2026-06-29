# Crypto Paper-Trading Bot — Engine

AI-driven crypto **paper-trading** bot (simulated money). One cron cycle:
ccxt data → indicators → LLM decision → risk gate → simulated fill → `data/`.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real MYHERMES_API_KEY in .env
```

## Run one cycle
```bash
set -a && source .env && set +a
python -m engine.bot
```
Prints each symbol's decision and the cash/equity summary. State lives in
`data/state.json`; trades in `data/trades.csv`.

## Schedule it (cadence = your choice)
```cron
*/15 * * * * cd /path/to/cryptotrading_ai && set -a && . ./.env && set +a && .venv/bin/python -m engine.bot >> data/bot.log 2>&1
```
Change the cron expression to change cadence — hourly, daily, etc.

## Config
Edit `engine/config.yaml` — symbols, capital, risk limits, and the LLM
provider/model. Default: MyHermes AI + `z-ai/glm-5.2`. Swap `base_url` +
`api_key_env` + `model` for OpenRouter or any OpenAI-compatible endpoint.

## Backtesting

Replay a strategy over historical candles and see if it beats buy-and-hold:

```bash
python -m engine.backtest --symbols BTC/USDT,ETH/USDT --timeframe 1h \
  --since 2024-01-01 --strategy indicator_rule
```

Historical candles are cached under `data/cache/` and reused on later runs
over the same (or a contained) window; an open-ended run (no `--until`)
refetches once newer candles have closed. The equity + buy-hold curves are written to
`data/backtest_equity.csv`. Defaults (fees, slippage, risk, capital) come from
`engine/config.yaml`.

`indicator_rule` is the fast, deterministic strategy. Backtesting `hybrid` is
supported but makes one LLM call per candle per symbol (slow + costly) — you'll
get a warning.

## Sentiment

The bot can blend market + news + social sentiment into one `[-1, +1]` score per
symbol, fed into both the LLM brain (it appears in the prompt) and the deterministic
`sentiment_rule` strategy (which gates the indicator signals — it won't buy into
strong negativity and exits on extreme negativity).

The desktop dashboard is organized as a **nav sidebar + section views**. The sidebar pins the
bot's **mode** (color-coded — PAPER / SHADOW / LIVE, and a red **HALTED** when `data/HALT` is
present) plus live equity and P&L, so the safety-critical state is always visible. The sidebar also has a **mode toggle** (Paper / Shadow / Live) that writes `data/control.json`, which
the engine reads as a mode override on its next cycle (switching to **Live** asks for confirmation).
Live still requires `LIVE_TRADING_ARMED=yes` in the bot's env to place real orders — the toggle alone
runs **shadow** when unarmed, shown as `LIVE · UNARMED` in the rail. The nav switches
between **Overview** (account, equity curve, open positions, risk limits), **Positions**,
**Activity** (decisions + trades), **Sentiment**, and **Backtest** (strategy vs buy-and-hold from
`data/backtest_equity.csv`). The sidebar shows data **freshness** ("updated 8s ago") and flips to **STALE · bot stopped?** when the last `status.json` is older than ~2.5× `interval_seconds` (set this in `config.yaml` to match your cron cadence). It also shows a **brain-health** chip (OK / DEGRADED) derived from the latest decisions, and the decision log collapses repeated identical reasons into one `×N` row. It reads the same `data/*.json` snapshots the bot writes each cycle.

The **Sentiment** view renders per symbol: the blended score (Fear/Greed label + gauge), the per-source breakdown (`F&G` / `news` / `reddit` / `X`, with `—` for sources without a key), and the active strategy. It reads `data/sentiment.json`, which the bot writes each cycle.

Sources (each fail-safe — a missing key or dead API just drops that source):

| source | signal | key (`.env`) | backtestable |
|---|---|---|---|
| Fear & Greed | market-wide index | none (free) | yes (history) |
| CryptoPanic | per-coin news votes | `CRYPTOPANIC_TOKEN` | no |
| Reddit | per-coin post sentiment (VADER) | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | no |
| X / Twitter | per-coin tweet sentiment (VADER) | `X_BEARER_TOKEN` | no |

Configure weights, cache TTLs, and the `buy_min`/`sell_max` thresholds under
`sentiment:` in `engine/config.yaml`. Backtests replay only the Fear & Greed
component (the others have no clean history):

```bash
python -m engine.backtest --since 2024-01-01 --strategy sentiment_rule
```

## Shorting

Set `risk.allow_short: true` (or point at a derivatives exchange, where it auto-enables) to
let the bot hold **short** positions: a `sell` from flat opens a short (`qty < 0`), a `buy`
covers it, and the stop-loss works both directions. Capped by `max_position_pct` like longs.
The dashboard's positions table shows a **Side** (Long/Short) column.

## Leverage + liquidation

Set `risk.leverage` > 1 to trade with **leverage** (isolated margin, opt-in — the default
`1.0` is unleveraged and changes nothing). Each position posts `margin = |qty|·avg / leverage`,
so the exposure cap rises to `max_position_pct · equity · leverage`. A position is **liquidated**
— force-closed at its isolated liquidation price — when an adverse move erodes that margin down
to `risk.maintenance_margin_pct` (default 0.5%). The protective stop-loss still fires first on
low leverage; liquidation is the high-leverage / gap backstop, and a gap *past* the liquidation
price is socialized as bad debt (cash never goes negative). Like shorting, this only activates on
a derivatives venue or explicit config — the default spot setup is unchanged. The positions table
shows **Lev** and **Liq. price** columns.

## Funding

Set `risk.funding_rate` (per `risk.funding_interval_hours`, default 8h) to charge perpetual
**funding** on open positions: a positive rate means **longs pay shorts** (and vice versa),
`funding_rate · notional` each interval. It debits/credits cash (clamped ≥ 0) and so erodes or
boosts equity for as long as a position is held — the holding cost the leverage + liquidation model
was missing. `funding_rate = 0` (the default) is off and changes nothing. Funding is an account
cash flow here; it doesn't shift a position's isolated liquidation price (the realistic refinement,
and a live ccxt funding feed, are the upgrade paths).

## Shadow mode (real-account dry-run)

Set `mode: shadow` to run the bot against your **real exchange account read-only** - it fetches
your real balance + price, computes the order it *would* place, and logs it (decisions show
`executed: false` with a `[shadow]` reason), but **places nothing and moves no money**. Use a
**read-only / no-trade API key** in `.env` (`EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`). The
dashboard's Status strip shows `MODE: SHADOW`. This is the dry-run stage before live execution:
`paper` (simulated) -> `shadow` (real reads, zero execution) -> live (slice 2). `create_order` does
not exist in the codebase yet - shadow cannot trade.

## Live execution (real orders)

Set `mode: live` **and** export `LIVE_TRADING_ARMED=yes` to place **real spot market orders**
(long-only). Both switches are required — `mode: live` alone (or a stale committed config) falls
back to shadow and places nothing. Use a **trade-enabled, withdrawal-disabled** API key in `.env`
(`EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`).

The exchange is the source of truth: each cycle re-reads your real cash + balances, so a crash, a
partial fill, or a manual trade never desyncs the bot. Entry price and stop-loss (which the exchange
doesn't store) live in `data/live_meta.json`; `data/state.json` is a read-only mirror for the
dashboard. Orders are sized by the same risk gate as paper, rounded to the exchange's precision, and
skipped if below its minimum notional.

**Kill switch:** `touch data/HALT` stops all execution instantly (the dashboard shows `HALTED`);
`rm data/HALT` resumes. Progression: `paper` (simulated) → `shadow` (real reads, zero execution) →
`live` (real orders). `create_order` exists in exactly one place (`market.create_order`), reachable
only when live, armed, and not halted.

## Tests
```bash
python -m pytest -q
```
