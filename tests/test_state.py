import json as _json
import pytest
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

def test_write_sentiment_atomic_json(tmp_path):
    from engine.state import write_sentiment
    import json
    snap = {"ts": "2026-06-26T00:00:00+00:00", "strategy": "sentiment_rule",
            "symbols": {"BTC/USDT": {"blended": -0.62,
                                     "sources": {"fear_greed": -0.78, "cryptopanic": None,
                                                 "reddit": None, "x_twitter": None}}}}
    write_sentiment(snap, str(tmp_path))
    path = tmp_path / "sentiment.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["strategy"] == "sentiment_rule"
    assert loaded["symbols"]["BTC/USDT"]["blended"] == -0.62
    assert loaded["symbols"]["BTC/USDT"]["sources"]["cryptopanic"] is None
    assert not (tmp_path / "sentiment.json.tmp").exists()   # temp cleaned up (atomic replace)

def test_equity_unchanged_for_long_book(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0)  # 1x long
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 2.0 * 600.0   # == old cash+qty*price

def test_equity_leveraged_long_is_margin_plus_unrealized(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0, leverage=5.0)
    # margin 2*500/5 = 200; unrealized 2*(600-500) = 200
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 200.0 + 200.0

def test_save_load_preserves_leverage(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=100.0,
                                         stop_price=95.0, leverage=5.0)
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].leverage == 5.0

def test_snapshot_includes_liq_price_for_leveraged(tmp_path):
    import json
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=100.0,
                                         stop_price=95.0, leverage=5.0)
    save_state_atomic(st, str(tmp_path), maintenance_margin_pct=0.005)
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["positions"]["BTC/USDT"]["liq_price"] > 0    # written for the dashboard
    # and a snapshot carrying liq_price reloads cleanly (key stripped)
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 1.0

def test_last_funding_ts_roundtrips(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.last_funding_ts = "2026-06-28T08:00:00+00:00"
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.last_funding_ts == "2026-06-28T08:00:00+00:00"

def test_last_funding_ts_defaults_none_and_old_snapshot(tmp_path):
    import json
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.last_funding_ts is None                 # fresh state
    save_state_atomic(st, str(tmp_path))
    raw = json.loads((tmp_path / "state.json").read_text())
    del raw["last_funding_ts"]                         # simulate a pre-funding snapshot
    (tmp_path / "state.json").write_text(json.dumps(raw))
    assert load_state(str(tmp_path), 10000.0, ["BTC/USDT"]).last_funding_ts is None

def test_funding_accrued_roundtrips(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.funding_accrued = -1.25
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == -1.25

def test_funding_accrued_defaults_zero_and_old_snapshot(tmp_path):
    import json
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.funding_accrued == 0.0
    save_state_atomic(st, str(tmp_path))
    raw = json.loads((tmp_path / "state.json").read_text())
    del raw["funding_accrued"]
    (tmp_path / "state.json").write_text(json.dumps(raw))
    assert load_state(str(tmp_path), 10000.0, ["BTC/USDT"]).funding_accrued == 0.0

def test_write_status_atomic_json(tmp_path):
    from engine.state import write_status
    import json
    write_status({"ts": "t1", "strategy": "hybrid", "exchange": "binance",
                  "risk": {"allow_short": True, "leverage": 5.0},
                  "funding": {"accrued": -1.0, "last_funding_ts": None}}, str(tmp_path))
    path = tmp_path / "status.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["strategy"] == "hybrid" and loaded["risk"]["allow_short"] is True
    assert not (tmp_path / "status.json.tmp").exists()   # temp cleaned (atomic replace)


def test_live_meta_round_trips(tmp_path):
    from engine import state as state_mod
    meta = {"BTC/USDT": {"avg_price": 64000.0, "stop_price": 60800.0}}
    state_mod.save_live_meta(meta, str(tmp_path))
    assert state_mod.load_live_meta(str(tmp_path)) == meta


def test_live_meta_missing_file_is_empty(tmp_path):
    from engine import state as state_mod
    assert state_mod.load_live_meta(str(tmp_path)) == {}


def test_live_meta_corrupt_file_is_empty(tmp_path):
    from engine import state as state_mod
    (tmp_path / "live_meta.json").write_text("{not json")
    assert state_mod.load_live_meta(str(tmp_path)) == {}


def test_live_meta_non_utf8_file_is_empty(tmp_path):
    from engine import state as state_mod
    (tmp_path / "live_meta.json").write_bytes(b"\xff\xfe\x00bad")
    assert state_mod.load_live_meta(str(tmp_path)) == {}


def test_load_state_corrupt_json_backs_up_and_raises(tmp_path):
    (tmp_path / "state.json").write_text("{not valid json")
    with pytest.raises(RuntimeError, match="corrupt"):
        load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    assert (tmp_path / "state.json.corrupt").exists()      # bad file preserved
    assert not (tmp_path / "state.json").exists()          # moved aside, not silently reset


def test_load_state_missing_required_key_backs_up_and_raises(tmp_path):
    (tmp_path / "state.json").write_text('{"positions": {}}')   # no "cash" key
    with pytest.raises(RuntimeError):
        load_state(str(tmp_path), 1000.0, [])
    assert (tmp_path / "state.json.corrupt").exists()
