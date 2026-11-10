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
    uvicorn.run(create_app(engine), host=args.host, port=args.port)


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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
