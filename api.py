import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from contextlib import asynccontextmanager

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from seamless_listener import SeamlessListener
import asyncio
from pydantic import BaseModel
import click


@asynccontextmanager
async def lifespan(app: FastAPI):
    global loop
    if seamless_listener is None:
        raise Exception("seamless listener is None, whyy")

    await seamless_listener.start_listening()
    yield
    seamless_listener.unsubscribe_from_osc_kreuz()


class ServiceStatus(BaseModel):
    name: str
    load_state: str
    active_state: str
    sub_state: str


class Services(BaseModel):
    services: list[ServiceStatus]


pc_status: dict[str, dict[str, Services]] = {
    "test": {"kaorutest": Services(services=[])}
}


app = FastAPI(lifespan=lifespan)
seamless_listener: SeamlessListener | None = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        await self.send_full_position_update(websocket)
        print("active connections: ", len(self.active_connections))

    async def send_full_position_update(self, websocket: WebSocket):
        if seamless_listener is None:
            raise Exception("seamless listener is none, wth")
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
    print(services)
    return services


@app.get("/servicestatus/{room_id}")
async def get_service_status(room_id: str):
    if room_id not in pc_status:
        raise HTTPException(status_code=404, detail="Room not found")

    return pc_status[room_id]


# this enables serving static html files
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@click.command(help="Start the backend of the seamless status")
@click.option(
    "-o",
    "--osc-kreuz-hostname",
    default="127.0.0.1",
    type=click.STRING,
    help="The hostname of the osc-kreuz to connect to",
)
@click.option(
    "--osc-kreuz-port",
    default=4999,
    type=click.INT,
    help="the settings port of the osc-kreuz to connect to",
)
@click.option(
    "-i",
    "--ip",
    default="0.0.0.0",
    type=click.STRING,
    help="the ip this program should listen on. needs to be accessible by the osc-kreuz",
)
@click.option(
    "-l",
    "--listener-port",
    default=55156,
    type=click.INT,
    help="the port the osc-kreuz listener listens on",
)
@click.option(
    "-p",
    "--api-port",
    default=8000,
    type=click.INT,
    help="the port the api listens on",
)
@click.option(
    "-s",
    "--n-sources",
    default=64,
    type=click.INT,
    help="the number of sources in the osc-kreuz",
)
@click.option(
    "-n",
    "--name",
    default="seamless_status",
    type=click.STRING,
    help="the name with which to register at the osc-kreuz",
)
def main(
    osc_kreuz_hostname, osc_kreuz_port, ip, listener_port, api_port, n_sources, name
):
    # osc_kreuz_ip = "130.149.23.211" # kaorutest

    # osc_kreuz_ip = "dose.ak.tu-berlin.de"
    # osc_kreuz_ip = "127.0.0.1"
    # osc_kreuz_hostname = "130.149.23.33"  # newmark#
    # osc_kreuz_ip = "3900-zg-re-01.asg"  # hufo

    # osc_kreuz_ip = "192.168.178.100"  # tengo

    global seamless_listener
    seamless_listener = SeamlessListener(
        n_sources, ip, listener_port, osc_kreuz_hostname, osc_kreuz_port, name
    )

    seamless_listener.register_position_callback(manager.send_position_update)
    seamless_listener.register_gain_callback(manager.send_gain_update)

    import uvicorn

    uvicorn.run(app, host=ip, port=api_port)


if __name__ == "__main__":
    main()
