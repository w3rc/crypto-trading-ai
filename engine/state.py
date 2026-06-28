import csv
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field

from engine import broker
from engine.models import Position, Fill

_TRADE_HEADER = ["ts", "symbol", "side", "qty", "price", "fee"]
_POS_FIELDS = {"symbol", "qty", "avg_price", "stop_price", "leverage"}


@dataclass
class State:
    cash: float
    positions: dict
    equity_history: list = field(default_factory=list)
    last_funding_ts: str | None = None


def position_value(p, price: float) -> float:
    """Account value of a position: margin + unrealized P&L (isolated margin)."""
    lev = getattr(p, "leverage", 1.0) or 1.0
    return abs(p.qty) * p.avg_price / lev + p.qty * (price - p.avg_price)


def _state_path(data_dir: str) -> str:
    return os.path.join(data_dir, "state.json")


def load_state(data_dir: str, initial_capital: float, symbols: list[str]) -> State:
    os.makedirs(data_dir, exist_ok=True)
    path = _state_path(data_dir)
    if not os.path.exists(path):
        return State(cash=initial_capital,
                     positions={s: Position(s) for s in symbols},
                     equity_history=[])
    with open(path) as f:
        raw = json.load(f)
    positions = {s: Position(**{k: v for k, v in p.items() if k in _POS_FIELDS})
                 for s, p in raw["positions"].items()}
    for s in symbols:                       # ensure newly-added symbols exist
        positions.setdefault(s, Position(s))
    return State(cash=raw["cash"], positions=positions,
                 equity_history=raw.get("equity_history", []),
                 last_funding_ts=raw.get("last_funding_ts"))


def save_state_atomic(state: State, data_dir: str,
                      maintenance_margin_pct: float = 0.005) -> None:
    os.makedirs(data_dir, exist_ok=True)
    payload = {
        "cash": state.cash,
        "positions": {s: {**vars(p),
                          "liq_price": broker.liquidation_price(p, maintenance_margin_pct)}
                      for s, p in state.positions.items()},
        "equity_history": state.equity_history,
        "last_funding_ts": state.last_funding_ts,
    }
    path = _state_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX


def write_sentiment(snapshot: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "sentiment.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX


def append_trade(fill: Fill, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "trades.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(_TRADE_HEADER)
        w.writerow([fill.ts, fill.symbol, fill.side, fill.qty, fill.price, fill.fee])


def append_decision(record: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "decisions.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def equity(state: State, price_map: dict) -> float:
    return state.cash + sum(position_value(p, price_map.get(s, p.avg_price))
                            for s, p in state.positions.items())


@contextmanager
def acquire_lock(data_dir: str):
    os.makedirs(data_dir, exist_ok=True)
    lock_file = open(os.path.join(data_dir, "bot.lock"), "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another cycle is already running; exiting")
        sys.exit(0)
    try:
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
