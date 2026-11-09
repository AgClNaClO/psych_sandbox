"""Independent experiments must never mutate production state or releases."""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from psychsandbox.artifacts import exclusive_run_dir
from psychsandbox.domain import SandboxConfig
from psychsandbox.runtime import CounselingSandbox
from psychsandbox.skills import SkillRegistry
from psychsandbox.workbench.skill_experiment import (
    BranchChoice, CreateExperiment, ExperimentStore, JobRequest, ManagementDecision,
    Quote, SkillDraft, digest, execute_job, experiment_registry, extract_candidate,
    align_evidence, fixed_context, import_source, independent_simulation, readonly, source_sessions,
)
from psychsandbox.workbench.skill_experiment_api import experiment_router
from tests.deterministic_gateway import DeterministicGateway


@pytest.fixture
def experiment_env(root, tmp_path, repository):
    config = SandboxConfig(project_root=root, max_turns_per_session=2,
                           database_path=tmp_path / 'production.sqlite3', trace_dir=tmp_path / 'traces',
                           rft={'enabled': False}, logprob_scoring={'enabled': False})
    sandbox = CounselingSandbox(config, gateway=DeterministicGateway(), repository=repository)
    result = asyncio.run(sandbox.run_case('psycheval-cbt-001', session_count=1))
    source = import_source(config.database_path, CreateExperiment(run_id=result.run_id, session_index=1))
    registry = SkillRegistry.from_project(root)
    store = ExperimentStore(tmp_path / 'experiments')
    doc = store.create(source, registry)
    yield config, sandbox, result, store, doc, registry
    sandbox.store.close()


class EvolutionGateway(DeterministicGateway):
    def __init__(self, source, action='append', invalid_quote=False):
        self.source = source
        self.action = action
        self.invalid_quote = invalid_quote
        self.payloads = []

    async def complete_structured(self, **kwargs):
        schema, payload = kwargs['output_schema'], kwargs['input_payload']
        self.payloads.append(copy.deepcopy(payload))
        index, message = next((i, m) for i, m in enumerate(self.source['messages']) if m['role'] == 'client')
        quote = Quote(message_index=index, text='伪造的证据' if self.invalid_quote else message['content'][:20])
        if schema is BranchChoice:
            return BranchChoice(meta_skill_id=payload['branches'][0]['meta_skill_id'], reason='依据公开困扰选择对应分支', evidence=quote)
        if schema is SkillDraft:
            return SkillDraft(name='逐步澄清体验', description='先复述已表达的感受，再邀请来访者选择一个具体场景分步讨论。',
                              when_to_use='来访者表达困扰并愿意讨论具体场景时', triggers=['表达困扰'], evidence=[quote])
        if schema is ManagementDecision:
            ref = payload['similar'][0]['skill']
            draft = SkillDraft.model_validate(payload['draft'])
            draft.contraindications = ref['contraindications']
            return ManagementDecision(action=self.action, reason='测试模型根据当前分支比较内容后作出决策',
                                      reference_skill_id=ref['skill_id'] if self.action == 'merge' else None,
                                      merged_skill=draft if self.action == 'merge' else None)
        return await super().complete_structured(**kwargs)


def test_readonly_source_excludes_private_state_and_preserves_database(experiment_env):
    config, sandbox, result, store, doc, registry = experiment_env
    before = config.database_path.read_bytes()
    source = import_source(config.database_path, CreateExperiment(run_id=result.run_id, session_index=1))
    assert source['memory_recorded']
    assert 'initial_state' not in source and 'final_state' not in source
    assert 'profile' not in source and 'client_generation' not in json.dumps(source)
    assert source['memory']['known_background']['facts'] == []
    assert source_sessions(config.database_path)[0]['source_kind'] == 'exploratory'
    with readonly(config.database_path) as conn:
        with pytest.raises(Exception, match='readonly'):
            conn.execute('DELETE FROM sessions')
    assert config.database_path.read_bytes() == before
    assert doc['baseline_hash'] == digest({'skills': doc['versions'][0]['skills'], 'meta': doc['meta_skills']})
    assert sandbox.store.load_sessions(result.run_id)[0].messages


