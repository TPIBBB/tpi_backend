"""實驗設定：從 YAML 載入。一個設定檔 = 一組實驗條件。"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EventConfig:
    food_shock_prob: float = 0.15  # 每回合產生「明天糧食減產」的機率
    food_shock_multiplier: float = 0.4


@dataclass
class MarketConfig:
    initial_prices: dict[str, float] = field(
        default_factory=lambda: {"food": 5.0, "wood": 3.0, "tools": 12.0}
    )
    initial_stock: dict[str, float] = field(
        default_factory=lambda: {"food": 60.0, "wood": 30.0, "tools": 10.0}
    )
    treasury: float = 2000.0
    price_elasticity: float = 0.08


@dataclass
class InstitutionConfig:
    preset: str = "equal"  # equal | hierarchical | none
    elite_fraction: float = 0.15  # hierarchical 時掌握資訊與授權的比例


@dataclass
class SimConfig:
    name: str = "default"
    seed: int = 42
    ticks: int = 30
    roles: dict[str, int] = field(
        default_factory=lambda: {"farmer": 8, "woodcutter": 6, "craftsman": 4, "merchant": 6}
    )
    initial_inventory: dict[str, float] = field(
        default_factory=lambda: {"food": 8.0, "wood": 0.0, "tools": 1.0, "money": 50.0}
    )
    action_points: int = 2
    agent_controller: str = "rule_based"  # rule_based | llm
    allow_info_sharing: bool = True
    institution: InstitutionConfig = field(default_factory=InstitutionConfig)
    events: EventConfig = field(default_factory=EventConfig)
    market: MarketConfig = field(default_factory=MarketConfig)

    @property
    def n_agents(self) -> int:
        return sum(self.roles.values())


_NESTED = {"institution": InstitutionConfig, "events": EventConfig, "market": MarketConfig}


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
