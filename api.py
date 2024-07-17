import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
from seamless_listener import SeamlessListener
import asyncio


@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    seamless_listener.asyncio_event_loop = asyncio.get_running_loop()
    yield
    seamless_listener.unsubscribe_from_osc_kreuz()


app = FastAPI(lifespan=lifespan)

osc_kreuz_ip = "130.149.23.211"
osc_kreuz_port = 4999
name = "seamless_status"

n_sources = 64

ip = "0.0.0.0"
listen_port = 55156
seamless_listener = SeamlessListener(
    n_sources, ip, listen_port, osc_kreuz_ip, osc_kreuz_port, name
)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self.send_full_position_update(websocket)
        print("active connections: ", len(self.active_connections))

    async def send_full_position_update(self, websocket: WebSocket):
        for source in seamless_listener.sources:
            await websocket.send_json(
                {
                    "id": source.idx,
                    "position": {"x": source.x, "y": source.y, "z": source.z},
                    "gains": source.gain,
                }
            )

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def send_position_update(self, source_id, x, y, z):
        for connection in self.active_connections:
            await connection.send_json(
                {"id": source_id, "position": {"x": x, "y": y, "z": z}}
            )

    async def send_gain_update(self, source_id, renderer_id, gain):
        for connection in self.active_connections:
            await connection.send_json(
                {"id": source_id, "renderer_id": renderer_id, "renderer_gain": gain}
            )

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()

seamless_listener.register_position_callback(manager.send_position_update)
seamless_listener.register_gain_callback(manager.send_gain_update)


@app.websocket("/pos")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # TODO do something with that?
    except WebSocketDisconnect:

        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
