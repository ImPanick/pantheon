# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live phone's picture is not held back on its way to the viewer.

The owner, 2026-11-23, after the screen became video: "Ok so the phone is a lot
smoother but it is still very choppy.. the Linux workstation however performs
fantastic." Each frame left the worker as a run of small writes behind a large
one. With Nagle on, a small write behind unacknowledged data waits for the
relay's delayed ACK, about 40 ms a frame on Linux and longer on Windows. And
the viewer looked for a new frame at the video's own rate, so a frame that
landed just after a look waited a whole interval or was skipped.
"""
import io
import socket
import struct
import threading

import pytest
from PIL import Image

from workstation.native_android import rfb, video


class Writes:
    """The viewer's side of the stream, keeping each write as it was made."""

    def __init__(self, data):
        self.data, self.writes = io.BytesIO(data), []

    def read(self, size):
        data = self.data.read(size)
        if len(data) != size:
            raise rfb.StreamEnded()
        return data

    def write(self, data):
        self.writes.append(bytes(data))


def _greeting(*encodings):
    return (b'RFB 003.008\n\1\1' + b'\2\0' + struct.pack('>H', len(encodings))
            + struct.pack('>' + 'i' * len(encodings), *encodings))


def _request(w, h, incremental=1):
    return b'\3' + struct.pack('>BHHHH', incremental, 0, 0, w, h)


def test_a_frame_leaves_as_one_write():
    image = Image.new('RGB', (320, 640), (200, 30, 40))

    def frame():
        return image, 'one'

    stream = Writes(_greeting(7, -224, -308, -239) + _request(320, 640, 0))
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, frame, lambda _: None, lambda: None, frame_interval=0)
    updates = [w for w in stream.writes if b'\xff\xd8\xff' in w]
    assert len(updates) == 1
    update = updates[0]
    # The update's header, its geometry and cursor, the picture and its LastRect: all in it.
    assert update.startswith(struct.pack('>BBH', 0, 0, 4))
    assert update.endswith(struct.pack('>HHHHi', 0, 0, 0, 0, -224))
    assert struct.pack('>HHHHi', 0, 0, 320, 640, 7) in update
    # Nothing of this update follows it in another write.
    assert stream.writes[-1] == update


def test_a_resized_frame_leaves_as_one_write():
    images = {size: Image.new('RGB', size) for size in [(320, 640), (640, 320)]}
    state = {'size': (320, 640)}

    def frame():
        return images[state['size']], state['size']

    class Turning(Writes):
        def write(self, data):
            super().write(data)
            if b'\xff\xd8\xff' in data:
                state['size'] = (640, 320)

    stream = Turning(_greeting(7, -224, -308) + _request(320, 640, 0) + _request(320, 640))
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, frame, lambda _: None, lambda: None, frame_interval=0)
    updates = [w for w in stream.writes if b'\xff\xd8\xff' in w]
    assert len(updates) == 2
    assert struct.pack('>HHHHi', 0, 0, 640, 320, -308) in updates[1]
    assert updates[1].endswith(struct.pack('>HHHHi', 0, 0, 0, 0, -224))


def test_the_stream_looks_for_a_frame_twice_per_video_frame():
    assert rfb.FRAME_INTERVAL <= 1 / (2 * video.MAX_FPS)


def test_the_phone_worker_turns_nagle_off(tmp_path, monkeypatch):
    from workstation.native_android import server

    class Host:
        accel = None
        why = 'Not installed'

        def __init__(self, config):
            pass

    seen = []
    handle = server.Handler.handle

    def recording(self):
        seen.append(self.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
        return handle(self)

    monkeypatch.setattr(server, 'Host', Host)
    monkeypatch.setattr(server.Handler, 'handle', recording)
    worker = server.make_server(dict(state=str(tmp_path), sdk=str(tmp_path),
                                     token_file=str(tmp_path / 'token'), port=0))
    thread = threading.Thread(target=worker.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(('127.0.0.1', worker.server_port), timeout=10) as client:
            client.sendall(b'GET /v1/nothing HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n')
            client.recv(4096)
    finally:
        worker.shutdown()
        worker.server_close()
        thread.join()
    assert seen and all(seen)
