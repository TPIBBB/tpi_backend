"""均衡價格與均衡區間。

均衡價格是一個區間（11/9 會議）：用穩定期每日成交價的平均 ± k 個標準差。

穩定期的價格要用「校準期」來算：同一個 seed、同一批平民，但沒有政府、沒有天災，從初始狀態跑
calibration_days 天，去掉前 burn_in_days 天，剩下每日成交價的平均與標準差就是基準。
這樣不論政府平時做了什麼，A／B／C 組同一個 seed 的均衡區間都相同，結果才能比較。

為什麼價格會有均衡點（推導見 docs/society.md）：平民報價的參考價是
    ref_t = w × 習慣價格 + (1 - w) × p_{t-1}
集合競價的成交價大約是 p_t = c × ref_t，c 是當天供需決定的倍率（供不應求 c > 1，供過於求 c < 1）。
供需平衡時 c 是常數 c*，價格收斂到固定點
    p* = w × c* × 習慣價格 / (1 - (1 - w) × c*)
天災讓供給變少、c 變大，價格上升；天災結束後 c 回到 c*，價格以 (1 - w) × c* 的速度回到 p*。
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, replace

from civsim.config import SimConfig


@dataclass(frozen=True)
class EquilibriumBand:
    mean: float
    std: float
    low: float
    high: float
    k: float
    samples: int

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def to_dict(self) -> dict:
        return asdict(self)


def band_from_prices(prices: list[float], k: float, min_half_width: float = 0.0) -> EquilibriumBand:
    if not prices:
        raise ValueError("沒有價格資料，無法計算均衡區間")
    mean = statistics.fmean(prices)
    std = statistics.pstdev(prices) if len(prices) > 1 else 0.0
    half = max(k * std, min_half_width * mean)
    return EquilibriumBand(round(mean, 4), round(std, 4), round(mean - half, 4), round(mean + half, 4),
                           k, len(prices))


def calibration_config(config: SimConfig) -> SimConfig:
    eq = config.equilibrium
    return replace(
        config,
        name=f"{config.name}:calibration",
        ticks=eq.calibration_days,
        disasters=replace(config.disasters, count=0),
        government=replace(config.government, controller="none"),
    )


def calibrate(config: SimConfig) -> tuple[EquilibriumBand, list[float]]:
    """回傳均衡區間，以及校準期每日記錄的價格。"""
    from civsim.world.engine import SimulationEngine

    eq = config.equilibrium

    if eq.calibration_days <= eq.burn_in_days:
        raise ValueError("calibration_days 必須大於 burn_in_days")

    # 1. 執行沒有政府、沒有天災的校準模擬
    history = SimulationEngine(
        calibration_config(config),
        government=None,
        band=None,
    ).run()

    # 2. 確認是否真的跑完預定天數
    if len(history) != eq.calibration_days:
        raise ValueError(
            f"校準期預期 {eq.calibration_days} 天，"
            f"實際只有 {len(history)} 筆資料"
        )

    # 3. 去掉前面的收斂期
    stable_history = history[eq.burn_in_days:]

    # 4. 只取有實際成交的日期
    traded_rows = [
        m for m in stable_history
        if m["traded"] and not m["price_capped"]
    ]

    traded_prices = [
        float(m["price"]) for m in traded_rows
    ]

    # 至少要有兩筆有效成交資料才能計算標準差
    if len(traded_prices) < 2:
        raise ValueError(
            f"校準期有效成交資料不足：只有 {len(traded_prices)} 筆"
        )

    # 5. 計算均衡價格區間
    band = band_from_prices(
        traded_prices,
        eq.k,
        eq.min_half_width,
    )

    # 保留完整校準期的每日價格紀錄
    all_prices = [float(m["price"]) for m in history]

    return band, all_prices
