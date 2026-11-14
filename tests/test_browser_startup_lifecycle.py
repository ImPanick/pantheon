# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real subprocess pipes cannot hold browser/phone startup hostage.

Python children stand in for Firefox at the Popen boundary. Their pipes,
processes, deadlines, cancellation and cleanup are real; BiDi and the phone
display remain explicit fixtures. These tests do not run Firefox or Android.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from workstation import browser as B
from workstation import phone as PH


class Task:
    def __init__(self, call):
        self.value = None
        self.error = None
        self.done = threading.Event()

        def work():
            try:
                self.value = call()
            except BaseException as error:
                self.error = error
            finally:
                self.done.set()

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()


@pytest.fixture
def children(tmp_path, monkeypatch):
    """Change only Firefox's launch argv; retain real Popen and process groups."""
    original_popen = subprocess.Popen
    scripts, processes, browsers, tasks, ports = deque(), [], [], [], []

    def launch(argv, **kwargs):
        assert scripts, "Unexpected additional browser process"
        assert kwargs.get("start_new_session") is True
        proc = original_popen([sys.executable, "-u", "-c", scripts.popleft()], **kwargs)
        processes.append(proc)
        return proc

    class Session:
        closed = False

        def __init__(self, host, port):
            assert host == "127.0.0.1"
            ports.append(port)

        def start(self):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(B.subprocess, "Popen", launch)
    monkeypatch.setattr(B, "find_firefox", lambda: sys.executable)
    monkeypatch.setattr(B, "Session", Session)
    monkeypatch.setattr(B, "START_TIMEOUT_S", 0.25)

    def make(script):
        scripts.append(script)
        browser = B.AccountBrowser([], dict(os.environ), tmp_path / f"profile-{len(browsers)}", True)
        # Profile no-follow behavior has its own Linux tests. This fixture
        # makes the unrelated profile write portable to Windows too.
        def profile_file(name, text):
            path = browser.profile / name
            path.write_text(text, encoding="utf-8")
            return path
        browser._write_profile_file = profile_file
        browser._contexts = lambda: [{"context": "fixture-context"}]
        browser._viewport = lambda context: None
        browsers.append(browser)
        return browser

    def start(browser, *, hold_lock=False):
        def call():
            with browser.lock if hold_lock else contextlib.nullcontext():
                return browser.start()
        task = Task(call)
        tasks.append(task)
        return task

    yield SimpleNamespace(make=make, start=start, processes=processes, ports=ports)
    # Even a regression must not leave a hanging child or test thread behind.
    for browser in browsers:
        if hasattr(browser, "cancel_start"):
            browser.cancel_start()
    for proc in processes:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    for task in tasks:
        task.thread.join(2)
    for browser in browsers:
        browser.stop()


@pytest.mark.parametrize("script", [
    "import time; time.sleep(5)",
    "import sys,time; sys.stdout.write('partial startup without newline'); sys.stdout.flush(); time.sleep(5)",
    "import sys,time\nfor _ in range(100):\n sys.stdout.write('x'); sys.stdout.flush(); time.sleep(.04)",
    "import sys,time\nfor _ in range(100):\n print('still starting',flush=True); time.sleep(.04)",
], ids=["silent", "partial-line", "trickled-partial", "trickled-lines"])
def test_real_silent_partial_and_trickling_pipes_obey_the_absolute_start_deadline(children, script):
    browser = children.make(script)
    before = time.monotonic()
    task = children.start(browser, hold_lock=True)
    assert task.done.wait(1.2), "Startup blocked on a child pipe past its 0.25-second deadline"
    assert time.monotonic() - before < 1.2
    assert isinstance(task.error, B.BrowserError) and task.error.code == "unavailable"
    assert children.processes and all(proc.poll() is not None for proc in children.processes)
    assert not browser.running() and not children.ports


def test_fragmented_port_digits_are_not_used_before_the_line_is_complete(children):
    browser = children.make(
        "import sys,time; sys.stdout.write('WebDriver BiDi listening on ws://127.0.0.1:1'); "
        "sys.stdout.flush(); time.sleep(.06); sys.stdout.write('2345\\n'); sys.stdout.flush(); time.sleep(5)")
    task = children.start(browser)
    assert task.done.wait(1.2)
    assert task.error is None, task.error
    assert children.ports == [12345] and browser.running()


