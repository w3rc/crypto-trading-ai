"""Read-only exchange connection check: build the exchange from config and fetch the
real balance. Backs the dashboard's Settings "Test connection" button. Places no orders."""
import logging
import sys

from engine import market
from engine.config import load_config


def main() -> int:
    cfg = load_config()
    try:
        ex = market.make_exchange(cfg.exchange, "shadow", cfg.exchange_api_key, cfg.exchange_secret,
                                  wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                  testnet=cfg.testnet)
        cash, _ = market.fetch_balance(ex, cfg.symbols)
    except Exception as e:                       # bad key / network / auth -> reported, never raised
        print(f"connection FAILED: {e}")
        return 1
    net = "testnet" if cfg.testnet else "mainnet"
    print(f"connection ok — {cfg.exchange} ({net}); available quote balance: {cash}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from engine.env import load_dotenv
    load_dotenv()
    sys.exit(main())
