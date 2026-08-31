from __future__ import annotations

import asyncio

import pytest

from psychsandbox.datasets.atomizer import ExtractiveAtomizer
from psychsandbox.datasets.profile_compiler import AtomicSpan, stable_evidence_id
from psychsandbox.datasets.psycheval import (
    PsychEvalAdapter,
    convert_psycheval_extractive,
)
from psychsandbox.domain import ClientState, TrustTier
from psychsandbox.model_client import ModelGateway


class AtomizerGateway(ModelGateway):
    provider_name = "atomizer-test"

    def __init__(self, *, invalid: bool = False, wrong_offsets: bool = False):
        self.invalid = invalid
        self.wrong_offsets = wrong_offsets
        self.calls = 0
        self.models = {"profile": "test-profile-model"}

    async def complete_structured(self, **kwargs):
        self.calls += 1
        schema = kwargs["output_schema"]
        if self.invalid:
            return schema.model_validate(
                {
                    "spans": [{
                        "start": 0,
                        "end": 5,
                        "text": "模型编造。",
                        "activation_tags": ["模型"],
                        "trust_tier": "sensitive",
                    }]
                }
            )
        if self.wrong_offsets:
            return schema.model_validate(
                {
                    "spans": [
                        {
                            "start": 1,
                            "end": 6,
                            "text": "家庭支持。",
                            "activation_tags": ["家庭"],
                            "trust_tier": "moderate",
                        },
                        {
                            "start": 7,
                            "end": 12,
                            "text": "实习失败。",
                            "activation_tags": ["实习"],
                            "trust_tier": "sensitive",
                        },
                    ]
                }
            )
        return schema.model_validate(
            {
                "spans": [
                    {
                        "start": 0,
                        "end": 5,
                        "text": "家庭支持。",
                        "activation_tags": ["家庭"],
                        "trust_tier": "moderate",
                    },
                    {
                        "start": 5,
                        "end": 10,
                        "text": "实习失败。",
                        "activation_tags": ["实习"],
                        "trust_tier": "sensitive",
                    },
                ]
            }
        )


def test_extractive_atomizer_accepts_only_exact_spans_and_caches(tmp_path):
    gateway = AtomizerGateway()
    atomizer = ExtractiveAtomizer(gateway, tmp_path)
    first, first_audit = asyncio.run(
        atomizer.atomize(
            source_path="client_info.growth_experiences[0]",
            source_text="家庭支持。实习失败。",
        )
    )
    second, second_audit = asyncio.run(
        atomizer.atomize(
            source_path="client_info.growth_experiences[0]",
            source_text="家庭支持。实习失败。",
        )
    )

    assert [item.text for item in first] == ["家庭支持。", "实习失败。"]
    assert first[1].trust_tier is TrustTier.SENSITIVE
    assert first_audit.fallback is False
    assert second == first
    assert second_audit.cache_hit is True
    assert gateway.calls == 1


def test_extractive_atomizer_falls_back_on_hallucinated_span(tmp_path):
    spans, audit = asyncio.run(
        ExtractiveAtomizer(AtomizerGateway(invalid=True), tmp_path).atomize(
            source_path="client_info.growth_experiences[0]",
            source_text="家庭支持。实习失败。",
        )
    )

    assert [item.text for item in spans] == ["家庭支持。实习失败。"]
    assert audit.fallback is True
    assert audit.validation_failed is True
    assert audit.needs_review is True
    assert spans[0].needs_review is True


def test_extractive_atomizer_locates_exact_text_instead_of_trusting_model_offsets(
    tmp_path,
):
    spans, audit = asyncio.run(
        ExtractiveAtomizer(
            AtomizerGateway(wrong_offsets=True), tmp_path
        ).atomize(
            source_path="client_info.growth_experiences[0]",
            source_text="家庭支持。实习失败。",
        )
    )

    assert [(item.start, item.end, item.text) for item in spans] == [
        (0, 5, "家庭支持。"),
        (5, 10, "实习失败。"),
    ]
    assert audit.fallback is False


def test_pilot_failure_reports_the_underlying_atomizer_reason(root, tmp_path):
    with pytest.raises(RuntimeError, match=r"43/43.*reasons:.*exact source span"):
        asyncio.run(
            convert_psycheval_extractive(
                root,
                tmp_path / "output",
                therapy="bt",
                gateway=AtomizerGateway(invalid=True),
                cache_dir=tmp_path / "cache",
            )
        )


