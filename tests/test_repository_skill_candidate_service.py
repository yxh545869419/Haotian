from __future__ import annotations

from haotian.services.repository_skill_candidate_service import RepositorySkillCandidateService


def test_extract_candidates_builds_stable_candidate_ids() -> None:
    service = RepositorySkillCandidateService()

    items = [
        {
            "repo_full_name": "shareAI-lab/learn-claude-code",
            "repo_url": "https://github.com/shareAI-lab/learn-claude-code",
            "description": "Learn Claude Code skills.",
            "matched_keywords": ["SKILL.md", "scripts/**"],
            "architecture_signals": ["codex-skill-package"],
            "discovered_skill_packages": [
                {
                    "skill_name": "agent-builder",
                    "relative_root": "skills/agent-builder",
                    "files": ["SKILL.md", "references/agent-philosophy.md", "scripts/init_agent.py"],
                }
            ],
        }
    ]

    first = service.extract(items)
    second = service.extract(items)

    assert len(first) == 1
    assert first[0].candidate_id == second[0].candidate_id
    assert first[0].slug == "agent-builder"
    assert first[0].relative_root == "skills/agent-builder"


def test_extract_candidates_prefers_skill_description_over_repo_description() -> None:
    service = RepositorySkillCandidateService()

    items = [
        {
            "repo_full_name": "Yeachan-Heo/oh-my-codex",
            "repo_url": "https://github.com/Yeachan-Heo/oh-my-codex",
            "description": "OmX - Oh My codeX: Your codex is not alone.",
            "discovered_skill_packages": [
                {
                    "skill_name": "ask-claude",
                    "relative_root": "skills/ask-claude",
                    "files": ["SKILL.md"],
                    "description": "Ask Claude via local CLI and capture a reusable artifact.",
                }
            ],
        }
    ]

    candidates = service.extract(items)

    assert candidates[0].description == "Ask Claude via local CLI and capture a reusable artifact."


def test_extract_candidates_skips_items_without_discovered_skill_packages() -> None:
    service = RepositorySkillCandidateService()

    items = [
        {
            "repo_full_name": "acme/browser-bot",
            "repo_url": "https://github.com/acme/browser-bot",
            "description": "Browser bot.",
            "discovered_skill_packages": [],
        }
    ]

    assert service.extract(items) == []
