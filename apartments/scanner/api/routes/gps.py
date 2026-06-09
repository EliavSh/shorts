"""GPS WebSocket — frontend pushes live coordinates here.

Useful for cross-device broadcast (e.g., phone driving the position, desktop
mirroring the map). Single-broadcast hub: subscribers receive everyone's pings.
"""
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/ws/gps", tags=["gps"])

_subscribers: Set[WebSocket] = set()


@router.websocket("")
async def gps_socket(ws: WebSocket):
    await ws.accept()
    _subscribers.add(ws)
    try:
        while True:
            text = await ws.receive_text()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            # Echo to all other subscribers (multi-device sync)
            stale: list[WebSocket] = []
            for sub in _subscribers:
                if sub is ws:
                    continue
                try:
                    await sub.send_json(payload)
                except Exception:
                    stale.append(sub)
            for s in stale:
                _subscribers.discard(s)
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.discard(ws)
