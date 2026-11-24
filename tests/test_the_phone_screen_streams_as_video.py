# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live phone runs at the screen video's rate, not one screenshot a second.

The owner, 2026-11-22: "Okay so things are working! How do we get this to
function at more than 1 FPS?" Every frame was a raw `screencap` pulled out of
Android (about 10 MB at 1080 x 2400), and on an emulator each takes the better
part of a second. The pinned scrcpy server now streams the screen as H.264,
decoded on the host; screencap only measures the display and fills in when the
video cannot.
"""
import io
from fractions import Fraction
import struct
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from workstation.native_android import rfb


# -- the screen ------------------------------------------------------------------

class FakeVideo:
    """`ScrcpyVideo`'s two calls: a new picture each time `step()` is called."""
    def __init__(self, size=(540, 1200)):
        self.size, self.serial, self.wanted, self.image = size, 0, 0, None

    def step(self, size=None):
        self.serial += 1
        self.image = Image.new('RGB', size or self.size, (self.serial, 2, 3))

    def want(self):
        self.wanted += 1

    def picture(self):
        return None if self.image is None else (self.image, self.serial)


def _screen(monkeypatch, capture_size=(1080, 2400), device='pixel_9', posture=None):
    from workstation.native_android import screen as S
    phone = SimpleNamespace(lock=threading.RLock(), generation='g', control=object(), state='on',
                            device=device, posture=posture, rotation=0, direct=object(),
                            _active=lambda: None, touch=lambda: None, stream_ready=lambda: True)
    captures = []

    def capture(_):
        captures.append(capture_size)
        return Image.new('RGB', capture_size, (9, 9, 9))
    monkeypatch.setattr(S, 'raw_capture', capture)
    screen = S.Screen(phone)
    return screen, captures


def test_the_phone_screen_comes_from_its_video_not_a_screenshot_per_frame(monkeypatch):
    screen, captures = _screen(monkeypatch)
    video = FakeVideo()
    screen.video = video
    screen.frame()  # the first picture measures the display: one screenshot
    assert captures == [(1080, 2400)]
    shown = []
    for _ in range(30):
        video.step()
        screen.cached_at = 0  # long enough ago that a screenshot would be taken again
        image, geometry = screen.frame()
        shown.append(image.getpixel((0, 0))[0])
    assert captures == [(1080, 2400)], "a frame of the live screen was a screenshot again"
    assert shown == list(range(1, 31))
    assert image.size == screen.size and geometry == ('g', screen.size, (1080, 2400))
    assert video.wanted >= 30


def test_an_unchanged_video_frame_is_the_same_picture(monkeypatch):
    screen, captures = _screen(monkeypatch)
    screen.video = video = FakeVideo()
    screen.frame()
    video.step()
    first, _ = screen.frame()
    screen.cached_at = 0
    again, _ = screen.frame()
    assert again is first and captures == [(1080, 2400)]


def test_a_turned_display_is_measured_again_before_its_video_is_shown(monkeypatch):
    screen, captures = _screen(monkeypatch)
    screen.video = video = FakeVideo()
    screen.frame()
    video.step(size=(1200, 540))  # the video turned before the screen was measured again
    screen.cached_at = 0
    screen.frame()
    assert len(captures) == 2, "the turned picture was stretched onto the old display"


def test_a_folded_cover_screen_keeps_its_screenshot(monkeypatch):
    from workstation.native_android import screen as S
    screen, captures = _screen(monkeypatch, device='pixel_fold', posture='closed')
    if S.P.PHONE_DEVICES.get('pixel_fold', {}).get('kind') != 'foldable':
        pytest.skip('no foldable device profile by that name')
    screen.video = video = FakeVideo()
    video.step()
    assert screen._video() is None


def test_without_video_the_screenshot_still_streams(monkeypatch):
    screen, captures = _screen(monkeypatch)
    screen.frame()
    screen.cached_at = 0
    screen.frame()
    assert len(captures) == 2


# -- the stream to the viewer -------------------------------------------------------

class Stream:
    def __init__(self, data):
        self.data, self.output = io.BytesIO(data), bytearray()

    def read(self, size):
        data = self.data.read(size)
        if len(data) != size:
            raise rfb.StreamEnded()
        return data

    def write(self, data):
        self.output.extend(data)


def request(w, h, incremental=1):
    return b'\3' + struct.pack('>BHHHH', incremental, 0, 0, w, h)


