from asyncio import AbstractEventLoop, BaseTransport
import asyncio
from types import NoneType

# from oscpy.server import OSCThreadServer, ServerClass
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
from pythonosc.udp_client import SimpleUDPClient
import signal
from dataclasses import dataclass, field
from typing import Any, Callable, List, Coroutine
import logging
from threading import Timer

log = logging.getLogger()


n_renderers = 3


@dataclass
class Source:
    idx: int
    x: float = 0
    y: float = 0
    z: float = 0
    gain: List[float] = field(default_factory=lambda: [0.0 for i in range(n_renderers)])


@dataclass
class Point3D:
    x: float
    y: float
    z: float

    def to_dict(self):
        return {"x": self.x, "y": self.y, "z": self.z}


class Watchdog(Exception):
    def __init__(self, timeout, userHandler=None):  # timeout in seconds
        self.timeout = timeout
        self.handler = userHandler if userHandler is not None else self.defaultHandler

    def start(self):
        self.timer = Timer(self.timeout, self.handler)
        self.timer.start()

    def reset(self):
        self.timer.cancel()
        self.timer = Timer(self.timeout, self.handler)
        self.timer.start()

    def stop(self):
        self.timer.cancel()

    def defaultHandler(self):
        raise self


class SeamlessListener:
    def __init__(
        self,
        n_sources: int,
        listen_ip,
        listen_port,
        osc_kreuz_hostname,
        osc_kreuz_port,
        name="seamless_status",
        reconnect_timeout=5,
    ) -> None:

        self.name = name
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.osc_kreuz_hostname = osc_kreuz_hostname
        self.osc_kreuz_port = osc_kreuz_port

        self.sources = [Source(idx=i) for i in range(n_sources)]
        self.room_name: str = ""
        self.polygon: list[Point3D] = []

        self.osc_dispatcher = Dispatcher()

        self.osc_client = SimpleUDPClient(self.osc_kreuz_hostname, self.osc_kreuz_port)
        self.reconnect_timer = Watchdog(reconnect_timeout, self.subscribe_to_osc_kreuz)
        self.asyncio_event_loop: None | AbstractEventLoop = None

        self.position_callback: (
            None | Callable[[int, float, float, float], Coroutine]
        ) = None
        self.gain_callback: None | Callable[[int, int, float], Coroutine] = None
        self.polygon_callback: None | Callable[[str, list[Point3D]], Coroutine] = None
        # TODO do something with this
        self.attribute_callback: None | Callable[[str, Any], Coroutine] = None
        self.transport: BaseTransport | None = None

    # TODO reinitialize if no ping for x Seconds

    async def start_listening(self):
        self.osc_dispatcher.map("/oscrouter/ping", self.pong)
        self.osc_dispatcher.map("/source/xyz", self.receive_xyz)
        self.osc_dispatcher.map("/source/send", self.receive_gain)
        self.osc_dispatcher.map("/room/polygon", self.receive_polygon)

        self.osc_dispatcher.set_default_handler(self.default_osc_handler)
        self.asyncio_event_loop = asyncio.get_running_loop()
        self.osc = AsyncIOOSCUDPServer(
            (self.listen_ip, self.listen_port),
            self.osc_dispatcher,
            self.asyncio_event_loop,
        )
        self.transport, protocol = await self.osc.create_serve_endpoint()
        self.subscribe_to_osc_kreuz()

    def send_full_positions(self):
        # TODO use seperate callback maybe?
        for source in self.sources:
            if self.position_callback is not None:
                _ = self.position_callback(source.idx, source.x, source.y, source.z)

    def register_position_callback(
        self, callback: Callable[[int, float, float, float], Coroutine]
    ):
        self.position_callback = callback

    def register_gain_callback(self, callback: Callable[[int, int, float], Coroutine]):
        self.gain_callback = callback

    def register_polygon_callback(
        self, callback: Callable[[str, list[Point3D]], Coroutine]
    ):
        self.polygon_callback = callback

    def pong(self, path, *values):
        self.reconnect_timer.reset()
        self.osc_client.send_message(
            "/oscrouter/pong",
            self.name,
        )

    def default_osc_handler(self, path, *values):
        print(f"received unhandled osc packet for path {path} {values}")

    def receive_xyz(self, path, *values):
        if len(values) != 4:
            return

        source_id = int(values[0])
        x, y, z = map(float, values[1:])

        self.sources[source_id].x = x
        self.sources[source_id].y = y
        self.sources[source_id].z = z

        # if self.position_callback is not None:
        #     await self.position_callback(source_id, x, y, z)
        if self.asyncio_event_loop is not None and self.position_callback is not None:
            self.asyncio_event_loop.create_task(
                self.position_callback(source_id, x, y, z)
            )

    def receive_gain(self, path, *values):
        if len(values) != 3:
            return
        source_id = int(values[0])
        renderer_id = int(values[1])
        gain = float(values[2])
        self.sources[source_id].gain[renderer_id] = gain

        # if self.gain_callback is not None:
        #     await self.gain_callback(source_id, renderer_id, gain)
        if self.asyncio_event_loop is not None and self.gain_callback is not None:

            self.asyncio_event_loop.create_task(
                self.gain_callback(source_id, renderer_id, gain)
            )

    def receive_polygon(self, path, room_name: str, n_points: int, *values):
        self.room_name = room_name
        if len(values) / n_points != 3:
            logging.error("receive polygon is wrong size")
            return

        self.polygon = []
        for i in range(n_points):
            base_index = i * 3
            self.polygon.append(
                Point3D(
                    values[base_index], values[base_index + 1], values[base_index + 2]
                )
            )

        if len(self.polygon) > 1:
            self.polygon.append(self.polygon[0])
        if self.asyncio_event_loop is not None and self.polygon_callback is not None:
            self.asyncio_event_loop.create_task(
                self.polygon_callback(room_name, self.polygon)
            )

    def subscribe_to_osc_kreuz(self):
        logging.info(f"sending subscribe message to {self.name}:{self.listen_port}")
        print(
            f"sending subscribe message to {self.osc_kreuz_hostname}:{self.osc_kreuz_port}"
        )
        self.osc_client.send_message(
            "/osckreuz/subscribe",
            [self.name, self.listen_port, "xyz", 0, 10],
        )
        self.reconnect_timer.start()

    def unsubscribe_from_osc_kreuz(self):
        try:
            self.osc_client.send_message(
                "/osckreuz/unsubscribe",
                self.name,
            )

            self.reconnect_timer.stop()
            if self.transport is not None:
                self.transport.close()

        except (RuntimeError, AttributeError):
            # handle shutdowns in dev mode of fastapi
            pass

    def __del__(self):
        self.unsubscribe_from_osc_kreuz()


# if __name__ == "__main__":
# register with osc_kreuz
# osc_kreuz_ip = "127.0.0.1"
# osc_kreuz_ip = "newmark.ak.tu-berlin.de"
# osc_kreuz_port = 4999
# name = "seamless_status"

# n_sources = 64

# ip = "130.149.23.42"
# port = 51312

# listener = SeamlessListener(n_sources, ip, port, osc_kreuz_ip, osc_kreuz_port, name)
# listener.start_listening()
# signal.pause()
