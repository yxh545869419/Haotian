"""Minimal cross-platform local web server for Haotian chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from haotian.services.chat_service import ChatService

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Haotian Local Chat</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    .layout { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
    .sidebar { background: #111827; border-right: 1px solid #334155; padding: 20px; }
    .main { padding: 20px; }
    .nav-btn { display:block; width:100%; margin-bottom:10px; padding:12px; border-radius:10px; border:1px solid #475569; background:#1e293b; color:#e2e8f0; cursor:pointer; text-align:left; }
    .panel { display:none; }
    .panel.active { display:block; }
    .card { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    #messages { min-height: 360px; max-height: 60vh; overflow-y:auto; white-space: pre-wrap; }
    .msg { padding: 10px 12px; border-radius: 10px; margin-bottom: 10px; }
    .user { background: #1d4ed8; }
    .assistant { background: #1f2937; }
    textarea { width: 100%; min-height: 96px; border-radius: 10px; border: 1px solid #475569; background: #020617; color: #e2e8f0; padding: 12px; }
    input[type=file] { margin-top: 12px; }
    button { margin-top: 12px; background: #22c55e; border: 0; color: #06210f; font-weight: bold; padding: 10px 16px; border-radius: 10px; cursor: pointer; }
    .danger { background:#ef4444; color:white; }
    .hint { color: #94a3b8; font-size: 14px; }
    .list-item { border-bottom: 1px solid #334155; padding: 10px 0; }
    .tag { display:inline-block; background:#334155; color:#e2e8f0; border-radius:999px; padding:2px 8px; margin-left:8px; font-size:12px; }
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h2>Haotian</h2>
      <button class="nav-btn" onclick="showPanel('chat')">对话</button>
      <button class="nav-btn" onclick="showPanel('skills')">技能</button>
      <button class="nav-btn" onclick="showPanel('config')">配置</button>
      <div class="hint">若配置了 TelegramBotToken，启动网页版或命令行版时会自动同时连上 Telegram。</div>
    </aside>
    <main class="main">
      <section id="panel-chat" class="panel active">
        <div class="card">
          <h3>对话履历</h3>
          <div id="messages"></div>
          <button class="danger" onclick="clearHistory()">一键删除全部对话</button>
        </div>
        <div class="card">
          <h3>输入</h3>
          <textarea id="question" placeholder="例如：今天新增了哪些 repo？哪些能力需要手动配置？"></textarea>
          <input id="attachments" type="file" multiple />
          <div class="hint">支持上传文件、图片等附件；当前会把附件名称和类型一并传入上下文。</div>
          <button onclick="sendQuestion()">发送</button>
        </div>
      </section>
      <section id="panel-skills" class="panel">
        <div class="card"><h3>技能</h3><div id="skills"></div></div>
      </section>
      <section id="panel-config" class="panel">
        <div class="card"><h3>配置</h3><div id="config"></div></div>
      </section>
    </main>
  </div>
<script>
function showPanel(name) {
  document.querySelectorAll('.panel').forEach(panel => panel.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'skills') loadSkills();
  if (name === 'config') loadConfig();
}
async function loadHistory() {
  const response = await fetch('/api/history');
  const data = await response.json();
  const container = document.getElementById('messages');
  container.innerHTML = '';
  data.items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'msg ' + item.role;
    let text = item.content;
    if (item.attachments && item.attachments.length) {
      text += '\n\n附件：' + item.attachments.map(a => a.name + ' (' + a.type + ')').join(', ');
    }
    div.textContent = text;
    container.appendChild(div);
  });
}
async function clearHistory() {
  await fetch('/api/history', {method:'DELETE'});
  await loadHistory();
}
async function loadSkills() {
  const response = await fetch('/api/skills');
  const data = await response.json();
  const container = document.getElementById('skills');
  container.innerHTML = '';
  ['active','inactive'].forEach(bucket => {
    const section = document.createElement('div');
    section.innerHTML = `<h4>${bucket === 'active' ? '已生效技能' : '未生效技能'}</h4>`;
    (data[bucket] || []).forEach(item => {
      const div = document.createElement('div');
      div.className = 'list-item';
      div.innerHTML = `<strong>${item.canonical_name}</strong> <span class="tag">${item.status}</span> ${item.needs_manual_configuration ? '<span class="tag">需要手动配置</span>' : ''}<br/>出处 repos：${(item.source_repos || []).join(', ') || '无'}`;
      section.appendChild(div);
    });
    container.appendChild(section);
  });
}
async function loadConfig() {
  const response = await fetch('/api/config');
  const data = await response.json();
  const container = document.getElementById('config');
  container.innerHTML = '';
  data.items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'list-item';
    div.innerHTML = `<strong>${item.key}</strong><br/>${item.value}`;
    container.appendChild(div);
  });
}
async function sendQuestion() {
  const question = document.getElementById('question').value.trim();
  if (!question) return;
  const files = Array.from(document.getElementById('attachments').files || []);
  const attachments = await Promise.all(files.map(readAttachment));
  await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question, attachments})
  });
  document.getElementById('question').value = '';
  document.getElementById('attachments').value = '';
  await loadHistory();
}
async function readAttachment(file) {
  const isTextLike = (file.type || '').startsWith('text/') || /json|xml|yaml|csv/.test(file.type || '') || /\.(md|txt|py|js|ts|json|ya?ml|toml|csv)$/i.test(file.name);
  if (isTextLike) {
    const text = await file.text();
    return {
      name: file.name,
      type: file.type || 'text/plain',
      size: String(file.size),
      content: text.slice(0, 4000),
    };
  }
  return await new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve({
      name: file.name,
      type: file.type || 'application/octet-stream',
      size: String(file.size),
      content: String(reader.result || '').slice(0, 4000),
    });
    reader.readAsDataURL(file);
  });
}
loadHistory();
</script>
</body>
</html>
"""


@dataclass(slots=True)
class WebServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765


class HaotianWebServer:
    """Serve the local chat page and JSON chat API."""

    def __init__(self, chat_service: ChatService | None = None) -> None:
        self.chat_service = chat_service or ChatService()

    def serve(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        config = WebServerConfig(host=host, port=port)
        server = ThreadingHTTPServer((config.host, config.port), self._build_handler())
        print(f"Haotian web chat listening on http://{config.host}:{config.port}")
        try:
            server.serve_forever()
        finally:
            server.server_close()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        chat_service = self.chat_service

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/":
                    self._html_response(HTML_PAGE)
                    return
                if self.path == "/api/history":
                    self._json_response(HTTPStatus.OK, {"items": chat_service.list_history()})
                    return
                if self.path == "/api/skills":
                    self._json_response(HTTPStatus.OK, chat_service.list_skills())
                    return
                if self.path == "/api/config":
                    self._json_response(HTTPStatus.OK, {"items": chat_service.masked_config()})
                    return
                self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})

            def do_DELETE(self) -> None:  # noqa: N802
                if self.path != "/api/history":
                    self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return
                chat_service.delete_history()
                self._json_response(HTTPStatus.OK, {"ok": True})

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/chat":
                    self._json_response(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(raw or "{}")
                question = str(payload.get("question", "")).strip()
                attachments = payload.get("attachments", [])
                try:
                    reply = chat_service.ask(question, attachments=attachments if isinstance(attachments, list) else [])
                except Exception as exc:  # noqa: BLE001
                    self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._json_response(
                    HTTPStatus.OK,
                    {"answer": reply.answer, "context_summary": reply.context_summary},
                )

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def _html_response(self, content: str) -> None:
                data = content.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _json_response(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler
