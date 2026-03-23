from __future__ import annotations

import builtins
import sys

from haotian.services.cli_chat_service import CLIChatService


class FakeConsoleStream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding
        self.reconfigured_to: str | None = None
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        if self.encoding.lower() == "cp1252" and any(ord(char) > 127 for char in text):
            raise UnicodeEncodeError("cp1252", text, 0, len(text), "character maps to <undefined>")
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        return

    def reconfigure(self, *, encoding: str | None = None, errors: str | None = None) -> None:
        if encoding:
            self.encoding = encoding
            self.reconfigured_to = encoding


class StubChatService:
    def ask(self, question: str) -> object:
        raise AssertionError("chat service should not be called in this test")


def test_cli_chat_service_reconfigures_console_for_non_utf8_output(monkeypatch) -> None:
    stdout = FakeConsoleStream("cp1252")
    stderr = FakeConsoleStream("cp1252")

    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "quit")

    CLIChatService(chat_service=StubChatService()).run()

    assert stdout.reconfigured_to == "utf-8"
    assert stderr.reconfigured_to == "utf-8"
    assert any("Haotian CLI chat started." in chunk for chunk in stdout.writes)
