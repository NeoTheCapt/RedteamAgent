from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class RunBroadcaster:
    def __init__(self) -> None:
        self._connections: dict[tuple[int, int], set[WebSocket]] = defaultdict(set)

    async def connect(self, project_id: int, run_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[(project_id, run_id)].add(websocket)

    def disconnect(self, project_id: int, run_id: int, websocket: WebSocket) -> None:
        key = (project_id, run_id)
        self._connections[key].discard(websocket)
        if not self._connections[key]:
            self._connections.pop(key, None)

    async def publish(self, project_id: int, run_id: int, payload: dict) -> None:
        key = (project_id, run_id)
        stale: list[WebSocket] = []
        for websocket in self._connections.get(key, set()):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(project_id, run_id, websocket)


broadcaster = RunBroadcaster()
