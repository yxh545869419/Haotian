from __future__ import annotations

import json
from io import BytesIO

from haotian.services.chat_service import ChatReply
from haotian.webapp.server import HaotianWebServer


class StubChatService:
    def __init__(self) -> None:
        self.last_question = ""
        self.last_attachments = []

    def ask(self, question: str, attachments: list[dict[str, str]] | None = None) -> ChatReply:
        self.last_question = question
        self.last_attachments = attachments or []
        return ChatReply(answer=f"reply:{question}", context_summary="summary")

    def list_history(self) -> list[dict[str, object]]:
        return []

    def list_skills(self) -> dict[str, list[dict[str, object]]]:
        return {"active": [], "inactive": []}

    def masked_config(self) -> list[dict[str, str]]:
        return [{"key": "openai_api_key", "value": "abc***xyz"}]

    def delete_history(self) -> None:
        return


def test_web_server_serves_html_and_chat_api() -> None:
    stub = StubChatService()
    server = HaotianWebServer(chat_service=stub)
    handler_cls = server._build_handler()
    assert handler_cls is not None
    assert "Haotian Local Chat" in __import__('haotian.webapp.server', fromlist=['HTML_PAGE']).HTML_PAGE
    assert "需要手动配置" in __import__('haotian.webapp.server', fromlist=['HTML_PAGE']).HTML_PAGE

    handler = handler_cls.__new__(handler_cls)
    handler.path = "/api/chat"
    handler.headers = {"Content-Length": "94"}
    body = json.dumps(
        {
            "question": "hello",
            "attachments": [{"name": "file.txt", "type": "text/plain", "size": "5", "content": "hello"}],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.send_response = lambda *args, **kwargs: None
    handler.send_header = lambda *args, **kwargs: None
    handler.end_headers = lambda *args, **kwargs: None

    handler.do_POST()

    assert stub.last_question == "hello"
    assert stub.last_attachments == [{"name": "file.txt", "type": "text/plain", "size": "5", "content": "hello"}]
