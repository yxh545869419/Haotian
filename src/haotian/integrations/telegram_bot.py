"""Telegram bot integration for Haotian chat."""

from __future__ import annotations

import json
import time
from threading import Thread
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from haotian.services.chat_service import ChatService


@dataclass(slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    text: str


class TelegramBotService:
    """Run a long-polling Telegram bot backed by the local chat service."""

    def __init__(self, token: str, chat_service: ChatService | None = None, timeout: int = 30) -> None:
        self.token = token
        self.chat_service = chat_service or ChatService()
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def serve_forever(self) -> None:
        offset: int | None = None
        print("Haotian Telegram bot polling started.")
        while True:
            try:
                updates = self.fetch_updates(offset=offset)
            except Exception as exc:  # noqa: BLE001
                print(f"Telegram polling error: {exc}")
                time.sleep(3)
                continue
            for update in updates:
                offset = update.update_id + 1
                response = self.handle_update(update)
                self.send_message(update.chat_id, response)

    def fetch_updates(self, offset: int | None = None) -> list[TelegramUpdate]:
        params = {"timeout": self.timeout}
        if offset is not None:
            params["offset"] = offset
        payload = self._request_json(f"{self.base_url}/getUpdates?{urlencode(params)}")
        return [self._parse_update(item) for item in payload.get("result", []) if self._parse_update(item) is not None]

    def handle_update(self, update: TelegramUpdate) -> str:
        text = update.text.strip()
        if text in {"/start", "/help"}:
            return (
                "Haotian Telegram bot 已连接。\n"
                "直接发送问题即可，例如：今天新增了哪些 repo？哪些能力需要人工注意？"
            )
        reply = self.chat_service.ask(text)
        return reply.answer

    def send_message(self, chat_id: int, text: str) -> None:
        data = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        request = Request(
            url=f"{self.base_url}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._request_json(request)

    def _request_json(self, request: str | Request) -> dict[str, object]:
        try:
            with urlopen(request, timeout=self.timeout + 5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Telegram API request failed with status {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Telegram API request failed: {exc.reason}") from exc
        if not data.get("ok", False):
            raise RuntimeError(f"Telegram API error: {data}")
        return data

    @staticmethod
    def _parse_update(payload: dict[str, object]) -> TelegramUpdate | None:
        message = payload.get("message")
        if not isinstance(message, dict):
            return None
        text = message.get("text")
        chat = message.get("chat")
        update_id = payload.get("update_id")
        if not isinstance(text, str) or not isinstance(chat, dict) or not isinstance(update_id, int):
            return None
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return None
        return TelegramUpdate(update_id=update_id, chat_id=chat_id, text=text)


def start_background_telegram_bot(token: str | None, chat_service: ChatService | None = None) -> Thread | None:
    """Start the Telegram polling bridge in a daemon thread when configured."""

    if not token:
        return None
    service = TelegramBotService(token=token, chat_service=chat_service)
    thread = Thread(target=service.serve_forever, daemon=True)
    thread.start()
    return thread
