import logging
import os
import sys

from engine import state as state_mod
from engine.bot import run_once, _live_armed
from engine.config import load_config
from engine.env import load_dotenv
from engine.models import Decision

log = logging.getLogger("execute")


def _trade_count(data_dir: str) -> int:
    """Return the number of lines in <data_dir>/trades.csv; 0 if the file is missing."""
    path = os.path.join(data_dir, "trades.csv")
    try:
        with open(path) as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def main(symbol: str, cfg=None, market=None) -> int:
    """Execute one stored pending suggestion for `symbol`. Returns a shell exit code."""
    if cfg is None:
        load_dotenv()                 # honor a .env arm before checking _live_armed()
        cfg = load_config()
    if cfg.mode == "shadow":
        print("[EXECUTE] shadow mode is dry-run; switch to paper or live to place orders", file=sys.stderr)
        return 2
    if cfg.mode == "live" and not _live_armed():
        print("[EXECUTE] live mode but LIVE_TRADING_ARMED != 'yes' — relaunch the app armed to place real orders", file=sys.stderr)
        return 3
    p = state_mod.load_pending(cfg.data_dir).get(symbol)
    if not p:
        print(f"[EXECUTE] no pending suggestion for {symbol}", file=sys.stderr)
        return 4
    decision = Decision(action=p["action"], size=float(p.get("size", 1.0)), reason=p.get("reason", ""))
    before = _trade_count(cfg.data_dir)
    run_once(cfg=cfg, market=market, only_symbol=symbol, forced_decision=decision)
    after = _trade_count(cfg.data_dir)
    if after > before:
        return 0
    print(
        f"[EXECUTE] no order placed for {symbol} (busy/halted/balance unavailable, or insufficient size/cash)"
        f" — the suggestion remains; try again or Dismiss",
        file=sys.stderr,
    )
    return 5


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("usage: python -m engine.execute SYMBOL")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
