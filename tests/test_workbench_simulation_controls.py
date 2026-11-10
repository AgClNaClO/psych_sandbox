"""Web simulation settings, report publication and recovery regressions."""
import pytest
from fastapi.testclient import TestClient

from psychsandbox.artifacts import find_run_dir, write_json
from psychsandbox.domain import CounselorActorOutput, SandboxConfig
from psychsandbox.runtime import CounselingSandbox
from psychsandbox.runtime.storage import SQLiteStore
from psychsandbox.workbench.api import create_app
from psychsandbox.workbench.db import get_connection, init_db
from psychsandbox.workbench.models import SimulationJobPayload
from psychsandbox.workbench.projections import get_run_detail
from psychsandbox.workbench.worker import WorkbenchWorker
from tests.deterministic_gateway import DeterministicGateway, DISABLED_LOGPROB_SCORING


class DiverseGateway(DeterministicGateway):
    replies = 0

    async def complete_structured(self, **kwargs):
        result = await super().complete_structured(**kwargs)
        if kwargs['output_schema'] is CounselorActorOutput:
            self.replies += 1
            result.response += f' 我们可以慢慢探讨这个片段（{self.replies}）。'
            result.decision.end_session = False
        return result


@pytest.mark.parametrize('settings', [
    {'max_turns_per_session': 0}, {'max_turns_per_session': 51},
    {'session_turn_limits': [1, 0]}, {'session_turn_limits': [1]},
    {'session_turn_limits': [1, 2.5]}, {'session_turn_limits': [True, 2]},
    {'rft': {'enabled': True, 'candidates': 1}},
])
def test_invalid_simulation_controls(settings):
    with pytest.raises(ValueError):
        SimulationJobPayload(case_id='case', session_count=2, **settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('rft', [False, True])
async def test_web_controls_change_real_sessions_and_publish_html(root, tmp_path, monkeypatch, rft):
    config = SandboxConfig(project_root=root, max_turns_per_session=4,
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / 'sim.sqlite3', trace_dir=tmp_path / 'traces')
    monkeypatch.setattr('psychsandbox.workbench.worker.default_config', lambda: config)
    wb = str(tmp_path / 'workbench.sqlite3')
    init_db(wb)
    worker = WorkbenchWorker('long', wb, gateway_factory=DiverseGateway)
    app = create_app(db_path=wb, sim_db_path=config.database_path, trace_dir=config.trace_dir,
                     frontend_dir=tmp_path / 'no-frontend')
    with TestClient(app) as client:
        response = client.post('/api/jobs', json={'kind': 'simulation', 'payload': {
            'case_id': 'psycheval-cbt-001', 'session_count': 2,
            'max_turns_per_session': 3, 'session_turn_limits': [1, 2],
            'rft': {'enabled': rft, 'candidates': 2},
        }})
        assert response.status_code == 200, response.text
        await worker._execute_job(worker.job_manager.claim_job('long', worker.worker_id))
        job = worker.job_manager.get_job(response.json()['job_id'])
        assert job.status == 'succeeded', job.error
        with_store = SQLiteStore(config.database_path)
        try:
            result = with_store.load_run(job.run_id)
            assert [len(session.turn_records) for session in result.sessions] == [1, 2]
            assert all(bool(session.rollout_selection) == rft for session in result.sessions)
            saved = with_store.load_run_metadata(job.run_id)['config']
            assert saved['max_turns_per_session'] == 3
            assert saved['session_turn_limits'] == [1, 2]
            assert saved['rft']['enabled'] == rft
        finally:
            with_store.close()
        report = client.get(f'/api/runs/{job.run_id}/report')
        assert report.status_code == 200
        assert '<html' in report.text
        assert any(run['run_id'] == job.run_id and run['has_html_report'] for run in client.get('/api/runs').json())
        assert client.get(f'/api/runs/{job.run_id}').json()['requested_sessions'] == 2
        # A fresh page can find the completed job and replay persisted progress.
        assert client.get('/api/jobs?lane=long').json()[0]['job_id'] == job.job_id
        events = worker.event_hub.get_events(f'job:{job.job_id}')
        assert any(event.type == 'simulation_progress' for event in events)
        assert events[-1].type == 'job_succeeded'
        snapshot = client.get(f'/api/jobs/{job.job_id}').json()['progress']
        assert snapshot['phase'] == 'report'
        assert (snapshot['sessions_completed'], snapshot['sessions_total']) == (2, 2)
        stages = [event.payload['progress']['phase'] for event in events if event.type == 'simulation_status']
        assert {'planning', 'generating', 'consolidating', 'committed', 'holistic', 'report'} <= set(stages)
        assert ('scoring' in stages) == rft
        initial = [event.payload['progress'] for event in events if event.type == 'simulation_status'
                   and event.payload['progress']['phase'] == 'generating']
        assert any(candidate['turn_index'] == 0 for tick in initial for candidate in tick['candidates'])

        # Completed retry must recover HTML without another model request.
        async def no_generation(**kwargs):
            raise AssertionError('Completed retry must not generate or score again')

        # Worker still creates a gateway, but no generation is allowed.
        gateway = DiverseGateway()
        monkeypatch.setattr(gateway, 'complete_structured', no_generation)
        worker.gateway_factory = lambda: gateway
        # Later YAML defaults must not change the original RFT experiment.
        config.rft.judge_temperature = 1.1
        report_file = next(config.trace_dir.glob('*/report.html'))
        report_file.unlink()
        conn = get_connection(wb)
        conn.execute("UPDATE jobs SET status = 'queued' WHERE job_id = ?", (job.job_id,))
        conn.close()
        claimed = worker.job_manager.claim_job('long', worker.worker_id)
        assert claimed.attempt == 2
        await worker._execute_job(claimed)
        assert worker.job_manager.get_job(job.job_id).status == 'succeeded'
        assert report_file.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('rft', [False, True])
async def test_failed_web_run_resumes_committed_boundary_with_original_settings(root, tmp_path, monkeypatch, rft):
    config = SandboxConfig(project_root=root, max_turns_per_session=4,
        logprob_scoring=DISABLED_LOGPROB_SCORING,
        database_path=tmp_path / 'sim.sqlite3', trace_dir=tmp_path / 'traces')
    monkeypatch.setattr('psychsandbox.workbench.worker.default_config', lambda: config)
    wb = str(tmp_path / 'workbench.sqlite3')
    init_db(wb)
    worker = WorkbenchWorker('long', wb, gateway_factory=DiverseGateway)
    app = create_app(db_path=wb, sim_db_path=config.database_path, trace_dir=config.trace_dir,
                     frontend_dir=tmp_path / 'no-frontend')
    original_run_case = CounselingSandbox.run_case

    async def fail_at_second_session(self, **kwargs):
        callback = kwargs['progress_callback']

        def progress(message):
            callback(message)
            if message == 'Session 2/2 开始':
                raise RuntimeError('Interrupted before second session')

        return await original_run_case(self, **{**kwargs, 'progress_callback': progress})

    with TestClient(app) as client:
        with monkeypatch.context() as patch:
            patch.setattr(CounselingSandbox, 'run_case', fail_at_second_session)
            response = client.post('/api/jobs', json={'kind': 'simulation', 'max_attempts': 1, 'payload': {
                'case_id': 'psycheval-cbt-001', 'session_count': 2, 'seed': 0,
                'max_turns_per_session': 3, 'session_turn_limits': [1, 2],
                'rft': {'enabled': rft, 'candidates': 2},
            }})
            assert response.status_code == 200, response.text
            await worker._execute_job(worker.job_manager.claim_job('long', worker.worker_id))
        failed = worker.job_manager.get_job(response.json()['job_id'])
        assert failed.status == 'failed', failed.error
        detail = client.get(f'/api/runs/{failed.run_id}').json()
        assert detail['status'] == 'failed'
        assert detail['requested_sessions'] == 2
        assert len(detail['sessions']) == 1
        original_session = detail['sessions'][0]
        # Resume must be independent of the new-experiment form and changed YAML defaults.
        config.max_turns_per_session = 5
        config.rft.enabled = not rft
        resumed = client.post('/api/jobs', json={'kind': 'simulation', 'payload': {
            'resume_run_id': detail['run_id'], 'case_id': detail['case_id'],
            'therapy': detail['therapy'], 'seed': detail['seed'],
            'session_count': detail['requested_sessions'],
        }})
        assert resumed.status_code == 200, resumed.text
        await worker._execute_job(worker.job_manager.claim_job('long', worker.worker_id))
        finished = worker.job_manager.get_job(resumed.json()['job_id'])
        assert finished.status == 'succeeded', finished.error
        assert finished.run_id == failed.run_id
        restored = client.get(f'/api/runs/{finished.run_id}').json()
        assert restored['sessions'][0] == original_session
        assert [len(session['turns']) for session in restored['sessions']] == [1, 2]
        assert restored['config']['rft']['enabled'] == rft
        assert restored['config']['max_turns_per_session'] == 3
        assert restored['config']['session_turn_limits'] == [1, 2]
        assert restored['seed'] == 0
        assert len(client.get('/api/runs').json()) == 1


@pytest.mark.parametrize('total', [None, True, 0, 101, '7'])
def test_run_detail_without_valid_recovery_metadata_stays_readable(tmp_path, total):
    store = SQLiteStore(tmp_path / 'sim.sqlite3')
    store.start_run('run-metadata', 'case', 'cbt', 'api', 42, {})
    directory = tmp_path / 'traces' / 'saved__run-metadata'
    directory.mkdir(parents=True)
    write_json(directory / 'run.json', {'run_id': 'run-metadata', 'requested_sessions': total})
    try:
        assert get_run_detail(store, tmp_path / 'traces', 'run-metadata').requested_sessions is None
        find_run_dir(tmp_path / 'traces', 'run-metadata').joinpath('run.json').unlink()
        assert get_run_detail(store, tmp_path / 'traces', 'run-metadata').requested_sessions is None
    finally:
        store.close()
