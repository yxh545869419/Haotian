"""LLM-backed local chat helpers for the Haotian web UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from haotian.config import get_settings
from haotian.db.schema import get_connection, initialize_schema
from haotian.llm.openai_codex import OpenAICodexCapabilityClient


@dataclass(slots=True)
class ChatReply:
    answer: str
    context_summary: str


class ChatService:
    """Answer operator questions using the latest local pipeline context."""

    def __init__(self, llm_client: OpenAICodexCapabilityClient | None = None, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.llm_client = llm_client or self._build_llm_client()

    def ask(self, question: str, attachments: list[dict[str, str]] | None = None) -> ChatReply:
        if not question.strip():
            raise ValueError("Question must not be empty.")
        context = self.build_context()
        if self.llm_client is None:
            raise RuntimeError("OpenAIAPI secret is required for chat replies.")
        normalized_attachments = self._normalize_attachments(attachments or [])
        user_content = question
        if normalized_attachments:
            attachment_summary = "\n".join(
                self._render_attachment_for_prompt(item)
                for item in normalized_attachments
            )
            user_content += f"\n\nAttachments:\n{attachment_summary}"
        self._save_message("user", user_content, normalized_attachments)
        answer = self.llm_client.respond(
            system_prompt=(
                "You are Haotian's local operations assistant. Answer using the provided local pipeline context. "
                "If the answer is uncertain, say so clearly and point to the relevant report or registry facts."
            ),
            user_prompt=user_content,
            context=context,
        )
        self._save_message("assistant", answer, [])
        return ChatReply(answer=answer, context_summary=context.splitlines()[0] if context else "")

    def list_history(self) -> list[dict[str, object]]:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            rows = connection.execute(
                "SELECT id, role, content, attachments_json, created_at FROM chat_messages ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "attachments": json.loads(row["attachments_json"] or "[]"),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def delete_history(self) -> None:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            connection.execute("DELETE FROM chat_messages")
            connection.commit()

    def list_skills(self) -> dict[str, list[dict[str, object]]]:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            registry_rows = connection.execute(
                """
                SELECT capability_id, canonical_name, status, source_repo_full_name
                FROM capability_registry
                ORDER BY capability_id ASC
                """
            ).fetchall()
            repo_rows = connection.execute(
                """
                SELECT capability_id, repo_full_name, MAX(needs_review) AS needs_review
                FROM repo_capabilities
                GROUP BY capability_id, repo_full_name
                ORDER BY capability_id ASC, repo_full_name ASC
                """
            ).fetchall()
        repo_map: dict[str, set[str]] = {}
        manual_map: dict[str, bool] = {}
        for row in repo_rows:
            capability_id = str(row["capability_id"])
            repo_map.setdefault(capability_id, set()).add(str(row["repo_full_name"]))
            manual_map[capability_id] = manual_map.get(capability_id, False) or bool(row["needs_review"])
        registry_map = {
            str(row["capability_id"]): row
            for row in registry_rows
        }
        active_statuses = {"active", "poc", "watchlist"}
        result = {"active": [], "inactive": []}
        for capability_id in sorted(set(registry_map) | set(repo_map)):
            row = registry_map.get(capability_id)
            source_repos = set(repo_map.get(capability_id, set()))
            if row and row["source_repo_full_name"]:
                source_repos.add(str(row["source_repo_full_name"]))
            item = {
                "capability_id": capability_id,
                "canonical_name": str(row["canonical_name"]) if row else self._humanize_capability_id(capability_id),
                "status": str(row["status"]) if row else "pending_review",
                "source_repos": sorted(source_repos),
                "needs_manual_configuration": manual_map.get(capability_id, False) or row is None,
            }
            bucket = "active" if item["status"] in active_statuses else "inactive"
            result[bucket].append(item)
        return result

    def masked_config(self) -> list[dict[str, str]]:
        settings = get_settings()
        items = []
        for key, value in settings.model_dump().items():
            display = str(value)
            if key in {"openai_api_key", "telegram_bot_token"} and value:
                display = self._mask_secret(str(value))
            items.append({"key": key, "value": display})
        return items

    def build_context(self) -> str:
        initialize_schema(self.database_url)
        settings = get_settings()
        latest_report = self._load_latest_report(settings.report_dir)
        latest_snapshot = self._load_latest_snapshot()
        recent_history = self._load_recent_history()
        return "\n\n".join(part for part in [latest_snapshot, latest_report, recent_history] if part).strip()

    def _load_latest_report(self, report_dir: Path) -> str:
        reports = sorted(report_dir.glob("*.md"))
        if not reports:
            return "No generated reports are available yet."
        latest = reports[-1]
        return f"Latest report file: {latest.name}\n{latest.read_text(encoding='utf-8')}"

    def _load_latest_snapshot(self) -> str:
        with get_connection(self.database_url) as connection:
            snapshot_row = connection.execute(
                "SELECT MAX(snapshot_date) AS snapshot_date FROM trending_repos"
            ).fetchone()
            snapshot_date = snapshot_row["snapshot_date"] if snapshot_row else None
            if not snapshot_date:
                return "No trending snapshot data is available yet."
            repos = connection.execute(
                "SELECT DISTINCT repo_full_name FROM trending_repos WHERE snapshot_date = ? ORDER BY repo_full_name ASC",
                (snapshot_date,),
            ).fetchall()
            capabilities = connection.execute(
                "SELECT capability_id, status, last_score FROM capability_registry ORDER BY updated_at DESC, capability_id ASC LIMIT 10"
            ).fetchall()
        repo_list = ", ".join(row["repo_full_name"] for row in repos)
        capability_list = "; ".join(
            f"{row['capability_id']} ({row['status']}, score={float(row['last_score']):.2f})"
            for row in capabilities
        ) or "No capability registry rows yet."
        return (
            f"Latest snapshot date: {snapshot_date}\n"
            f"Repos: {repo_list}\n"
            f"Capability registry summary: {capability_list}"
        )

    def _load_recent_history(self) -> str:
        history = self.list_history()[-10:]
        if not history:
            return "No prior chat history."
        rendered = "\n".join(f"{item['role']}: {item['content']}" for item in history)
        return f"Recent chat history:\n{rendered}"

    def _save_message(self, role: str, content: str, attachments: list[dict[str, str]]) -> None:
        initialize_schema(self.database_url)
        with get_connection(self.database_url) as connection:
            connection.execute(
                "INSERT INTO chat_messages (role, content, attachments_json) VALUES (?, ?, ?)",
                (role, content, json.dumps(attachments, ensure_ascii=False)),
            )
            connection.commit()

    @staticmethod
    def _normalize_attachments(attachments: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "name": str(item.get("name", "attachment")),
                    "type": str(item.get("type", "application/octet-stream")),
                    "size": str(item.get("size", "")),
                    "content": str(item.get("content", ""))[:4000],
                }
            )
        return normalized

    @staticmethod
    def _render_attachment_for_prompt(item: dict[str, str]) -> str:
        details = [f"{item.get('name', 'attachment')} ({item.get('type', 'unknown')})"]
        if item.get("size"):
            details.append(f"size={item['size']}")
        if item.get("content"):
            details.append(f"preview={item['content']}")
        return "- " + ", ".join(details)

    @staticmethod
    def _humanize_capability_id(capability_id: str) -> str:
        return capability_id.replace("_", " ").replace("-", " ").title()

    @staticmethod
    def _mask_secret(value: str) -> str:
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:3]}***{value[-3:]}"

    @staticmethod
    def _build_llm_client() -> OpenAICodexCapabilityClient | None:
        settings = get_settings()
        if settings.llm_provider != "openai" or not settings.openai_api_key:
            return None
        return OpenAICodexCapabilityClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
