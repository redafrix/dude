from __future__ import annotations

import asyncio
from pathlib import Path

from dude.control import ControlPlane, send_command


def test_control_server_round_trip(tmp_path: Path) -> None:
    asyncio.run(_round_trip(tmp_path))


async def _round_trip(tmp_path: Path) -> None:
    socket_path = tmp_path / "control.sock"

    async def handler(payload: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "echo": payload}

    plane = ControlPlane(socket_path, handler=handler)
    await plane.start()
    plane_task = asyncio.create_task(plane.serve_forever())
    try:
        response = await send_command(socket_path, {"command": "status"})
        assert response == {"ok": True, "echo": {"command": "status"}}
    finally:
        await plane.close()
        plane_task.cancel()
        try:
            await plane_task
        except asyncio.CancelledError:
            pass
