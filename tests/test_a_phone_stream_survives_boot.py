# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phone's live screen stays up while Android boots.

The owner, 2026-11-17, first run of the android-vm service: *"got to see the
boot up though"*, then the viewer showed "Session Disconnected" partway
through the boot. Android's display is not steady while it starts: a capture
fails while SurfaceFlinger hands over from the boot animation, and the screen
changes size when boot completes (`wm size reset`). Each of those ended the
stream, and the pinned viewer gives up after five quick reconnects. What is
pinned:

  * a display that changes size mid-stream is resized in the stream
    (ExtendedDesktopSize, or DesktopSize), not ended;
  * a new geometry of the same size is adopted in the stream;
  * a viewer that can do neither still gets the old ending;
  * a capture that fails while Android still streams repeats the last picture;
  * input aimed at a display that has since changed is dropped, not fatal;
  * the phone's viewer never stops reconnecting on its own.
"""
from __future__ import annotations

import io
import struct
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from workstation.native_android import rfb


class Stream:
    def __init__(self, data):
        self.data = io.BytesIO(data)
        self.output = bytearray()

    def read(self, size):
        data = self.data.read(size)
        if len(data) != size:
            raise rfb.StreamEnded()
        return data

    def write(self, data):
        self.output.extend(data)


def request(w, h):
    return b'\3' + struct.pack('>BHHHH', 1, 0, 0, w, h)


def greeting(*encodings):
    return (b'RFB 003.008\n\1\1' + b'\2\0' + struct.pack('>H', len(encodings))
            + struct.pack('>' + 'i' * len(encodings), *encodings))


def frames(*answers):
    answers = iter(answers)
    return lambda: next(answers)


def jpeg_sizes(output):
    sizes, offset = [], 0
    while True:
        try:
            offset = output.index(b'\xff\xd8', offset)
        except ValueError:
            return sizes
        end = output.index(b'\xff\xd9', offset) + 2
        image = Image.open(io.BytesIO(output[offset:end]))
        image.load()
        sizes.append(image.size)
        offset = end


def test_a_display_that_changes_size_is_resized_in_the_stream():
    boot, final = Image.new('RGB', (320, 640)), Image.new('RGB', (360, 780))
    stream = Stream(greeting(7, -224, -308) + request(320, 640) * 2 + request(360, 780))
    with pytest.raises(rfb.StreamEnded):  # the script runs out, not the display
        # A new picture each time (`final.copy()`): an unchanged one is not sent again.
        rfb.serve(stream, frames((boot, 'boot'), (boot, 'boot'), (final, 'final'), (final.copy(), 'final')),
                  lambda _: None, lambda: None, frame_interval=0)
    output = bytes(stream.output)
    resize = (struct.pack('>HHHHi', 0, 0, 360, 780, -308) + b'\1\0\0\0'
              + struct.pack('>IHHHHI', 0, 0, 0, 360, 780, 0))
    assert output.count(resize) == 1
    assert jpeg_sizes(output) == [(320, 640), (360, 780), (360, 780)]
    assert output.index(resize) < output.rindex(b'\xff\xd8')


def test_a_viewer_with_only_desktop_size_is_resized_too():
    boot, final = Image.new('RGB', (320, 640)), Image.new('RGB', (360, 780))
    stream = Stream(greeting(7, -224, -223) + request(320, 640) * 2)
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, frames((boot, 'boot'), (boot, 'boot'), (final, 'final')),
                  lambda _: None, lambda: None, frame_interval=0)
    assert struct.pack('>HHHHi', 0, 0, 360, 780, -223) in bytes(stream.output)
    assert jpeg_sizes(bytes(stream.output)) == [(320, 640), (360, 780)]


def test_a_new_geometry_of_the_same_size_is_adopted_and_input_carries_it():
    image = Image.new('RGB', (320, 640))
    pointer = b'\5' + struct.pack('>HHHhh', 0, 10, 10, 0, 0)
    stream = Stream(greeting(7, -224, -308) + request(320, 640) + pointer + request(320, 640) + pointer)
    events = []
    with pytest.raises(rfb.StreamEnded):
        rfb.serve(stream, frames((image, 'one'), (image, 'one'), (image, 'two')),
                  events.append, lambda: None, frame_interval=0)
    assert [e['geometry'] for e in events] == ['one', 'two']
    assert len(jpeg_sizes(bytes(stream.output))) == 2


def test_a_viewer_that_cannot_resize_still_reconnects():
    boot, final = Image.new('RGB', (320, 640)), Image.new('RGB', (360, 780))
    stream = Stream(greeting(7, -224) + request(320, 640) * 2)
    with pytest.raises(rfb.StreamEnded, match='reconnect'):
        rfb.serve(stream, frames((boot, 'boot'), (boot, 'boot'), (final, 'final')),
                  lambda _: None, lambda: None, frame_interval=0)
    assert jpeg_sizes(bytes(stream.output)) == [(320, 640)]


def _screen(capture):
    from workstation.native_android import screen as S
    phone = SimpleNamespace(lock=threading.RLock(), generation='g', control=None, state='starting',
                            device='pixel_9', posture=None, rotation=0, direct=object(),
                            _active=lambda: None, touch=lambda: None, stream_ready=lambda: True)
    return S, S.Screen(phone), phone


def test_a_failed_capture_while_android_streams_repeats_the_last_picture(monkeypatch):
    from workstation.native_android.adb import AdbError
    S, screen, phone = _screen(None)
    answers = [Image.new('RGB', (360, 780), (9, 9, 9))]

    def capture(_):
        if answers:
            return answers.pop()
        raise AdbError('Android returned a truncated raw frame.')
    monkeypatch.setattr(S, 'raw_capture', capture)
    first, geometry = screen.frame()
    screen.cached_at = 0  # stale: the next frame asks Android again
    again, same = screen.frame()
    assert again.size == first.size and again.getpixel((0, 0)) == (9, 9, 9)
    assert same == geometry


def test_a_capture_that_fails_before_any_picture_still_fails(monkeypatch):
    from workstation.native_android.adb import AdbError
    from workstation.phone import PhoneError
    S, screen, phone = _screen(None)

    def capture(_):
        raise AdbError('Android returned a truncated raw frame.')
    monkeypatch.setattr(S, 'raw_capture', capture)
    with pytest.raises(PhoneError):
        screen.frame()


def test_a_stopped_phone_does_not_stream_its_last_picture(monkeypatch):
    from workstation.phone import PhoneError
    S, screen, phone = _screen(None)
    monkeypatch.setattr(S, 'raw_capture', lambda _: Image.new('RGB', (360, 780)))
    screen.frame()
    phone.stream_ready = lambda: False
    with pytest.raises(PhoneError, match='no live display'):
        screen.frame()


def test_input_aimed_at_a_changed_display_is_dropped_not_fatal():
    S, screen, phone = _screen(None)
    phone.state, phone.control = 'on', SimpleNamespace()
    phone._on = lambda: None
    screen.size, screen.physical = (100, 200), (1000, 2000)
    screen.gestures['viewer'] = (5, 5)
    released = []
    screen.release = lambda session: released.append(session)
    event = {'kind': 'pointer', 'buttons': 0, 'x': 1, 'y': 1, 'scroll_x': 0, 'scroll_y': 0,
             'geometry': ('old', (100, 200), (1000, 2000))}
    assert screen.rfb_event(event, 'viewer', lambda: 'person') is None
    assert released == ['viewer']


def test_the_phone_viewer_never_stops_reconnecting():
    from src import desktop_client as D
    query = parse_qs(urlsplit(D.page_url(stream=D.PHONE_STREAM_PATH)).query)
    assert query['reconnect'] == ['true']
    # The pinned client reads 0 as "no limit"; its default is five tries.
    assert query['reconnect_retries'] == ['0']


def test_android_is_kept_awake_once_it_has_booted(tmp_path, monkeypatch):
    # The emulator's own post-boot setup runs through adb, which this host
    # withholds from it (its log: "settings put system screen_off_timeout …
    # failed"). Left at Android's default, the screen sleeps a minute later and
    # the stream shows a dark or failing display; the host keeps it on itself.
    from tests.test_android_shows_its_own_boot_screen import Guest, _phone
    guest = Guest(["display", "done"])
    phone, proc, _ = _phone(tmp_path, monkeypatch, guest)
    phone._boot(proc)
    assert phone.state == "on"
    assert ("settings", "put", "system", "screen_off_timeout", "2147483647") in guest.asked
    assert ("svc", "power", "stayon", "true") in guest.asked
