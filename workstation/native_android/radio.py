"""Private radio transport for a dedicated Android VM.

Netsim listens only inside its own Docker network namespace. The host proxy admits one
fixed CONNECT target with a fresh secret, then uses Docker's trusted local exec
transport. It publishes no raw Netsim listener or Docker endpoint to a guest.
"""
from pathlib import Path
import base64
import hmac
import json
import os
import secrets
import socket
import socketserver
import subprocess
import threading
import time

IMAGE = "python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df"
TARGET = "pantheon-radio.invalid:7443"
PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n" + bytes.fromhex("000000040000000000")
RELAY = '''import socket,sys,threading
s=socket.create_connection(("127.0.0.1",7443),5)
s.settimeout(90)
def incoming():
 try:
  while True:
   b=sys.stdin.buffer.read1(65536)
   if not b:break
   s.sendall(b)
 finally:
  try:s.shutdown(socket.SHUT_WR)
  except OSError:pass
t=threading.Thread(target=incoming,daemon=True);t.start()
while True:
 b=s.recv(65536)
 if not b:break
 sys.stdout.buffer.write(b);sys.stdout.buffer.flush()
'''


class PrivateRadio:
    TARGET = TARGET
    def __init__(self, folder, binary, *, internet=False):
        self.folder = Path(folder)
        self.binary = Path(binary)
        self.internet = internet
        self.network = None
        self.name = "pantheon-android-radio-" + secrets.token_hex(5)
        self.secret = secrets.token_urlsafe(48)
        self.credential = b"Basic " + base64.b64encode(("radio:" + self.secret).encode())
        self.report = {"container": self.name, "network_mode": "none", "published_ports": [],
                       "authorized_connections": 0, "refused_connections": 0,
                       "transport": "authenticated_private_container"}
        self.server = None
        self.started = False
        self.connections = set()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(16)

    def docker(self, *args, **kwargs):
        return subprocess.run(["docker", *args], check=True, capture_output=True,
                              timeout=kwargs.pop("timeout", 30), **kwargs)

    def __enter__(self):
        binary = self.binary
        if not binary.is_file():
            raise RuntimeError("The licensed and verified private Netsim binary is absent.")
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            if self.internet:
                self.network=self.name+'-network'
                self.docker('network','create','--label','pantheon.android-radio='+self.name,self.network)
            mode=self.network or 'none'
            capabilities=['--cap-add=NET_ADMIN','--cap-add=SETPCAP','--cap-add=SETUID','--cap-add=SETGID'] if self.internet else []
            image='pantheon-android-radio:37.2.13' if self.internet else IMAGE
            command=['--internet'] if self.internet else ['/opt/netsimd','--grpc-port','7443','--hci-port','0','--no-web-ui','--no-cli-ui','--no-shutdown','--logtostderr']
            self.docker("run", "-d", "--name", self.name, "--pull=never", "--platform=linux/amd64",
                        "--label", "pantheon.android-radio=" + self.name,
                        "--network="+mode, "--read-only", "--cap-drop=ALL", *capabilities, "--security-opt=no-new-privileges",
                        "--log-driver=local", "--log-opt=max-size=1m", "--log-opt=max-file=2",
                        "--pids-limit=128", "--memory=384m", "--cpus=1", "--user", "0:0" if self.internet else str(getattr(os, "getuid", lambda: 1000)()) + ":" + str(getattr(os, "getgid", lambda: 1000)()),
                        "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777", "-e", "HOME=/tmp", "-e", "TMPDIR=/tmp",
                        "--mount", "type=bind,source=" + str(binary) + ",target=/opt/netsimd,readonly",
                        image, *command, timeout=90)
            self.started = True
            deadline = time.monotonic() + 25
            while True:
                state = json.loads(self.docker("inspect", self.name).stdout)[0]
                if not state["State"]["Running"]:
                    raise RuntimeError("Private Netsim exited: " + self.docker("logs", self.name).stdout.decode()[-3000:])
                try:
                    probe = "import socket;s=socket.create_connection(('127.0.0.1',7443),1);s.sendall(" + repr(PREFACE) + ");assert s.recv(100);s.close()"
                    self.docker("exec", "--user=0", self.name, "python3", "-c", probe, timeout=5)
                    break
                except subprocess.CalledProcessError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Private Netsim did not become ready.")
                    time.sleep(.25)
            time.sleep(2)
            state=json.loads(self.docker('inspect',self.name).stdout)[0]
            if not state['State']['Running']:
                raise RuntimeError('The Android radio stopped during its network initialization.')
            assert state["HostConfig"]["NetworkMode"] == mode
            self.report["network_mode"] = "internet_kernel_rules" if self.internet else "none"
            assert not state["NetworkSettings"]["Ports"]
            owner = self

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    relay = None
                    try:
                        with owner.lock:
                            owner.connections.add(self.request)
                        deadline = time.monotonic() + 5
                        header = bytearray()
                        # Read exactly the headers, leaving the HTTP/2 preface
                        # on the socket for the authenticated relay.
                        while not header.endswith(b"\r\n\r\n"):
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise ValueError("CONNECT header deadline exceeded")
                            self.request.settimeout(remaining)
                            byte = self.request.recv(1)
                            if not byte or len(header) >= 8192:
                                raise ValueError("Invalid CONNECT headers")
                            header.extend(byte)
                        rows = bytes(header).split(b"\r\n")
                        values = {}
                        for row in rows[1:-2]:
                            key, value = row.split(b":", 1)
                            key = key.strip().lower()
                            if key in values:
                                raise ValueError("Duplicate CONNECT header")
                            values[key] = value.strip()
                        if rows[0] != ("CONNECT " + TARGET + " HTTP/1.1").encode():
                            raise ValueError("Foreign CONNECT target")
                        if not hmac.compare_digest(values.get(b"proxy-authorization", b""), owner.credential):
                            raise ValueError("Missing proxy authentication")
                        if b"transfer-encoding" in values or values.get(b"content-length", b"0") != b"0":
                            raise ValueError("CONNECT request body")
                        owner.report["authorized_connections"] += 1
                        relay = subprocess.Popen(["docker", "exec", "--user=0", "-i", owner.name, "python3", "-u", "-c", RELAY],
                                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                        self.request.settimeout(90)

                        def incoming():
                            try:
                                while True:
                                    block = self.request.recv(65536)
                                    if not block:
                                        break
                                    relay.stdin.write(block)
                                    relay.stdin.flush()
                            except (OSError, ValueError):
                                pass
                            finally:
                                try:
                                    relay.stdin.close()
                                except OSError:
                                    pass

                        pump = threading.Thread(target=incoming, daemon=True)
                        pump.start()
                        while True:
                            block = relay.stdout.read1(65536)
                            if not block:
                                break
                            self.request.sendall(block)
                    except (OSError, ValueError):
                        if relay is None:
                            owner.report["refused_connections"] += 1
                            try:
                                self.request.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                            except OSError:
                                pass
                    finally:
                        with owner.lock:
                            owner.connections.discard(self.request)
                        if relay is not None:
                            relay.terminate()
                            try:
                                relay.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                relay.kill()
                                relay.wait(timeout=5)

            class Server(socketserver.ThreadingTCPServer):
                daemon_threads = True
                block_on_close = False

                def process_request(self, request, client_address):
                    if not owner.slots.acquire(blocking=False):
                        owner.report["refused_connections"] += 1
                        self.shutdown_request(request)
                        return
                    try:
                        super().process_request(request, client_address)
                    except BaseException:
                        owner.slots.release()
                        raise

                def process_request_thread(self, request, client_address):
                    try:
                        super().process_request_thread(request, client_address)
                    finally:
                        owner.slots.release()

            self.server = Server(("127.0.0.1", 0), Handler)
            self.port = self.server.server_address[1]
            self.report["authenticated_proxy_port"] = self.port
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.env = {"grpc_proxy": "http://radio:" + self.secret + "@127.0.0.1:" + str(self.port),
                        "no_grpc_proxy": ""}
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        cleanup_error = None
        try:
            if self.server is not None:
                self.server.shutdown()
                with self.lock:
                    connections = list(self.connections)
                for conn in connections:
                    try:
                        conn.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    conn.close()
                self.server.server_close()
        finally:
            # Even a timed-out docker run may have created its unique container.
            try:
                state = json.loads(self.docker("inspect", self.name).stdout)[0]
            except subprocess.CalledProcessError as e:
                if b"No such" not in e.stderr:
                    cleanup_error = "Could not determine whether the owned radio container remains."
                state = None
            except Exception:
                cleanup_error = "Could not inspect the owned radio container during cleanup."
                state = None
            if state is not None:
                if state["Config"].get("Labels", {}).get("pantheon.android-radio") != self.name:
                    cleanup_error = "The radio container ownership label changed; refusing removal."
                else:
                    try:
                        logs = self.docker("logs", "--tail=200", self.name)
                        (self.folder / "netsim-container.log").write_bytes(logs.stdout + logs.stderr)
                    except Exception:
                        self.report["cleanup_log_capture"] = "failed"
                    finally:
                        try:
                            self.docker("rm", "-f", self.name, timeout=45)
                            self.report["owned_container_removed"] = True
                        except Exception:
                            cleanup_error = "The owned radio container could not be removed."
            if self.network is not None:
                try:
                    network=json.loads(self.docker('network','inspect',self.network).stdout)[0]
                    if network.get('Labels',{}).get('pantheon.android-radio')!=self.name:
                        raise RuntimeError('The radio network ownership label changed.')
                    self.docker('network','rm',self.network)
                    self.report['owned_network_removed']=True
                except Exception:
                    cleanup_error='Could not remove the owned radio network.'
            self.report["cleanup_error"] = cleanup_error
            (self.folder / "radio-transport.json").write_text(json.dumps(self.report, indent=2) + "\n")
        if cleanup_error:
            raise RuntimeError(cleanup_error)
