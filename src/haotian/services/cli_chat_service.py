"""Interactive terminal chat mode for Haotian."""

from __future__ import annotations

import sys

from haotian.services.chat_service import ChatService


class CLIChatService:
    """Simple REPL wrapper for the chat service."""

    def __init__(self, chat_service: ChatService | None = None) -> None:
        self.chat_service = chat_service or ChatService()

    def run(self) -> None:
        _ensure_console_streams_support_unicode()
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


def _ensure_console_streams_support_unicode() -> None:
    # Reconfigure Windows-style legacy console encodings before emitting localized prompts.
    for stream in (sys.stdout, sys.stderr):
        _reconfigure_stream_for_unicode(stream, probe_text="输入退出")


def _reconfigure_stream_for_unicode(stream: object, *, probe_text: str) -> None:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        probe_text.encode(encoding)
        return
    except (LookupError, UnicodeEncodeError):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            return
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except TypeError:
            reconfigure(encoding="utf-8")
        except ValueError:
            return
