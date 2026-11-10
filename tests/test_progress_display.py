import io
import os
import re

from psychsandbox.cli import _ProgressRenderer
from psychsandbox.console import ProgressDisplay, fit_text, progress_text, text_width
from psychsandbox.runtime.progress import RunProgress, ScoringProgress, SimulationProgressTracker, TurnProgress
from psychsandbox.workbench.db import get_connection, init_db
from psychsandbox.workbench.events import EventHub
from psychsandbox.workbench.job_manager import JobManager


class Terminal(io.StringIO):
    def isatty(self):
        return True


def test_narrow_terminal_clips_chinese_by_cells_and_never_wraps():
    stream = Terminal()
    display = ProgressDisplay(stream, ansi=True, size=lambda: os.terminal_size((42, 12)))
    text = progress_text('第 123 场 候选 32/32', 12, 20, 41, unit='轮上限', elapsed=123, eta=456)
    display.show([text, '正在执行候选评估，中文不能按字符个数截断。' * 5])
    clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', stream.getvalue())
    assert all(text_width(line) <= 41 for line in clean.splitlines())
    assert '12/20' in clean
    assert text_width(fit_text('中文abcd', 5)) <= 5


def test_redirected_simulation_is_bounded_plain_text_not_carriage_return_frames():
    stream = io.StringIO()
    renderer = _ProgressRenderer(False, stream=stream)
    for index in range(1001):
        renderer.progress(TurnProgress(1, index, 1000, index, 1000 - index, '1/3'))
    renderer.progress(None)
    renderer.finish()
    assert len(stream.getvalue().splitlines()) == 11
    assert '\r' not in stream.getvalue() and '\x1b' not in stream.getvalue()
    assert '1000/1000' in stream.getvalue()


def test_legacy_cmd_finishes_one_line_before_regular_output():
    stream = Terminal()
    renderer = _ProgressRenderer(False, stream=stream, size=lambda: os.terminal_size((80, 24)))
    renderer.progress(TurnProgress(1, 2, 20, 10, 90, '1/3'))
    renderer.line('会谈已提交')
    renderer.progress(None)
    renderer.finish()
    assert '\x1b' not in stream.getvalue()
    assert stream.getvalue().endswith('\n')
    assert '会谈已提交\n' in stream.getvalue()


def test_terminal_limits_candidate_rows_and_recovers_from_resize():
    stream = Terminal()
    size = [os.terminal_size((90, 9))]
    display = ProgressDisplay(stream, ansi=True, size=lambda: size[0])
    display.show([f'候选 {i}' for i in range(32)])
    assert display.rows == 5
    assert '另有 28 项' in stream.getvalue()
    size[0] = os.terminal_size((30, 9))
    before = len(stream.getvalue())
    display.show(['更窄的窗口中也不能越界' * 4])
    assert '\x1b[5A' not in stream.getvalue()[before:]
    assert text_width(display.lines[0]) <= 29


def test_progress_tracker_resumes_committed_sessions_and_keeps_parallel_candidates():
    now = [100.0]
    tracker = SimulationProgressTracker(7, candidates_total=3, clock=lambda: now[0])
    tracker.update(RunProgress('planning', 4, 7, 3, 0))
    tracker.update(TurnProgress(4, 3, 20, 10, 60, '1/3'))
    snapshot = tracker.update(TurnProgress(4, 2, 20, 8, 72, '2/3'))
    assert snapshot['sessions_completed'] == 3
    assert [candidate['turn_index'] for candidate in snapshot['candidates']] == [3, 2]
    snapshot = tracker.update(ScoringProgress(4, 2, 12, 0, 3, 5, 25))
    assert snapshot['phase'] == 'scoring' and snapshot['scoring']['instruments_done'] == 2
    snapshot = tracker.update(RunProgress('planning', 5, 7, 4, 120))
    assert snapshot['candidates'] == [] and snapshot['scoring'] is None
    assert snapshot['sessions_completed'] == 4


def test_snapshot_is_durable_and_rejects_expired_or_old_attempts(tmp_path):
    database = str(tmp_path / 'workbench.sqlite3')
    init_db(database)
    jobs = JobManager(database)
    hub = EventHub(database)
    queued = jobs.enqueue_job('simulation', 'long', {'case_id': 'fixture'})
    first = jobs.claim_job('long', 'worker-one')
    payload = {'attempt': first.attempt, 'progress': {'attempt': first.attempt, 'revision': 1, 'phase': 'scoring'}}
    assert hub.emit(f'job:{queued.job_id}', 'simulation_status', payload, job_fence=(queued.job_id, first.attempt, 'worker-one'))
    assert jobs.get_job(queued.job_id).progress['phase'] == 'scoring'
    assert jobs.list_jobs('long')[0].progress['revision'] == 1
    connection = get_connection(database)
    connection.execute("UPDATE jobs SET status = 'queued' WHERE job_id = ?", (queued.job_id,))
    connection.close()
    second = jobs.claim_job('long', 'worker-two')
    assert second.attempt == first.attempt + 1
    assert jobs.get_job(queued.job_id).progress is None
    assert hub.emit(f'job:{queued.job_id}', 'simulation_status', payload, job_fence=(queued.job_id, first.attempt, 'worker-one')) is None
    connection = get_connection(database)
    connection.execute("UPDATE jobs SET lease_expires_at = '2000-01-01' WHERE job_id = ?", (queued.job_id,))
    connection.close()
    assert hub.emit(f'job:{queued.job_id}', 'simulation_status', {'attempt': second.attempt}, job_fence=(queued.job_id, second.attempt, 'worker-two')) is None
    assert len(hub.get_events(f'job:{queued.job_id}')) == 1
