# News / Sentiment / Social Inputs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blend market + news + social sentiment into one normalized `[-1, +1]` score per symbol, feed it into the features dict (the LLM brain + any strategy) and a new deterministic `sentiment_rule` strategy — fail-safe, cost-bounded, and F&G-backtestable.

**Architecture:** A new `engine/sentiment.py` module holding four fail-safe source adapters (Fear & Greed, CryptoPanic, Reddit, X) behind a `SOURCES` registry, a VADER scorer for social text, and a weighted aggregator with a TTL cache. Small additive hooks inject the score into `bot.run_once` and `backtest.run_backtest`. A new `sentiment_rule` strategy gates the existing `indicator_rule` signals by the score.

**Tech Stack:** Python 3.14, stdlib `urllib`/`csv`/`base64`, `vaderSentiment` (one new dep), pytest. No `requests`/`praw`/SDK.

## Global Constraints

- **One new dependency only:** `vaderSentiment` (pure-Python). All HTTP via stdlib `urllib.request`.
- **Fail-safe:** every source catches all errors and returns `{}` (or omits a symbol); the aggregator never raises. A dead API or missing key degrades to neutral — the bot keeps its HOLD-on-error guarantee.
- **Every decision still flows through the unmodified `broker.plan_order` gate and `apply_fill`.** `sentiment_rule` only changes which `Decision` is proposed; spot long-only and position/cash caps are untouched.
- **Scores normalize to `[-1, +1]`.** Fear & Greed `0/50/100 → -1/0/+1` (momentum reading: greed positive).
- **Backtest replays only backtestable sources** (Fear & Greed history, keyed to candle ts); news/social return `{}` in `backtest=True`.
- **Sentiment writes only its caches** (`data/cache/*`) — never `state.json`/`trades.csv`/the lock.
- **Keys come from the gitignored `.env`:** `CRYPTOPANIC_TOKEN`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `X_BEARER_TOKEN`. A missing key disables only that source.
- Local commits OK (already authorized for this project). Do not push or open a PR without explicit go-ahead.

---

### Task 1: Config — `SentimentConfig`

**Files:**
- Modify: `engine/config.py`
- Modify: `engine/config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `SentimentConfig(enabled: bool, weights: dict, cache_ttl: dict, buy_min: float, sell_max: float, http_timeout: float)`; `Config` gains `sentiment: SentimentConfig` (default factory). `load_config` reads the `sentiment:` block with per-key fallbacks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_sentiment_loads_from_yaml(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.sentiment.enabled is True
    assert cfg.sentiment.weights["fear_greed"] == 1.0
    assert cfg.sentiment.cache_ttl["fear_greed"] == 86400
    assert cfg.sentiment.buy_min == -0.2
    assert cfg.sentiment.sell_max == -0.5


def test_sentiment_defaults_when_block_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.sentiment.enabled is True           # default
    assert cfg.sentiment.weights["reddit"] == 1.0  # default weights
    assert cfg.sentiment.buy_min == -0.2


def test_sentiment_partial_override_merges(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
        "sentiment:\n  enabled: false\n  weights: {fear_greed: 2.0}\n  buy_min: 0.1\n"
    )
    cfg = load_config(str(p))
    assert cfg.sentiment.enabled is False
    assert cfg.sentiment.weights["fear_greed"] == 2.0   # overridden
    assert cfg.sentiment.weights["reddit"] == 1.0       # default preserved (merge)
    assert cfg.sentiment.buy_min == 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -k sentiment -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'sentiment'`

- [ ] **Step 3: Implement `SentimentConfig` in `engine/config.py`**

Add after the `RulesConfig` dataclass:

```python
def _default_weights():
    return {"fear_greed": 1.0, "cryptopanic": 1.0, "reddit": 1.0, "x_twitter": 1.0}


def _default_ttl():
    return {"fear_greed": 86400, "cryptopanic": 3600, "reddit": 3600, "x_twitter": 3600}


@dataclass
class SentimentConfig:
    enabled: bool = True
    weights: dict = field(default_factory=_default_weights)
    cache_ttl: dict = field(default_factory=_default_ttl)
    buy_min: float = -0.2
    sell_max: float = -0.5
    http_timeout: float = 6.0
```

