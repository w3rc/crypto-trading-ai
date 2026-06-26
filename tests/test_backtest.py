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
