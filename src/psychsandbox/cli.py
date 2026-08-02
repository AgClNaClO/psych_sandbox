from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from .datasets import CaseRepository, convert_psycheval, fetch_psycheval
from .domain import SandboxConfig
from .runtime import CounselingSandbox, SQLiteStore
from .visualization import generate_run_report


DISCLAIMER = "仅用于非商业教学研究；不是医疗服务，不用于诊断、治疗或危机处置。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="心理咨询多智能体研究沙盒")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    data = commands.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    fetch = data_commands.add_parser("fetch")
    fetch.add_argument("dataset", choices=["psycheval"])
    convert = data_commands.add_parser("convert")
    convert.add_argument("--therapy", choices=["cbt"], default="cbt")

    cases = commands.add_parser("cases")
    case_commands = cases.add_subparsers(dest="cases_command", required=True)
    listing = case_commands.add_parser("list")
    listing.add_argument("--therapy", default="cbt")

    simulate = commands.add_parser("simulate")
    simulate.add_argument("--case", required=True)
    simulate.add_argument("--therapy")
    simulate.add_argument("--sessions", type=int, default=3)
    simulate.add_argument("--provider", choices=["mock", "api", "local"], default="mock")
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--max-turns", type=int, default=8)
    simulate.add_argument("--local-model", default="")
    simulate.add_argument("--local-device", default="auto")
    simulate.add_argument("--resume-run")
    simulate.add_argument("--json", action="store_true")
    simulate.add_argument("--no-visualization", action="store_true")

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run", required=True)
    report = commands.add_parser("report")
    report.add_argument("--run", required=True)
    visualize = commands.add_parser("visualize")
    visualize.add_argument("--run", required=True)
    visualize.add_argument("--output", type=Path)
    return parser


def _config(args: argparse.Namespace) -> SandboxConfig:
    return SandboxConfig(
        project_root=args.root.resolve(),
        provider=getattr(args, "provider", "mock"),
        seed=getattr(args, "seed", 42),
        max_turns_per_session=getattr(args, "max_turns", 8),
        local_model_name=getattr(args, "local_model", ""),
        local_device=getattr(args, "local_device", "auto"),
    )


async def _simulate(args: argparse.Namespace) -> int:
    sandbox = CounselingSandbox(_config(args))
    result = await sandbox.run_case(
        args.case,
        therapy=args.therapy,
        session_count=args.sessions,
        seed=args.seed,
        resume_run_id=args.resume_run,
        progress_callback=(
            None
            if args.json
            else lambda message: print(message, flush=True)
        ),
    )
    visualization = None
    if not args.no_visualization:
        visualization = generate_run_report(
            result,
            sandbox.config.trace_dir / f"{result.run_id}.html",
        )
    if args.json:
        print(result.model_dump_json(indent=2))
        return 0
    print(DISCLAIMER)
    print(f"运行：{result.run_id}；案例：{result.case_id}；sessions：{len(result.sessions)}")
    for session in result.sessions:
        score = session.supervisor_report.overall_score if session.supervisor_report else "N/A"
        print(
            f"Session {session.session_index}: {session.end_reason}; "
            f"督导={score}; 技能={','.join(session.interventions_used) or '无'}"
        )
    if visualization:
        print(f"可视化报告：{visualization}")
    return 0


def _evaluate(root: Path, run_id: str, full: bool) -> int:
    store = SQLiteStore(root / "runs" / "psychsandbox.sqlite3")
    rows = store.evaluation_rows(run_id)
    if not rows:
        raise SystemExit(f"找不到运行 {run_id} 的督导结果")
    if full:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            report = row["rule_report"]
            dimensions = ", ".join(
                f"{item['name']}={item['score']}" for item in report["metrics"]
            )
            print(
                f"Session {row['session_index']}: overall={report['overall_score']}; "
                f"{dimensions}"
            )
            if row.get("llm_report"):
                print(f"  llm_overall={row['llm_report']['overall_score']}")
    return 0


def _visualize(root: Path, run_id: str, output: Path | None) -> int:
    store = SQLiteStore(root / "runs" / "psychsandbox.sqlite3")
    result = store.load_run(run_id)
    destination = output or root / "runs" / f"{run_id}.html"
    print(generate_run_report(result, destination.resolve()))
    return 0


def main() -> int:
    # Auto-load .env from project root so MODEL_API_KEY etc. are available
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.command == "data":
        if args.data_command == "fetch":
            print(fetch_psycheval(root / "data" / "external" / "psycheval"))
        else:
            manifest = convert_psycheval(
                root / "data" / "external" / "psycheval",
                root / "data" / "processed" / "psycheval",
                therapy=args.therapy,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == "cases":
        repository = CaseRepository(
            root / "data" / "processed" / "psycheval", root / "data" / "profiles"
        )
        for case in repository.list(args.therapy):
            print(f"{case.case_id}\t{case.profile.topic}\t{len(case.global_plan)} sessions")
        return 0
    if args.command == "simulate":
        return asyncio.run(_simulate(args))
    if args.command == "visualize":
        return _visualize(root, args.run, args.output)
    return _evaluate(root, args.run, args.command == "report")


if __name__ == "__main__":
    raise SystemExit(main())