def test_an_early_exit_reports_a_bounded_diagnostic_tail(children):
    browser = children.make("import sys; sys.stdout.write('first line\\n' + 'x'*12000 + ' LAST-CAUSE-MARKER\\n'); sys.stdout.flush(); sys.exit(23)")
    task = children.start(browser)
    assert task.done.wait(1.2)
    assert isinstance(task.error, B.BrowserError)
    assert "LAST-CAUSE-MARKER" in task.error.message
    assert len(task.error.message) <= 400
    assert children.processes[0].poll() is not None and not browser.running()


def test_cancellation_wakes_a_starter_that_holds_the_browser_lock(children, monkeypatch):
    monkeypatch.setattr(B, "START_TIMEOUT_S", 5.0)
    browser = children.make("import time; time.sleep(5)")
    task = children.start(browser, hold_lock=True)
    end = time.monotonic() + 1.0
    while browser.proc is None and time.monotonic() < end:
        task.done.wait(.005)
    assert browser.proc is not None
    cancel = Task(browser.cancel_start)
    assert cancel.done.wait(.25), "cancel_start waited for the lock held by startup"
    assert cancel.error is None
    assert task.done.wait(.7), "Cancellation did not wake the blocking startup"
    assert isinstance(task.error, B.BrowserError) and "cancel" in task.error.message.lower()
    assert children.processes[0].poll() is not None and not browser.running()


@pytest.mark.parametrize("phase", ["handshake", "session-new"])
@pytest.mark.parametrize("ignore_term", [False, True], ids=["normal-termination", "ignores-sigterm"])
def test_cancelling_a_real_process_wakes_real_bidi_startup_socket_waits(children, monkeypatch, phase, ignore_term):
    if ignore_term and not hasattr(os, "killpg"):
        pytest.skip("Ignoring SIGTERM and group escalation are POSIX-specific")
    from workstation.bidi import Session
    monkeypatch.setattr(B, "Session", Session)  # Actual BiDi socket and waiting-call implementation.
    monkeypatch.setattr(B, "START_TIMEOUT_S", 5.0)
    script = """
import socket,time,base64,hashlib,re,signal
"""
    if ignore_term:
        script += "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
    script += """
server=socket.socket(); server.bind(('127.0.0.1',0)); server.listen(1)
print('WebDriver BiDi listening on ws://127.0.0.1:'+str(server.getsockname()[1]),flush=True)
peer,_=server.accept(); request=peer.recv(8192)
"""
    if phase == "session-new":
        script += """
key=re.search(br'Sec-WebSocket-Key: ([^\\r\\n]+)',request).group(1)
accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
peer.sendall(b'HTTP/1.1 101 Switching Protocols\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\nSec-WebSocket-Accept: '+accept+b'\\r\\n\\r\\n')
peer.recv(8192)
"""
    script += "print('SOCKET-WAITING',flush=True); time.sleep(5)\n"
    browser = children.make(script)
    task = children.start(browser, hold_lock=True)
    end = time.monotonic() + 1.2
    while time.monotonic() < end:
        output = browser._output
        if output is not None and "SOCKET-WAITING" in output.last_words():
            break
        assert not task.done.is_set(), task.error
        task.done.wait(.005)
    else:
        pytest.fail("The real BiDi socket never reached its controlled blocking phase")
    session = browser.session
    cancel = Task(browser.cancel_start)
    assert cancel.done.wait(.25) and cancel.error is None
    assert task.done.wait(1.5 if ignore_term else .8), "Cancellation left a BiDi connect/session call waiting for its long timeout"
    assert isinstance(task.error, B.BrowserError) and task.error.code == "unavailable"
    assert children.processes[0].poll() is not None and not browser.running()
    if ignore_term:
        import signal
        assert children.processes[0].returncode == -signal.SIGKILL
    output.thread.join(.7)
    assert not output.thread.is_alive() and output.eof.is_set()
    if session is not None:
        session._reader.join(.7)
        assert session.closed and not session._reader.is_alive()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="Inherited same-group wrapper family is POSIX-specific")