@pytest.mark.parametrize('action', ['append', 'merge', 'skip'])
def test_evolution_snapshots_do_not_modify_base_or_formal_registry(experiment_env, action):
    config, sandbox, result, store, doc, registry = experiment_env
    original = copy.deepcopy(doc['versions'][0])
    original_registry = {k: v.model_dump(mode='json') for k, v in registry.atomic_skills.items()}
    gateway = EvolutionGateway(doc['source'], action)
    candidate = asyncio.run(extract_candidate(doc, 0, gateway, lambda _: None))
    assert candidate['action'] == action
    with store.document(doc['id']) as current:
        current['candidates'].append(candidate)
    if action == 'skip':
        with pytest.raises(ValueError):
            store.apply(doc['id'], candidate['id'])
        assert len(store.read(doc['id'])['versions']) == 1
    else:
        saved = store.apply(doc['id'], candidate['id'])
        assert saved['versions'][0] == original
        assert saved['current_version'] == 1
        skill = saved['versions'][1]['skills'][candidate['after']['skill_id']]
        assert skill['status'] == 'candidate'
        assert skill['source'] == 'experimental-unreviewed'
        assert len(saved['versions'][1]['skills']) == len(original['skills']) + (action == 'append')
        assert experiment_registry(saved, 1).atomic_skills[skill['skill_id']].status == 'approved'
        store.select(doc['id'], 0)
        assert store.read(doc['id'])['current_version'] == 0
        with pytest.raises(ValueError, match='已保存'):
            store.apply(doc['id'], candidate['id'])
    assert {k: v.model_dump(mode='json') for k, v in registry.atomic_skills.items()} == original_registry
    assert len(sandbox.store.load_sessions(result.run_id)) == 1
    assert not list(store.directory(doc['id']).glob('*workbench*'))


def test_fabricated_evidence_and_incomplete_embeddings_fail(experiment_env):
    *_, store, doc, registry = experiment_env
    with pytest.raises(ValueError, match='逐字'):
        asyncio.run(extract_candidate(doc, 0, EvolutionGateway(doc['source'], invalid_quote=True), lambda _: None))

    class MissingEmbedding(EvolutionGateway):
        async def embed_texts(self, texts):
            return [[1.0]]

    with pytest.raises(ValueError, match='数量不完整'):
        asyncio.run(extract_candidate(doc, 0, MissingEmbedding(doc['source']), lambda _: None))


def test_failed_jobs_and_interruption_never_create_versions(experiment_env, root):
    config, sandbox, result, store, doc, registry = experiment_env
    job = store.enqueue(doc['id'], JobRequest(kind='extract', version=0))
    asyncio.run(execute_job(store, doc['id'], job['id'], root,
                            gateway=EvolutionGateway(doc['source'], invalid_quote=True)))
    saved = store.read(doc['id'])
    assert saved['jobs'][0]['status'] == 'failed'
    assert '元技能选择失败' in saved['jobs'][0]['error']
    assert '逐字' in saved['jobs'][0]['error']
    diagnostics = list((store.directory(doc['id']) / job['id'] / 'diagnostics').glob('extraction-*.json'))
    assert len(diagnostics) == 2
    if os.name == 'nt':
        diagnostics = [Path('\\\\?\\' + str(p.resolve())) for p in diagnostics]
    assert all(json.loads(p.read_text(encoding='utf-8'))['status'] == 'rejected' for p in diagnostics)
    assert saved['candidates'] == [] and len(saved['versions']) == 1
    retry = store.enqueue(doc['id'], JobRequest(kind='extract', version=0))
    with store.document(doc['id']) as current:
        current['jobs'][-1].update(status='running', created_at='2020-01-01T00:00:00+00:00')
    job_dir = store.directory(doc['id']) / retry['id']
    job_dir.mkdir()
    with exclusive_run_dir(job_dir):
        assert store.recover(doc['id'])['jobs'][-1]['status'] == 'running'
    assert store.recover(doc['id'])['jobs'][-1]['status'] == 'failed'
    assert len(store.read(doc['id'])['versions']) == 1


