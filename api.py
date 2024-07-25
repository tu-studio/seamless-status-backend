import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager
from seamless_listener import SeamlessListener
import asyncio
from pydantic import BaseModel


@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    seamless_listener.start_listening()
    seamless_listener.asyncio_event_loop = asyncio.get_running_loop()
    yield
    seamless_listener.unsubscribe_from_osc_kreuz()

class ServiceStatus(BaseModel):
    name: str
    load_state: str
    active_state: str
    sub_state: str
class Services(BaseModel):
    services: list[ServiceStatus]

pc_status: dict[str, dict[str, Services]] = {"test": {"kaorutest": Services(services=[])}}



app = FastAPI(lifespan=lifespan)

# osc_kreuz_ip = "130.149.23.211" # kaorutest

# osc_kreuz_ip = "127.0.0.1"
osc_kreuz_ip = "130.149.23.33" # newmark
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

@app.post("/servicestatus/{room_id}/{pc_id}")
async def update_service_status(room_id: str, pc_id: str, services: Services):
    if room_id not in pc_status:
        raise HTTPException(status_code=404, detail="Room not found")
    if pc_id not in pc_status[room_id]:
        raise HTTPException(status_code=404, detail="PC not found")

    pc_status[room_id][pc_id] = services
    return services

@app.get("/servicestatus/{room_id}")
async def get_service_status(room_id: str):
    if room_id not in pc_status:
        raise HTTPException(status_code=404, detail="Room not found")
    
    return pc_status[room_id]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
