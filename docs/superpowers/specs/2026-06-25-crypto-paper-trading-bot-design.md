# AI-Driven Crypto Paper-Trading Bot — Design

**Date:** 2026-06-25
**Status:** Approved (design), pending implementation plan

## 1. Goal & non-goals

Build a crypto trading bot that makes **AI-driven** buy/sell/hold decisions and
**paper-trades** them (simulated money) against live market data, so the strategy
can be forward-tested and watched before any real capital is risked.

**Non-goals for v1 — explicitly planned for v2:**

- Live real-money execution on an exchange
- Shorting / margin / derivatives (spot long-only in v1)
- Backtesting against historical data
- News / sentiment / social inputs
- Additional / pluggable strategies (v1 ships the single hybrid indicators+LLM strategy)

**Out of scope entirely for now (YAGNI):** dashboard authentication / public hosting.

## 2. Core principles

1. **The LLM proposes; deterministic code disposes.** Every LLM decision passes
   through a risk gate written in plain Python that can clamp or veto it. The
   LLM's raw size/price never reaches the broker unchecked. This is the single
   most important safety property of the system.
2. **Fail-safe = HOLD.** Any error — network failure, malformed LLM output,
   corrupt state — results in *doing nothing* that cycle. Never trade on
   uncertainty.
3. **Stateless per run.** Each cron invocation is one independent decision cycle:
   load state → decide → act → persist → exit. No long-running daemon.
4. **Decoupled dashboard.** The dashboard only ever *reads* the state files the
   engine writes. It never imports or touches trading logic. The engine can run
   with the dashboard off; the dashboard can run with the engine off.

## 3. Decisions locked in

| Dimension | Decision |
|---|---|
| Risk posture | Paper trading (simulated money) |
| Brain | Hybrid — code computes indicators, LLM makes the final call with written reasoning |
| Cadence | Config-driven; bot runs once per invocation, triggered by cron/systemd-timer at any interval. Default cron `*/15 * * * *` |
| Interface | Desktop dashboard — custom **Electron** app (Vite + React), dark/gradient/glass aesthetic (motionsites-inspired), read-only + console/log output. (Was Next.js; changed to Electron 2026-06-25.) |
| Data + execution layer | CCXT (market data now; same library enables live `create_order` later) |
| Default exchange/data | Binance via CCXT (deepest liquidity; one-line swap to Crypto.com/Kraken/etc.) |
| Default symbols | `BTC/USDT`, `ETH/USDT` (configurable list) |
| Paper capital | $10,000 virtual (configurable) |
| Risk limits | Max 25% of equity per position; hard per-trade stop-loss; spot long-only |
| LLM | **OpenAI-compatible** endpoint via the `openai` Python SDK — one code path, `base_url`/`api_key`/`model` from config. Three presets: **OpenRouter**, **MyHermes AI** (`https://ai.myhermes.cloud/v1`), **custom** OpenAI-compatible endpoint. **Default: MyHermes AI + `z-ai/glm-5.2`.** Not the Anthropic SDK. |

## 4. Components

```
# Python engine (the bot) — writes state, never serves UI
engine/
  bot.py          # cron entrypoint: runs exactly one decision cycle, then exits
  broker.py       # paper broker (simulated fills, fees, slippage) + risk gate
  indicators.py   # RSI / MACD / moving averages / ATR from OHLCV (pandas-ta)
  llm.py          # build prompt, call Claude, parse STRUCTURED decision
  config.yaml     # symbols, paper capital, risk limits, model

# Shared state contract (the ONLY link between the two runtimes)
data/
  state.json      # cash, open positions, equity history (atomic writes)
  trades.csv      # append-only trade log

# Electron dashboard (read-only viewer) — separate desktop app (Node main + React renderer)
desktop/          # Electron + Vite + React, dark/gradient/glass UI
                  #   main process reads ../data/{state.json,trades.csv,decisions.jsonl}
                  #   renderer polls main via IPC; equity curve + positions + decision log
```

Runtime artifacts (gitignored): `data/state.json`, `data/trades.csv`, `.env`
(`ANTHROPIC_API_KEY`), `data/bot.lock`.

**Two runtimes, one contract.** The Python engine and the Next.js dashboard
share *nothing* but the files in `data/`. The engine never imports the
dashboard; the dashboard never imports the engine. The dashboard's server reads
the JSON/CSV from disk on each request and the client polls to refresh — no API
between them, no shared database, no shared process.

### Component responsibilities

- **bot.py** — orchestrates one cycle (see §5). Owns no business logic itself;
  wires the other modules together and handles persistence + logging.