Add the field to the `Config` dataclass (after `rules`):

```python
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
```

In `load_config`, after `rules_raw = raw.get("rules", {})` add:

```python
    sent_raw = raw.get("sentiment", {})
```

and add this to the `Config(...)` constructor (after the `rules=...` argument):

```python
        sentiment=SentimentConfig(
            enabled=bool(sent_raw.get("enabled", True)),
            weights={**_default_weights(), **sent_raw.get("weights", {})},
            cache_ttl={**_default_ttl(), **sent_raw.get("cache_ttl", {})},
            buy_min=float(sent_raw.get("buy_min", -0.2)),
            sell_max=float(sent_raw.get("sell_max", -0.5)),
            http_timeout=float(sent_raw.get("http_timeout", 6.0)),
        ),
```

- [ ] **Step 4: Add the `sentiment:` block to `engine/config.yaml`**

Append to `engine/config.yaml`:

```yaml
sentiment:
  enabled: true
  weights: {fear_greed: 1.0, cryptopanic: 1.0, reddit: 1.0, x_twitter: 1.0}
  cache_ttl: {fear_greed: 86400, cryptopanic: 3600, reddit: 3600, x_twitter: 3600}
  buy_min: -0.2
  sell_max: -0.5
  http_timeout: 6
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests).

- [ ] **Step 6: Commit**

```bash
git add engine/config.py engine/config.yaml tests/test_config.py
git commit -m "feat(sentiment): SentimentConfig + config.yaml block

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Sentiment primitives + Fear & Greed adapter — `engine/sentiment.py`

**Files:**
- Create: `engine/sentiment.py`
- Modify: `requirements.txt`
- Test: `tests/test_sentiment.py`

**Interfaces:**
- Produces:
  - `_coin(symbol) -> str` (`"BTC/USDT" -> "BTC"`)
  - `_http_json(url, headers=None, timeout=6.0) -> dict` (stdlib urllib GET)
  - `_vader_score(texts) -> float | None` (mean VADER compound, `None` if empty)
  - `_clamp(x) -> float` (to `[-1, 1]`)
  - `fear_greed(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]`
  - Module globals `_CACHE = {}`, `_FNG_HISTORY = None`; helpers `_fng_history(cfg)`, `_fng_lookup(hist, day_ms)`.

- [ ] **Step 1: Add the dependency**

Append `vaderSentiment` to `requirements.txt`, then install it:

Run: `pip install vaderSentiment`
Expected: installs successfully (pure-Python, no build step).

- [ ] **Step 2: Write the failing tests**

Create `tests/test_sentiment.py`:

```python
from types import SimpleNamespace
from engine import sentiment


def _cfg(weights=None):
    return SimpleNamespace(sentiment=SimpleNamespace(
        weights=weights or {"fear_greed": 1.0, "cryptopanic": 1.0,
                            "reddit": 1.0, "x_twitter": 1.0},
        cache_ttl={"fear_greed": 86400, "cryptopanic": 3600,
                   "reddit": 3600, "x_twitter": 3600},
        http_timeout=6.0, enabled=True, buy_min=-0.2, sell_max=-0.5))


def test_coin_extracts_base():
    assert sentiment._coin("BTC/USDT") == "BTC"
    assert sentiment._coin("eth/usdt") == "ETH"


def test_vader_score_sign_and_empty():
    assert sentiment._vader_score(["to the moon, super bullish breakout!"]) > 0
    assert sentiment._vader_score(["rug pull, scam, dumping hard, bearish"]) < 0
    assert sentiment._vader_score([]) is None


def test_fear_greed_normalizes_live(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "75"}]})
    out = sentiment.fear_greed(["BTC/USDT", "ETH/USDT"], _cfg())
    assert out["BTC/USDT"] == 0.5 and out["ETH/USDT"] == 0.5   # (75-50)/50, market-wide


def test_fear_greed_extremes(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "0"}]})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg())["BTC/USDT"] == -1.0
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "100"}]})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg())["BTC/USDT"] == 1.0


def test_fear_greed_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(sentiment, "_http_json", boom)
    assert sentiment.fear_greed(["BTC/USDT"], _cfg()) == {}


def test_fear_greed_backtest_uses_history(monkeypatch):
    day = (1_700_000_000_000 // 86_400_000) * 86_400_000
    monkeypatch.setattr(sentiment, "_fng_history", lambda cfg: {day: 75.0})
    out = sentiment.fear_greed(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1_700_000_000_000)
    assert out["BTC/USDT"] == 0.5
    # a day with no history (and none in the prior week) -> empty
    monkeypatch.setattr(sentiment, "_fng_history", lambda cfg: {})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1_700_000_000_000) == {}


def test_fng_lookup_floors_to_earlier_day():
    day = 10 * 86_400_000
    hist = {day - 2 * 86_400_000: 40.0}        # value 2 days earlier
    assert sentiment._fng_lookup(hist, day) == 40.0   # walks back to the nearest earlier day
    assert sentiment._fng_lookup({}, day) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.sentiment'`

