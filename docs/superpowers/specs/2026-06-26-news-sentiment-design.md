# News / Sentiment / Social Inputs — Design

**Date:** 2026-06-26
**Status:** Approved
**Sub-project:** 3 of 5 in the v2 roadmap (strategies → backtesting → **news/sentiment** → shorting/margin → live execution).
**Depends on:** the strategy seam (`engine/strategies.py`) and the backtest harness (`engine/backtest.py`), both merged to `main`.

## Goal

Blend market + news + social sentiment into a single normalized `sentiment`
score per symbol in `[-1, +1]`, and use it two ways:

1. **Feed the brain** — inject `sentiment` into the features dict every strategy
   already receives, so the hybrid LLM weighs it and any rule strategy can read it.
2. **A deterministic `sentiment_rule` strategy** — the existing `indicator_rule`
   logic with sentiment as a confirm/veto gate.

Realistic constraints baked in: **fail-safe** (a dead API or missing key never
breaks a cycle — it just drops that source), **cost-bounded** (per-source TTL
cache; news scoring uses provider votes, social scoring is offline), and
**F&G-backtestable** (the one source with real history replays in the harness).

Non-goals (later, if wanted): per-source dashboards, sentiment charting, an
LLM-scored social path, gap-only history fetch, contrarian F&G inversion.

## Architecture

One new module plus small additive hooks into existing code:

```
engine/sentiment.py   the SentimentSource seam, 4 adapters, VADER scoring,
                      the aggregator, per-source TTL cache, F&G history
engine/strategies.py  + sentiment_rule (registry entry)
engine/config.py      + SentimentConfig
engine/config.yaml    + sentiment: block
engine/bot.py         inject feats[sym]["sentiment"] before strategy dispatch
engine/backtest.py    inject backtest-mode sentiment (F&G history) per bar
```

**One new dependency:** `vaderSentiment` (pure-Python, no numpy/transitive deps —
none of the pandas-ta fragility the indicators were hand-rolled to avoid). All
HTTP uses stdlib `urllib.request` — no `requests`/`praw`/SDK added.

## 1. Source seam — `engine/sentiment.py`

Each source is a function returning a per-symbol score, normalized to `[-1, +1]`,
that **never raises** — any error, timeout, missing key, or empty result is caught
and that symbol is simply omitted (the aggregator excludes it from the blend):

```python
def fear_greed(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]
def cryptopanic(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]
def reddit(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]
def x_twitter(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]

SOURCES = {"fear_greed": fear_greed, "cryptopanic": cryptopanic,
           "reddit": reddit, "x_twitter": x_twitter}
```

A returned dict maps `symbol -> score` for every symbol the source could read; a
source that is down/keyless returns `{}`. `# ponytail: a per-source try/except
returns {} on any failure — sentiment is advisory, it must never break a cycle.`

**Symbol → coin:** `"BTC/USDT" -> "BTC"` (split on `/`, take the base) for news/social
queries. F&G is market-wide — the same score is applied to every symbol.

**Normalization (each → `[-1, +1]`):**
- **fear_greed** — alternative.me returns `0..100` (0 = extreme fear, 100 = extreme
  greed). `score = (value - 50) / 50`. Momentum reading: greed = positive. (Contrarian
  inversion is a future config flag, out of scope.)
- **cryptopanic** — over recent posts for the coin, use the provider's native vote
  counts: `(Σ positive - Σ negative) / max(1, Σ positive + Σ negative)`. No text
  scoring needed.
- **reddit / x_twitter** — fetch recent posts/titles mentioning the coin, score each
  with VADER's `compound` (already `[-1, +1]`), average them. Empty → omit the symbol.

**HTTP:** stdlib `urllib.request` with a short timeout and a User-Agent.
- fear_greed: `GET https://api.alternative.me/fng/?limit=1` (live) / `?limit=0` (history).
- cryptopanic: `GET https://cryptopanic.com/api/v1/posts/?auth_token=…&currencies=BTC`.
- reddit: OAuth2 client-credentials (`REDDIT_CLIENT_ID/SECRET` → bearer) then
  `GET /search` over crypto subreddits. `# ponytail: client-credentials read-only
  flow via urllib, no praw; upgrade to praw if pagination/rate-handling is needed.`
- x_twitter: `GET /2/tweets/search/recent` with `X_BEARER_TOKEN`; no key → `{}`.

## 2. Aggregator

```python
def aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]
```

- For each enabled source (per `cfg.sentiment.weights`), call it (cached — see below)
  and collect `{symbol: score}`.
- **Backtest mode** (`backtest=True`): only sources with real history run (just
  `fear_greed`, keyed to `ts_ms`); the rest return `{}`. So the blend in a backtest is
  the F&G component — replayable and deterministic.
- Per symbol: **weighted average over the sources that returned that symbol** (a source
  that errored/was excluded does not drag the score toward 0 — it simply isn't in the
  denominator). No source returned it → `0.0` (neutral).
- Result clamped to `[-1, +1]`.

**Caching** — `# ponytail: in-process dict {(source, key): (fetched_ms, value)} with a
per-source TTL; no disk cache for live (the bot loops in one process). Upgrade path:
shared disk cache if multiple processes need it.` TTLs default F&G 24h, news/social 1h.
The F&G **history** for backtests is fetched once and cached to disk
(`data/cache/feargreed.csv`, reusing the datafeed cache convention).

## 3. Integration

**Bot** (`engine/bot.py`) — once per cycle, before the per-symbol strategy dispatch:
```python
sent = sentiment.aggregate_sentiment(symbols, cfg)        # {sym: score}
...
feats["sentiment"] = sent.get(sym, 0.0)                    # inject per symbol
decision = strategy(feats, pos, st.cash, cfg)
```
The hybrid LLM path surfaces it **automatically with no `llm.py` change** —
`_build_user` already does `json.dumps(features)` into the prompt, so the new key
appears as `"sentiment": <score>`. (Optional ≤1-line polish: relabel the prompt's
`Indicators:` line or add a dedicated sentiment line for the model's clarity.)
Existing strategies that ignore `sentiment` are unaffected.

**New `sentiment_rule` strategy** (`engine/strategies.py`, registry) — the
`indicator_rule` signal logic with sentiment as a confirm/veto gate:

| indicators | sentiment `s` | action |
|---|---|---|
| bullish | `s >= buy_min` | **buy** (`buy_size`) |
| bullish | `s < buy_min` | hold (sentiment vetoes the buy) |
| bearish | any | **sell** (full) |
| neutral | `s <= sell_max` | **sell** (full — extreme negativity exits) |
| neutral | `s > sell_max` | hold |
| conflict (bullish+bearish) | any | hold |

Defaults: `buy_min = -0.2` (don't buy into strong negativity), `sell_max = -0.5`
(extreme negativity exits even when indicators are neutral). `# ponytail: fixed
buy_size; sentiment-proportional sizing is an easy follow-up.` Deterministic and
provably non-throwing (reads `feats.get("sentiment", 0.0)`), so it flows through the
unmodified `broker.plan_order` gate exactly like the other strategies.

## 4. Config

`engine/config.yaml`:
```yaml
sentiment:
  enabled: true
  weights: {fear_greed: 1.0, cryptopanic: 1.0, reddit: 1.0, x_twitter: 1.0}
  cache_ttl: {fear_greed: 86400, cryptopanic: 3600, reddit: 3600, x_twitter: 3600}
  buy_min: -0.2
  sell_max: -0.5
  http_timeout: 6
```
`SentimentConfig` dataclass mirrors this with defaults; `load_config` reads it with
per-key fallbacks (same pattern as `RulesConfig`). Keys come from the gitignored
`.env`: `CRYPTOPANIC_TOKEN`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`,
`X_BEARER_TOKEN`. A missing key disables only that source.

## 5. Backtest

`run_backtest` injects `feats[sym]["sentiment"] = aggregate_sentiment(symbols, cfg,
backtest=True, ts_ms=ts)[sym]` per bar. Only `fear_greed` contributes (its daily
history, cached to `data/cache/feargreed.csv`, floored to each candle's day). News/
social return `{}` → neutral. So `sentiment_rule` is genuinely backtestable on the
F&G component; the CLI gains it as a selectable `--strategy sentiment_rule`. The
`DETERMINISTIC` set in `backtest.py` adds `sentiment_rule` (no LLM warning).

## Safety properties (preserved)

- Every decision still passes through the **unmodified** `broker.plan_order` gate and
  `apply_fill`; `sentiment_rule` only changes which Decision is proposed, never how it
  executes. Spot long-only and the position/cash caps are untouched.
- Sentiment is strictly advisory and fail-safe: the aggregator never raises, so a
  network outage or absent key degrades to neutral — the bot keeps its HOLD-on-error
  guarantee.
- No new writes to live state; sentiment touches only its caches (`data/cache/*`).

## Testing

`tests/test_sentiment.py` (stub `urllib`/VADER inputs — no network):
- each adapter: a canned API payload → expected normalized score; error/missing-key → `{}`
- normalization math: F&G `0/50/100 → -1/0/+1`; cryptopanic vote ratio; VADER averaging
- aggregator: weighted blend over available sources; an excluded source doesn't drag toward 0; all-absent → 0.0; `backtest=True` runs only F&G; cache hit (no second fetch within TTL)

`tests/test_strategies.py` (extend): `sentiment_rule` truth table — bullish+positive →
buy, bullish+negative → veto/hold, neutral+extreme-negative → sell, conflict → hold,
missing `sentiment` key → treated as 0.0.

`tests/test_bot.py` / `tests/test_backtest.py` (extend): sentiment injected into the
features dict; absent sources → neutral, bot/backtest still trade; backtest F&G history
keyed to candle ts.

## Files

| file | change |
|---|---|
| `engine/sentiment.py` | **new** — sources + VADER scoring + aggregator + cache + F&G history |
| `engine/strategies.py` | **+** `sentiment_rule` (registry) |
| `engine/config.py` | **+** `SentimentConfig` + `load_config` wiring |
| `engine/config.yaml` | **+** `sentiment:` block |
| `engine/bot.py` | inject `feats["sentiment"]` before dispatch |
| `engine/backtest.py` | inject backtest-mode sentiment; add `sentiment_rule` to `DETERMINISTIC` |
| `engine/llm.py` | no change required (features dict is `json.dumps`'d into the prompt); optional ≤1-line relabel |
| `tests/test_sentiment.py`, `tests/test_strategies.py`, `tests/test_bot.py`, `tests/test_backtest.py` | tests |
| `README.md` | sentiment sources, keys, the `sentiment_rule` strategy |
| `requirements` | **+** `vaderSentiment` |

New dependency: `vaderSentiment`. No other live-execution, shorting, or order-routing
changes — those are later sub-projects.
