import json as _json
import pytest
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


def test_short_opens_when_allow_short(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = True
    # a flat position + a bearish "sell" strategy -> opens a short
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="sell", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty < 0          # now short


def test_no_short_when_allow_short_off(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = False
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="sell", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty == 0.0       # flat sell nullified (spot long-only)


def test_allow_short_resolves_from_exchange(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = None                       # auto
    monkeypatch.setattr(bot.market_mod, "supports_short", lambda ex: True)
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="sell", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty < 0          # auto-resolved to short-enabled


def test_short_stop_loss_covers_with_buy(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = True
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    # seed a SHORT (qty<0) whose stop (155) sits BELOW the current price (159):
    # price has risen past the short stop -> the bot must cover with a BUY.
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=-1.0, avg_price=150.0, stop_price=155.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0   # covered to flat via a buy-to-close


def test_leveraged_position_liquidated_on_adverse_move(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.leverage = 5.0
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 0.0
    # 5x long, avg 210 -> liq ~168.8; stop sits low (1.0) so only liquidation can fire.
    # current price 159 is below the liq price -> must force-close as a liquidation.
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0,
                                         stop_price=1.0, leverage=5.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path), cfg.risk.maintenance_margin_pct)
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0          # force-closed
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["reason"] == "liquidation"


def test_funding_charges_long_across_interval(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.funding_rate = 0.001
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 10000.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    st.last_funding_ts = "2020-01-01T00:00:00+00:00"   # long ago -> funding is due
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.cash == pytest.approx(10000.0 - 0.001 * 1.0 * 159.0)   # long paid funding
    assert st2.last_funding_ts is not None and st2.last_funding_ts > "2026-01-01"  # clock advanced to ~now
    assert st2.positions["BTC/USDT"].qty == 1.0                        # position untouched

def test_funding_short_receives(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.funding_rate = 0.001
    cfg.risk.allow_short = True
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 10000.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=-1.0, avg_price=170.0, stop_price=1e9)
    st.last_funding_ts = "2020-01-01T00:00:00+00:00"
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.cash == pytest.approx(10000.0 + 0.001 * 1.0 * 159.0)   # short received funding
    assert st2.positions["BTC/USDT"].qty == -1.0   # short stayed open (not force-closed)

def test_funding_off_no_charge_no_timestamp(tmp_path):
    cfg = _cfg(tmp_path)   # funding_rate defaults 0.0
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 5000.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.cash == 5000.0                  # no funding applied
    assert st2.last_funding_ts is None         # not tracked when funding is off

def test_funding_accrues_cumulative(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.funding_rate = 0.001
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    st.last_funding_ts = "2020-01-01T00:00:00+00:00"
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == pytest.approx(-0.001 * 1.0 * 159.0)   # long paid -> negative

def test_funding_accrued_stays_zero_when_off(tmp_path):
    cfg = _cfg(tmp_path)   # funding off (rate defaults 0.0)
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == 0.0

def test_status_written_with_resolved_mode(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = None        # auto -> resolved from the exchange
    cfg.risk.leverage = 3.0
    monkeypatch.setattr(bot.market_mod, "supports_short", lambda ex: True)
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["strategy"] == cfg.strategy
    assert data["exchange"] == cfg.exchange
    assert data["risk"]["allow_short"] is True      # resolved None -> True (written as a bool)
    assert data["risk"]["leverage"] == 3.0
    for key in ("maintenance_margin_pct", "funding_rate", "funding_interval_hours",
                "max_position_pct", "stop_loss_pct"):
        assert key in data["risk"], f"missing risk field: {key}"
    assert "accrued" in data["funding"] and "last_funding_ts" in data["funding"]

def test_status_write_failure_does_not_abort(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    def boom(*a, **k):
        raise IOError("disk full")
    monkeypatch.setattr(bot.state_mod, "write_status", boom)
    # the cycle still completes and persists the trade despite the status write failing
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0


def test_shadow_logs_intent_executes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.mode = "shadow"
    class ShadowMarket:
        def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
        def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
        def fetch_price(self, ex, sym): return 159.0
        def fetch_balance(self, ex, symbols): return 5000.0, {s: 0.0 for s in symbols}
    bot.run_once(cfg, market=ShadowMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["action"] == "buy" and rec["executed"] is False     # intended, not executed
    assert rec["reason"].startswith("[shadow]")
    assert not (tmp_path / "trades.csv").exists()                  # NO fill written
    assert not (tmp_path / "state.json").exists()                  # NO money state written
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["mode"] == "shadow"

def test_shadow_balance_failure_does_not_crash(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.mode = "shadow"
    class FailBalanceMarket:
        def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
        def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
        def fetch_price(self, ex, sym): return 159.0
        def fetch_balance(self, ex, symbols): raise RuntimeError("auth failed")
    bot.run_once(cfg, market=FailBalanceMarket(), strategy=_strat(Decision(action="hold")))
    assert (tmp_path / "status.json").exists()                     # cycle survived, status still written
    assert not (tmp_path / "state.json").exists()   # still writes no money state
    assert not (tmp_path / "trades.csv").exists()    # still places nothing

def test_paper_mode_still_simulates(tmp_path):
    cfg = _cfg(tmp_path)   # mode defaults "paper"
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0                        # paper path unchanged
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["mode"] == "paper"                                 # status now carries mode


class _LiveMarket:
    """Fake live market; records create_order calls and returns a closed fill."""
    def __init__(self, cash=5000.0, qty=None, price=159.0):
        self.cash, self.qty, self.price = cash, qty or {}, price
        self.orders = []
    def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
    def fetch_price(self, ex, sym): return self.price
    def fetch_balance(self, ex, symbols): return self.cash, {s: self.qty.get(s, 0.0) for s in symbols}
    def clamp_to_market(self, ex, sym, qty, price): return qty
    def create_order(self, ex, sym, side, qty, ref_price, ts):
        self.orders.append((sym, side, qty))
        from engine.models import Fill
        return Fill(sym, side, qty, ref_price, qty * ref_price * 0.001, ts)


def test_live_armed_places_real_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert len(mk.orders) == 1 and mk.orders[0][1] == "buy"       # a REAL order placed
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["action"] == "buy" and rec["executed"] is True
    assert (tmp_path / "trades.csv").exists()                     # real fill recorded
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert meta["BTC/USDT"]["avg_price"] > 0                      # sidecar updated from fill
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["mode"] == "live" and status["halted"] is False


def test_live_unarmed_falls_back_to_shadow(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # NO real order
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["executed"] is False and rec["reason"].startswith("[shadow]")
    assert not (tmp_path / "trades.csv").exists()


def test_live_halt_file_blocks_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    (tmp_path / "HALT").write_text("")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # halted before any order
    assert not (tmp_path / "trades.csv").exists()
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["halted"] is True


def test_live_balance_failure_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    class _FailBal(_LiveMarket):
        def fetch_balance(self, ex, symbols): raise RuntimeError("auth failed")
    mk = _FailBal()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # no balance -> no order
    assert (tmp_path / "status.json").exists()                    # cycle survived


def test_live_below_min_notional_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    class _ClampZero(_LiveMarket):
        def clamp_to_market(self, ex, sym, qty, price): return 0.0
    mk = _ClampZero()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["executed"] is False and "min notional" in rec["reason"]


def test_live_stop_loss_sells_to_flat(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    # seed a held long with a stop ABOVE the current price -> stop fires
    (tmp_path / "live_meta.json").write_text(
        _json.dumps({"BTC/USDT": {"avg_price": 200.0, "stop_price": 190.0}}))
    mk = _LiveMarket(qty={"BTC/USDT": 0.5}, price=159.0)          # price 159 <= stop 190
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="hold")))
    assert len(mk.orders) == 1 and mk.orders[0] == ("BTC/USDT", "sell", 0.5)
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert "BTC/USDT" not in meta                                 # sidecar cleared on close


def test_live_balance_failure_halted_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    class _FailBal(_LiveMarket):
        def fetch_balance(self, ex, symbols): raise RuntimeError("auth failed")
    mk = _FailBal()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # no balance -> no order
    assert (tmp_path / "status.json").exists()                    # cycle survived
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["halted"] is False                              # balance failure is NOT a HALT event


def test_live_fill_persists_meta_even_if_trade_log_write_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    import engine.state as state_mod
    def _boom(*a, **k): raise OSError("disk full")
    monkeypatch.setattr(state_mod, "append_trade", _boom)
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert len(mk.orders) == 1                                   # real fill was placed
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert meta["BTC/USDT"]["avg_price"] > 0                     # safety-critical sidecar persisted post-fill


def test_live_persists_each_fill_to_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT")); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert meta["BTC/USDT"]["avg_price"] > 0 and meta["ETH/USDT"]["avg_price"] > 0   # each fill persisted


def test_live_halt_midcycle_stops_further_orders(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT")); cfg.mode = "live"
    class _HaltOnFirst(_LiveMarket):
        def create_order(self, ex, sym, side, qty, ref_price, ts):
            (tmp_path / "HALT").write_text("")                      # kill switch trips during the first order
            return super().create_order(ex, sym, side, qty, ref_price, ts)
    mk = _HaltOnFirst()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert len(mk.orders) == 1                                      # only the first symbol traded; HALT stopped the rest
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["halted"] is True


def test_status_carries_armed_true(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path)                                  # paper mode
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["armed"] is True

def test_status_carries_armed_false(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["armed"] is False
