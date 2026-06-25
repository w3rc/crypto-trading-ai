# Backtesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay a strategy over historical candles and report whether it beats buy-and-hold, with realistic fees/slippage/stops and a cached data feed.

**Architecture:** Three new modules — `engine/metrics.py` (pure performance math), `engine/datafeed.py` (paginated ccxt fetch + disk cache), `engine/backtest.py` (the replay loop + CLI). The replay loop reuses the engine's existing pure functions (`indicators.compute_indicators`, `strategies.get`, `broker.plan_order`/`apply_fill`/`stop_triggered`) and modifies no live-bot code.

**Tech Stack:** Python 3.14, pandas, ccxt, argparse, pytest. No new dependencies.

## Global Constraints

- **No new dependencies.**
- **No live-bot code is modified** — `bot.py`, `broker.py`, `strategies.py`, `indicators.py`, `models.py` are untouched. The backtest reuses them read-only.
- Every decision flows through the **unmodified** `broker.plan_order` risk gate and `broker.apply_fill` — the backtest cannot exceed position caps or cash; spot long-only holds.
- The backtest never touches `data/state.json`, `data/trades.csv`, or the file lock. It writes only `data/cache/*` (the feed) and the equity output file.
- Indicator warmup is derived from `indicators.MIN_ROWS` (= 50), not a magic constant.
- Both the equity curve and the buy-hold curve start at `cfg.paper_capital` so returns share a baseline.
- Buy-and-hold is **equal-weight** across symbols and pays the same one-time entry fee + slippage the strategy would.
- Single symbol or N-symbol portfolio via one code path (timestamp-intersection timeline).
- Local commits OK (already authorized for this project). Do not push or open a PR without explicit go-ahead.

---

### Task 1: Performance metrics — `engine/metrics.py`

**Files:**
- Create: `engine/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces:
  - `max_drawdown(curve: list[float]) -> float` — most negative peak-to-trough return (≤ 0).
  - `summarize(equity: list[float], buy_hold: list[float], n_trades: int) -> dict` with keys `final_equity, total_return, buy_hold_return, max_drawdown, n_trades, beats_hold`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metrics.py`:

```python
import pytest
from engine.metrics import max_drawdown, summarize


def test_max_drawdown_peak_to_trough():
    # 100 -> 120 (peak) -> 90 (trough) -> 110 ; dd = 90/120 - 1 = -0.25
    assert max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)


def test_max_drawdown_monotonic_up_is_zero():
    assert max_drawdown([100, 110, 120]) == 0.0


def test_max_drawdown_empty_is_zero():
    assert max_drawdown([]) == 0.0


def test_summarize_beats_hold():
    s = summarize(equity=[100, 130], buy_hold=[100, 120], n_trades=3)
    assert s["total_return"] == pytest.approx(0.30)
    assert s["buy_hold_return"] == pytest.approx(0.20)
    assert s["beats_hold"] is True
    assert s["final_equity"] == 130
    assert s["n_trades"] == 3


def test_summarize_loses_to_hold():
    s = summarize(equity=[100, 110], buy_hold=[100, 125], n_trades=1)
    assert s["beats_hold"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.metrics'`

- [ ] **Step 3: Implement `engine/metrics.py`**

