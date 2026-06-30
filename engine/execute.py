import logging
import sys

from engine import state as state_mod
from engine.bot import run_once, _live_armed
from engine.config import load_config
from engine.env import load_dotenv
from engine.models import Decision

log = logging.getLogger("execute")


def main(symbol: str, cfg=None, market=None) -> int:
    """Execute one stored pending suggestion for `symbol`. Returns a shell exit code."""
    if cfg is None:
        load_dotenv()                 # honor a .env arm before checking _live_armed()
        cfg = load_config()
    if cfg.mode == "shadow":
        print("[EXECUTE] shadow mode is dry-run; switch to paper or live to place orders")
        return 2
    if cfg.mode == "live" and not _live_armed():
        print("[EXECUTE] live mode but LIVE_TRADING_ARMED != 'yes' — relaunch the app armed to place real orders")
        return 3
    p = state_mod.load_pending(cfg.data_dir).get(symbol)
    if not p:
        print(f"[EXECUTE] no pending suggestion for {symbol}")
        return 4
    decision = Decision(action=p["action"], size=float(p.get("size", 1.0)), reason=p.get("reason", ""))
    run_once(cfg=cfg, market=market, only_symbol=symbol, forced_decision=decision)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("usage: python -m engine.execute SYMBOL")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
