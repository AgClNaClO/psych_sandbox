from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv

from .artifacts import (
    create_artifact_dir, latest_data_dir, local_temp_dir, runtime_root,
    set_latest_data, write_json,
)
from .config import default_config
from .datasets import (
    CaseRepository,
    convert_psycheval_extractive,
    fetch_psycheval,
    merge_therapy_conversions,
)
from .domain import SandboxConfig
from .runtime import CounselingSandbox, SQLiteStore
from .model_client import create_gateway
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
        "--therapy", choices=["all", "bt", "cbt", "het", "pdt", "pmt"], default="all"
    )
    convert.add_argument(
        "--atomizer", choices=["extractive", "rules"], default="extractive"
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


def _enable_windows_vt() -> bool:
    """Try to enable ANSI/VT processing; return whether ANSI is available.

    The legacy Windows console does not interpret ``\\x1b[...`` sequences by
    default, so a live progress bar would print a trailing ``[K``. Enabling
    virtual-terminal processing fixes that. Non-Windows terminals handle ANSI
    natively, and non-TTY output is handled separately by the renderer.
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        updated = ctypes.c_uint32()
        kernel32.GetConsoleMode(handle, ctypes.byref(updated))
        return bool(updated.value & 0x0004)
    except Exception:
        return False


class _ProgressRenderer:
    """Draw live progress bars alongside line messages without interleaving.

    When ANSI is available, progress bars form a block anchored at the bottom
    and line messages are inserted above it. Otherwise it falls back to a
    single carriage-return bar, which every terminal supports.
    """

    def __init__(self, ansi: bool) -> None:
        self._ansi = ansi and bool(getattr(sys.stdout, "isatty", lambda: False)())
        self._entries: dict[str, str] = {}
        self._order: list[str] = []
        self._active = False
        self._width = 0

    def line(self, message: str) -> None:
        if self._ansi:
            n = len(self._order)
            if n:
                sys.stdout.write(f"\x1b[{n}A\r")
            sys.stdout.write(message + "\x1b[K\n")
            for key in self._order:
                sys.stdout.write("\r" + self._entries[key] + "\x1b[K\n")
            sys.stdout.flush()
            return
        self._clear_line()
        print(message, flush=True)

    def progress(self, progress) -> None:
        if progress is None:
            self._entries.clear()
            self._order.clear()
            self._active = False
            self._width = 0
            return
        text = progress.render()
        if self._ansi:
            key = progress.label
            if key not in self._entries:
                self._order.append(key)
                self._entries[key] = text
                sys.stdout.write("\r" + text + "\x1b[K\n")
                sys.stdout.flush()
                return
            self._entries[key] = text
            self._redraw()
            return
        self._active = True
        if len(text) < self._width:
            text += " " * (self._width - len(text))
        else:
            self._width = len(text)
        sys.stdout.write("\r" + text)
        sys.stdout.flush()

    def _redraw(self) -> None:
        n = len(self._order)
        if n == 0:
            return
        sys.stdout.write(f"\x1b[{n}A\r")
        for key in self._order:
            sys.stdout.write("\r" + self._entries[key] + "\x1b[K\n")
        sys.stdout.flush()

    def _clear_line(self) -> None:
        if self._active:
            sys.stdout.write("\r" + " " * self._width + "\r")
            sys.stdout.flush()
            self._active = False
            self._width = 0


async def _simulate(args: argparse.Namespace) -> int:
    config = _config(args)
    sandbox = CounselingSandbox(config)
    renderer = _ProgressRenderer(_enable_windows_vt())
    try:
        result = await sandbox.run_case(
            args.case,
            therapy=args.therapy,
            session_count=config.session_count,
            seed=None if args.resume_run and args.seed is None else config.seed,
            resume_run_id=args.resume_run,
            progress_callback=(None if args.json else renderer.line),
            turn_progress=(None if args.json else renderer.progress),
        )
    finally:
        sandbox.store.close()
    visualization = None
    if not args.no_visualization:
        trace_dir = config.trace_dir
        if trace_dir is None:
            raise RuntimeError("trace_dir 未解析")
        with available_run_dir(trace_dir, result.run_id) as run_dir:
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
    database_path = config.database_path
    trace_dir = config.trace_dir
    if database_path is None or trace_dir is None:
        raise RuntimeError("运行时路径未解析")
    manager = RunManager(database_path, trace_dir)
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
    if args.data_command != "fetch":
        raise RuntimeError(
            "schema-v4 conversion is handled only by the atomic staging pipeline"
        )
    kind = "external"
    label = "data-fetch"
    run_dir = create_artifact_dir(runtime_root(root), label)
    destination = run_dir / kind / "psycheval"
    metadata = {"command": label, "status": "running"}
    write_json(run_dir / "run.json", metadata)
    with local_temp_dir(run_dir / "tmp"):
        try:
            fetch_psycheval(destination)
            set_latest_data(root, kind, destination)
            metadata["status"] = "completed"
        except BaseException:
            metadata["status"] = "failed"
            raise
        finally:
            write_json(run_dir / "run.json", metadata)
    print(f"产物目录：{run_dir}")
    return 0


async def _convert_data(args: argparse.Namespace, root: Path) -> dict:
    if args.therapy != "all":
        raise RuntimeError(
            "schema-v4 runtime cache is atomic and must be compiled with --therapy all"
        )
    therapies = (
        ["bt", "cbt", "het", "pdt", "pmt"]
        if args.therapy == "all" else [args.therapy]
    )
    source_dir = root
    if not all((source_dir / "data" / therapy).is_dir() for therapy in therapies):
        source_dir = latest_data_dir(root, "external")
    output_root = root / "data" / "processed" / "psycheval"
    staging_root = output_root.parent / f".psycheval-staging-{uuid.uuid4().hex[:8]}"
    if args.atomizer != "extractive":
        raise RuntimeError(
            "schema-v4 production conversion requires --atomizer extractive"
        )
    if not os.getenv("PROFILE_MODEL"):
        raise RuntimeError("PROFILE_MODEL must be configured for schema-v4 conversion")
    gateway = (
        create_gateway(
            diagnostic_dir=staging_root / "diagnostics",
            required_roles={"profile"},
        )
        if args.atomizer == "extractive" else None
    )
    if not getattr(gateway, "models", {}).get("profile"):
        raise RuntimeError("PROFILE_MODEL must be configured for schema-v4 conversion")
    manifests = []
    try:
        for therapy in therapies:
            output = (
                staging_root / "by_therapy" / therapy
                if args.therapy == "all" else staging_root
            )
            manifest = await convert_psycheval_extractive(
                source_dir,
                output,
                therapy=therapy,
                gateway=gateway,
                cache_dir=(
                    root / "data" / "processed" / ".psycheval-profile-cache" / therapy
                ),
            )
            manifests.append(manifest)
        combined = (
            merge_therapy_conversions(staging_root, manifests)
            if args.therapy == "all" else manifests[0]
        )
        if args.therapy == "all":
            repository = CaseRepository(staging_root, raw_data_dir=source_dir)
            repository.list()
        if output_root.exists():
            shutil.rmtree(output_root)
        staging_root.replace(output_root)
        return combined
    except BaseException:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise


def main() -> int:
    # Auto-load .env from project root so MODEL_API_KEY etc. are available
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    args = build_parser().parse_args()
    root = args.root.resolve()
    if args.command == "runs":
        return _runs(args, root)
    if args.command == "data":
        if args.data_command == "fetch":
            return _data(args, root)
        else:
            manifest = asyncio.run(_convert_data(args, root))
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
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
