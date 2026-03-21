"""Interactive terminal chat mode for Haotian."""

from __future__ import annotations

from haotian.services.chat_service import ChatService


class CLIChatService:
    """Simple REPL wrapper for the chat service."""

    def __init__(self, chat_service: ChatService | None = None) -> None:
        self.chat_service = chat_service or ChatService()

    def run(self) -> None:
        print("Haotian CLI chat started. 输入 exit / quit 退出。")
        while True:
            question = input("You> ").strip()
            if question.lower() in {"exit", "quit"}:
                print("Bye.")
                return
            if not question:
                continue
            try:
                reply = self.chat_service.ask(question)
            except Exception as exc:  # noqa: BLE001
                print(f"AI> Error: {exc}")
                continue
            print(f"AI> {reply.answer}")
