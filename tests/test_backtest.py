import pandas as pd
from engine import backtest
from engine.config import Config, RiskConfig, LLMConfig, RulesConfig, SentimentConfig
from engine.models import Decision

COLS = ["ts", "open", "high", "low", "close", "volume"]
TF_MS = 3_600_000


def _cfg(tmp_path, symbols):
    return Config(exchange="x", symbols=list(symbols), timeframe="1h",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  strategy="indicator_rule", rules=RulesConfig(),
                  sentiment=SentimentConfig(enabled=False))


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


def test_stop_loss_triggers_forced_sell(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    # 50 rising candles (closes 100..149) satisfy warmup; crash candle (close 1.0)
    # is far below the stop (~141.55) set after the first buy fill.
    candles = _candles(50)  # ts 0..49*TF_MS, closes 100..149
    candles.append([50 * TF_MS, 2.0, 2.0, 0.5, 1.0, 5.0])
    feed = _feed_for({"BTC/USDT": candles})
    r = backtest.run_backtest(
        ["BTC/USDT"], "1h", 0, 51 * TF_MS, "indicator_rule", cfg,
        feed=feed, strategy=_always(Decision(action="buy", size=0.5)),
    )
    sides = [t.side for t in r["trades"]]
    # Strategy never emits sell → any sell fill proves the stop-loss branch ran
    assert "sell" in sides, "stop-loss branch did not produce a sell fill"
    assert sides[0] == "buy"
    assert sides[-1] == "sell"
    # Crash price (1.0) << entry (~149) → equity is well below starting capital
    assert r["equity_curve"][-1] < 10000.0


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


def test_preset_strategies_are_deterministic_no_warning():
    # the rule-based presets never call the LLM -> must not trigger the cost warning
    for name in ("ma_cross", "macd_cross", "rsi_reversion", "bollinger"):
        assert name in backtest.DETERMINISTIC
    assert "hybrid" not in backtest.DETERMINISTIC   # hybrid is the only LLM strategy


def test_append_history_is_append_only_with_the_run_summary(tmp_path):
    import json as _json
    result = {"metrics": {"final_equity": 11302.6, "total_return": 0.1303, "buy_hold_return": 0.2535,
                          "beats_hold": False, "max_drawdown": -0.127, "n_trades": 242}}
    backtest._append_history(result, ["BTC/USDT"], "macd_cross", "1d", "2021-07-01", None, str(tmp_path))
    backtest._append_history(result, ["ETH/USDT"], "rsi_reversion", "1d", "2021-07-01", "2026-07-01", str(tmp_path))
    lines = (tmp_path / "backtest_history.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2                                  # append-only, not overwritten
    e = _json.loads(lines[0])
    assert e["symbols"] == ["BTC/USDT"] and e["strategy"] == "macd_cross" and e["timeframe"] == "1d"
    assert e["total_return"] == 0.1303 and e["beats_hold"] is False and e["n_trades"] == 242
    assert e["until"] is None and "ts" in e
    assert _json.loads(lines[1])["until"] == "2026-07-01"


def test_auto_timeframe_coarsens_with_range():
    d = 86_400_000
    assert backtest._auto_timeframe(0, 5 * d) == "15m"        # ~1 week
    assert backtest._auto_timeframe(0, 30 * d) == "15m"       # 1 month (2880 bars)
    assert backtest._auto_timeframe(0, 90 * d) == "1h"        # 3 months
    assert backtest._auto_timeframe(0, 365 * d) == "4h"       # 1 year
    assert backtest._auto_timeframe(0, 5 * 365 * d) == "1d"   # 5 years -> ~1825 bars, not ~175k


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


def test_backtest_can_short_when_allow_short(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    cfg.risk.allow_short = True
    feed = _feed_for({"BTC/USDT": _candles(60)})
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="sell", size=1.0)))
    assert any(t.side == "sell" for t in r["trades"])   # opened shorts
    assert len(r["equity_curve"]) == len(r["buy_hold_curve"])


def test_backtest_runs_with_leverage(tmp_path):
    # leverage must not crash the replay and must still produce aligned curves
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    cfg.risk.leverage = 3.0
    feed = _feed_for({"BTC/USDT": _candles(60)})
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="buy", size=0.5)))
    assert len(r["equity_curve"]) == len(r["buy_hold_curve"])
    assert isinstance(r["metrics"]["final_equity"], float)
    assert len(r["trades"]) > 0                  # leverage lets the buy fill


def test_funding_bleeds_long_equity(tmp_path):
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    feed = _feed_for({"BTC/USDT": _candles(60)})   # 1h candles; 8h funding lands ~once
    r0 = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                               feed=feed, strategy=_always(Decision(action="buy", size=0.5)))
    cfg.risk.funding_rate = 0.001                  # positive -> a held long bleeds funding
    r1 = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                               feed=feed, strategy=_always(Decision(action="buy", size=0.5)))
    assert r1["metrics"]["final_equity"] < r0["metrics"]["final_equity"]   # funding cost
    assert len(r1["equity_curve"]) == len(r1["buy_hold_curve"])             # curves aligned
