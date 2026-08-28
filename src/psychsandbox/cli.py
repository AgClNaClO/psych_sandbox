from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv

from .artifacts import (
    create_artifact_dir, latest_data_dir, local_temp_dir, runtime_root,
    set_latest_data, write_json,
)
from .config import default_config
from .datasets import CaseRepository, convert_psycheval, fetch_psycheval
from .domain import SandboxConfig
from .runtime import CounselingSandbox, SQLiteStore
from .runtime.run_management import RunManager, available_run_dir
from .therapies import normalize_therapy_id
from .visualization import generate_run_report


DISCLAIMER = "仅用于非商业教学研究；不是医疗服务，不用于诊断、治疗或危机处置。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="心理咨询多智能体研究沙盒")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    runs = commands.add_parser("runs", help="列出或按编号同步删除运行")
    run_commands = runs.add_subparsers(dest="runs_command", required=True)
    run_commands.add_parser("list", help="列出运行、目录及删除状态")
    delete = run_commands.add_parser("delete", help="默认只预览；--yes 确认删除")
    delete.add_argument("--run", required=True)
    delete.add_argument("--yes", action="store_true", help="确认永久删除该运行目录和关联数据库记录")

    data = commands.add_parser("data")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    fetch = data_commands.add_parser("fetch")
    fetch.add_argument("dataset", choices=["psycheval"])
    convert = data_commands.add_parser("convert")
    convert.add_argument(
        "--therapy", choices=["bt", "cbt", "het", "pdt", "pmt"], default="cbt"
    )

    cases = commands.add_parser("cases")
    case_commands = cases.add_subparsers(dest="cases_command", required=True)
    listing = case_commands.add_parser("list")
    listing.add_argument("--therapy", default="cbt")

    simulate = commands.add_parser("simulate")
    simulate.add_argument("--case", required=True)
    simulate.add_argument("--therapy")
    simulate.add_argument("--sessions", type=int, default=None)
    simulate.add_argument("--seed", type=int, default=None)
    simulate.add_argument("--max-turns", type=int, default=None)
    rft = simulate.add_mutually_exclusive_group()
    rft.add_argument("--rollouts", type=int, help="候选数：至少 2 启用 RFT，1 关闭")
    rft.add_argument("--no-rft", action="store_true", help="关闭 RFT")
    simulate.add_argument("--rollout-concurrency", type=int)
    simulate.add_argument("--judge-concurrency", type=int)
    simulate.add_argument("--resume-run")
    simulate.add_argument("--json", action="store_true")
    simulate.add_argument("--no-visualization", action="store_true")

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--run", required=True)
    report = commands.add_parser("report")
    report.add_argument("--run", required=True)
    visualize = commands.add_parser("visualize")
    visualize.add_argument("--run", required=True)
    visualize.add_argument("--output", type=Path, help="报告文件名或本次运行目录内的路径")
    return parser


