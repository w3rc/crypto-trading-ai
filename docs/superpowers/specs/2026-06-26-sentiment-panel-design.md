# Sentiment Panel (dashboard) — Design

**Date:** 2026-06-26
**Status:** Approved
**Follows:** the news/sentiment sub-project (`engine/sentiment.py`, merged to `main`).
**Depends on:** the Electron dashboard (`desktop/`, merged) and the sentiment module.

## Goal

Make the sentiment signal **visible** in the dashboard. Today the bot computes a
blended sentiment score each cycle and throws it away — the only trace is a cryptic
`s=+0.41` inside a decision's `reason`. This adds a **Sentiment panel** showing, per
symbol: the blended score (with a Fear/Greed label + color + a small gauge bar), the
per-source breakdown (Fear & Greed / news / Reddit / X, with unavailable sources shown
as `—`), and the **active strategy**.

The dashboard only renders what the bot writes to `data/`, so this has two halves:
the engine must **persist** a per-source breakdown, then the dashboard reads + renders it.

Non-goals (YAGNI): historical sentiment charting; per-source sparklines; backtest
sentiment in the panel (the panel is for watching the *live* bot); configuring sentiment
from the UI.

## Architecture

```
engine/sentiment.py   + breakdown() (per-source + blended); shared _blend helper
engine/state.py       + write_sentiment() (atomic write of data/sentiment.json)
engine/bot.py         compute breakdown once/cycle -> features + write sentiment.json
desktop/src/lib/      parse + read data/sentiment.json into the snapshot
desktop/src/renderer  + SentimentPanel component + a card in App
```

Data flow: **bot cycle → `data/sentiment.json` → dashboard polls (5s) → `SentimentPanel`.**

## 1. Engine — expose & persist the breakdown

```python
def breakdown(symbols, cfg, backtest=False, ts_ms=None) -> dict
# -> { "BTC/USDT": {"blended": -0.62,
#                   "sources": {"fear_greed": -0.78, "cryptopanic": -0.20,
#                               "reddit": None, "x_twitter": None}}, ... }
```

- Calls each weighted source (through the existing TTL cache), records each source's
  per-symbol score, and computes the weighted blend. A source that returned nothing for
  a symbol (no key / error / empty) is reported as `None` — distinct from a real `0.0`.
- The blend is computed by a shared helper so `breakdown` and `aggregate_sentiment` can't
  drift: extract `_blend(contrib) -> float` (weighted mean over present `(weight, score)`
  pairs, `0.0` if none, clamped) from today's aggregator. `aggregate_sentiment` becomes a
  thin wrapper: `{sym: breakdown(...)[sym]["blended"]}` — so its existing tests and the
  backtest caller keep working unchanged.
- `breakdown` is itself **fail-safe** (the same per-source try/except backstop), never raises.

```python
# engine/state.py
def write_sentiment(snapshot: dict, data_dir: str) -> None   # json.dump to data/sentiment.json
```
Atomic write (temp + replace, like `save_state_atomic`). The snapshot the bot writes:
```json
{ "ts": "<iso>", "strategy": "sentiment_rule",
  "symbols": { "BTC/USDT": {"blended": -0.62, "sources": {...}}, ... } }
```

**Bot wiring** (`engine/bot.py`): replace the one `aggregate_sentiment` call with a single
`breakdown` call per cycle when `cfg.sentiment.enabled`:
- features still get the blended score: `feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)`
  — **trading behavior is unchanged** (same value as before).
- after the per-symbol loop, write the snapshot:
  `state.write_sentiment({"ts": ts, "strategy": cfg.strategy, "symbols": bd}, cfg.data_dir)`.
- a write failure is caught and logged — it never aborts the cycle.
- when `cfg.sentiment.enabled` is false, no `breakdown` call and no file write (the dashboard
  reads the file as absent → panel shows "off").

## 2. Dashboard — read & render

**`desktop/src/lib/parse.ts`** — new types + parser:
```ts
export type SourceScores = { fear_greed: number | null; cryptopanic: number | null;
                             reddit: number | null; x_twitter: number | null };
export type SymbolSentiment = { blended: number; sources: SourceScores };
export type SentimentSnapshot = { ts: string; strategy: string;
                                  symbols: Record<string, SymbolSentiment> };
export function parseSentiment(text: string): SentimentSnapshot   // JSON.parse + shape
```
`Snapshot` gains `sentiment: SentimentSnapshot | null`.

