"""On-demand sentiment analysis: fetch per-symbol sentiment and write the snapshot,
without running a trading cycle. Backs the dashboard's "Analyze now" button."""
import logging
from datetime import datetime, timezone

from engine import sentiment as sentiment_mod, state as state_mod
from engine.config import load_config


def main() -> None:
    cfg = load_config()
    if not cfg.sentiment.enabled:
        print("sentiment disabled in config — nothing to analyze")
        return
    bd = sentiment_mod.breakdown(cfg.symbols, cfg)   # never raises; failed sources drop out
    state_mod.write_sentiment(
        {"ts": datetime.now(timezone.utc).isoformat(), "strategy": cfg.strategy, "symbols": bd},
        cfg.data_dir)
    print(f"sentiment analyzed for {len(bd)} symbol(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from engine.env import load_dotenv
    load_dotenv()
    main()
