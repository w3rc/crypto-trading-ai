import os
from dataclasses import dataclass, field

import yaml


@dataclass
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float


@dataclass
class RulesConfig:
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    buy_size: float = 0.5


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


def load_config(path: str = "engine/config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)
    llm = raw["llm"]
    rules_raw = raw.get("rules", {})
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
    )
