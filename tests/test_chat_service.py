from __future__ import annotations

from pathlib import Path

from haotian.collectors.github_trending import TrendingRepo
from haotian.db.schema import get_connection, initialize_schema
from haotian.services.chat_service import ChatService
from haotian.services.orchestration_service import OrchestrationService


class StubCollector:
    def fetch_trending(self, period: str) -> list[TrendingRepo]:
        return [
            TrendingRepo(
                snapshot_date="2026-03-21",
                period=period,
                rank=1,
                repo_full_name=f"acme/{period}-agent",
                repo_url=f"https://github.com/acme/{period}-agent",
                description="Browser automation agent",
                language="Python",
                stars=42,
                forks=5,
            )
        ]


class StubLLMClient:
    def respond(self, *, system_prompt: str, user_prompt: str, context: str = "") -> str:
        assert "Latest snapshot date" in context
        assert "Latest report file" in context
        return f"Answering: {user_prompt}"


class EchoLLMClient:
    def respond(self, *, system_prompt: str, user_prompt: str, context: str = "") -> str:
        return f"Answering: {user_prompt}"


def test_chat_service_uses_latest_report_and_snapshot_context(tmp_path, monkeypatch) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPORT_DIR", str(report_dir))
    from haotian.config import get_settings
    get_settings.cache_clear()

    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    OrchestrationService(collector=StubCollector(), database_url=database_url).run_daily_pipeline()
    reply = ChatService(llm_client=StubLLMClient(), database_url=database_url).ask("今天有哪些 repo？")

    assert reply.answer == "Answering: 今天有哪些 repo？"
    assert "Latest snapshot date" in reply.context_summary


def test_chat_service_includes_attachment_preview_and_lists_pending_skills(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    initialize_schema(database_url)
    with get_connection(database_url) as connection:
        connection.execute(
            """
            INSERT INTO repo_capabilities (
                snapshot_date, period, repo_full_name, capability_id, confidence, reason, summary, needs_review
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-03-21", "daily", "acme/vision-agent", "vision_agent", 0.88, "repo summary", "vision", 1),
        )
        connection.commit()

    reply = ChatService(llm_client=EchoLLMClient(), database_url=database_url).ask(
        "请分析这个附件",
        attachments=[
            {
                "name": "notes.txt",
                "type": "text/plain",
                "size": "12",
                "content": "hello world",
            }
        ],
    )

    assert "notes.txt (text/plain), size=12, preview=hello world" in reply.answer

    skills = ChatService(llm_client=EchoLLMClient(), database_url=database_url).list_skills()
    assert skills["inactive"] == [
        {
            "capability_id": "vision_agent",
            "canonical_name": "Vision Agent",
            "status": "pending_review",
            "source_repos": ["acme/vision-agent"],
            "needs_manual_configuration": True,
        }
    ]
