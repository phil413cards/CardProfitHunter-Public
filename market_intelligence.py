from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

import pandas as pd


@dataclass(frozen=True)
class MarketContext:
    valuation_available: bool
    raw_market_value: Optional[float]
    psa9_value: Optional[float]
    psa10_value: Optional[float]
    asking_price_vs_raw_pct: Optional[float]
    psa10_multiplier: Optional[float]
    market_confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        parsed = float(value)
        return parsed
    except (TypeError, ValueError):
        return None


def build_market_context(row: pd.Series) -> MarketContext:
    raw = _number(row.get("raw_market_value"))
    psa9 = _number(row.get("psa9_value"))
    psa10 = _number(row.get("psa10_value"))
    total = _number(row.get("total_price"))
    available = raw is not None and raw > 0
    discount = ((total / raw) - 1) * 100 if available and total is not None else None
    multiplier = psa10 / raw if available and psa10 is not None else None
    confidence = "HIGH" if available and psa9 and psa10 else "MEDIUM" if available else "NONE"
    return MarketContext(available, raw, psa9, psa10, discount, multiplier, confidence)
