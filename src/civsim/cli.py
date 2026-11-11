"""命令列入口：civsim <command>（或 python -m civsim <command>）。"""

from __future__ import annotations

import argparse
from pathlib import Path

from civsim.config import load_config


def cmd_run(args) -> None:
    from civsim.experiments.runner import run_one

    config = load_config(args.config, seed=args.seed, ticks=args.ticks)
    out = Path(args.out) / config.name / f"seed{config.seed}"
    engine = run_one(config, out)
    band = engine.band
    print(f"均衡區間 {band.low:.2f} ~ {band.high:.2f}（平均 {band.mean:.2f}，標準差 {band.std:.2f}）")
    for m in engine.history:
        mark = "" if m.get("in_band", True) else "  ← 區間外"
        print(f"tick {m['tick']:>3}  {m['phase']:<10}  price={m['price']:>6.2f}  volume={m['volume']:>6.1f}  "
              f"hungry={m['hungry']:>2}  budget={m['gov_budget']:>8.1f}  reserve={m['gov_reserve']:>6.1f}{mark}")
    for r in engine.reports:
        print(f"天災 {r['disaster_id']}：{'成功' if r['success'] else '失敗'}"
              f"（評估期第 {r['recovered_day']} 天回到區間，最高價 {r['peak_price']:.2f}）")
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
    app = create_app(engine)
    print(f"run_id = {app.state.run_id}（政府的路徑：/runs/{app.state.run_id}/government/...）")
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_govern(args) -> None:
    from civsim.agents import NoGovernment, make_government
    from civsim.gateway.client import HttpWorldClient, RunInvalid, run_government

    controller = NoGovernment() if args.controller == "none" else make_government()

    def show(r: dict) -> None:
        if r.get("recovered"):
            print(f"tick {r['tick']:>4}  （逾時後確認已送達，沒有當天的結算結果）")
            return
        made = "、".join(f"{d['type']}{'' if d['accepted'] else '（被拒絕）'}" for d in r["decisions"]) or "不行動"
        print(f"tick {r['tick']:>4}  price={r['price']:>7.3f}  {made}")

    def show_reflection(report: dict, r: dict) -> None:
        memory = {"updated": f"更新為第 {r['memory_version']} 版", "unchanged": "不更新",
                  "rejected": "被拒絕（太長或格式錯誤）", None: "（逾時後確認已送達）"}[r["memory_result"]]
        print(f"── 天災 {report['disaster_id']} 結束：{'成功' if report['success'] else '失敗'}，記憶{memory}，世界調回均衡狀態")

    try:
        client = HttpWorldClient(args.base_url, run_id=args.run_id, max_retries=args.retries)
        print(f"run_id = {client.run_id}，政府 = {args.controller}")
        summary = run_government(client, controller, on_day=None if args.quiet else show,
                                 on_reflect=show_reflection)
    except RunInvalid as e:
        print(f"\nrun 作廢：{e}")
        raise SystemExit(1) from None
    print(f"\n完成：共 {summary['days']} 天、反思 {summary['reflections']} 次，"
          f"逾時後確認已送達 {summary['recovered']} 次")


def main(argv: list[str] | None = None) -> None:
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

    p = sub.add_parser("govern", help="扮演政府：經 HTTP（直連或 digiRunner）把 world-api 上的 run 跑完")
    p.add_argument("--base-url", help="不給就用環境變數 DIGIRUNNER_BASE_URL，再沒有就是 http://localhost:8000")
    p.add_argument("--run-id", help="不給就用 world-api 目前唯一的 run")
    p.add_argument("--controller", choices=["none", "llm"], default="none",
                   help="none = 每天都不行動（測試連線用）；llm = Agent 組的 LLM 政府")
    p.add_argument("--retries", type=int, default=3, help="基礎設施錯誤最多重試幾次")
    p.add_argument("--quiet", action="store_true", help="不印每天的結果")
    p.set_defaults(func=cmd_govern)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
