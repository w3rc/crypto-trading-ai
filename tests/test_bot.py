import json as _json
import pandas as pd
from engine import bot
from engine.config import Config, RiskConfig, LLMConfig, SentimentConfig
from engine.models import Decision, Position
from engine.state import load_state

def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  sentiment=SentimentConfig(enabled=False))

def _df():
    closes = [100.0 + i for i in range(60)]
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [5.0] * 60})

class FakeMarket:
    def __init__(self, price=159.0, raise_for=()):
        self.price, self.raise_for = price, set(raise_for)
    def make_exchange(self, name): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200):
        if sym in self.raise_for: raise RuntimeError("fetch failed")
        return _df()
    def fetch_price(self, ex, sym): return self.price

def _strat(decision):
    return lambda features, position, cash, cfg: decision

def test_buy_decision_updates_state_and_logs_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash < 10000.0
    assert st.positions["BTC/USDT"].qty > 0
    assert len(st.equity_history) == 1
    trades = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert len(trades) == 2  # header + 1 buy

def test_hold_decision_makes_no_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash == 10000.0
    assert not (tmp_path / "trades.csv").exists()

def test_fetch_error_skips_symbol_keeps_going(tmp_path):
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT"))
    market = FakeMarket(raise_for=("BTC/USDT",))
    bot.run_once(cfg, market=market, strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT", "ETH/USDT"])
    assert st.positions["BTC/USDT"].qty == 0      # skipped
    assert st.positions["ETH/USDT"].qty > 0       # processed

def test_stop_loss_forces_exit(tmp_path):
    cfg = _cfg(tmp_path)
    # seed a position whose stop (200) sits above the current price (159) -> must sell
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 0.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0, stop_price=200.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    # Strategy says hold, but the stop must override and exit
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0
    assert st2.cash > 0.0

def test_nonpositive_price_skips_symbol_no_liquidation(tmp_path):
    cfg = _cfg(tmp_path)
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 0.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0, stop_price=200.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    # a zero ticker must NOT liquidate the stopped-out position
    bot.run_once(cfg, market=FakeMarket(price=0.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 1.0
    assert st2.cash == 0.0

def test_decisions_are_logged_each_cycle(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1                      # one priced symbol -> one decision record
    rec = _json.loads(lines[0])
    assert rec["symbol"] == "BTC/USDT"
    assert rec["action"] == "buy" and rec["executed"] is True
    assert "price" in rec and "reason" in rec and "ts" in rec

def test_hold_decision_is_logged_not_executed(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold", reason="flat")))
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["action"] == "hold" and rec["executed"] is False and rec["reason"] == "flat"

def test_sentiment_injected_into_features(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown",
                        lambda symbols, c: {"BTC/USDT": {"blended": 0.42, "sources": {}}})
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.42


def test_sentiment_absent_symbol_is_neutral(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown", lambda symbols, c: {})
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.0


def test_sentiment_snapshot_written(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown",
                        lambda symbols, c: {"BTC/USDT": {"blended": -0.3,
                                                         "sources": {"fear_greed": -0.3}}})
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "sentiment.json").read_text())
    assert data["symbols"]["BTC/USDT"]["blended"] == -0.3
    assert "strategy" in data and "ts" in data


def test_sentiment_disabled_writes_no_file(tmp_path):
    cfg = _cfg(tmp_path)   # enabled=False by default in _cfg
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    assert not (tmp_path / "sentiment.json").exists()
