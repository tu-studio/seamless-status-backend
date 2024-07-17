from asyncio import AbstractEventLoop
from types import NoneType
from oscpy.server import OSCThreadServer, ServerClass
import signal
from dataclasses import dataclass, field
from typing import Callable, List, Coroutine


n_renderers = 3


@dataclass
class Source:
    idx: int
    x: float = 0
    y: float = 0
    z: float = 0
    gain: List[float] = field(default_factory=lambda: [0.0 for i in range(n_renderers)])


@ServerClass
class SeamlessListener:
    def __init__(
        self,
        n_sources: int,
        listen_ip,
        listen_port,
        osc_kreuz_hostname,
        osc_kreuz_port,
        name="seamless_status",
    ) -> None:

        self.name = name
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.osc_kreuz_hostname = osc_kreuz_hostname
        self.osc_kreuz_port = osc_kreuz_port

        self.sources = [Source(idx=i) for i in range(n_sources)]
        self.osc = OSCThreadServer()

        self.osc.listen(self.listen_ip, self.listen_port, True)

        self.osc.bind(b"/oscrouter/ping", self.pong)
        self.osc.bind(b"/source/xyz", self.receive_xyz)
        self.osc.bind(b"/source/send", self.receive_gain)
        self.asyncio_event_loop: None | AbstractEventLoop = None

        self.position_callback: (
            NoneType | Callable[[int, float, float, float], Coroutine]
        ) = None
        self.gain_callback: NoneType | Callable[[int, int, float], Coroutine] = None

        self.subscribe_to_osc_kreuz()

    # TODO reinitialize if no ping for x Seconds

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

    def pong(self, *values):
        self.osc.send_message(
            b"/oscrouter/pong",
            (self.name.encode(),),
            self.osc_kreuz_hostname,
            self.osc_kreuz_port,
        )

    def receive_xyz(self, *values):
        if len(values) != 4:
            return

        source_id = int(values[0])
        x, y, z = map(float, values[1:])

        self.sources[source_id].x = x
        self.sources[source_id].y = y
        self.sources[source_id].z = z

        if self.asyncio_event_loop is not None and self.position_callback is not None:
            self.asyncio_event_loop.create_task(
                self.position_callback(source_id, x, y, z)
            )

    def receive_gain(self, *values):
        if len(values) != 3:
            return
        source_id = int(values[0])
        renderer_id = int(values[1])
        gain = float(values[2])
        self.sources[source_id].gain[renderer_id] = gain

        if self.asyncio_event_loop is not None and self.gain_callback is not None:

            self.asyncio_event_loop.create_task(
                self.gain_callback(source_id, renderer_id, gain)
            )

    def subscribe_to_osc_kreuz(self):
        self.osc.send_message(
            "/oscrouter/subscribe".encode(),
            [self.name.encode(), self.listen_port, b"xyz", 0, 5],
            self.osc_kreuz_hostname,
            self.osc_kreuz_port,
        )

    def unsubscribe_from_osc_kreuz(self):
        self.osc.send_message(
            b"/oscrouter/unsubscribe",
            [self.name.encode()],
            self.osc_kreuz_hostname,
            self.osc_kreuz_port,
        )

    def __del__(self):
        self.unsubscribe_from_osc_kreuz()


if __name__ == "__main__":
    # register with osc_kreuz
    osc_kreuz_ip = "130.149.23.211"
    osc_kreuz_port = 4999
    name = "seamless_status"

    n_sources = 64

    ip = "0.0.0.0"
    port = 51213

    SeamlessListener(n_sources, ip, port, osc_kreuz_ip, osc_kreuz_port, name)
    signal.pause()
