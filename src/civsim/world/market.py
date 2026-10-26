"""簡化市場：鎮上有一個做市商，依淨需求調整價格。

TODO: 第二階段可加入 Agent 之間的雙邊交易 / 掛單簿。
"""

from __future__ import annotations

from civsim.config import MarketConfig
from civsim.models import Market

MIN_PRICE = 0.5


def update_prices(market: Market, demand: dict[str, float], config: MarketConfig) -> None:
    """demand[good] = 本回合買入量 - 賣出量。"""
    for good, net in demand.items():
        if good not in market.prices:
            continue
        change = config.price_elasticity * net / (abs(net) + 5)
        market.prices[good] = max(MIN_PRICE, round(market.prices[good] * (1 + change), 3))