def test_cancellation_kills_an_inherited_bidi_peer_even_after_the_wrapper_exits(children, monkeypatch, tmp_path):
    from workstation.bidi import Session
    monkeypatch.setattr(B, "Session", Session)
    monkeypatch.setattr(B, "START_TIMEOUT_S", 5.0)
    exit_marker = tmp_path / "release-family-fixture"
    script = f"""
import os,signal,socket,time,sys
exit_marker={str(exit_marker)!r}
child=os.fork()
if child:
 time.sleep(5)
 sys.exit(0)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
server=socket.socket(); server.bind(('127.0.0.1',0)); server.listen(1); server.settimeout(.1)
print('WebDriver BiDi listening on ws://127.0.0.1:'+str(server.getsockname()[1]),flush=True)
peer=None
end=time.monotonic()+5
while peer is None and not os.path.exists(exit_marker) and time.monotonic()<end:
 try: peer,_=server.accept()
 except socket.timeout: pass
if peer is not None:
 peer.settimeout(.1)
 request=b''
 while not request and not os.path.exists(exit_marker) and time.monotonic()<end:
  try: request=peer.recv(8192)
  except socket.timeout: pass
 print('INHERITED-BIDI-WAIT:'+str(os.getpid()),flush=True)
 while not os.path.exists(exit_marker) and time.monotonic()<end:
  time.sleep(.01)
 peer.close()
server.close()
"""
    browser = children.make(script)
    task = children.start(browser, hold_lock=True)
    child_pid = None
    try:
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            output = browser._output
            tail = output.last_words() if output is not None else ""
            if "INHERITED-BIDI-WAIT:" in tail:
                child_pid = int(tail.rsplit("INHERITED-BIDI-WAIT:", 1)[1].split()[0])
                break
            assert not task.done.is_set(), task.error
            task.done.wait(.005)
        else:
            pytest.fail("The inherited child never reached its real BiDi handshake wait")
        assert child_pid != children.processes[0].pid
        cancel = Task(browser.cancel_start)
        assert cancel.done.wait(.25) and cancel.error is None
        assert task.done.wait(1.5), "The reaped wrapper prevented escalation to its inherited BiDi peer"
        assert isinstance(task.error, B.BrowserError) and task.error.code == "unavailable"
        assert children.processes[0].poll() is not None
        output.thread.join(.7)
        assert output.eof.is_set() and not output.thread.is_alive()
        assert not exit_marker.exists(), "Test cleanup, rather than cancellation, released the child"
    finally:
        # A failing implementation is released through a fixture-owned file,
        # never by signalling a numeric descendant PID which might be reused.
        exit_marker.touch()
        task.thread.join(2)
        if child_pid is not None:
            try:
                os.waitpid(child_pid, 0)  # pytest as container PID1 may adopt the orphan
            except ChildProcessError:
                pass  # the host's init/subreaper owns and reaps it instead


class ObservedPipe:
    def __init__(self, pipe):
        self.pipe = pipe
        self.reads = 0

    def read1(self, size):
        self.reads += 1
        return self.pipe.read1(size) if hasattr(self.pipe, "read1") else self.pipe.read(size)

    def __getattr__(self, name):
        return getattr(self.pipe, name)


def test_an_old_output_reader_never_consumes_a_replacement_process_pipe(tmp_path):
    # The output worker must retain the process passed at construction, even
    # when its owner has moved on to a new producer.
    original_popen = subprocess.Popen
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                  start_new_session=True)
    old = original_popen([sys.executable, "-u", "-c",
                          "import time; time.sleep(.12); print('WebDriver BiDi listening on ws://127.0.0.1:12345',flush=True)"], **kwargs)
    new = original_popen([sys.executable, "-u", "-c",
                          "import time; print('WebDriver BiDi listening on ws://127.0.0.1:23456',flush=True); time.sleep(5)"], **kwargs)
    new.stdout = ObservedPipe(new.stdout)
    browser = B.AccountBrowser([], {}, tmp_path / "unused", True)
    browser.proc = old
    try:
        output = B._FirefoxOutput(old)
        browser._output = output
        browser.proc = new
        output.thread.join(1.2)
        assert not output.thread.is_alive() and output.port == 12345
        assert new.stdout.reads == 0 and new.poll() is None
        assert new.stdout.readline().startswith(b"WebDriver BiDi listening on ws://127.0.0.1:23456")
    finally:
        for proc in (old, new):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()