**`desktop/src/lib/snapshot.ts`** — `readSnapshot` reads `data/sentiment.json` via the
existing `readOr(..., null, parseSentiment)` (missing/unreadable → `null`, never throws).

**`desktop/src/renderer/.../SentimentPanel.tsx`** — a new card. `null` sentiment →
`"Sentiment off"` empty state. Otherwise, a section per symbol:
- **blended**: the score, a Fear/Greed-style label (`≤ -0.5` Extreme Fear, `< -0.15` Fear,
  `≤ 0.15` Neutral, `< 0.5` Greed, else Extreme Greed), colored red→green, and a horizontal
  **gauge bar** (a CSS div; marker position = `(blended + 1) / 2`).
- **sources**: one row each — `F&G`, `news` (cryptopanic), `reddit`, `X` (x_twitter) — showing
  the score or `—` when `null`.
- a footer line: `strategy: <name>`.

`App.tsx` renders `<SentimentPanel sentiment={snap.sentiment} />` in a new grid card
(alongside Positions/Decisions). The label thresholds + gauge are pure CSS/JS — no new
chart dependency (recharts stays for the equity curve only).

## Safety / properties (preserved)

- Trading is unaffected: the blended value injected into `features` is identical to today's;
  `sentiment_rule` and the gate are untouched. This change only *persists and displays* what
  the bot already computes.
- `breakdown` and `write_sentiment` are fail-safe — a sentiment or disk error never breaks a
  bot cycle (the HOLD-on-error guarantee holds).
- The dashboard stays read-only and resilient: a missing/garbled `sentiment.json` → `null` →
  the panel shows "off", never crashes (same `readOr` pattern as the other files).

## Testing

`tests/test_sentiment.py` (extend): `breakdown` returns per-source scores + `null` for an
absent source + a blended value matching `aggregate_sentiment`; fail-safe (a raising source
→ that source `None`, no raise); `aggregate_sentiment` still returns blended-only and equals
`breakdown`'s blended.

`tests/test_state.py` (extend): `write_sentiment` writes valid JSON to `data/sentiment.json`
with `ts`/`strategy`/`symbols`; atomic (no partial file).

`tests/test_bot.py` (extend): with sentiment enabled, the cycle writes `sentiment.json` and
still injects the blended score into features (existing two tests updated to monkeypatch
`breakdown`); disabled → no file written.

`desktop` vitest: `parseSentiment` round-trips the snapshot; `readSnapshot` returns `null`
sentiment when the file is absent; `SentimentPanel` renders blended/label/sources/strategy
and the "off" empty state (component render test).

**Playwright visual verification** at 1280 / 768 / 375 with a representative `sentiment.json`
(via the built-renderer harness) — confirm the panel renders, colors/labels are right, and the
mobile reflow holds.

## Files

| file | change |
|---|---|
| `engine/sentiment.py` | **+** `breakdown()`, `_blend()` helper; `aggregate_sentiment` → thin wrapper |
| `engine/state.py` | **+** `write_sentiment()` (atomic) |
| `engine/bot.py` | compute `breakdown` once/cycle → features + write `sentiment.json` |
| `desktop/src/lib/parse.ts` | **+** sentiment types + `parseSentiment` |
| `desktop/src/lib/snapshot.ts` | read `data/sentiment.json` into the snapshot |
| `desktop/src/renderer/src/components/SentimentPanel.tsx` | **new** component |
| `desktop/src/renderer/src/App.tsx` | render the panel in a card |
| `desktop/src/renderer/src/index.css` | gauge bar + sentiment color styles |
| `.gitignore` | **+** `data/sentiment.json` (generated runtime artifact, like `state.json`/`trades.csv`) |
| tests (engine + desktop) | as above |
| `README.md` / `desktop/README.md` | note the sentiment panel + `sentiment.json` |

No new dependencies (engine or desktop). No change to `broker`/`indicators`/`models`/the gate.
