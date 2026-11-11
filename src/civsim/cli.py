"""命令列入口：civsim <command>（或 python -m civsim <command>）。"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from civsim.config import load_config


def cmd_run(args) -> None:
    from civsim.experiments.runner import run_one

    config = load_config(args.config, seed=args.seed, ticks=args.ticks)
    out = Path(args.out) / config.name / f"seed{config.seed}"
    history = run_one(config, out)
    for m in history:
        print(f"tick {m['tick']:>3}  alive={m['alive']:>2}  gini={m['wealth_gini']:.3f}  "
              f"authorities={m['n_authorities']}  food_price={m['prices']['food']:.2f}")
    print(f"\n紀錄已寫入 {out}")


def cmd_experiment(args) -> None:
    from civsim.experiments.runner import run_batch

    configs = [load_config(p) for p in args.configs]
    summary = run_batch(configs, args.repeats, Path(args.out))
    print(summary.read_text(encoding="utf-8"))
    print(f"摘要已寫入 {summary}")


def cmd_serve(args) -> None:
    import uvicorn

    from civsim.api.server import create_app
    from civsim.world import SimulationEngine

    engine = SimulationEngine(load_config(args.config, seed=args.seed))
    uvicorn.run(create_app(engine), host=args.host, port=args.port)


def cmd_remote(args) -> None:
    from civsim.agents import build_controllers
    from civsim.gateway.client import HttpWorldClient, run_remote
    from civsim.world.setup import create_world

    config = load_config(args.config, seed=args.seed)
    # Agent 端只需要知道有哪些 Agent，以同樣的 seed 建立決策模組
    world = create_world(config, random.Random(config.seed))
    run_remote(HttpWorldClient(args.base_url), build_controllers(world, config), args.ticks or config.ticks)


def cmd_llm_check(args) -> None:
    """用一個假的天災情境呼叫一次 LLM 政府，確認 API key 與模型設定可以用。"""
    from civsim.agents.government import build_prompt, make_government
    from civsim.world.government import GovernmentObservation

    gov = make_government()
    obs = GovernmentObservation(
        tick=12, prices={"food": 8.5}, memory="", rules=["不能處決平民"],
        phase="disaster", days_since_disaster=2, budget=500.0, food_reserve=40.0, deaths=0,
    )
    print(f"模型：{gov.client.model}\n\n--- 送出的觀察 ---\n{build_prompt(obs)}")
    decisions = gov.decide(obs)
    call = gov.calls[-1]
    print(f"--- LLM 回應 ---\n{call.response}\n")
    if call.error:
        print(f"呼叫失敗：{call.error}")
        raise SystemExit(1)
    print(f"--- 解析出的決策 ---\n{decisions}\n略過的項目：{call.skipped}\ntoken 用量：{call.usage}")


def main(argv: list[str] | None = None) -> None:
    from civsim.agents.llm_client import load_dotenv

    load_dotenv()  # 讀入專案根目錄的 .env（已設定的環境變數優先）
    parser = argparse.ArgumentParser(prog="civsim", description="Multi-Agent 文明模擬器")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="執行單次模擬")
    p.add_argument("--config", default="configs/baseline.yaml")
    p.add_argument("--seed", type=int)
    p.add_argument("--ticks", type=int)
    p.add_argument("--out", default="runs")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("experiment", help="多組條件 × 多個 seed 的批次實驗")
    p.add_argument("configs", nargs="+")
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--out", default="runs")
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("serve", help="啟動 world-api（註冊到 digiRunner 後面）")
    p.add_argument("--config", default="configs/baseline.yaml")
    p.add_argument("--seed", type=int)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("remote", help="Agent 端：經由 Gateway 呼叫 world-api 跑模擬")
    p.add_argument("--config", default="configs/baseline.yaml")
    p.add_argument("--seed", type=int)
    p.add_argument("--ticks", type=int)
    p.add_argument("--base-url", help="預設讀 DIGIRUNNER_BASE_URL")
    p.set_defaults(func=cmd_remote)

    p = sub.add_parser("llm-check", help="呼叫一次 LLM 政府，確認 API key 與模型設定")
    p.set_defaults(func=cmd_llm_check)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
