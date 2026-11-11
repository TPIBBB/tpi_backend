"""實驗設定：從 YAML 載入。一個設定檔 = 一組實驗條件。

各欄位的意義與預設值的由來見 docs/society.md。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CitizenConfig:
    """平民的初始狀態與生產參數。dict 的 key 是 CitizenType 的值。"""

    initial_food: dict[str, float] = field(default_factory=lambda: {
        "producer_trader": 10.0, "producer_self": 10.0, "consumer": 6.0, "dependent": 3.0,  # dependent 只帶幾天的糧，之後要靠政府
    })
    initial_money: dict[str, float] = field(default_factory=lambda: {
        "producer_trader": 30.0, "producer_self": 0.0, "consumer": 40.0, "dependent": 0.0,
    })
    initial_jitter: float = 0.5  # 初始存糧與存款 × U(1-jitter, 1+jitter)，避免大家同一天去買糧
    harvest_min: float = 5.0  # 每次收成的產量在 [min, max] 之間隨機
    harvest_max: float = 9.0
    wage: float = 12.0  # 打工一次的收入
    food_per_day: float = 1.0  # 每人每天吃掉的糧食
    safety_days: float = 4.0  # 存糧的安全天數（再依 persona 調整）
    noncompliance_rate: float = 0.3  # 不遵守政府政策的平民比例


@dataclass
class MarketConfig:
    base_price: float = 5.0  # 糧食的基準價值（習慣價格，貨幣量倍率之前）
    anchor_weight: float = 0.5  # 報價時習慣價格的權重，其餘參考昨天的成交價（越小價格越黏）
    urgency_premium: float = 1.0  # 存糧見底時，買價最多比參考價高多少（1.0 = +100%）
    surplus_discount: float = 0.3  # 存貨越多，賣價最多比參考價低多少
    greed_markup: float = 0.2  # 最貪心的賣家，賣價比參考價高多少
    min_price: float = 0.5


@dataclass
class GovernmentConfig:
    controller: str = "none"  # none（不介入）| llm
    budget: float = 1000.0
    food_reserve: float = 100.0
    memory: bool = True  # False = 無記憶組，不呼叫 reflect
    initial_memory: str = ""
    memory_max_chars: int = 4000
    max_decisions_per_day: int = 1  # 和平民一樣一天一個動作；第 2 個以後的決策會被拒絕
    import_premium: float = 1.5  # 進口單價 = 習慣價格 × 這個倍率
    max_import_per_day: float = 100.0
    recent_decisions: int = 20  # 觀察裡保留最近幾筆決策結果


@dataclass
class DisasterConfig:
    """每次天災週期：[穩定期][天災][評估期] → 調回均衡狀態 → 下一次。

    天災與評估期的長度每次相同（結果才能比較）；穩定期長度每次隨機，天災發生的時間才無法預測。
    """

    count: int = 5
    stable_days: int = 20  # 穩定期的平均天數
    stable_jitter: int = 5  # 每次穩定期在 stable_days ± jitter 天內隨機，政府才學不到天災的固定時間
    disaster_days: int = 5
    evaluation_days: int = 15
    kind: str = "drought"
    food_multiplier: float = 0.2  # 天災期間的收成倍率
    multiplier_jitter: float = 0.0  # 每次天災的倍率在 ±jitter 內隨機；0 = 每次相同
    schedule_seed: int = 0  # 只影響穩定期長度與天災強度，和 seed 分開，所有組別才會遇到相同的天災



@dataclass
class EquilibriumConfig:
    """均衡區間 = 校準期（沒有政府、沒有天災）每日成交價的平均 ± k 個標準差。"""

    calibration_days: int = 80
    burn_in_days: int = 20  # 前幾天還在從初始狀態收斂，不算
    k: float = 2.0  # 會議定 2～3；2.5 時波動大的 seed 區間太寬（見 docs/society.md）
    min_half_width: float = 0.02  # 標準差太小時，區間半寬至少是平均的這個比例


@dataclass
class SocialRuleConfig:
    path: str | None = None  # 規則集 YAML，例如 rules/v0.yaml
    mode: str = "enforce"  # enforce（違規就拒絕）| record（照常執行，只記錄違規；B 組用）| off


@dataclass
class SimConfig:
    name: str = "default"
    seed: int = 42
    ticks: int | None = None  # None = 跑完所有天災週期
    population: dict[str, int] = field(default_factory=lambda: {
        "producer_trader": 10, "producer_self": 5, "consumer": 20, "dependent": 5,
    })
    citizens: CitizenConfig = field(default_factory=CitizenConfig)
    market: MarketConfig = field(default_factory=MarketConfig)
    government: GovernmentConfig = field(default_factory=GovernmentConfig)
    disasters: DisasterConfig = field(default_factory=DisasterConfig)
    equilibrium: EquilibriumConfig = field(default_factory=EquilibriumConfig)
    social_rules: SocialRuleConfig = field(default_factory=SocialRuleConfig)

    @property
    def n_citizens(self) -> int:
        return sum(self.population.values())

    @property
    def total_ticks(self) -> int:
        if self.ticks is not None:
            return self.ticks
        from civsim.world.disasters import build_schedule  # 延後匯入，避免循環

        schedule = build_schedule(self.disasters)
        return schedule[-1].window_end + 1 if schedule else 0


_NESTED = {
    "citizens": CitizenConfig, "market": MarketConfig, "government": GovernmentConfig,
    "disasters": DisasterConfig, "equilibrium": EquilibriumConfig, "social_rules": SocialRuleConfig,
}


def _build(cls: type, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"{cls.__name__} 有未知的設定欄位: {sorted(unknown)}")
    kwargs = {}
    for key, value in data.items():
        if cls is SimConfig and key in _NESTED:
            value = _build(_NESTED[key], value or {})
        kwargs[key] = value
    return cls(**kwargs)


def load_config(path: str | Path, **overrides: Any) -> SimConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return _build(SimConfig, data)