- [ ] **Step 4: Implement `engine/sentiment.py`**

```python
import csv
import json
import os
import time
import urllib.parse
import urllib.request

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_VADER = SentimentIntensityAnalyzer()
_CACHE = {}          # {(source, symbols): (fetched_ms, {sym: score})}
_FNG_HISTORY = None  # {day_ms: value}, loaded once for backtests

_DAY_MS = 86_400_000


def _coin(symbol):
    return symbol.split("/")[0].upper()


def _clamp(x):
    return max(-1.0, min(1.0, x))


def _http_json(url, headers=None, timeout=6.0):
    req = urllib.request.Request(
        url, headers=headers or {"User-Agent": "cryptotrading-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _vader_score(texts):
    if not texts:
        return None
    scores = [_VADER.polarity_scores(t)["compound"] for t in texts]
    return sum(scores) / len(scores)


# ---- Fear & Greed (alternative.me) — market-wide, the one backtestable source ----

def _read_fng_cache(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path) as f:
        for row in csv.reader(f):
            out[int(row[0])] = float(row[1])
    return out


def _write_fng_cache(path, hist):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for day_ms, val in sorted(hist.items()):
            w.writerow([day_ms, val])


def _fng_history(cfg):
    # ponytail: fetched once, cached to disk + a process global; no incremental
    # refresh (the daily series rarely needs the last day or two for a backtest).
    global _FNG_HISTORY
    if _FNG_HISTORY is not None:
        return _FNG_HISTORY
    path = os.path.join("data", "cache", "feargreed.csv")
    hist = _read_fng_cache(path)
    if not hist:
        data = _http_json("https://api.alternative.me/fng/?limit=0",
                          timeout=cfg.sentiment.http_timeout)
        hist = {}
        for d in data["data"]:
            day_ms = (int(d["timestamp"]) // 86400) * 86400 * 1000
            hist[day_ms] = float(d["value"])
        _write_fng_cache(path, hist)
    _FNG_HISTORY = hist
    return hist


def _fng_lookup(hist, day_ms):
    d = day_ms
    for _ in range(8):                 # this day, or the nearest earlier (up to a week)
        if d in hist:
            return hist[d]
        d -= _DAY_MS
    return None


def fear_greed(symbols, cfg, backtest=False, ts_ms=None):
    try:
        if backtest:
            day = (ts_ms // _DAY_MS) * _DAY_MS
            val = _fng_lookup(_fng_history(cfg), day)
            if val is None:
                return {}
        else:
            data = _http_json("https://api.alternative.me/fng/?limit=1",
                              timeout=cfg.sentiment.http_timeout)
            val = float(data["data"][0]["value"])
        score = (val - 50) / 50.0      # 0->-1, 50->0, 100->+1
        return {s: score for s in symbols}
    except Exception:
        return {}                      # fail-safe: advisory only, never break a cycle
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add engine/sentiment.py tests/test_sentiment.py requirements.txt
git commit -m "feat(sentiment): primitives + Fear & Greed adapter (live + backtest history)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: News + social adapters — CryptoPanic, Reddit, X

**Files:**
- Modify: `engine/sentiment.py`
- Test: `tests/test_sentiment.py`

**Interfaces:**
- Produces:
  - `cryptopanic(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]` (vote ratio per coin)
  - `reddit(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]` (VADER over titles)
  - `x_twitter(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]` (VADER over tweets)
  - `_reddit_token(cfg) -> str | None` (OAuth client-credentials)
  - `SOURCES = {"fear_greed": ..., "cryptopanic": ..., "reddit": ..., "x_twitter": ...}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sentiment.py`:

```python
def test_cryptopanic_vote_ratio(monkeypatch):
    monkeypatch.setenv("CRYPTOPANIC_TOKEN", "tok")
    payload = {"results": [
        {"votes": {"positive": 6, "negative": 2}},
        {"votes": {"positive": 0, "negative": 0}},
    ]}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    out = sentiment.cryptopanic(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] == (6 - 2) / (6 + 2)   # 0.5


