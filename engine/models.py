from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class Decision(BaseModel):
    action: Literal["buy", "sell", "hold"]
    size: float = 0.0
    reason: str = ""
    stop: Optional[float] = None

    @field_validator("size")
    @classmethod
    def _clamp_size(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    stop_price: float = 0.0


@dataclass
class Order:
    side: str  # "buy" | "sell"
    qty: float
    price: float


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    ts: str