def test_three_free_text_fields_are_separated_without_counselor_leakage():
    language = "说话简短。提到父亲时会停顿。"
    language_split = language.index("提到")
    demands = "希望更能表达自己；咨询师应使用认知重构"
    demand_split = demands.index("咨询师")
    growth = "小时候经常被批评。现在会反复检查。"
    growth_split = growth.index("现在")
    raw = {
        "client_id": 999,
        "client_info": {
            "static_traits": {"name": "测试者", "language_features": language},
            "main_problem": "反复担心出错",
            "topic": "个人成长",
            "core_demands": demands,
            "growth_experiences": [growth],
            "special_situations": [],
        },
        "sessions": [],
    }
    spans = {
        "client_info.static_traits.language_features": [
            AtomicSpan(0, language_split, language[:language_split], "verbal_style"),
            AtomicSpan(language_split, len(language), language[language_split:], "conditional_observation"),
        ],
        "client_info.core_demands": [
            AtomicSpan(0, demand_split, demands[:demand_split], "client_goal", trust_tier=TrustTier.ROUTINE),
            AtomicSpan(demand_split, len(demands), demands[demand_split:], "treatment_instruction"),
        ],
        "client_info.growth_experiences[0]": [
            AtomicSpan(0, growth_split, growth[:growth_split], "event", five_ps_roles=("predisposing",)),
            AtomicSpan(growth_split, len(growth), growth[growth_split:], "coping", five_ps_roles=("perpetuating",)),
        ],
    }

    profile = PsychEvalAdapter().convert_case(raw, free_text_spans=spans).profile

    assert profile.static_traits.language_features == language
    assert [item.text for item in profile.expression_style.verbal_style] == [language[:language_split]]
    assert language[language_split:] not in str(profile.expression_style.model_dump())
    demand_items = [item.content for item in profile.disclosure_items if item.category == "client_goal"]
    assert demand_items == [demands[:demand_split]]
    assert demands[demand_split:] not in demand_items
    assert profile.formulation_5ps.coverage["predisposing"].status.value == "supported"
    assert profile.formulation_5ps.coverage["perpetuating"].status.value == "supported"
    evidence_ids = {item.evidence_id for item in profile.evidence_nodes}
    assert all(
        set(item.source_ids).issubset(evidence_ids)
        for section in (
            profile.formulation_5ps.predisposing_factors,
            profile.formulation_5ps.perpetuating_factors,
        )
        for item in section
    )


def test_evidence_ids_are_stable_by_source_path_and_span():
    first = stable_evidence_id("case", "client_info.growth[0]", 0, 4)
    assert first == stable_evidence_id("case", "client_info.growth[0]", 0, 4)
    assert first != stable_evidence_id("case", "client_info.growth[0]", 4, 8)


def test_legacy_topic_readiness_is_discarded_from_new_state_output():
    state = ClientState.model_validate(
        {"trust": 0.4, "topic_readiness": {"work": 0.8}}
    )
    assert "topic_readiness" not in state.model_dump(mode="json")


def test_five_therapy_profiles_have_auditable_new_contract(repository):
    for therapy in ("bt", "cbt", "het", "pdt", "pmt"):
        profile = repository.get(f"psycheval-{therapy}-001").profile
        evidence_ids = {item.evidence_id for item in profile.evidence_nodes}
        assert evidence_ids
        assert profile.disclosure_items
        assert all(
            set(item.evidence_ids).issubset(evidence_ids)
            for item in profile.disclosure_items
        )
        dumped = profile.model_dump(mode="json")
        assert "hidden_facts" not in dumped
        assert "personality" not in dumped
        assert "relational" not in dumped


def test_only_pdt_builds_complete_ccrt_by_default(repository):
    pdt = repository.get("psycheval-pdt-001").profile.interaction_prior
    assert pdt.therapist_pattern is not None
    assert pdt.therapist_pattern.source_ids
    for therapy in ("bt", "cbt", "het", "pmt"):
        prior = repository.get(f"psycheval-{therapy}-001").profile.interaction_prior
        assert prior.therapist_pattern is None
