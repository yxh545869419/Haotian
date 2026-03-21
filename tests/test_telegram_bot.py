from __future__ import annotations

from haotian.integrations.telegram_bot import TelegramBotService, TelegramUpdate
from haotian.services.chat_service import ChatReply


class StubChatService:
    def ask(self, question: str) -> ChatReply:
        return ChatReply(answer=f"answer:{question}", context_summary="summary")


def test_parse_update_extracts_text_message() -> None:
    update = TelegramBotService._parse_update(
        {
            "update_id": 10,
            "message": {
                "text": "hello",
                "chat": {"id": 123},
            },
        }
    )
    assert update == TelegramUpdate(update_id=10, chat_id=123, text="hello")


def test_handle_update_returns_help_and_chat_answer() -> None:
    service = TelegramBotService(token="token", chat_service=StubChatService())
    assert "Haotian Telegram bot" in service.handle_update(TelegramUpdate(1, 1, "/start"))
    assert service.handle_update(TelegramUpdate(2, 1, "今天怎么样？")) == "answer:今天怎么样？"
