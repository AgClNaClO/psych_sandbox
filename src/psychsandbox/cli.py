from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .artifacts import (
    create_artifact_dir, exclusive_run_dir, latest_data_dir, local_temp_dir, runtime_root,
    set_latest_data, write_json,
)
from .console import ProgressDisplay, enable_vt, progress_text
from .runtime.progress import PHASE_LABELS, RunProgress, ScoringProgress, TurnProgress
from .config import default_config
from .datasets import (
    CaseRepository,
    ConversionProgress,
    convert_psycheval_extractive,
    fetch_psycheval,
    merge_therapy_conversions,
)
from .domain import SandboxConfig
from .evaluation import format_intake, instrument_registry
from .evaluation.scoring_probe import (
    PROBE_FIXTURE_DIALOGUE,
    probe_instrument_rating,
    write_probe_record,
)
from .runtime import CounselingSandbox, SQLiteStore
from .model_client import create_gateway
from .runtime.run_management import RunManager, available_run_dir
from .therapies import normalize_therapy_id
from .visualization import generate_run_report


DISCLAIMER = "仅用于非商业教学研究；不是医疗服务，不用于诊断、治疗或危机处置。"


def _conversion_concurrency(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("并发数必须是 1–32 的整数") from exc
    if not 1 <= result <= 32:
        raise argparse.ArgumentTypeError("并发数必须是 1–32 的整数")
    return result


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
    clean_tests = run_commands.add_parser(
        "clean-tests", help="清理 runs/tests 下的测试日志；默认只预览，--yes 确认删除"
    )
    clean_tests.add_argument(
        "--yes", action="store_true", help="确认删除 runs/tests 下的全部测试产物目录"
    )

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
    convert.add_argument(
        "--concurrency", type=_conversion_concurrency, default=5,
        help="抽取请求的最大并发数，1–32，默认 5；设为 1 串行执行",
    )
    convert.add_argument("--no-progress", action="store_true", help="关闭转换进度输出；标准输出仍为 JSON")

    cases = commands.add_parser("cases")
    case_commands = cases.add_subparsers(dest="cases_command", required=True)
    listing = case_commands.add_parser("list")
    listing.add_argument("--therapy", default="cbt")

    probe = commands.add_parser("probe", help="探测接口能力；每次调用建立一个产物目录")
    probe_commands = probe.add_subparsers(dest="probe_command", required=True)
    logprob = probe_commands.add_parser(
        "logprob-scoring",
        help="用一次真实判分探测端点是否返回 logprobs，并记录概率加权期望",
    )
    logprob.add_argument("--case", required=True)
    logprob.add_argument("--instrument", required=True, help="量表键，例如 wai、ctrs、bdi_ii")
    logprob.add_argument(
        "--dialogue-file",
        type=Path,
        help="可选：使用自己准备的对话文本；默认使用固定合成对话",
    )
    logprob.add_argument("--json", action="store_true", help="标准输出打印完整记录")

    simulate = commands.add_parser("simulate")
    simulate.add_argument("--case", required=True)
    simulate.add_argument("--therapy")
    simulate.add_argument("--sessions", type=int, default=None)
    simulate.add_argument("--seed", type=int, default=None)
    simulate.add_argument("--max-turns", type=int, default=None)
    rft = simulate.add_mutually_exclusive_group()
    rft.add_argument("--rollouts", type=int, help="候选数：默认启用 RFT（3 个），至少 2 启用，1 关闭")
    rft.add_argument("--no-rft", action="store_true", help="关闭 RFT")
    simulate.add_argument("--rollout-concurrency", type=int)
    simulate.add_argument("--judge-concurrency", type=int)
    simulate.add_argument(
        "--logprob-scoring",
        action=argparse.BooleanOptionalAction, default=None,
        help="按论文式 8 的概率加权期望评分（默认关闭；开启前先确认端点返回 logprobs）",
    )
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
    if getattr(args, "logprob_scoring", None) is not None:
        values["logprob_scoring"]["enabled"] = args.logprob_scoring
    return SandboxConfig.model_validate(values)


def _enable_windows_vt() -> bool:
    return enable_vt(sys.stdout)


class _ProgressRenderer:
    """Stable width-aware bars in CMD; bounded plain lines when redirected."""

    def __init__(self, ansi: bool, *, stream=None, clock=time.monotonic, size=None) -> None:
        self.display = ProgressDisplay(stream, ansi=ansi, size=size)
        self.clock = clock
        self._ticks = {}
        self._run = None
        self._run_received = clock()
        self._drawn = 0.0
        self._buckets = {}
        self._printed_counts = {}

    def line(self, message: str) -> None:
        self.display.line(message)

    def status(self, event: RunProgress) -> None:
        if self._run is None or self._run.phase != event.phase:
            self.display.finish()
            self._ticks.clear()
        self._run, self._run_received = event, self.clock()
        if self.display.tty:
            self.refresh(force=True)
        else:
            self.display.line(f"{PHASE_LABELS.get(event.phase, event.phase)} | "
                              f"会谈 {event.sessions_completed}/{event.sessions_total} 已提交")

    def progress(self, event) -> None:
        if event is None:
            if self.display.tty:
                self.refresh(force=True)
            else:
                for key, (tick, _) in self._ticks.items():
                    if self._printed_counts.get(key) != self._counts(tick)[0]:
                        self.display.line(self._format(tick, 160, tick.elapsed))
            self.display.finish()
            self._ticks.clear()
            return
        key = (type(event).__name__, event.session_index, event.label)
        self._ticks[key] = (event, self.clock())
        if self._run:
            phase = "scoring" if isinstance(event, ScoringProgress) else "generating"
            self._run = RunProgress(phase, event.session_index, self._run.sessions_total,
                                    self._run.sessions_completed, self._run.elapsed)
        done, total = self._counts(event)
        if not self.display.tty:
            bucket = int(min(1.0, done / max(1, total)) * 10)
            if bucket > self._buckets.get(key, -1):
                self.display.line(self._format(event, 160, event.elapsed))
                self._buckets[key] = bucket
                self._printed_counts[key] = done
            return
        self.refresh(force=done >= total)

    @staticmethod
    def _counts(event):
        if isinstance(event, TurnProgress):
            return event.turn_index, event.total_turns
        return ((event.instruments_done, event.instruments_total) if event.instruments_total > 0
                else (event.candidates_scored, event.candidates_total))

    def _format(self, event, width, elapsed):
        done, total = self._counts(event)
        if isinstance(event, TurnProgress):
            prefix = f"会谈 {event.session_index}" + (f" 候选 {event.label}" if event.label else "")
            unit, detail = "轮上限", ""
        else:
            prefix = f"会谈 {event.session_index} 候选评估"
            unit = "量表" if event.instruments_total > 0 else "候选"
            detail = f"候选 {event.candidates_scored}/{event.candidates_total}"
        return progress_text(prefix, done, total, width, unit=unit, elapsed=elapsed,
                             eta=event.eta if done > 0 else None, detail=detail)

    def refresh(self, force: bool = False) -> None:
        if not self.display.tty:
            return
        now = self.clock()
        if not force and now - self._drawn < 0.1:
            return
        width, lines = self.display.columns, []
        if self._run:
            event = self._run
            elapsed = event.elapsed + now - self._run_received
            lines.append(progress_text("会谈提交", event.sessions_completed, event.sessions_total, width,
                                       unit="场", elapsed=elapsed,
                                       detail=PHASE_LABELS.get(event.phase, event.phase)))
        for event, received in self._ticks.values():
            done, total = self._counts(event)
            elapsed = event.elapsed if done >= total else event.elapsed + now - received
            lines.append(self._format(event, width, elapsed))
        self.display.show(lines)
        self._drawn = now

    def finish(self) -> None:
        self.display.finish()



class _ConversionProgressRenderer:
    """Keep JSON stdout clean; render live bars or bounded plain-text log lines."""

    def __init__(self, *, enabled: bool = True, stream=None):
        self.enabled = enabled
        self.stream = stream if stream is not None else sys.stderr
        self._display = ProgressDisplay(self.stream)
        self.tty = self._display.tty
        self._phase = None
        self._bucket = -1
        self._printed = 0.0
        self._width = 0

    def __call__(self, event: ConversionProgress) -> None:
        if not self.enabled:
            return
        key = (event.therapy, event.phase)
        changed = key != self._phase
        ratio = min(1.0, event.completed / event.total) if event.total else 1.0
        bucket = int(ratio * 10)
        complete = event.completed >= event.total
        now = time.monotonic()
        if not changed and not complete:
            if self.tty and now - self._printed < 0.1:
                return
            if not self.tty and bucket <= self._bucket:
                return
        if changed:
            self.finish()
        phases = {"pilot": "试转换", "extract": "抽取", "compile": "编译病例",
                  "merge": "合并", "validate": "校验", "publish": "发布"}
        filled = int(ratio * 20)
        eta = "--" if event.eta is None else f"{event.eta:.0f}s"
        text = (
            f"{event.therapy.upper()} {phases.get(event.phase, event.phase)} "
            f"[{'#' * filled}{'-' * (20 - filled)}] {ratio:6.1%} "
            f"{event.completed}/{event.total}  缓存 {event.cache_hits} "
            f"复用 {event.reused} 回退 {event.fallbacks} 跳过 {event.skipped} "
            f"用时 {event.elapsed:.1f}s  预计剩余 {eta}"
        )
        if self.tty:
            text = progress_text(f"{event.therapy.upper()} {phases.get(event.phase, event.phase)}",
                                 event.completed, event.total, self._display.columns,
                                 elapsed=event.elapsed, eta=event.eta,
                                 detail=f"缓存 {event.cache_hits} 复用 {event.reused}")
            self._display.show([text])
        else:
            self.stream.write(text + "\n")
        self.stream.flush()
        self._phase, self._bucket, self._printed = key, bucket, now
        if complete:
            self.finish()

    def finish(self) -> None:
        self._display.finish()


async def _simulate(args: argparse.Namespace) -> int:
    config = _config(args)
    sandbox = CounselingSandbox(config)
    renderer = _ProgressRenderer(_enable_windows_vt())

    async def refresh_display():
        while True:
            await asyncio.sleep(0.25)
            renderer.refresh()

    ticker = asyncio.create_task(refresh_display()) if not args.json and renderer.display.tty else None
    try:
        result = await sandbox.run_case(
            args.case,
            therapy=args.therapy,
            session_count=config.session_count,
            seed=None if args.resume_run and args.seed is None else config.seed,
            resume_run_id=args.resume_run,
            progress_callback=(None if args.json else renderer.line),
            turn_progress=(None if args.json else renderer.progress),
            status_progress=(None if args.json else renderer.status),
        )
    finally:
        if ticker:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
        renderer.finish()
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
        print(
            f"Session {session.session_index}: {session.end_reason}; "
            f"技能={','.join(session.interventions_used) or '无'}"
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
        report = store.load_holistic_report(run_id)
    if report is None:
        raise SystemExit(f"找不到运行 {run_id} 的整体督导结果")
    if full:
        print(report.model_dump_json(indent=2))
    else:
        scales = (
            report.counselor_shared
            + report.counselor_specific
            + report.client_shared
            + report.client_specific
        )
        dimensions = ", ".join(
            f"{item.name}={item.score}" for item in scales
        )
        print(
            f"整体督导：counselor={report.counselor_overall}, "
            f"client={report.client_overall}; {dimensions}"
        )
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


def _clean_tests(args: argparse.Namespace, root: Path) -> int:
    tests_root = (root / "runs" / "tests").resolve()
    directories = sorted(
        (path for path in tests_root.glob("*") if path.is_dir()),
        key=lambda path: path.name,
    )
    preview = {
        "tests_root": str(tests_root),
        "count": len(directories),
        "directories": [
            {"name": path.name, "path": str(path)} for path in directories
        ],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    if not args.yes:
        print("仅预览，未删除任何内容。确认删除时再次执行并添加 --yes。")
        return 0
    removed = 0
    for path in directories:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            print(f"删除失败：{path}（{exc}）", file=sys.stderr)
    print(f"已删除 {removed}/{len(directories)} 个测试产物目录。")
    return 0 if removed == len(directories) else 1


def _runs(args: argparse.Namespace, root: Path) -> int:
    if args.runs_command == "clean-tests":
        return _clean_tests(args, root)
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
    therapies = ["bt", "cbt", "het", "pdt", "pmt"]
    concurrency = getattr(args, "concurrency", 5)
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= 32:
        raise ValueError("conversion concurrency must be an integer from 1 to 32")
    root = root.resolve()
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
    config = default_config(root)
    run_dir = create_artifact_dir(runtime_root(root), "data-convert")
    metadata = {
        "command": "data convert", "status": "running", "concurrency": concurrency,
        "started_at": datetime.now().astimezone().isoformat(),
        "staging_dir": str(staging_root), "output_dir": str(output_root),
    }
    write_json(run_dir / "run.json", metadata)
    renderer = _ConversionProgressRenderer(enabled=not getattr(args, "no_progress", False))
    if renderer.enabled:
        print(f"转换记录：{run_dir}", file=sys.stderr, flush=True)
    output_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        # A second converter must not publish over this invocation's output.
        with exclusive_run_dir(output_root.parent), (run_dir / "progress.jsonl").open("w", encoding="utf-8") as log:
            def progress(event: ConversionProgress) -> None:
                log.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
                if event.completed >= event.total or event.completed == 0:
                    log.flush()
                renderer(event)

            gateway = create_gateway(
                diagnostic_dir=run_dir / "diagnostics", required_roles={"profile"},
            )
            if not getattr(gateway, "models", {}).get("profile"):
                raise RuntimeError("PROFILE_MODEL must be configured for schema-v4 conversion")
            manifests = []
            for therapy in therapies:
                manifest = await convert_psycheval_extractive(
                    source_dir, staging_root / "by_therapy" / therapy,
                    therapy=therapy, gateway=gateway,
                    temperature=config.temperature_control, concurrency=concurrency,
                    progress_callback=progress,
                    cache_dir=root / "data" / "processed" / ".psycheval-profile-cache" / therapy,
                )
                manifests.append(manifest)
            started = time.monotonic()
            progress(ConversionProgress("all", "merge", 0, 1))
            combined = merge_therapy_conversions(staging_root, manifests)
            progress(ConversionProgress("all", "merge", 1, 1, time.monotonic() - started))
            started = time.monotonic()
            progress(ConversionProgress("all", "validate", 0, 1))
            repository = CaseRepository(staging_root, raw_data_dir=source_dir)
            repository.list()
            progress(ConversionProgress("all", "validate", 1, 1, time.monotonic() - started))
            progress(ConversionProgress("all", "publish", 0, 1))
            backup = run_dir / "processed-backup"
            if staging_root.resolve().parent != output_root.resolve().parent:
                raise ValueError("Processed staging/output paths must share the expected parent")
            if backup.resolve().parent != run_dir.resolve():
                raise ValueError("Processed backup must stay inside this conversion's artifact directory")
            try:
                if output_root.exists():
                    output_root.replace(backup)
                    metadata["previous_processed_backup"] = str(backup)
                    write_json(run_dir / "run.json", metadata)
                staging_root.replace(output_root)
            except BaseException:
                if backup.exists() and not output_root.exists():
                    backup.replace(output_root)
                    metadata["previous_processed_restored"] = True
                raise
            progress(ConversionProgress("all", "publish", 1, 1))
            metadata["status"] = "completed"
            metadata["case_count"] = combined["case_count"]
            return combined
    except BaseException as exc:
        # Keep diagnostics and this invocation's staging files for inspection.
        metadata["status"] = "failed"
        metadata["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        raise
    finally:
        renderer.finish()
        metadata["finished_at"] = datetime.now().astimezone().isoformat()
        write_json(run_dir / "run.json", metadata)


async def _probe(args: argparse.Namespace, root: Path) -> int:
    """Probe one endpoint capability and keep the record in its own directory.

    Returns 0 only when the endpoint returned a usable logprob distribution that
    passed the mass gate; an unsupported endpoint and a refused judgement both
    exit non-zero while still writing their record.
    """
    if args.probe_command != "logprob-scoring":
        raise RuntimeError(f"unsupported probe: {args.probe_command}")
    config = default_config(root)
    case = CaseRepository.from_project(root).get(args.case)
    instruments = instrument_registry(case.therapy)
    instrument = instruments.get(args.instrument.strip().lower())
    if instrument is None:
        available = ", ".join(sorted(instruments))
        raise ValueError(
            f"unknown instrument {args.instrument!r} for therapy {case.therapy!r}; "
            f"available: {available}"
        )
    if args.dialogue_file:
        dialogue = Path(args.dialogue_file).read_text(encoding="utf-8")
        dialogue_source = f"file:{Path(args.dialogue_file)}"
    else:
        dialogue = PROBE_FIXTURE_DIALOGUE
        dialogue_source = "fixture"
    run_dir = create_artifact_dir(runtime_root(root), "probe-logprob-scoring")
    metadata = {
        "command": "probe logprob-scoring",
        "status": "running",
        "case_id": case.case_id,
        "therapy": case.therapy,
        "instrument": instrument.key,
        "dialogue_source": dialogue_source,
    }
    record: dict = {}
    try:
        gateway = create_gateway(
            diagnostic_dir=run_dir / "diagnostics", required_roles={"supervisor"}
        )
        with local_temp_dir(run_dir / "tmp"):
            record = await probe_instrument_rating(
                gateway,
                root / "prompts" / "eval",
                instrument=instrument,
                intake=format_intake(case),
                dialogue=dialogue,
                config=config.logprob_scoring,
                dialogue_source=dialogue_source,
            )
        metadata["supported"] = record["supported"]
        metadata["accepted"] = record["accepted"]
        metadata["status"] = "completed" if record["accepted"] else "inconclusive"
    except BaseException:
        metadata["status"] = "failed"
        raise
    finally:
        write_json(run_dir / "run.json", metadata)
        if record:
            write_probe_record(run_dir, record)
    print(f"产物目录：{run_dir}")
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    if record["accepted"]:
        print(
            f"端点返回 logprobs：{instrument.key} 条目聚合分（0–10） "
            f"{record['rating']['value']:.3f}（最低条目质量 {record['mass']:.3f}）"
        )
        return 0
    if record["supported"]:
        print(f"端点返回 logprobs，但本次判分未通过质量门：{record['error']}")
    else:
        print(f"端点未返回可用 logprobs：{record['error']}")
    return 1


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
    if args.command == "probe":
        return asyncio.run(_probe(args, root))
    if args.command == "visualize":
        return _visualize(root, args.run, args.output)
    return _evaluate(root, args.run, args.command == "report")


if __name__ == "__main__":
    raise SystemExit(main())
