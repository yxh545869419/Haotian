from __future__ import annotations

from haotian.analyzers.capability_classifier import CapabilityClassifier, RepoMetadata
from haotian.llm.openai_codex import LLMNormalizedCapability


class StubLLMClient:
    def normalize_capabilities(self, metadata: RepoMetadata, prompt: str) -> list[LLMNormalizedCapability]:
        assert metadata.repo_full_name == "openai/codex"
        assert prompt
        return [
            LLMNormalizedCapability(
                capability_id="code_generation",
                confidence=0.94,
                reason="README and description indicate a coding agent.",
                summary="Generates and edits source code.",
                needs_review=False,
            ),
            LLMNormalizedCapability(
                capability_id="autonomous_browser_testing",
                confidence=0.73,
                reason="The repo also automates browser tasks.",
                summary="Autonomous browser testing: Automates browser workflows.",
                needs_review=False,
            ),
        ]


class FailingLLMClient:
    def normalize_capabilities(self, metadata: RepoMetadata, prompt: str) -> list[LLMNormalizedCapability]:
        raise RuntimeError("llm unavailable")


def test_classifier_prefers_llm_led_normalization_when_available() -> None:
    classifier = CapabilityClassifier(llm_client=StubLLMClient())

    result = classifier.classify(
        RepoMetadata(
            repo_full_name="openai/codex",
            description="AI coding agent",
        )
    )

    assert [capability.capability_id for capability in result.capabilities] == [
        "code_generation",
        "autonomous_browser_testing",
    ]
    assert result.capabilities[0].reason == "README and description indicate a coding agent."
    assert result.capabilities[0].source_label == "llm"
    assert result.llm_status == "LLM enabled."
    assert result.capabilities[1].name == "Autonomous browser testing"
    assert result.capabilities[1].summary == "Autonomous browser testing: Automates browser workflows."


def test_classifier_falls_back_to_local_normalizer_when_llm_fails() -> None:
    classifier = CapabilityClassifier(llm_client=FailingLLMClient())

    result = classifier.classify(
        RepoMetadata(
            repo_full_name="openai/codex",
            description="Browser automation platform",
            tags=["AI coding agent"],
        )
    )

    assert {capability.capability_id for capability in result.capabilities} >= {
        "browser_automation",
        "code_generation",
    }
    assert result.llm_status == "LLM unavailable: llm unavailable"


def test_classifier_splits_readme_into_multiple_capability_candidates() -> None:
    classifier = CapabilityClassifier(llm_client=FailingLLMClient())

    result = classifier.classify(
        RepoMetadata(
            repo_full_name="obra/superpowers",
            description="Agentic skills framework.",
            readme="""
            ## Features
            Browser automation workflows for websites.
            Code generation and patching for local repos.
            Workflow orchestration for multi-step agents.
            """,
        )
    )

    assert {capability.capability_id for capability in result.capabilities} >= {
        "browser_automation",
        "code_generation",
        "workflow_orchestration",
    }