def greeting(*encodings):
    return (b'RFB 003.008\n\1\1' + b'\2\0' + struct.pack('>H', len(encodings))
            + struct.pack('>' + 'i' * len(encodings), *encodings))


def jpegs(output):
    return output.count(b'\xff\xd8\xff')


NOTHING_NEW = struct.pack('>BBH', 0, 0, 0xffff) + struct.pack('>HHHHi', 0, 0, 0, 0, -224)


def test_an_unchanged_screen_is_not_sent_again():
    image = Image.new('RGB', (320, 640))
    stream = Stream(greeting(7, -224, -308) + request(320, 640) * 3)
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, lambda: (image, 'one'), lambda _: None, lambda: None, frame_interval=0)
    output = bytes(stream.output)
    assert jpegs(output) == 1
    # Never a zero-length update: Kasm's client stops asking after one.
    assert output.count(NOTHING_NEW) == 2


def test_a_full_request_gets_the_picture_even_when_unchanged():
    image = Image.new('RGB', (320, 640))
    stream = Stream(greeting(7, -224, -308) + request(320, 640) + request(320, 640, incremental=0))
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, lambda: (image, 'one'), lambda _: None, lambda: None, frame_interval=0)
    assert jpegs(bytes(stream.output)) == 2


def test_the_stream_asks_for_frames_at_video_rate():
    assert rfb.FRAME_INTERVAL <= 1 / 25
    import inspect
    assert inspect.signature(rfb.serve).parameters['frame_interval'].default == rfb.FRAME_INTERVAL


# -- the video itself ----------------------------------------------------------------

class Wire:
    def __init__(self):
        self.deadline = 0
        self.sock = SimpleNamespace(shutdown=lambda how: None)


class Channel:
    def __init__(self, data):
        self.data, self.wire, self.max_pending = io.BytesIO(data), Wire(), 0
        self.done = threading.Event()

    def read(self, count):
        out = self.data.read(count)
        if len(out) < count:
            self.done.set()
            from workstation.native_android.adb import AdbError
            raise AdbError("Android returned an incomplete stream.")
        return out


class Adb:
    def __init__(self, channel):
        self.channel_, self.commands = channel, []

    def execute_bytes(self, args, timeout=20):
        return b'its log'

    def shell(self, args, timeout=20):
        self.commands.append(args)
        return '4242\n'

    def channel(self, service, timeout=20):
        assert service.startswith('localabstract:scrcpy_')
        channel = self.channel_

        class Context:
            def __enter__(self):
                return channel

            def __exit__(self, *args):
                return False
        return Context()


def _encoded(size, count):
    av = pytest.importorskip('av')
    if 'libx264' not in av.codecs_available:
        pytest.skip('this PyAV has no H.264 encoder to make a stream with')
    encoder = av.CodecContext.create('libx264', 'w')
    encoder.width, encoder.height, encoder.pix_fmt = size[0], size[1], 'yuv420p'
    encoder.time_base = Fraction(1, 30)
    encoder.options = {'tune': 'zerolatency', 'preset': 'ultrafast'}
    packets = []
    for index in range(count):
        frame = av.VideoFrame.from_image(Image.new('RGB', size, (index * 20, 40, 80)))
        frame.pts = index
        packets += [bytes(p) for p in encoder.encode(frame)]
    packets += [bytes(p) for p in encoder.encode(None)]
    return packets


def _stream(size, packets, codec=0x68323634):
    data = b'\0' + struct.pack('>III', codec, *size)
    for pts, packet in enumerate(packets):
        data += struct.pack('>QI', pts, len(packet)) + packet
    return data


def test_the_scrcpy_video_is_decoded_into_pictures(monkeypatch):
    from workstation.native_android import video as V
    size = (64, 128)
    packets = _encoded(size, 6)
    channel = Channel(_stream(size, packets))
    adb = Adb(channel)
    monkeypatch.setattr(V, 'install', lambda adb, jar: '/data/local/tmp/server.jar')
    video = V.ScrcpyVideo(adb, 'unused.jar', who='someone')
    pictures = []
    original = video._read

    def read(channel, decoder):
        try:
            original(channel, decoder)
        finally:
            pictures.append(video.serial)
    monkeypatch.setattr(video, '_read', read)
    video.want()
    video.thread.join(timeout=10)
    assert pictures and pictures[0] >= 1, "no frame of the stream was decoded"
    launched = ' '.join(adb.commands[-1])
    for option in ('video=true', 'control=false', 'video_codec=h264', 'max_size=1280', 'max_fps=30'):
        assert option in launched


