from dataclasses import replace

import pytest

from civsim.config import DisasterConfig, EquilibriumConfig, SimConfig


@pytest.fixture
def small_config() -> SimConfig:
    """縮短天數的設定，讓測試跑得快。"""
    return replace(
        SimConfig(),
        disasters=DisasterConfig(count=2, stable_days=8, stable_jitter=0, disaster_days=3, evaluation_days=6),
        equilibrium=EquilibriumConfig(calibration_days=30, burn_in_days=10),
    )
