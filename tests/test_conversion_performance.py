import asyncio
import io
import json
from pathlib import Path
import shutil

import pytest

from psychsandbox import cli
from psychsandbox.datasets import CaseRepository, ConversionProgress, convert_psycheval_extractive
from psychsandbox.datasets.atomizer import ExtractiveAtomizer
from tests.conversion_gateway import ConversionGateway


@pytest.fixture
def conversion_source(tmp_path):
    source = tmp_path / "data" / "cbt"
    source.mkdir(parents=True)
    for index in range(1, 9):
        (source / f"{index}.json").write_text(json.dumps({
            "client_id": index,
            "client_info": {
                "static_traits": {
                    "name": f"测试{index}", "age": "28", "gender": "女",
                    "language_features": f"表达情况{index}",
                    "family_status": f"家庭情况{index}",
                    "social_status": "有朋友支持。", "medical_history": f"就医情况{index}",
                },
                "main_problem": "最近考试紧张", "topic": "学习",
                "core_demands": f"希望改善学习{index}",
                "growth_experiences": [f"有过{index}次失败经历。"],
            },
            "sessions": [],
        }, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_bounded_conversion_reuses_pilot_and_duplicate_inputs(conversion_source):
    gateway = ConversionGateway()
    ticks = []
    output = conversion_source / "output"
    manifest = asyncio.run(convert_psycheval_extractive(
        conversion_source, output, therapy="cbt", gateway=gateway,
        concurrency=4, cache_dir=conversion_source / "cache", progress_callback=ticks.append,
    ))
    assert gateway.peak == 4
    assert gateway.active == 0
    keys = [(r["source_path"], r["source_text"], r["purpose"]) for r in gateway.requests]
    assert len(keys) == len(set(keys)) == 41  # 40 unique fields + one shared social field.
    audit = manifest["atomization_audit"]
    assert audit["pilot_items"] == 30
    assert audit["reused"] >= audit["pilot_items"]
    assert audit["fallbacks"] == 0
    for phase, total in (("pilot", 30), ("extract", 48), ("compile", 8)):
        events = [tick for tick in ticks if tick.phase == phase]
        assert events[0].completed == 0
        assert events[-1].completed == events[-1].total == total
        assert [e.completed for e in events] == sorted(e.completed for e in events)
    rows = [json.loads(line) for line in (output / "atomization_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 48
    assert [row["client_id"] for row in rows] == [str(i) for i in range(1, 9) for _ in range(6)]
    assert sum(row["reused"] for row in rows) == audit["reused"]


def test_serial_concurrent_and_warm_cache_produce_identical_cases(conversion_source):
    outputs = []
    for name, concurrency in (("serial", 1), ("parallel", 4), ("warm", 4)):
        gateway = ConversionGateway()
        output = conversion_source / name
        manifest = asyncio.run(convert_psycheval_extractive(
            conversion_source, output, therapy="cbt", gateway=gateway,
            concurrency=concurrency,
            cache_dir=conversion_source / ("serial-cache" if name == "serial" else "parallel-cache"),
        ))
        if name == "serial":
            assert gateway.peak == 1
        if name == "warm":
            assert gateway.requests == []
            assert manifest["atomization_audit"]["cache_hits"] > 0
            assert manifest["atomization_audit"]["pilot_cache_hits"] > 0
        outputs.append(output)
    for filename in ("all.jsonl", "train.jsonl", "validation.jsonl", "test.jsonl", "skills.json"):
        assert len({(out / filename).read_bytes() for out in outputs}) == 1


def test_pilot_fallback_is_reused_but_stays_quarantined(conversion_source):
    # Every pilot has six fields; one failure stays below the existing 5% gate.
    gateway = ConversionGateway(fail_text="有过1次失败经历。")
    output = conversion_source / "output"
    manifest = asyncio.run(convert_psycheval_extractive(
        conversion_source, output, therapy="cbt", gateway=gateway,
        cache_dir=conversion_source / "cache",
    ))
    assert sum(r["source_text"] == gateway.fail_text for r in gateway.requests) == 1
    assert manifest["atomization_audit"]["pilot_fallbacks"] == 1
    assert manifest["atomization_audit"]["fallbacks"] == 1
    first = json.loads((output / "all.jsonl").read_text(encoding="utf-8").splitlines()[0])
    nodes = [node for node in first["profile"]["evidence_nodes"] if node["source_text"] == gateway.fail_text]
    assert nodes and all(node["needs_review"] for node in nodes)


def test_cancelling_conversion_drains_all_workers(conversion_source):
    async def run():
        entered = asyncio.Event()
        gateway = ConversionGateway(delay=30, entered=entered)
        task = asyncio.create_task(convert_psycheval_extractive(
            conversion_source, conversion_source / "output", therapy="cbt", gateway=gateway,
            concurrency=4, cache_dir=conversion_source / "cache",
        ))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gateway.active == 0
        assert len(gateway.requests) == 4
    asyncio.run(run())


@pytest.mark.parametrize("text", ["", " ，。、→ "])
def test_nonsemantic_inputs_skip_model_calls(tmp_path, text):
    gateway = ConversionGateway()
    spans, audit = asyncio.run(ExtractiveAtomizer(gateway, tmp_path).atomize(
        source_path="source", source_text=text,
    ))
    assert spans == [] and audit.skipped and not audit.needs_review
    assert gateway.requests == []


@pytest.mark.parametrize("text", ["女", "无", "0"])
def test_short_semantic_inputs_still_use_strict_extraction(tmp_path, text):
    gateway = ConversionGateway()
    spans, audit = asyncio.run(ExtractiveAtomizer(gateway, tmp_path).atomize(
        source_path="source", source_text=text,
    ))
    assert [span.text for span in spans] == [text]
    assert not audit.skipped and not audit.fallback


@pytest.mark.parametrize("value", [0, 33, -1, True, 1.5])
def test_conversion_rejects_invalid_concurrency_before_requests(tmp_path, value):
    gateway = ConversionGateway()
    with pytest.raises(ValueError, match="concurrency"):
        asyncio.run(convert_psycheval_extractive(tmp_path, tmp_path / "out", therapy="cbt", gateway=gateway, concurrency=value))
    assert gateway.requests == []


def test_conversion_progress_is_separate_from_json_and_bounded_when_redirected():
    stream = io.StringIO()
    renderer = cli._ConversionProgressRenderer(stream=stream)
    for completed in range(1001):
        renderer(ConversionProgress("cbt", "extract", completed, 1000, completed / 10,
                                    cache_hits=10, reused=5, fallbacks=1))
    lines = stream.getvalue().splitlines()
    assert len(lines) == 11
    assert "0.0%" in lines[0] and "100.0%" in lines[-1]
    assert "缓存 10" in lines[-1] and "回退 1" in lines[-1]
    assert "\r" not in stream.getvalue() and "\x1b" not in stream.getvalue()
    disabled = io.StringIO()
    cli._ConversionProgressRenderer(enabled=False, stream=disabled)(ConversionProgress("cbt", "pilot", 0, 1))
    assert disabled.getvalue() == ""


def test_cli_conversion_options_reject_invalid_limits():
    parser = cli.build_parser()
    assert parser.parse_args(["data", "convert"]).concurrency == 5
    assert parser.parse_args(["data", "convert", "--concurrency", "1", "--no-progress"]).no_progress
    for value in ("0", "33", "1.5", "text"):
        with pytest.raises(SystemExit):
            parser.parse_args(["data", "convert", "--concurrency", value])


def test_conversion_refuses_source_changes_during_extraction(conversion_source):
    changed = False
    def mutate(tick):
        nonlocal changed
        if not changed and tick.phase == "extract" and tick.completed == tick.total:
            source = conversion_source / "data" / "cbt" / "1.json"
            source.write_text(source.read_text(encoding="utf-8") + " ", encoding="utf-8")
            changed = True
    with pytest.raises(RuntimeError, match="source changed"):
        asyncio.run(convert_psycheval_extractive(
            conversion_source, conversion_source / "output", therapy="cbt", gateway=ConversionGateway(),
            progress_callback=mutate,
        ))


def test_cli_converts_all_therapies_with_progress_and_retains_previous(root, tmp_path, monkeypatch, capsys):
    for therapy in ("bt", "cbt", "het", "pdt", "pmt"):
        shutil.copytree(root / "data" / therapy, tmp_path / "data" / therapy)
    output = tmp_path / "data" / "processed" / "psycheval"
    output.mkdir(parents=True)
    (output / "previous.txt").write_text("keep previous corpus", encoding="utf-8")
    gateway = ConversionGateway(delay=0)
    monkeypatch.setattr(cli, "create_gateway", lambda **_: gateway)
    monkeypatch.setenv("PROFILE_MODEL", "conversion-test-double")
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runs" / "runtime"))
    monkeypatch.setattr("sys.argv", ["psych-sandbox", "--root", str(tmp_path), "data", "convert", "--concurrency", "4"])
    assert cli.main() == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["case_count"] == 341
    assert "试转换" in captured.err and "100.0%" in captured.err and "发布" in captured.err
    assert len(CaseRepository.from_project(tmp_path).list()) == 341
    [run_dir] = (tmp_path / "runs" / "runtime").glob("*__data-convert__*")
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "completed"
    assert (Path(metadata["previous_processed_backup"]) / "previous.txt").read_text() == "keep previous corpus"
    phases = [json.loads(line)["phase"] for line in (run_dir / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
    assert phases[-6:] == ["merge", "merge", "validate", "validate", "publish", "publish"]


@pytest.mark.parametrize("failure", ["extract", "validate", "publish"])
def test_failed_conversion_preserves_old_output_and_diagnostics(tmp_path, monkeypatch, failure):
    for therapy in ("bt", "cbt", "het", "pdt", "pmt"):
        (tmp_path / "data" / therapy).mkdir(parents=True)
    output = tmp_path / "data" / "processed" / "psycheval"
    output.mkdir(parents=True)
    (output / "previous.txt").write_text("untouched", encoding="utf-8")
    async def convert(_source, destination, **_kwargs):
        destination.mkdir(parents=True)
        (destination / "partial.json").write_text("{}")
        if failure == "extract":
            raise RuntimeError("fixture extraction failed")
        return {}
    monkeypatch.setattr(cli, "convert_psycheval_extractive", convert)
    monkeypatch.setattr(cli, "create_gateway", lambda **_: ConversionGateway())
    monkeypatch.setattr(cli, "merge_therapy_conversions", lambda *_: {"case_count": 341})
    def validate(*_):
        if failure == "validate":
            raise RuntimeError("fixture validation failed")
        return []
    monkeypatch.setattr(cli.CaseRepository, "list", validate)
    monkeypatch.setenv("PROFILE_MODEL", "conversion-test-double")
    monkeypatch.setenv("PSYCHSANDBOX_RUNTIME_DIR", str(tmp_path / "runs" / "runtime"))
    replace = Path.replace
    def publish_fault(path, target):
        if path.name.startswith(".psycheval-staging-"):
            raise PermissionError("fixture publish failed")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", publish_fault)
    args = cli.build_parser().parse_args(["data", "convert", "--no-progress"])
    with pytest.raises((RuntimeError, PermissionError), match="fixture"):
        asyncio.run(cli._convert_data(args, tmp_path))
    assert (output / "previous.txt").read_text() == "untouched"
    [run_dir] = (tmp_path / "runs" / "runtime").glob("*__data-convert__*")
    metadata = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert Path(metadata["staging_dir"]).is_dir()
    if failure == "publish":
        assert metadata["previous_processed_restored"]
