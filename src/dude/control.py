from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

JsonDict = dict[str, object]
Handler = Callable[[JsonDict], Awaitable[JsonDict]]


class ControlPlane:
    def __init__(self, socket_path: Path, handler: Handler) -> None:
        self.socket_path = socket_path
        self.handler = handler
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            request = json.loads(raw.decode("utf-8")) if raw else {}
            response = await self.handler(request if isinstance(request, dict) else {})
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("Control plane was not started.")
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()


async def send_command(
    socket_path: Path,
    payload: JsonDict,
    timeout_seconds: float = 5.0,
) -> JsonDict:
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(str(socket_path)),
        timeout=timeout_seconds,
    )
    try:
        writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
        return json.loads(raw.decode("utf-8")) if raw else {}
    finally:
        writer.close()
        await writer.wait_closed()