def test_cryptopanic_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("CRYPTOPANIC_TOKEN", raising=False)
    assert sentiment.cryptopanic(["BTC/USDT"], _cfg()) == {}


def test_cryptopanic_backtest_returns_empty(monkeypatch):
    monkeypatch.setenv("CRYPTOPANIC_TOKEN", "tok")
    assert sentiment.cryptopanic(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1) == {}


def test_reddit_scores_titles_with_vader(monkeypatch):
    monkeypatch.setattr(sentiment, "_reddit_token", lambda cfg: "tok")
    payload = {"data": {"children": [
        {"data": {"title": "bullish breakout, mooning"}},
        {"data": {"title": "great accumulation zone, very bullish"}},
    ]}}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    out = sentiment.reddit(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] > 0


def test_reddit_no_token_returns_empty(monkeypatch):
    monkeypatch.setattr(sentiment, "_reddit_token", lambda cfg: None)
    assert sentiment.reddit(["BTC/USDT"], _cfg()) == {}


def test_x_twitter_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert sentiment.x_twitter(["BTC/USDT"], _cfg()) == {}


def test_x_twitter_scores_tweets(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")
    payload = {"data": [{"text": "bearish, dumping, rug"}, {"text": "scam, crashing"}]}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    assert sentiment.x_twitter(["BTC/USDT"], _cfg())["BTC/USDT"] < 0


def test_sources_registry_has_four():
    assert set(sentiment.SOURCES) == {"fear_greed", "cryptopanic", "reddit", "x_twitter"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment.py -k "cryptopanic or reddit or x_twitter or sources" -v`
Expected: FAIL — `AttributeError: module 'engine.sentiment' has no attribute 'cryptopanic'`

- [ ] **Step 3: Implement the three adapters + registry**

Add `import base64` to the top of `engine/sentiment.py` (with the other imports), then append:

```python
# ---- CryptoPanic (news) — per-coin, uses native bullish/bearish votes ----

def cryptopanic(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    token = os.environ.get("CRYPTOPANIC_TOKEN", "")
    if not token:
        return {}
    out = {}
    for sym in symbols:
        try:
            url = ("https://cryptopanic.com/api/v1/posts/?public=true&auth_token="
                   + urllib.parse.quote(token) + "&currencies=" + _coin(sym))
            data = _http_json(url, timeout=cfg.sentiment.http_timeout)
            pos = neg = 0
            for post in data.get("results", []):
                v = post.get("votes", {})
                pos += v.get("positive", 0)
                neg += v.get("negative", 0)
            total = pos + neg
            if total:
                out[sym] = _clamp((pos - neg) / total)
        except Exception:
            continue
    return out


# ---- Reddit (social) — OAuth client-credentials, VADER over titles ----

def _reddit_token(cfg):
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not (cid and secret):
        return None
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=body,
        headers={"Authorization": f"Basic {auth}",
                 "User-Agent": "cryptotrading-bot/1.0"})
    with urllib.request.urlopen(req, timeout=cfg.sentiment.http_timeout) as resp:
        return json.loads(resp.read().decode()).get("access_token")


def reddit(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    try:
        token = _reddit_token(cfg)
    except Exception:
        token = None
    if not token:
        return {}
    headers = {"Authorization": f"bearer {token}",
               "User-Agent": "cryptotrading-bot/1.0"}
    out = {}
    for sym in symbols:
        try:
            url = ("https://oauth.reddit.com/r/CryptoCurrency/search?restrict_sr=1"
                   "&limit=25&sort=new&q=" + urllib.parse.quote(_coin(sym)))
            data = _http_json(url, headers=headers, timeout=cfg.sentiment.http_timeout)
            titles = [c.get("data", {}).get("title", "")
                      for c in data.get("data", {}).get("children", [])]
            score = _vader_score(titles)
            if score is not None:
                out[sym] = _clamp(score)
        except Exception:
            continue
    return out


# ---- X / Twitter (social) — bearer token, VADER over recent tweets ----

def x_twitter(symbols, cfg, backtest=False, ts_ms=None):
    if backtest:
        return {}
    token = os.environ.get("X_BEARER_TOKEN", "")
    if not token:
        return {}
    headers = {"Authorization": f"Bearer {token}",
               "User-Agent": "cryptotrading-bot/1.0"}
    out = {}
    for sym in symbols:
        try:
            q = urllib.parse.quote(f"{_coin(sym)} crypto -is:retweet lang:en")
            url = ("https://api.twitter.com/2/tweets/search/recent?max_results=25"
                   "&query=" + q)
            data = _http_json(url, headers=headers, timeout=cfg.sentiment.http_timeout)
            texts = [t.get("text", "") for t in data.get("data", [])]
            score = _vader_score(texts)
            if score is not None:
                out[sym] = _clamp(score)
        except Exception:
            continue
    return out


SOURCES = {"fear_greed": fear_greed, "cryptopanic": cryptopanic,
           "reddit": reddit, "x_twitter": x_twitter}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: PASS (all sentiment tests so far).

- [ ] **Step 5: Commit**

```bash
git add engine/sentiment.py tests/test_sentiment.py
git commit -m "feat(sentiment): CryptoPanic, Reddit, X adapters + SOURCES registry

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Aggregator + TTL cache — `engine/sentiment.py`

**Files:**
- Modify: `engine/sentiment.py`
- Test: `tests/test_sentiment.py`

**Interfaces:**
- Produces: `aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None) -> dict[str, float]`; cache helpers `_cache_get(key, ttl)`, `_cache_put(key, value)`.

- [ ] **Step 1: Write the failing tests**

First, add `import pytest` to the top of `tests/test_sentiment.py` (just below `from types import SimpleNamespace`). Then append the cache fixture and tests:

```python
@pytest.fixture(autouse=True)
def _clear_cache():
    sentiment._CACHE.clear()
    yield
    sentiment._CACHE.clear()


def test_aggregate_weighted_blend(monkeypatch):
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 1.0 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic",
                        lambda s, c, backtest=False, ts_ms=None: {x: -1.0 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "reddit",
                        lambda s, c, backtest=False, ts_ms=None: {})
    monkeypatch.setitem(sentiment.SOURCES, "x_twitter",
                        lambda s, c, backtest=False, ts_ms=None: {})
    cfg = _cfg(weights={"fear_greed": 3.0, "cryptopanic": 1.0,
                        "reddit": 1.0, "x_twitter": 1.0})
    out = sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    assert out["BTC/USDT"] == pytest.approx((3 * 1.0 + 1 * -1.0) / 4)   # 0.5


def test_aggregate_excluded_source_does_not_drag(monkeypatch):
    # only fear_greed reports; an absent source must NOT pull the score toward 0
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.8 for x in s})
    for name in ("cryptopanic", "reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    out = sentiment.aggregate_sentiment(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] == pytest.approx(0.8)


def test_aggregate_all_absent_is_zero(monkeypatch):
    for name in sentiment.SOURCES:
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    assert sentiment.aggregate_sentiment(["BTC/USDT"], _cfg())["BTC/USDT"] == 0.0


def test_aggregate_backtest_only_runs_fear_greed(monkeypatch):
    seen = []

    def fg(s, c, backtest=False, ts_ms=None):
        seen.append(("fear_greed", backtest))
        return {x: 0.5 for x in s}

    def others(s, c, backtest=False, ts_ms=None):
        seen.append(("other", backtest))
        return {}                          # adapters self-disable when backtest=True

    monkeypatch.setitem(sentiment.SOURCES, "fear_greed", fg)
    for name in ("cryptopanic", "reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name, others)
    out = sentiment.aggregate_sentiment(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1)
    assert out["BTC/USDT"] == 0.5
    assert ("fear_greed", True) in seen      # fear_greed called in backtest mode


def test_aggregate_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake(s, c, backtest=False, ts_ms=None):
        calls["n"] += 1
        return {x: 0.4 for x in s}

    monkeypatch.setitem(sentiment.SOURCES, "fear_greed", fake)
    cfg = _cfg(weights={"fear_greed": 1.0})   # only fear_greed weighted
    sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    assert calls["n"] == 1                     # second call served from cache
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment.py -k aggregate -v`
Expected: FAIL — `AttributeError: module 'engine.sentiment' has no attribute 'aggregate_sentiment'`

- [ ] **Step 3: Implement the aggregator + cache**

Append to `engine/sentiment.py`:

```python
def _cache_get(key, ttl):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_put(key, value):
    _CACHE[key] = (time.time(), value)


def _source_scores(name, fn, symbols, cfg, backtest, ts_ms):
    if backtest:
        return fn(symbols, cfg, backtest=True, ts_ms=ts_ms)   # history-backed, no live cache
    ttl = cfg.sentiment.cache_ttl.get(name, 3600)
    key = (name, tuple(symbols))
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached
    val = fn(symbols, cfg, backtest=False)
    _cache_put(key, val)
    return val


def aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None):
    weights = cfg.sentiment.weights
    contrib = {s: [] for s in symbols}      # {sym: [(weight, score), ...]}
    for name, fn in SOURCES.items():
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        for sym, score in _source_scores(name, fn, symbols, cfg, backtest, ts_ms).items():
            if sym in contrib:
                contrib[sym].append((w, score))
    out = {}
    for sym in symbols:
        items = contrib[sym]
        tw = sum(w for w, _ in items)
        out[sym] = _clamp(sum(w * sc for w, sc in items) / tw) if tw else 0.0
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: PASS (all sentiment tests).

- [ ] **Step 5: Commit**

```bash
git add engine/sentiment.py tests/test_sentiment.py
git commit -m "feat(sentiment): weighted aggregator + TTL cache

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `sentiment_rule` strategy — `engine/strategies.py`

**Files:**
- Modify: `engine/strategies.py`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `cfg.rules` (`rsi_buy/rsi_sell/buy_size`), `cfg.sentiment` (`buy_min/sell_max`), `features["sentiment"]` (defaults to `0.0` if absent).
- Produces: `sentiment_rule(features, position, cash, cfg) -> Decision`; added to `STRATEGIES`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_strategies.py`:

```python
def _ns_s(rsi_buy=30, rsi_sell=70, buy_size=0.5, buy_min=-0.2, sell_max=-0.5):
    return SimpleNamespace(
        rules=SimpleNamespace(rsi_buy=rsi_buy, rsi_sell=rsi_sell, buy_size=buy_size),
        sentiment=SimpleNamespace(buy_min=buy_min, sell_max=sell_max))


def _feats_s(rsi, sentiment, macd=0.0, sig=0.0, fast=100.0, slow=100.0):
    return {"price": 100.0, "rsi": rsi, "macd": macd, "macd_signal": sig,
            "ma_fast": fast, "ma_slow": slow, "atr": 1.0, "sentiment": sentiment}


def test_sentiment_rule_bullish_confirmed_buys():
    d = strategies.sentiment_rule(_feats_s(rsi=25, sentiment=0.5), _FLAT, 1000.0, _ns_s())
    assert d.action == "buy" and d.size == 0.5


def test_sentiment_rule_bullish_vetoed_by_negative():
    d = strategies.sentiment_rule(_feats_s(rsi=25, sentiment=-0.5), _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"          # indicators bullish but sentiment < buy_min -> veto


def test_sentiment_rule_bearish_sells():
    d = strategies.sentiment_rule(_feats_s(rsi=80, sentiment=0.9), _FLAT, 1000.0, _ns_s())
    assert d.action == "sell" and d.size == 1.0


def test_sentiment_rule_neutral_extreme_negative_exits():
    d = strategies.sentiment_rule(_feats_s(rsi=50, sentiment=-0.6), _FLAT, 1000.0, _ns_s())
    assert d.action == "sell"          # neutral indicators, sentiment <= sell_max -> risk-off


def test_sentiment_rule_neutral_holds():
    d = strategies.sentiment_rule(_feats_s(rsi=50, sentiment=0.0), _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"


def test_sentiment_rule_conflict_holds():
    # bullish via rsi<30 AND bearish via macd<sig & fast<slow -> conflict -> hold (even if very negative)
    d = strategies.sentiment_rule(
        _feats_s(rsi=25, sentiment=-0.9, macd=-1, sig=0, fast=99, slow=100),
        _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"


def test_sentiment_rule_missing_key_treated_as_neutral():
    feats = {"price": 100.0, "rsi": 50, "macd": 0.0, "macd_signal": 0.0,
             "ma_fast": 100.0, "ma_slow": 100.0, "atr": 1.0}   # no "sentiment"
    d = strategies.sentiment_rule(feats, _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"          # sentiment defaults to 0.0 -> neutral hold


def test_sentiment_rule_registered():
    assert strategies.get("sentiment_rule") is strategies.sentiment_rule
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategies.py -k sentiment -v`
Expected: FAIL — `AttributeError: module 'engine.strategies' has no attribute 'sentiment_rule'`

- [ ] **Step 3: Implement `sentiment_rule`**

Add to `engine/strategies.py` (after `indicator_rule`):

```python
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
```

Update the registry:

```python
STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule,
              "sentiment_rule": sentiment_rule}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: PASS (all strategy tests).

- [ ] **Step 5: Commit**

```bash
git add engine/strategies.py tests/test_strategies.py
git commit -m "feat(sentiment): sentiment_rule strategy (indicator signals gated by sentiment)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Bot integration — inject `sentiment` into the features dict

**Files:**
- Modify: `engine/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `sentiment.aggregate_sentiment(symbols, cfg)`, `cfg.sentiment.enabled`.
- Produces: each per-symbol `feats` gains `feats["sentiment"]` before strategy dispatch.

- [ ] **Step 1: Write the failing tests**

In `tests/test_bot.py`, update the imports and the `_cfg` helper so existing tests stay offline (sentiment disabled), then add two new tests.

Change the config import line to add `SentimentConfig`:

```python
from engine.config import Config, RiskConfig, LLMConfig, SentimentConfig
```

Update `_cfg` to disable sentiment by default (keeps the existing tests network-free):

```python
def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  sentiment=SentimentConfig(enabled=False))
```

Add these tests:

```python
def test_sentiment_injected_into_features(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "aggregate_sentiment",
                        lambda symbols, c: {"BTC/USDT": 0.42})
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.42


