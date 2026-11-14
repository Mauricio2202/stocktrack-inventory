"""Servidor SMTP mínimo en memoria para probar el envío real de correos (sin dependencias externas)."""
from __future__ import annotations

import asyncio
import email
import threading
from email import policy


class MiniSMTP:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.port = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def send(line: str) -> None:
            writer.write((line + "\r\n").encode())
            await writer.drain()

        mail_from, rcpts = "", []
        try:
            await send("220 minismtp ready")
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace").strip()
                cmd = line.upper()
                if cmd.startswith(("EHLO", "HELO")):
                    await send("250 minismtp")
                elif cmd.startswith("MAIL FROM"):
                    mail_from, rcpts = line.split(":", 1)[1].strip(), []
                    await send("250 OK")
                elif cmd.startswith("RCPT TO"):
                    rcpts.append(line.split(":", 1)[1].strip().strip("<>"))
                    await send("250 OK")
                elif cmd == "DATA":
                    await send("354 End data with <CR><LF>.<CR><LF>")
                    chunks = []
                    while True:
                        data_line = await reader.readline()
                        if data_line in (b".\r\n", b".\n", b""):
                            break
                        chunks.append(data_line[1:] if data_line.startswith(b"..") else data_line)
                    parsed = email.message_from_bytes(b"".join(chunks), policy=policy.default)
                    body = parsed.get_body(preferencelist=("plain",))
                    html = parsed.get_body(preferencelist=("html",))
                    self.messages.append({
                        "from": mail_from, "to": rcpts, "subject": str(parsed["Subject"]),
                        "text": body.get_content() if body else "", "html": html.get_content() if html else "",
                    })
                    await send("250 OK queued")
                elif cmd == "QUIT":
                    await send("221 bye")
                    break
                elif cmd == "NOOP":
                    await send("250 OK")
                else:
                    await send("502 command not implemented")
        finally:
            writer.close()

    def start(self) -> "MiniSMTP":
        def run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._server = self._loop.run_until_complete(asyncio.start_server(self._handle, "127.0.0.1", 0))
            self.port = self._server.sockets[0].getsockname()[1]
            self._ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, daemon=True, name="mini-smtp")
        self._thread.start()
        self._ready.wait(5)
        return self

    def stop(self) -> None:
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