```python
def max_drawdown(curve):
    """Most negative peak-to-trough return over the curve (<= 0). e.g. -0.25."""
    if not curve:
        return 0.0
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd
    return mdd


def summarize(equity, buy_hold, n_trades):
    total_return = equity[-1] / equity[0] - 1.0
    buy_hold_return = buy_hold[-1] / buy_hold[0] - 1.0
    return {
        "final_equity": equity[-1],
        "total_return": total_return,
        "buy_hold_return": buy_hold_return,
        "max_drawdown": max_drawdown(equity),
        "n_trades": n_trades,
        "beats_hold": total_return > buy_hold_return,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/metrics.py tests/test_metrics.py
git commit -m "feat(backtest): performance metrics — return, buy-and-hold, max drawdown

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Cached data feed — `engine/datafeed.py`

**Files:**
- Create: `engine/datafeed.py`
- Test: `tests/test_datafeed.py`

**Interfaces:**
- Consumes: an exchange object with `.id` (str), `.parse_timeframe(timeframe) -> seconds`, and `.fetch_ohlcv(symbol, timeframe, since, limit) -> list[[ts,o,h,l,c,v]]` (ccxt's interface; tests inject a fake).
- Produces:
  - `load_ohlcv(exchange, symbol, timeframe, since_ms, until_ms, cache_dir="data/cache") -> pd.DataFrame` with columns `["ts","open","high","low","close","volume"]`, `ts` ascending, restricted to `[since_ms, until_ms]`.
  - Module helpers used by tests: `_fetch_range(exchange, symbol, timeframe, since_ms, until_ms, limit=1000) -> pd.DataFrame`, `_cache_path(cache_dir, exchange_name, symbol, timeframe) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_datafeed.py`:

```python
import pandas as pd
from engine import datafeed

COLS = ["ts", "open", "high", "low", "close", "volume"]
TF_MS = 3_600_000  # 1h


def _candles(n, start=0):
    return [[start + i * TF_MS, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, 5.0]
            for i in range(n)]


class FakeExchange:
    id = "fake"

    def __init__(self, candles):
        self.candles = candles
        self.calls = 0

    def parse_timeframe(self, timeframe):
        return 3600  # seconds

    def fetch_ohlcv(self, symbol, timeframe, since=0, limit=1000):
        self.calls += 1
        rows = [r for r in self.candles if r[0] >= since]
        return rows[:limit]


def test_fetch_range_paginates(monkeypatch):
    ex = FakeExchange(_candles(5))
    df = datafeed._fetch_range(ex, "BTC/USDT", "1h", 0, 5 * TF_MS, limit=2)
    assert list(df["ts"]) == [i * TF_MS for i in range(5)]  # all 5 stitched
    assert ex.calls == 3                                    # 2 + 2 + 1


def test_load_ohlcv_cache_miss_then_hit(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    df1 = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert len(df1) == 5 and ex.calls >= 1
    # second call for the same range hits the cache file — no new fetch
    calls_before = ex.calls
    df2 = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert ex.calls == calls_before        # no extra fetch
    assert list(df2["ts"]) == list(df1["ts"])


def test_load_ohlcv_slices_to_range(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    df = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", TF_MS, 3 * TF_MS, cache_dir=cache)
    assert list(df["ts"]) == [TF_MS, 2 * TF_MS, 3 * TF_MS]  # only the requested window


def test_merge_dedupes_and_sorts(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    # prime the cache with the first 3 candles only
    path = datafeed._cache_path(cache, "fake", "BTC/USDT", "1h")
    import os
    os.makedirs(cache, exist_ok=True)
    pd.DataFrame(_candles(3), columns=COLS).to_csv(path, index=False)
    # request beyond cache -> fetch + merge, no duplicate ts
    df = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert list(df["ts"]) == [i * TF_MS for i in range(5)]
    assert df["ts"].is_unique
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_datafeed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.datafeed'`

- [ ] **Step 3: Implement `engine/datafeed.py`**

```python
import os

import pandas as pd

COLS = ["ts", "open", "high", "low", "close", "volume"]


def _cache_path(cache_dir, exchange_name, symbol, timeframe):
    safe = symbol.replace("/", "-")
    return os.path.join(cache_dir, f"{exchange_name}_{safe}_{timeframe}.csv")


def _read_cache(path):
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=COLS)


def _write_cache(path, df):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _covers(df, since_ms, until_ms):
    return not df.empty and df["ts"].min() <= since_ms and df["ts"].max() >= until_ms


def _fetch_range(exchange, symbol, timeframe, since_ms, until_ms, limit=1000):
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    rows = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + tf_ms
        if len(batch) < limit:
            break
    df = pd.DataFrame(rows, columns=COLS)
    return df[df["ts"] <= until_ms]


def _merge(cached, fetched):
    df = pd.concat([cached, fetched], ignore_index=True)
    return df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)


def load_ohlcv(exchange, symbol, timeframe, since_ms, until_ms, cache_dir="data/cache"):
    exchange_name = getattr(exchange, "id", "exchange")
    path = _cache_path(cache_dir, exchange_name, symbol, timeframe)
    cached = _read_cache(path)
    if not _covers(cached, since_ms, until_ms):
        # ponytail: re-fetches the whole requested range on a partial-coverage
        # miss, not just the gap; gap-only fetch is the upgrade path.
        fetched = _fetch_range(exchange, symbol, timeframe, since_ms, until_ms)
        cached = _merge(cached, fetched)
        _write_cache(path, cached)
    out = cached[(cached["ts"] >= since_ms) & (cached["ts"] <= until_ms)]
    return out.reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_datafeed.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/datafeed.py tests/test_datafeed.py
git commit -m "feat(backtest): cached, paginated historical OHLCV feed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Replay loop — `engine/backtest.py` (`run_backtest`)

**Files:**
- Create: `engine/backtest.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `datafeed.load_ohlcv` (default feed), `metrics.summarize`, `strategies.get`, `broker.plan_order`/`apply_fill`/`stop_triggered`, `indicators.compute_indicators`, `indicators.MIN_ROWS`, `models.Position`/`Order`, a `cfg` (`engine.config.Config`).
- Produces:
  - `run_backtest(symbols, timeframe, since_ms, until_ms, strategy_name, cfg, feed=datafeed.load_ohlcv, exchange=None, strategy=None) -> dict` with keys `metrics, equity_curve, buy_hold_curve, trades, timeline`.
  - The optional `strategy=` param overrides the registry lookup (a test/injection seam, mirroring `bot.run_once`); when `None`, uses `strategies.get(strategy_name)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest.py`:

```python
import pandas as pd
from engine import backtest
from engine.config import Config, RiskConfig, LLMConfig, RulesConfig
from engine.models import Decision

COLS = ["ts", "open", "high", "low", "close", "volume"]
TF_MS = 3_600_000


def _cfg(tmp_path, symbols):
    return Config(exchange="x", symbols=list(symbols), timeframe="1h",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  strategy="indicator_rule", rules=RulesConfig())


def _candles(n, start=0, base=100.0, step=1.0):
    return [[start + i * TF_MS, base + i * step, base + i * step + 1.0,
             base + i * step - 1.0, base + i * step, 5.0] for i in range(n)]


def _feed_for(candles_by_symbol):
    def feed(exchange, symbol, timeframe, since_ms, until_ms, cache_dir="data/cache"):
        return pd.DataFrame(candles_by_symbol[symbol], columns=COLS)
    return feed


def _always(decision):
    return lambda features, position, cash, cfg: decision


def test_buy_strategy_opens_position_and_curves_align(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    feed = _feed_for({"BTC/USDT": _candles(60)})  # 60 candles -> 11 post-warmup bars
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="buy", size=0.5)))
    assert r["equity_curve"][0] == 10000.0                  # baseline = capital
    assert len(r["equity_curve"]) == len(r["buy_hold_curve"])  # aligned
    assert len(r["trades"]) > 0                              # it traded
    assert r["metrics"]["buy_hold_return"] > 0               # rising prices


def test_hold_strategy_makes_no_trades_no_state_files(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    feed = _feed_for({"BTC/USDT": _candles(60)})
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="hold")))
    assert r["trades"] == []
    assert all(e == 10000.0 for e in r["equity_curve"])      # flat at capital
    assert not (tmp_path / "state.json").exists()
    assert not (tmp_path / "trades.csv").exists()


def test_warmup_skips_until_min_rows(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    feed = _feed_for({"BTC/USDT": _candles(50)})  # exactly MIN_ROWS -> 1 post-warmup bar
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 50 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="hold")))
    assert len(r["equity_curve"]) == 2  # [capital] + 1 traded bar


def test_two_symbol_timeline_is_intersection(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT", "ETH/USDT"])
    # BTC has 60 candles ts 0..59; ETH has 60 candles ts 1..60 -> intersection 1..59 (59 ts)
    feed = _feed_for({
        "BTC/USDT": _candles(60, start=0),
        "ETH/USDT": _candles(60, start=TF_MS),
    })
    r = backtest.run_backtest(["BTC/USDT", "ETH/USDT"], "1h", 0, 61 * TF_MS,
                              "indicator_rule", cfg, feed=feed,
                              strategy=_always(Decision(action="hold")))
    assert r["timeline"] == [i * TF_MS for i in range(1, 60)]  # 59 shared timestamps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.backtest'`

- [ ] **Step 3: Implement `engine/backtest.py`**

```python
from datetime import datetime, timezone

from engine import broker, datafeed, indicators, metrics, strategies
from engine.models import Order, Position


def _iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat()


def _common_timeline(data):
    sets = [set(df["ts"].tolist()) for df in data.values()]
    common = set.intersection(*sets) if sets else set()
    return sorted(common)


def _buy_hold_curve(price_history, symbols, cfg):
    curve = [cfg.paper_capital]
    if not price_history:
        return curve
    per = cfg.paper_capital / len(symbols)
    first = price_history[0]
    qty = {}
    for s in symbols:
        eff = first[s] * (1 + cfg.slippage_pct)   # same entry slippage as the strategy
        fee = per * cfg.fee_pct
        qty[s] = (per - fee) / eff
    for prices in price_history:
        curve.append(sum(qty[s] * prices[s] for s in symbols))
    return curve


def run_backtest(symbols, timeframe, since_ms, until_ms, strategy_name, cfg,
                 feed=datafeed.load_ohlcv, exchange=None, strategy=None):
    data = {sym: feed(exchange, sym, timeframe, since_ms, until_ms) for sym in symbols}
    timeline = _common_timeline(data)
    strat = strategy or strategies.get(strategy_name)

    cash = cfg.paper_capital
    positions = {sym: Position(sym) for sym in symbols}
    equity_curve = [cfg.paper_capital]
    price_history = []
    trades = []

    for ts in timeline:
        windows = {sym: data[sym][data[sym]["ts"] <= ts] for sym in symbols}
        if any(len(w) < indicators.MIN_ROWS for w in windows.values()):
            continue  # warmup: skip until every symbol has enough rows
        # ponytail: recomputes indicators over the whole trailing window each step
        # (O(n^2) total); precompute rolling indicators if backtests get slow.
        feats = {sym: indicators.compute_indicators(windows[sym]) for sym in symbols}
        prices = {sym: feats[sym]["price"] for sym in symbols}

        equity = cash + sum(positions[s].qty * prices[s] for s in symbols)
        for sym in symbols:
            pos = positions[sym]
            price = prices[sym]
            if broker.stop_triggered(pos, price):
                order = Order("sell", pos.qty, price)
            else:
                decision = strat(feats[sym], pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
            if order is not None:
                positions[sym], cash, fill = broker.apply_fill(
                    order, pos, cash, cfg.fee_pct, cfg.slippage_pct,
                    cfg.risk.stop_loss_pct, _iso(ts))
                trades.append(fill)

        price_history.append(prices)
        equity_curve.append(cash + sum(positions[s].qty * prices[s] for s in symbols))

    buy_hold_curve = _buy_hold_curve(price_history, symbols, cfg)
    summary = metrics.summarize(equity_curve, buy_hold_curve, len(trades))
    return {"metrics": summary, "equity_curve": equity_curve,
            "buy_hold_curve": buy_hold_curve, "trades": trades, "timeline": timeline}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all — engine + new backtest/datafeed/metrics tests).

- [ ] **Step 6: Commit**

```bash
git add engine/backtest.py tests/test_backtest.py
git commit -m "feat(backtest): portfolio replay loop reusing gate/fills/indicators

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: CLI + equity output + README — `engine/backtest.py`

**Files:**
- Modify: `engine/backtest.py` (add `main`, `_to_ms`, `_write_equity`, `_print_summary`, `__main__`)
- Modify: `README.md` (add a "Backtesting" section)
- Test: `tests/test_backtest.py` (add CLI tests)

**Interfaces:**
- Consumes: `run_backtest` (Task 3), `config.load_config`, `market.make_exchange`.
- Produces:
  - `_to_ms(date_str) -> int` (UTC `YYYY-MM-DD` → epoch ms)
  - `main(argv=None) -> dict` — parses args, runs the backtest, prints the summary, writes the equity CSV; returns the result dict.
  - CLI: `python -m engine.backtest --since YYYY-MM-DD [--symbols ...] [--timeframe ...] [--until ...] [--strategy ...] [--capital ...] [--out PATH]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest.py`:

```python
def test_to_ms_parses_utc_date():
    assert backtest._to_ms("2024-01-01") == 1_704_067_200_000


def test_main_runs_writes_equity_and_prints(monkeypatch, tmp_path, capsys):
    canned = {"metrics": {"final_equity": 10500.0, "total_return": 0.05,
                          "buy_hold_return": 0.03, "max_drawdown": -0.1,
                          "n_trades": 4, "beats_hold": True},
              "equity_curve": [10000.0, 10500.0],
              "buy_hold_curve": [10000.0, 10300.0],
              "trades": [], "timeline": [0, TF_MS]}
    monkeypatch.setattr(backtest, "run_backtest", lambda *a, **k: canned)
    monkeypatch.setattr(backtest.market, "make_exchange", lambda name: object())
    out = str(tmp_path / "eq.csv")
    backtest.main(["--since", "2024-01-01", "--symbols", "BTC/USDT",
                   "--strategy", "indicator_rule", "--out", out])
    text = capsys.readouterr().out
    assert "beats" in text.lower() and "10500" in text
    lines = open(out).read().strip().splitlines()
    assert lines[0] == "ts,equity,buy_hold"   # header
    assert len(lines) == 3                     # header + 2 points


def test_main_warns_on_non_deterministic_strategy(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(backtest, "run_backtest", lambda *a, **k: {
        "metrics": {"final_equity": 0, "total_return": 0, "buy_hold_return": 0,
                    "max_drawdown": 0, "n_trades": 0, "beats_hold": False},
        "equity_curve": [10000.0], "buy_hold_curve": [10000.0],
        "trades": [], "timeline": []})
    monkeypatch.setattr(backtest.market, "make_exchange", lambda name: object())
    backtest.main(["--since", "2024-01-01", "--symbols", "BTC/USDT",
                   "--strategy", "hybrid", "--out", str(tmp_path / "eq.csv")])
    assert "WARNING" in capsys.readouterr().out   # LLM cost warning
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest.py -k "to_ms or main" -v`
Expected: FAIL — `AttributeError: module 'engine.backtest' has no attribute '_to_ms'`

- [ ] **Step 3: Implement the CLI**

Add to the top of `engine/backtest.py` (imports):

```python
import argparse
import time

from engine import market
from engine.config import load_config
```

Add these to `engine/backtest.py` (after `run_backtest`):

```python
DETERMINISTIC = {"indicator_rule"}


def _to_ms(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _write_equity(result, path):
    eq = result["equity_curve"]
    bh = result["buy_hold_curve"]
    n_bars = len(eq) - 1                                         # post-warmup bars
    ts = result["timeline"][-n_bars:] if n_bars > 0 else []      # tail aligns with bars
    lines = ["ts,equity,buy_hold", f",{eq[0]},{bh[0]}"]          # baseline row (no ts)
    for i, t in enumerate(ts):
        lines.append(f"{t},{eq[i + 1]},{bh[i + 1]}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _print_summary(m, symbols, strategy, timeframe):
    verdict = "BEATS hold" if m["beats_hold"] else "loses to hold"
    print(
        f"\nBacktest: {strategy} on {','.join(symbols)} ({timeframe})\n"
        f"  final equity     {m['final_equity']:.2f}\n"
        f"  total return     {m['total_return'] * 100:+.2f}%\n"
        f"  buy & hold       {m['buy_hold_return'] * 100:+.2f}%   -> {verdict}\n"
        f"  max drawdown     {m['max_drawdown'] * 100:.2f}%\n"
        f"  trades           {m['n_trades']}\n"
    )


def main(argv=None):
    cfg = load_config()
    p = argparse.ArgumentParser(prog="engine.backtest")
    p.add_argument("--symbols", default=",".join(cfg.symbols))
    p.add_argument("--timeframe", default=cfg.timeframe)
    p.add_argument("--since", required=True)
    p.add_argument("--until", default=None)
    p.add_argument("--strategy", default=cfg.strategy)
    p.add_argument("--capital", type=float, default=cfg.paper_capital)
    p.add_argument("--out", default="data/backtest_equity.csv")
    args = p.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    since_ms = _to_ms(args.since)
    until_ms = _to_ms(args.until) if args.until else int(time.time() * 1000)
    cfg.symbols, cfg.timeframe, cfg.strategy, cfg.paper_capital = (
        symbols, args.timeframe, args.strategy, args.capital)

    if args.strategy not in DETERMINISTIC:
        print(f"WARNING: strategy '{args.strategy}' is not deterministic — it makes "
              f"~1 LLM call per candle per symbol ({len(symbols)} symbol(s)); "
              f"this can be slow and costly. The cheap path is 'indicator_rule'.")

    exchange = market.make_exchange(cfg.exchange)
    result = run_backtest(symbols, args.timeframe, since_ms, until_ms,
                          args.strategy, cfg, exchange=exchange)
    _print_summary(result["metrics"], symbols, args.strategy, args.timeframe)
    _write_equity(result, args.out)
    return result


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest.py -v`
Expected: PASS (all backtest tests, including the 3 CLI tests).

- [ ] **Step 5: Add the README section**

In `README.md`, add after the existing run/usage section:

```markdown
## Backtesting

Replay a strategy over historical candles and see if it beats buy-and-hold:

​```bash
python -m engine.backtest --symbols BTC/USDT,ETH/USDT --timeframe 1h \
  --since 2024-01-01 --strategy indicator_rule
​```

Historical candles are fetched once from the exchange and cached under
`data/cache/`. The equity + buy-hold curves are written to
`data/backtest_equity.csv`. Defaults (fees, slippage, risk, capital) come from
`engine/config.yaml`.

`indicator_rule` is the fast, deterministic strategy. Backtesting `hybrid` is
supported but makes one LLM call per candle per symbol (slow + costly) — you'll
get a warning.
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add engine/backtest.py tests/test_backtest.py README.md
git commit -m "feat(backtest): CLI, equity CSV output, README, LLM cost warning

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the reviewer

- `run_backtest`'s `strategy=` injection param mirrors `bot.run_once` — it's the test seam; production goes through `strategies.get(strategy_name)`.
- The equity and buy-hold curves are length `1 + (number of post-warmup bars)` and both start at `cfg.paper_capital`, so `metrics.summarize` compares like with like.
- `_write_equity`'s baseline row has an empty `ts` (the capital point precedes the first candle); each subsequent row carries the candle ts.
- No live-bot file is modified; the backtest writes only `data/cache/*` and the `--out` CSV.
