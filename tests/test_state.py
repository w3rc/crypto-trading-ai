import json as _json
from engine.state import load_state, save_state_atomic, append_trade, append_decision, equity
from engine.models import Position, Fill

def test_append_decision_writes_jsonl(tmp_path):
    append_decision({"ts": "t1", "symbol": "BTC/USDT", "action": "hold",
                     "reason": "weak signal", "price": 60000.0, "executed": False}, str(tmp_path))
    append_decision({"ts": "t2", "symbol": "ETH/USDT", "action": "buy",
                     "reason": "oversold", "price": 1600.0, "executed": True}, str(tmp_path))
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = _json.loads(lines[1])
    assert rec["action"] == "buy" and rec["executed"] is True and rec["symbol"] == "ETH/USDT"

def test_fresh_state_creates_flat_positions(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT", "ETH/USDT"])
    assert st.cash == 10000.0
    assert set(st.positions) == {"BTC/USDT", "ETH/USDT"}
    assert st.positions["BTC/USDT"].qty == 0.0
    assert st.equity_history == []

def test_save_then_load_roundtrip(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 8000.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=1000.0, stop_price=950.0)
    st.equity_history.append({"ts": "t1", "equity": 10000.0})
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.cash == 8000.0
    assert st2.positions["BTC/USDT"].qty == 2.0
    assert st2.positions["BTC/USDT"].stop_price == 950.0
    assert st2.equity_history == [{"ts": "t1", "equity": 10000.0}]

def test_append_trade_writes_header_then_rows(tmp_path):
    append_trade(Fill("BTC/USDT", "buy", 1.0, 100.0, 0.1, "t1"), str(tmp_path))
    append_trade(Fill("BTC/USDT", "sell", 1.0, 110.0, 0.11, "t2"), str(tmp_path))
    lines = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert lines[0] == "ts,symbol,side,qty,price,fee"
    assert len(lines) == 3   # header + 2 rows

def test_equity_uses_avg_price_when_missing(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0)
    assert equity(st, {}) == 1000.0 + 2.0 * 500.0          # falls back to avg
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 2.0 * 600.0
