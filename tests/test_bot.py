import json
import pandas as pd
from engine import bot
from engine.config import Config, RiskConfig, LLMConfig
from engine.models import Decision, Position
from engine.state import load_state

def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True))

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

class FakeLLM:
    def __init__(self, decision): self.decision = decision
    def decide(self, features, position, cash, cfg, client=None): return self.decision

def test_buy_decision_updates_state_and_logs_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash < 10000.0
    assert st.positions["BTC/USDT"].qty > 0
    assert len(st.equity_history) == 1
    trades = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert len(trades) == 2  # header + 1 buy

def test_hold_decision_makes_no_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="hold")))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash == 10000.0
    assert not (tmp_path / "trades.csv").exists()

def test_fetch_error_skips_symbol_keeps_going(tmp_path):
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT"))
    market = FakeMarket(raise_for=("BTC/USDT",))
    bot.run_once(cfg, market=market, llm=FakeLLM(Decision(action="buy", size=1.0)))
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
    # LLM says hold, but the stop must override and exit
    bot.run_once(cfg, market=FakeMarket(price=159.0), llm=FakeLLM(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0
    assert st2.cash > 0.0