def test_fixed_context_uses_identical_input_and_normal_skill_selection(experiment_env):
    config, sandbox, result, store, doc, registry = experiment_env

    class CaptureGateway(DeterministicGateway):
        def __init__(self):
            self.contexts = []

        async def complete_structured(self, **kwargs):
            if kwargs['output_schema'].__name__ == 'CounselorPlanning':
                self.contexts.append(copy.deepcopy(kwargs['input_payload']))
            return await super().complete_structured(**kwargs)

    gateway = CaptureGateway()
    count = next(i + 1 for i, m in enumerate(doc['source']['messages']) if m['role'] == 'client')
    replay = asyncio.run(fixed_context(doc, JobRequest(kind='replay', version=0, message_count=count), gateway, config, lambda _: None))
    assert replay['type'] == 'fixed_context'
    assert replay['outputs']['baseline']['response']
    assert replay['outputs']['experimental']['observation'] is not None
    assert gateway.contexts[0] == gateway.contexts[1]
    with pytest.raises(ValueError, match='截止到来访者'):
        asyncio.run(fixed_context(doc, JobRequest(kind='replay', version=0, message_count=1), gateway, config, lambda _: None))


def test_independent_simulation_has_separate_databases_and_no_production_writes(experiment_env, tmp_path, repository, monkeypatch):
    config, sandbox, result, store, doc, registry = experiment_env
    original_init = CounselingSandbox.__init__

    def isolated_init(self, settings, **kwargs):
        original_init(self, settings, repository=repository, **kwargs)

    monkeypatch.setattr(CounselingSandbox, '__init__', isolated_init)
    directory = tmp_path / 'pair'
    directory.mkdir()
    outputs = asyncio.run(independent_simulation(doc, JobRequest(kind='simulation', version=0, max_turns=2),
                                                DeterministicGateway(), config, directory, lambda _: None))
    for label in ('baseline', 'experimental'):
        assert (directory / label / 'simulation.sqlite3').exists()
        assert outputs['outputs'][label]['holistic_report'] is not None
    assert outputs['outputs']['baseline']['run_id'] != outputs['outputs']['experimental']['run_id']
    assert len(sandbox.store.load_sessions(result.run_id)) == 1
    assert sandbox.store.connection.execute('SELECT COUNT(*) FROM experiment_runs').fetchone()[0] == 1


def test_api_disabled_by_default_and_namespace_isolated(experiment_env, tmp_path, root, monkeypatch):
    config, sandbox, result, store, doc, registry = experiment_env
    base = tmp_path / 'api_experiments'
    app = FastAPI()
    app.include_router(experiment_router(root, base, config.database_path, root / 'assets/skills/sect'))
    monkeypatch.delenv('PSYCHSANDBOX_SKILL_EXPERIMENT', raising=False)
    with TestClient(app) as client:
        assert not client.get('/api/skill-experiments/status').json()['enabled']
        assert client.get('/api/skill-experiments').status_code == 403
        assert not base.exists()
        monkeypatch.setenv('PSYCHSANDBOX_SKILL_EXPERIMENT', '1')
        sources = client.get('/api/skill-experiments/sources').json()
        created = client.post('/api/skill-experiments', json={'run_id': sources[0]['run_id'], 'session_index': 1}).json()
        assert created['current_version'] == 0
        assert client.get(f"/api/skill-experiments/{created['id']}").status_code == 200
        assert client.post(f"/api/skill-experiments/{created['id']}/versions/99/select", json={}).status_code == 400
        assert client.get('/api/skill-experiments/not-a-run').status_code == 400
        assert not (base / 'psychsandbox.sqlite3').exists()


