"""新方向的骨架都能匯入，也不影響現有的引擎。各組實作後請把對應的項目換成真正的測試。"""

import importlib

import pytest

from civsim.config import SimConfig
from civsim.world import SimulationEngine


@pytest.mark.parametrize("module", [
    "civsim.agents.government",
    "civsim.analysis.goals",
    "civsim.experiments.disaster_runner",
    "civsim.storage.research_records",
    "civsim.world.disasters",
    "civsim.world.government",
    "civsim.world.social_rules",
])
def test_skeleton_modules_import(module):
    importlib.import_module(module)


def test_government_api_skeleton_imports():
    pytest.importorskip("fastapi")
    importlib.import_module("civsim.api.government")


def test_existing_engine_still_runs_after_importing_skeleton():
    importlib.import_module("civsim.world.government")
    assert len(SimulationEngine(SimConfig(ticks=3)).run()) == 3