def test_timing_out_an_old_pipe_never_stops_or_clears_the_replacement_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "START_TIMEOUT_S", .2)
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                  start_new_session=True)
    old = subprocess.Popen([sys.executable, "-u", "-c", "import time; time.sleep(5)"], **kwargs)
    replacement = subprocess.Popen([sys.executable, "-u", "-c",
                                    "import time; print('replacement output',flush=True); time.sleep(5)"], **kwargs)
    replacement.stdout = ObservedPipe(replacement.stdout)
    browser = B.AccountBrowser([], {}, tmp_path / "unused", True)
    session = SimpleNamespace(closed=False)
    browser.proc, browser.session, browser.current = replacement, session, "replacement-context"
    output = B._FirefoxOutput(old)
    task = Task(lambda: browser._listening_port(proc=old, output=output, cancelled=threading.Event()))
    try:
        assert task.done.wait(1.0)
        assert isinstance(task.error, B.BrowserError)
        old.wait(timeout=.7)
        assert replacement.poll() is None and replacement.stdout.reads == 0
        assert browser.proc is replacement and browser.session is session
        assert session.closed is False and browser.current == "replacement-context"
    finally:
        for proc in (old, replacement):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
        task.thread.join(1)
        output.thread.join(1)
        for proc in (old, replacement):
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="Real SIGTERM-ignoring process is POSIX-specific")
def test_old_cancel_escalation_never_signals_a_replacement_process(tmp_path):
    import signal
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                  start_new_session=True)
    old = subprocess.Popen([sys.executable, "-u", "-c",
                            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                            "print('ignoring-term-ready',flush=True); time.sleep(5)"], **kwargs)
    replacement = subprocess.Popen([sys.executable, "-u", "-c", "import time; time.sleep(5)"], **kwargs)
    browser = B.AccountBrowser([], {}, tmp_path / "unused", True)
    try:
        assert old.stdout.readline().strip() == b"ignoring-term-ready"
        browser.proc = browser._startup_proc = old
        browser._startup_cancel = threading.Event()
        for _ in range(5):
            browser.cancel_start()
        # A delayed cancellation helper may retain only the old Popen, not
        # consult fields that now belong to a replacement startup.
        browser.proc = browser._startup_proc = replacement
        browser._startup_cancel = threading.Event()
        old.wait(timeout=1.5)
        assert old.returncode == -signal.SIGKILL
        assert replacement.poll() is None and browser.proc is replacement
        assert not browser._startup_cancel.is_set()
    finally:
        for proc in (old, replacement):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()


def test_windows_stop_never_calls_a_missing_killpg_while_kill_is_still_asynchronous(tmp_path, monkeypatch):
    class WindowsOS:
        def __getattr__(self, name):
            if name == "killpg":
                raise AttributeError(name)
            if name == "kill":
                raise AssertionError("Only captured fake Popen methods may signal this fixture")
            return getattr(os, name)

    class Process:
        # The OS facade refuses native signalling. Only these captured fake
        # Popen methods may act on the fixture; no host process is targeted.
        pid = 123456
        returncode = None
        kills = 0
        waits = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            pass  # asynchronous termination can still be pending

        def kill(self):
            self.kills += 1  # poll deliberately remains None until wait()

        def wait(self, timeout=None):
            self.waits += 1
            if self.kills:
                self.returncode = -9
                return self.returncode
            raise subprocess.TimeoutExpired("fixture-only", timeout)

    monkeypatch.setattr(B, "os", WindowsOS())
    browser = B.AccountBrowser([], {}, tmp_path / "unused", True)
    process = Process()
    browser.proc = process
    try:
        browser.stop()
        assert process.kills and process.waits and process.returncode is not None
        assert browser.proc is None
    finally:
        # Any asynchronous watcher must see this fake as already reaped even
        # if a failing assertion unwinds the OS facade monkeypatch.
        process.returncode = -9


class FixtureProcess:
    alive = True

    def poll(self):
        return None if self.alive else 0


