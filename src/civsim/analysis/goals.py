"""判定每次天災後，價格能否在評估期內恢復到均衡區間。

負責人：分析組。這裡先依 11/9 會議的結論寫第一版，判定細節由分析組調整：
- 均衡價格是一個區間（world/equilibrium.py）
- 評估期內價格進入區間後要一直維持到評估期結束才算成功，中途跑出區間就算失敗
- 價格被政府的上限壓住的那幾天，不算在區間內
- 死亡與挨餓人數不影響判定，只記成輔助指標
"""

from __future__ import annotations

from civsim.world.equilibrium import EquilibriumBand


def evaluate_disaster(disaster, history: list[dict], band: EquilibriumBand,
                      decisions: list[dict] | None = None) -> dict:
    """評估期結束時產生這次天災的報告，引擎會把報告交給政府反思。disaster 是 world/disasters.py 的 Disaster。

    history 是這個天災週期每天的指標（analysis/metrics.py）；decisions 是這個週期政府的所有決策結果。
    """
    window = [m for m in history if disaster.end_tick < m["tick"] <= disaster.window_end]
    in_band = [band.contains(m["price"]) and not m["price_capped"] for m in window]

    entered = next((i for i, ok in enumerate(in_band) if ok), None)
    success = entered is not None and all(in_band[entered:])

    cycle = [m for m in history if disaster.cycle_start <= m["tick"] <= disaster.window_end]
    return {
        "disaster_id": disaster.id,
        "kind": disaster.kind,
        "window_start": disaster.end_tick + 1,
        "window_end": disaster.window_end,
        "band": band.to_dict(),
        "success": success,
        # 評估期第幾天（從 1 開始）第一次回到區間；None = 沒有回到過
        "recovered_day": entered + 1 if entered is not None else None,
        "left_band_after_recovery": entered is not None and not success,
        "window_prices": [m["price"] for m in window],
        "capped_days": sum(1 for m in window if m["price_capped"]),
        "peak_price": max((m["price"] for m in cycle), default=None),
        "hungry_person_days": sum(m["hungry"] for m in cycle),
        "deaths": cycle[-1]["deaths"] if cycle else 0,
        "decisions": decisions or [],
    }


def first_sustained(reports: list[dict]) -> int | None:
    """從第幾次天災開始，之後每一次都成功；從來沒有時回傳 None。

    TODO(分析組)：是否保留這個指標，依實驗方式決定。
    """
    first = None
    for r in reports:
        if r["success"]:
            first = first if first is not None else r["disaster_id"]
        else:
            first = None
    return first