def test_sentiment_absent_symbol_is_neutral(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "aggregate_sentiment",
                        lambda symbols, c: {})          # nothing reported
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.0                     # default neutral
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bot.py -k sentiment -v`
Expected: FAIL — `AttributeError: module 'engine.bot' has no attribute 'sentiment_mod'`

- [ ] **Step 3: Wire sentiment into `engine/bot.py`**

Add `sentiment as sentiment_mod` to the engine import line:

```python
from engine import broker, indicators, market as market_mod, sentiment as sentiment_mod, state as state_mod, strategies as strategies_mod
```

Inside `run_once`, just after `ts = _now()` (before the `for sym` loop), compute the per-cycle sentiment:

```python
        sent = (sentiment_mod.aggregate_sentiment(cfg.symbols, cfg)
                if cfg.sentiment.enabled else {})
```

In the per-symbol loop, right after the existing `feats["price"] = price` line, inject it:

```python
            feats["sentiment"] = sent.get(sym, 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS (all bot tests — existing ones offline via disabled sentiment, two new ones green).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat(sentiment): inject blended sentiment into the bot's features dict

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Backtest integration + README

**Files:**
- Modify: `engine/backtest.py`
- Modify: `README.md`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `sentiment.aggregate_sentiment(symbols, cfg, backtest=True, ts_ms=ts)`, `cfg.sentiment.enabled`.
- Produces: each bar's `feats[sym]` gains `feats[sym]["sentiment"]`; `sentiment_rule` added to `DETERMINISTIC`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_backtest.py`, update the `_cfg` helper to disable sentiment by default (keeps existing backtest tests offline), then add a sentiment test.

Add `SentimentConfig` to the config import:

```python
from engine.config import Config, RiskConfig, LLMConfig, RulesConfig, SentimentConfig
```

Update `_cfg` to pass `sentiment=SentimentConfig(enabled=False)` (append it as the final keyword argument to the existing `Config(...)` call):

```python
                  strategy="indicator_rule", rules=RulesConfig(),
                  sentiment=SentimentConfig(enabled=False))
```

Add this test:

```python
def test_backtest_injects_sentiment_per_bar(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    cfg.sentiment = SentimentConfig(enabled=True)
    feed = _feed_for({"BTC/USDT": _candles(60)})
    seen = {}

    monkeypatch.setattr(backtest.sentiment, "aggregate_sentiment",
                        lambda symbols, c, backtest=False, ts_ms=None: {"BTC/USDT": 0.3})

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "sentiment_rule", cfg,
                          feed=feed, strategy=capture)
    assert seen["sentiment"] == 0.3


def test_sentiment_rule_is_deterministic_no_warning():
    assert "sentiment_rule" in backtest.DETERMINISTIC
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest.py -k "sentiment or deterministic" -v`
Expected: FAIL — `AttributeError: module 'engine.backtest' has no attribute 'sentiment'` (and `sentiment_rule` not in `DETERMINISTIC`).

- [ ] **Step 3: Wire sentiment into `engine/backtest.py`**

Add `sentiment` to the engine import line:

```python
from engine import broker, datafeed, indicators, market, metrics, sentiment, strategies
```

In `run_backtest`, inside the timeline loop, right after the `feats = {...}` / `prices = {...}` lines and before `equity = ...`, inject sentiment per symbol:

```python
        sent = (sentiment.aggregate_sentiment(symbols, cfg, backtest=True, ts_ms=ts)
                if cfg.sentiment.enabled else {})
        for sym in symbols:
            feats[sym]["sentiment"] = sent.get(sym, 0.0)
```

Add `sentiment_rule` to the deterministic set:

```python
DETERMINISTIC = {"indicator_rule", "sentiment_rule"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (existing backtest tests offline via disabled sentiment, two new ones green).

- [ ] **Step 5: Add the README section**

In `README.md`, add after the "Backtesting" section:

```markdown
## Sentiment

The bot can blend market + news + social sentiment into one `[-1, +1]` score per
symbol, fed into both the LLM brain (it appears in the prompt) and the deterministic
`sentiment_rule` strategy (which gates the indicator signals — it won't buy into
strong negativity and exits on extreme negativity).

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

​```bash
python -m engine.backtest --since 2024-01-01 --strategy sentiment_rule
​```
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all — engine + sentiment + strategy + bot + backtest).

- [ ] **Step 7: Commit**

```bash
git add engine/backtest.py tests/test_backtest.py README.md
git commit -m "feat(sentiment): backtest F&G-mode sentiment injection + README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the reviewer

- **Offline tests:** the integration tasks (6, 7) disable sentiment in the existing `_cfg` helpers so the suite never hits the network; the new tests monkeypatch `aggregate_sentiment`. No test performs real HTTP.
- **Fail-safe everywhere:** every adapter is wrapped so any error/missing key yields `{}`; `aggregate_sentiment` never raises. The bot's HOLD-on-error guarantee is preserved.
- **Backtest fidelity:** only Fear & Greed contributes in `backtest=True` (it has history); so backtested `sentiment_rule` reflects the F&G component, not the full live blend — this is inherent and documented.
- **Gate unchanged:** `sentiment_rule` only proposes a `Decision`; it still flows through the unmodified `broker.plan_order` gate, so position caps, cash limits, and spot long-only hold exactly as before.