@pytest.fixture
def phone_startup(tmp_path, monkeypatch):
    instances, workers, events = [], [], []
    plans = deque()

    class Mobile:
        def __init__(self, *args, **kwargs):
            plan = plans.popleft() if plans else {}
            self.blocked = plan.get("blocked", False)
            self.cooperative = plan.get("cooperative", True)
            self.fail = plan.get("fail", False)
            self.entered, self.release, self.cancelled = threading.Event(), threading.Event(), threading.Event()
            self.proc = None
            self.stops = 0
            self.navigations = []
            self.lock = threading.RLock()
            instances.append(self)

        def start(self, *, cancel=None):
            events.append(("start", self))
            self.entered.set()
            if self.blocked:
                while not self.release.wait(.01):
                    if self.cooperative and (self.cancelled.is_set() or (cancel is not None and cancel.is_set())):
                        raise B.BrowserError("unavailable", "fixture browser startup cancelled")
            if self.fail:
                raise B.BrowserError("unavailable", "fixture stale startup failure")
            self.proc = FixtureProcess()

        def cancel_start(self):
            self.cancelled.set()

        def stop(self):
            events.append(("stop", self))
            self.stops += 1
            self.cancel_start()
            if self.proc:
                self.proc.alive = False
            self.proc = None

        def _ctx(self):
            return "fixture-context"

        def _call(self, method, params, **kwargs):
            self.navigations.append((method, params))
            return {}

        def _act(self, action, params, **kwargs):
            self.navigations.append((action, params))
            return {}

    class Screen:
        desktop_kind = "kasmvnc"
        width, height = 400, 800

        def set_size(self, size):
            self.width, self.height = size

        def stop(self):
            events.append(("screen-stop", None))

    system = SimpleNamespace(backend="container", home=lambda account: tmp_path,
                             uid=lambda account: 12000, files_as=lambda account: contextlib.nullcontext(),
                             run_as=lambda account, **kwargs: ([], dict(os.environ)))
    monkeypatch.setattr(PH, "MobileView", Mobile)
    monkeypatch.setattr(PH, "tools_installed", lambda: False)
    monkeypatch.setattr(PH, "license_accepted", lambda: False)
    phone = PH.AccountPhone(system, "fixture-phone", Screen())
    phone.android_why = lambda: "Android requires an isolated VM"
    phone.mobile_why = lambda: None

    def launch(plan, *, wait_start=True):
        before = len(instances)
        plans.append(plan)
        phone.preview()
        worker = phone._booting
        workers.append(worker)
        end = time.monotonic() + 1.0
        while len(instances) <= before and time.monotonic() < end:
            time.sleep(.005)
        assert len(instances) > before
        if wait_start:
            assert instances[-1].entered.wait(1.0)
        return instances[-1], worker

    yield SimpleNamespace(phone=phone, instances=instances, launch=launch, events=events)
    for instance in instances:
        instance.release.set()
        instance.cancel_start()
    phone.stop()
    for worker in workers:
        worker.join(2)


def test_phone_status_screen_and_stop_remain_responsive_while_preview_start_blocks(phone_startup):
    fixture = phone_startup
    browser, worker = fixture.launch({"blocked": True})
    assert not worker.is_alive() or fixture.phone.state == "starting"
    for call in (fixture.phone.info, fixture.phone.ensure_shown):
        task = Task(call)
        assert task.done.wait(.3), "A preview startup held the phone lifecycle lock"
        assert task.error is None
    stop = Task(fixture.phone.stop)
    assert stop.done.wait(.7), "Stopping the phone waited for Firefox's startup timeout"
    assert stop.error is None
    worker.join(.7)
    assert not worker.is_alive() and fixture.phone.mobile is None and fixture.phone.state == "off"
    assert browser.cancelled.is_set() and browser.proc is None


def test_a_crashed_preview_releases_its_lifecycle_worker_and_display(phone_startup):
    fixture = phone_startup
    browser, worker = fixture.launch({})
    end = time.monotonic() + 1.0
    while fixture.phone.state == "starting" and time.monotonic() < end:
        time.sleep(.005)
    assert fixture.phone.state == "on" and browser.proc is not None
    screen_stops = fixture.events.count(("screen-stop", None))
    browser.proc.alive = False
    fixture.phone.ensure_shown()
    assert fixture.phone.mobile is None and fixture.phone.state == "off"
    worker.join(.7)
    assert not worker.is_alive(), "Dead preview left a worker holding its display ownership forever"
    assert browser.stops and browser.proc is None
    assert fixture.events.count(("screen-stop", None)) > screen_stops


@pytest.mark.parametrize("old_fails", [False, True], ids=["late-success", "late-failure"])
def test_a_stale_preview_worker_cannot_attach_navigate_or_stop_the_replacement(phone_startup, old_fails):
    fixture = phone_startup
    old, old_worker = fixture.launch({"blocked": True, "cooperative": False, "fail": old_fails})
    stopped = Task(fixture.phone.stop)
    assert stopped.done.wait(.5), "Stop could not detach the old preview startup"
    assert stopped.error is None
    new, new_worker = fixture.launch({}, wait_start=False)
    assert fixture.phone.mobile is new and fixture.phone.state == "starting"
    assert not new.entered.wait(.05), "Replacement reused a display the old startup still owned"
    old.release.set()
    old_worker.join(1)
    assert not old_worker.is_alive()
    assert new.entered.wait(1)
    end = time.monotonic() + 1.0
    while fixture.phone.state == "starting" and time.monotonic() < end:
        time.sleep(.005)
    assert fixture.phone.mobile is new and fixture.phone.state == "on"
    assert new.proc is not None and new.proc.poll() is None and new.stops == 0
    assert len(new.navigations) == 1, "The stale worker navigated the new browser"
    assert old.proc is None
    stopped_old = fixture.events.index(("stop", old))
    started_new = fixture.events.index(("start", new))
    assert stopped_old < started_new
    assert ("screen-stop", None) in fixture.events[stopped_old + 1:started_new]
