import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float
    allow_short: Optional[bool] = None
    leverage: float = 1.0
    maintenance_margin_pct: float = 0.005
    funding_rate: float = 0.0
    funding_interval_hours: float = 8.0


@dataclass
class RulesConfig:
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    buy_size: float = 0.5


def _default_weights():
    return {"fear_greed": 1.0, "cryptopanic": 1.0, "reddit": 1.0, "x_twitter": 1.0}


def _default_ttl():
    return {"fear_greed": 86400, "cryptopanic": 3600, "reddit": 3600, "x_twitter": 3600}


@dataclass
class SentimentConfig:
    enabled: bool = True
    weights: dict = field(default_factory=_default_weights)
    cache_ttl: dict = field(default_factory=_default_ttl)
    buy_min: float = -0.2
    sell_max: float = -0.5
    http_timeout: float = 6.0


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    json_mode: bool


@dataclass
class Config:
    exchange: str
    symbols: list[str]
    timeframe: str
    paper_capital: float
    fee_pct: float
    slippage_pct: float
    data_dir: str
    risk: RiskConfig
    llm: LLMConfig
    strategy: str = "hybrid"
    rules: RulesConfig = field(default_factory=RulesConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    mode: str = "paper"
    exchange_api_key: str = field(default="", repr=False)
    exchange_secret: str = field(default="", repr=False)


def load_config(path: str = "engine/config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)
    llm = raw["llm"]
    rules_raw = raw.get("rules", {})
    sent_raw = raw.get("sentiment", {})
    mmr = float(raw["risk"].get("maintenance_margin_pct", 0.005))
    # ponytail: floor leverage at 1x; cap below 1/mmr so a long can't liquidate on
    # open (liq >= entry at/above 1/mmr). 0.5/mmr keeps the liq price clear of entry;
    # mmr <= 0 disables liquidation, so no ceiling is needed there.
    lev = float(raw["risk"].get("leverage", 1.0))
    if mmr > 0:
        lev = min(lev, 0.5 / mmr)
    lev = max(1.0, lev)
    return Config(
        exchange=raw["exchange"],
        symbols=list(raw["symbols"]),
        timeframe=raw["timeframe"],
        paper_capital=float(raw["paper_capital"]),
        fee_pct=float(raw["fee_pct"]),
        slippage_pct=float(raw["slippage_pct"]),
        data_dir=raw["data_dir"],
        risk=RiskConfig(
            max_position_pct=float(raw["risk"]["max_position_pct"]),
            stop_loss_pct=float(raw["risk"]["stop_loss_pct"]),
            allow_short=raw["risk"].get("allow_short", None),
            leverage=lev,
            maintenance_margin_pct=mmr,
            funding_rate=float(raw["risk"].get("funding_rate", 0.0)),
            funding_interval_hours=float(raw["risk"].get("funding_interval_hours", 8.0)),
        ),
        llm=LLMConfig(
            base_url=llm["base_url"],
            api_key=os.environ.get(llm["api_key_env"], ""),
            model=llm["model"],
            json_mode=bool(llm.get("json_mode", True)),
        ),
        strategy=raw.get("strategy", "hybrid"),
        rules=RulesConfig(
            rsi_buy=float(rules_raw.get("rsi_buy", 30)),
            rsi_sell=float(rules_raw.get("rsi_sell", 70)),
            buy_size=float(rules_raw.get("buy_size", 0.5)),
        ),
        sentiment=SentimentConfig(
            enabled=bool(sent_raw.get("enabled", True)),
            weights={k: float(v) for k, v in
                     {**_default_weights(), **sent_raw.get("weights", {})}.items()},
            cache_ttl={k: float(v) for k, v in
                       {**_default_ttl(), **sent_raw.get("cache_ttl", {})}.items()},
            buy_min=float(sent_raw.get("buy_min", -0.2)),
            sell_max=float(sent_raw.get("sell_max", -0.5)),
            http_timeout=float(sent_raw.get("http_timeout", 6.0)),
        ),
        mode=raw.get("mode", "paper"),
        exchange_api_key=os.environ.get(raw.get("exchange_api_key_env", "EXCHANGE_API_KEY"), ""),
        exchange_secret=os.environ.get(raw.get("exchange_secret_env", "EXCHANGE_API_SECRET"), ""),
    )