def _config(args: argparse.Namespace) -> SandboxConfig:
    values = default_config(args.root.resolve()).model_dump()
    for argument, field in (
        ("seed", "seed"),
        ("sessions", "session_count"),
        ("max_turns", "max_turns_per_session"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            values[field] = value

    rft = values["rft"]
    rollouts = getattr(args, "rollouts", None)
    if rollouts is not None:
        if rollouts < 1:
            raise ValueError("--rollouts must be at least 1")
        rft["enabled"] = rollouts >= 2
        # A single rollout disables selection; candidates must still be >= 2.
        if rollouts >= 2:
            rft["candidates"] = rollouts
    if getattr(args, "no_rft", False):
        rft["enabled"] = False
    for argument, field in (
        ("rollout_concurrency", "concurrency"),
        ("judge_concurrency", "judge_concurrency"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            rft[field] = value
    return SandboxConfig.model_validate(values)


async def _simulate(args: argparse.Namespace) -> int:
    config = _config(args)
    sandbox = CounselingSandbox(config)
    try:
        result = await sandbox.run_case(
            args.case,
            therapy=args.therapy,
            session_count=config.session_count,
            seed=None if args.resume_run and args.seed is None else config.seed,
            resume_run_id=args.resume_run,
            progress_callback=(
                None
                if args.json
                else lambda message: print(message, flush=True)
            ),
        )
    finally:
        sandbox.store.close()
    visualization = None
    if not args.no_visualization:
        with available_run_dir(config.trace_dir, result.run_id) as run_dir:
            visualization = generate_run_report(result, run_dir / "report.html")
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
    if result.holistic_report:
        report = result.holistic_report
        print(
            f"整体督导：Counselor={report.counselor_overall:.2f} "
            f"Client={report.client_overall:.2f}"
        )
    if visualization:
        print(f"可视化报告：{visualization}")
    return 0


def _evaluate(root: Path, run_id: str, full: bool) -> int:
    with closing(_open_store(root)) as store:
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
    with available_run_dir(runtime_root(root), run_id) as run_dir:
        with closing(_open_store(root)) as store:
            result = store.load_run(run_id)
        destination = output or Path("report.html")
        if not destination.is_absolute():
            destination = run_dir / destination
        if not destination.resolve().is_relative_to(run_dir):
            raise ValueError("Report output must stay inside this run's artifact directory")
        print(generate_run_report(result, destination.resolve()))
    return 0


def _runs(args: argparse.Namespace, root: Path) -> int:
    config = default_config(root)
    manager = RunManager(config.database_path, config.trace_dir)
    try:
        if args.runs_command == "list":
            print(json.dumps(manager.list_runs(), ensure_ascii=False, indent=2))
            return 0
        preview = manager.preview_delete(args.run)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        if not preview["found"]:
            raise FileNotFoundError(f"找不到运行 {args.run}")
        if not args.yes:
            print("仅预览，未删除任何内容。确认永久删除时再次执行并添加 --yes。")
            return 0
        print(json.dumps(manager.delete(args.run), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"运行清理未完成：{exc}", file=sys.stderr)
        return 1


def _open_store(root: Path) -> SQLiteStore:
    path = runtime_root(root) / "psychsandbox.sqlite3"
    if not path.is_file():
        raise FileNotFoundError(f"找不到运行数据库：{path}")
    return SQLiteStore(path)


def _data(args: argparse.Namespace, root: Path) -> int:
    kind = "external" if args.data_command == "fetch" else "processed"
    label = "data-fetch" if kind == "external" else f"data-convert-{args.therapy}"
    run_dir = create_artifact_dir(runtime_root(root), label)
    destination = run_dir / kind / "psycheval"
    metadata = {"command": label, "status": "running"}
    write_json(run_dir / "run.json", metadata)
    with local_temp_dir(run_dir / "tmp"):
        try:
            if kind == "external":
                fetch_psycheval(destination)
            else:
                source_dir = root
                if not (root / "data" / args.therapy).is_dir():
                    source_dir = latest_data_dir(root, "external")
                manifest = convert_psycheval(source_dir, destination, therapy=args.therapy)
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
            set_latest_data(root, kind, destination)
            metadata["status"] = "completed"
        except BaseException:
            metadata["status"] = "failed"
            raise
        finally:
            write_json(run_dir / "run.json", metadata)
    print(f"产物目录：{run_dir}")
    return 0


def main() -> int:
    # Auto-load .env from project root so MODEL_API_KEY etc. are available
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.command == "runs":
        return _runs(args, root)
    if args.command == "data":
        return _data(args, root)
    if args.command == "cases":
        repository = CaseRepository.from_project(root)
        for case in repository.list(normalize_therapy_id(args.therapy)):
            print(f"{case.case_id}\t{case.profile.topic}\t{len(case.global_plan)} sessions")
        return 0
    if args.command == "simulate":
        return asyncio.run(_simulate(args))
    if args.command == "visualize":
        return _visualize(root, args.run, args.output)
    return _evaluate(root, args.run, args.command == "report")


if __name__ == "__main__":
    raise SystemExit(main())