@pytest.mark.parametrize('wrong_index', [0, 2, 99])
def test_evidence_reanchors_only_unique_exact_client_quote(wrong_index):
    source = {'messages': [
        {'role': 'counselor', 'content': '可以说说最近的体验吗？'},
        {'role': 'client', 'content': '最近一想到找工作我就有点紧张。'},
        {'role': 'counselor', 'content': '听起来这件事令你紧张。'},
    ]}
    raw = Quote(message_index=wrong_index, text='一想到找工作我就有点紧张')
    quotes, corrections = align_evidence([raw], source)
    assert quotes[0].message_index == 1
    assert quotes[0].text == raw.text
    assert raw.message_index == wrong_index
    assert corrections == [{'from_message_index': wrong_index, 'to_message_index': 1,
                             'reason': 'unique_exact_client_quote'}]


@pytest.mark.parametrize('text', ['最近找工作非常焦虑', '可以说说最近的体验吗？'])
def test_evidence_does_not_accept_paraphrase_or_counselor_quote(text):
    source = {'messages': [
        {'role': 'counselor', 'content': '可以说说最近的体验吗？'},
        {'role': 'client', 'content': '最近一想到找工作我就有点紧张。'},
    ]}
    with pytest.raises(ValueError, match='逐字'):
        align_evidence([Quote(message_index=1, text=text)], source)


def test_repeated_quote_requires_valid_source_index():
    source = {'messages': [{'role': 'counselor', 'content': '我很担心'},
                           {'role': 'client', 'content': '我很担心'},
                           {'role': 'client', 'content': '我很担心'}]}
    with pytest.raises(ValueError, match='多条'):
        align_evidence([Quote(message_index=0, text='我很担心')], source)
    quotes, corrections = align_evidence([Quote(message_index=2, text='我很担心')], source)
    assert quotes[0].message_index == 2 and corrections == []


def test_extraction_repairs_one_semantic_failure_with_explicit_message_indices(experiment_env):
    config, sandbox, result, store, doc, registry = experiment_env

    class RepairGateway(EvolutionGateway):
        calls = 0

        async def complete_structured(self, **kwargs):
            output = await super().complete_structured(**kwargs)
            if kwargs['output_schema'] is BranchChoice:
                self.calls += 1
                if self.calls == 1:
                    output.evidence.text = '与原话不符的概述'
            if kwargs['output_schema'] is SkillDraft:
                output.evidence[0].message_index = 999
            return output

    gateway = RepairGateway(doc['source'])
    diagnostics, progress = [], []
    candidate = asyncio.run(extract_candidate(doc, 0, gateway, progress.append, diagnostics.append))
    assert gateway.calls == 2
    assert candidate['action'] == 'append'
    assert any('一次纠错' in text for text in progress)
    assert any('校正证据消息编号' in text for text in progress)
    assert diagnostics[0]['status'] == 'rejected'
    assert diagnostics[1]['status'] == 'accepted'
    assert candidate['evidence_corrections'][0]['from_message_index'] == 999
    assert all(m['message_index'] == i and 'turn_index' not in m
               for i, m in enumerate(gateway.payloads[0]['messages']))
    assert gateway.payloads[1]['validation_feedback']
    for quote in candidate['evidence']:
        message = doc['source']['messages'][quote['message_index']]
        assert message['role'] == 'client' and quote['text'] in message['content']


def test_semantic_correction_is_bounded_and_audited(experiment_env):
    *_, store, doc, registry = experiment_env
    gateway = EvolutionGateway(doc['source'], invalid_quote=True)
    diagnostics = []
    with pytest.raises(ValueError, match='一次纠错后仍未通过'):
        asyncio.run(extract_candidate(doc, 0, gateway, lambda _: None, diagnostics.append))
    assert len(gateway.payloads) == 2
    assert len(diagnostics) == 2
    assert diagnostics[-1]['stage'] == '元技能选择'