- **broker.py** — two units that belong together:
  - *risk gate*: pure function `(proposed_decision, position, cash, config) →
    approved_decision | HOLD`. Clamps size to max-% rule, blocks selling more
    than held, blocks buying beyond cash, blocks shorts, enforces stop-loss.
    *Stop-losses are evaluated once per cycle (at cron time), not intratick — so
    the effective stop granularity equals the cron cadence. A 15-min cron means a
    position can move past its stop for up to ~15 min before the exit fires.*
  - *paper broker*: pure function `(approved_decision, price, state) →
    (new_state, fill_record)`. Applies configurable fee + slippage. Never does
    network I/O — fully testable offline.
- **indicators.py** — pure functions: OHLCV DataFrame → indicator values. No
  network, no state.
- **llm.py** — builds a compact prompt (indicator values + current price +
  current position + available cash), calls the configured **OpenAI-compatible**
  endpoint (`openai` SDK, `base_url` + `model` from config) asking for a strict
  JSON decision (`response_format={"type":"json_object"}` best-effort), then
  **validates the response with Pydantic** into `{action, size, reason, stop?}`.
  Any parse/validation/transport failure → HOLD. No provider-specific branching;
  the same code hits OpenRouter, MyHermes AI, or any custom endpoint.
- **desktop/** — Electron app (Vite + React, dark/gradient/glass aesthetic):
  equity curve chart, open positions table, decision/trade log. The Electron
  **main** process reads `data/{state.json,trades.csv,decisions.jsonl}` from
  disk and exposes a snapshot over IPC via a `contextBridge` preload; the
  **renderer** (React) polls it on an interval to refresh. Read-only — never
  writes, never trades. No auth, no DB. Runs as a desktop window, independent
  of the engine.

## 5. One decision cycle (bot.py)

```
load config + state
acquire lockfile (skip run if another cycle is in progress)
for each configured symbol:
    fetch OHLCV + ticker + orderbook via ccxt
    compute indicators (indicators.py)
    ask Claude for {action, size, reason, stop?}  (llm.py, structured)
    pass through RISK GATE (broker.py)            # clamp / veto in code
    simulate fill at price + fee/slippage (broker.py)
    update positions, cash, equity
    append trades.csv + decision log
persist state.json atomically (temp file + rename)
print cycle summary
release lockfile and exit
```

## 6. Data flow

```
cron ─▶ bot.run_once() ─▶ ccxt(data) ─▶ indicators ─▶ Claude ─▶ risk gate ─▶ paper broker ─▶ data/state.json + data/trades.csv
                                                                                                          ▲
                                  Electron app: main process reads files ──┘  renderer polls main (IPC) every N s
```

## 7. Error handling

| Failure | Behavior |
|---|---|
| One symbol's data fetch fails | Skip that symbol this cycle; continue others; log warning |
| LLM call fails or returns malformed output | Treat as HOLD for that symbol (fail-safe) |
| State file corrupt / unreadable | Refuse to trade; log loudly; do **not** overwrite existing state |
| Two cron runs overlap | Lockfile — second run exits immediately |
| Crash mid-write | State written atomically (temp + rename), so prior state survives |

## 8. Testing

Ponytail discipline: the money/security paths each leave one runnable check.

- **broker.py self-test:** buy→sell P&L math is correct; cannot spend more cash
  than available; cannot sell more than held.
- **risk gate self-test:** oversized order is clamped to the max-% rule; a short
  is blocked; stop-loss triggers a forced exit.
- **LLM is mocked** in tests — no network calls, no token spend.
- Indicators: optional sanity check against a known input series.

## 9. Stack

**Engine (Python 3.12):** `ccxt` · `pandas` + `pandas-ta` · `openai`
(OpenAI-compatible client, any `base_url`) · `pydantic` (validate the LLM
decision) · `pyyaml` · stdlib `json` / `csv` / `logging` / file lock.

**LLM provider presets (`config.yaml` + `.env`):**

| Preset | `base_url` | Key (`.env`) | `model` |
|---|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | any OpenRouter slug |
| **MyHermes AI (default)** | `https://ai.myhermes.cloud/v1` | `MYHERMES_API_KEY` | **`z-ai/glm-5.2`** (default) |
| Custom | user-supplied | user-supplied | user-supplied |

Models use provider-prefixed slugs (e.g. `z-ai/glm-5.2`, `anthropic/claude-sonnet-4-20250514`). The engine uses the Python `openai` SDK with `base_url`/`api_key` exactly as the JS SDK does.

**Dashboard (Electron desktop app):** Electron · Vite · React · TypeScript ·
hand-written CSS for the dark/glass look · Recharts for the equity curve. The
main process reads the `data/` files (Node `fs`) and serves snapshots to the
React renderer over a `contextBridge`/IPC channel — no HTTP server, no DB.

## 10. Path to "live" later (informational, not v1)

Because CCXT spans both data and execution, going live is a contained change:
replace the paper broker's simulated fill with `exchange.create_order(...)`,
add API-key custody + a kill-switch, and keep the *same* indicators, LLM, and
risk gate. The risk gate becomes even more important at that point. Backtesting
(replaying historical OHLCV through the same engine) is the recommended step
between v1 and live.