def test_a_frame_is_shown_while_the_stream_runs(monkeypatch):
    from workstation.native_android import video as V
    size = (64, 128)
    packets = _encoded(size, 4)
    gate = threading.Event()

    class Held(Channel):
        def read(self, count):
            if self.data.tell() >= len(self.data.getvalue()):
                gate.wait(5)  # the screen is still: the stream waits for its next frame
            return super().read(count)
    channel = Held(_stream(size, packets))
    monkeypatch.setattr(V, 'install', lambda adb, jar: '/data/local/tmp/server.jar')
    video = V.ScrcpyVideo(Adb(channel), 'unused.jar')
    video.want()
    end = time.monotonic() + 10
    while video.picture() is None and time.monotonic() < end:
        time.sleep(.02)
    got = video.picture()
    assert got is not None, "the decoded frame was not offered while the stream ran"
    image, serial = got
    assert image.size == size and image.mode == 'RGB' and serial >= 1
    gate.set()
    video.close()


def test_a_host_without_pyav_streams_by_screenshot_and_says_so_once(monkeypatch, caplog):
    from workstation.native_android import video as V
    video = V.ScrcpyVideo(Adb(Channel(b'')), 'unused.jar', who='someone', decoder=lambda: None)
    with caplog.at_level('WARNING'):
        video.want()
        video.thread.join(timeout=5)
        video.want()
    assert video.thread is None or not video.thread.is_alive()
    assert video.picture() is None
    assert sum('PyAV' in record.getMessage() for record in caplog.records) == 1


def test_a_video_that_cannot_encode_falls_back_and_waits_before_trying_again(monkeypatch, caplog):
    from workstation.native_android import video as V
    monkeypatch.setattr(V, 'install', lambda adb, jar: '/data/local/tmp/server.jar')
    monkeypatch.setattr(V, 'READY_S', 0)
    adb = Adb(Channel(_stream((64, 128), [], codec=1)))
    video = V.ScrcpyVideo(adb, 'unused.jar', who='someone', decoder=lambda: object())
    with caplog.at_level('WARNING'):
        video.want()
        video.thread.join(timeout=5)
    assert video.failed_at is not None and video.picture() is None
    first = video.thread
    video.want()
    assert video.thread is first, "a failed stream was started again at once"
    assert any('did not start' in record.getMessage() for record in caplog.records)


def test_a_stream_nobody_watches_stops(monkeypatch):
    from workstation.native_android import video as V
    monkeypatch.setattr(V, 'IDLE_S', 0)
    channel = Channel(_stream((64, 128), [b'\0\0\0\1'] * 3))
    monkeypatch.setattr(V, 'install', lambda adb, jar: '/data/local/tmp/server.jar')
    decoded = []
    decoder = SimpleNamespace(decode=lambda packet: decoded.append(packet) or [])
    video = V.ScrcpyVideo(Adb(channel), 'unused.jar', decoder=lambda: decoder, packet=lambda data: data)
    video.wanted_at = time.monotonic() - 1
    video.want()
    video.wanted_at = time.monotonic() - 1  # nobody has asked since
    video.thread.join(timeout=5)
    assert not video.running and video.failed_at is None


def test_the_codec_parameters_go_with_the_next_frame(monkeypatch):
    from workstation.native_android import video as V
    monkeypatch.setattr(V, 'install', lambda adb, jar: '/data/local/tmp/server.jar')
    data = b'\0' + struct.pack('>III', 0x68323634, 64, 128)
    data += struct.pack('>QI', 1 << 63, 3) + b'SPS'
    data += struct.pack('>QI', 7, 5) + b'FRAME'
    data += struct.pack('>QI', 8, 4) + b'NEXT'
    decoded = []
    decoder = SimpleNamespace(decode=lambda packet: decoded.append(packet) or [])
    video = V.ScrcpyVideo(Adb(Channel(data)), 'unused.jar', decoder=lambda: decoder, packet=lambda data: data)
    video.want()
    video.thread.join(timeout=5)
    assert decoded == [b'SPSFRAME', b'NEXT']


def test_the_phone_stops_its_video_with_android():
    from workstation.native_android import host
    import inspect
    stop = inspect.getsource(host.NativePhone._stop_locked)
    assert 'video.close()' in stop
