"""Memory merge cannot import the private case or planned assignments."""
import asyncio

from psychsandbox.domain import ClinicalSummary, ExtractedClientInfo, SessionMemory, UnlockedClientInfo
from psychsandbox.runtime.memory import MemoryConsolidator
from psychsandbox.runtime.memory_pipeline import ClientMergeAgent, _prevent_global_backfill
from tests.deterministic_gateway import DeterministicGateway
from tests.test_session_controls import record


def test_theory_key_does_not_authorize_private_case_details():
    history = UnlockedClientInfo(client_id="client")
    current = ExtractedClientInfo(theory={"cbt": {"core_beliefs": ["我可能做不好"]}})
    merged = UnlockedClientInfo(client_id="client", theory={"cbt": {
        "core_beliefs": ["我可能做不好"],
        "special_situations": [{"event": "父亲赌博，父母重男轻女"}],
    }})
    result = _prevent_global_backfill(merged, history, current)
    assert "父亲赌博" not in str(result.theory)
    assert result.theory["cbt"]["core_beliefs"] == ["我可能做不好"]


def test_merge_request_contains_no_private_profile(sample_case):
    class RecordingGateway(DeterministicGateway):
        async def complete_structured(self, **kwargs):
            self.payload = kwargs["input_payload"]
            return await super().complete_structured(**kwargs)

    gateway = RecordingGateway()
    asyncio.run(ClientMergeAgent(gateway).merge(
        UnlockedClientInfo(client_id=sample_case.profile.client_id),
        ExtractedClientInfo(), ["cbt"],
    ))
    assert "global_profile" not in gateway.payload
    assert sample_case.profile.main_problem not in str(gateway.payload)


def test_unassigned_homework_cannot_enter_recap_or_open_ledger():
    session = record()
    session.clinical_summary = ClinicalSummary(session_index=1, homework=["记录一次情绪"])
    memory = SessionMemory(case_id="case", known_background=UnlockedClientInfo(client_id="client"))
    result = MemoryConsolidator().consolidate(memory, session, next_index=2)
    assert result.last_homework == []
    assert result.session_recaps[0].homework == []


def test_extraction_keeps_only_client_grounded_leaves_and_marks_hypotheses():
    from psychsandbox.domain import Message
    from psychsandbox.runtime.memory_pipeline import MemoryExtractionAgent

    class ExtractionGateway(DeterministicGateway):
        async def complete_structured(self, **kwargs):
            schema = kwargs["output_schema"]
            return schema.model_validate({"client_info_get": {
                "static_traits": {"name": "小周", "age": "19"},
                "theory": {"cbt": {"core_beliefs": ["担心自己无能"], "event": "父亲赌博"}},
                "field_evidence": [
                    {"field_path": "static_traits.name", "value": "小周", "source_session": 99,
                     "evidence": {"turn_index": 1, "role": "client", "quote": "叫我小周"}},
                    {"field_path": "static_traits.age", "value": "19",
                     "evidence": {"turn_index": 1, "role": "counselor", "quote": "你19岁吗"}},
                    {"field_path": "theory.cbt.core_beliefs", "value": "担心自己无能", "kind": "hypothesis",
                     "evidence": {"turn_index": 1, "role": "client", "quote": "我怕自己做不好"}},
                ],
            }})

    dialogue = [
        Message(session_index=2, turn_index=1, role="counselor", content="你19岁吗？"),
        Message(session_index=2, turn_index=1, role="client", content="叫我小周。我怕自己做不好。"),
    ]
    result = asyncio.run(MemoryExtractionAgent(ExtractionGateway()).extract(dialogue, ["cbt"], 2))
    assert result.static_traits.name == "小周"
    assert result.static_traits.age == ""
    assert result.theory == {"cbt": {"core_beliefs": ["担心自己无能"]}}
    assert all(item.source_session == 2 for item in result.field_evidence)
    assert result.field_evidence[-1].kind == "hypothesis"


def test_homework_proposal_and_agreement_have_distinct_evidence():
    from psychsandbox.domain import DialogueEvidence, HomeworkAssignment, Message
    session = record()
    session.messages = [
        Message(session_index=1, turn_index=1, role="counselor", content="这周试着记录一次情绪，愿意吗？"),
        Message(session_index=1, turn_index=1, role="client", content="这个记录任务我愿意试试。"),
    ]
    session.clinical_summary = ClinicalSummary(session_index=1, homework_assignments=[HomeworkAssignment(
        text="记录一次情绪",
        proposed_evidence=DialogueEvidence(turn_index=1, role="counselor", quote="这周试着记录一次情绪"),
        agreed_evidence=DialogueEvidence(turn_index=1, role="client", quote="这个记录任务我愿意试试"),
    )])
    memory = SessionMemory(case_id="case", known_background=UnlockedClientInfo(client_id="client"))
    result = MemoryConsolidator().consolidate(memory, session, next_index=2)
    assert result.last_homework[0].agreement_status == "agreed"
    assert result.last_homework[0].proposed_evidence.turn_index == 1
    session.clinical_summary.homework_assignments[0].agreed_evidence.quote = "我已经做完了"
    result = MemoryConsolidator().consolidate(memory, session, next_index=2)
    assert result.last_homework[0].agreement_status == "proposed"


def test_legacy_memory_is_readable_but_not_given_invented_provenance():
    from psychsandbox.runtime.memory_view import MemoryViewBuilder
    memory = SessionMemory(case_id="case", known_background=UnlockedClientInfo(
        client_id="client", theory={"cbt": {"event": "父亲赌博"}},
    ))
    original = memory.model_dump(mode="json")
    view = MemoryViewBuilder().build(memory)
    assert view["known_background"]["unverified_fields"] == ["theory.cbt.event"]
    assert memory.model_dump(mode="json") == original
