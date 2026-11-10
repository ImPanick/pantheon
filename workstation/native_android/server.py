# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticated phone-only host worker. It exposes no host file or shell API."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import logging
import secrets
import signal
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

from workstation import agentd,protocol as P
from workstation.phone import PhoneError
from .host import Host,write_private
from .rfb import WebSocketBytes,serve,StreamEnded,ProtocolError

logger=logging.getLogger(__name__)


class Station:
    authorised=agentd.Workstation.authorised
    check_account=staticmethod(agentd.Workstation.check_account)
    holder=agentd.Workstation.holder
    _phone_shot=staticmethod(agentd.Workstation._phone_shot)
    phone_screen=agentd.Workstation.phone_screen
    def __init__(self,host,token):
        self.system=host;self.phones=host;self.token=token
        self._holders={};self._lock=threading.RLock();self.run=secrets.token_hex(16)

    def phone(self,account,body):
        phone=self.phones.get(account)
        if not phone.lock.acquire(timeout=5):
            raise agentd.WorkstationError('busy','Another operation is using Android. Try again shortly.')
        try:
            # The inherited typed dispatcher checks the holder while the same
            # lock serializes takeover, input, profile changes and transfers.
            return agentd.Workstation.phone(self,account,body)
        finally:phone.lock.release()

    def choice(self,account,body):
        if body.get('holder') not in P.HOLDERS or (not isinstance(body.get('device'),str) or body.get('device') not in P.PHONE_DEVICES) or body.get('edition') not in P.PHONE_EDITIONS:
            raise agentd.WorkstationError('bad_request','Choose a device, edition and holder from the catalogue.')
        phone=self.phones.get(account)
        with phone.lock:
            phone._active()
            changed=(body['device'],body['edition'])!=(phone.device,phone.edition)
            if body.get('changing',False) not in (True,False):raise agentd.WorkstationError('bad_request','changing must be boolean.')
            if (changed or body.get('changing') is True) and body['holder']=='agent' and self.holder(account)['holder']=='person':
                raise agentd.WorkstationError('busy','A person has taken over Android. Wait for them to hand it back.')
            if changed:
                if phone.installer.running():raise agentd.WorkstationError('busy','Wait for the Android image install to finish.')
                phone._stop_locked()
                phone.device,phone.edition=body['device'],body['edition']
                phone._save_device()
            return phone.info('device')

    def control(self,account,body):
        who=body.get('holder')
        if who not in P.HOLDERS:raise agentd.WorkstationError('bad_request','holder is person or agent.')
        phone=self.phones.get(account)
        with phone.lock:
            phone.screen.release_all()
            with self._lock:
                import time
                self._holders[account]={'holder':who,'since':time.time()}
        return self.holder(account)


class Handler(agentd.Handler):
    def setup(self):
        super().setup();self.connection.settimeout(30)
        self.deadline=threading.Timer(8,self.expire);self.deadline.daemon=True;self.deadline.start()

    def expire(self):
        import socket
        try:self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        self.connection.close()

    def finish(self):
        self.deadline.cancel()
        super().finish()

    def _dispatch(self,method):
        self.deadline.cancel()
        self.deadline=threading.Timer(30,self.expire);self.deadline.daemon=True;self.deadline.start()
        upgraded=False
        try:
            if not self.station.authorised(self.headers.get('Authorization','')):
                raise agentd.WorkstationError('unauthorized','The Android host token is missing or wrong.')
            parts=urlsplit(self.path);path=parts.path.rstrip('/')
            if path=='/v1/health' and method=='GET':
                self._send(200,{'ok':True,'protocol':P.PROTOCOL_VERSION,'agent':P.AGENT_NAME,
                    'backend':'native_android','run':self.station.run,'accel':self.station.system.accel,
                    'why':self.station.system.why});return
            match=agentd._ROUTE_RE.fullmatch(path)
            if not match:raise agentd.WorkstationError('not_found','No such Android route.')
            account=self.station.check_account(match.group('account'));rest=match.group('rest')
            if method=='POST' and rest in ('phone','control','phone/choice'):
                body=self._body()
                self.deadline.cancel()
                answer={'phone':self.station.phone,'control':self.station.control,'phone/choice':self.station.choice}[rest](account,body)
                self._send(200,answer);return
            if method=='GET' and rest=='phone/screen':
                if self.headers.get('Upgrade','').lower()!='websocket':
                    self._send(200,self.station.phone_screen(account));return
                viewer=(parse_qs(parts.query).get('viewer') or ['person'])[0]
                if viewer not in P.DESKTOP_VIEWERS:raise agentd.WorkstationError('bad_request','Invalid phone viewer.')
                if (self.headers.get('Sec-WebSocket-Version')!='13' or
                    P.DESKTOP_SUBPROTOCOL not in [x.strip() for x in self.headers.get('Sec-WebSocket-Protocol','').split(',')]):
                    raise agentd.WorkstationError('bad_request','Invalid phone websocket protocol.')
                key=self.headers.get('Sec-WebSocket-Key','')
                if not agentd._WS_KEY_RE.fullmatch(key):raise agentd.WorkstationError('bad_request','Invalid websocket key.')
                phone=self.station.phones.get(account)
                with phone.lock:
                    if not phone.stream_ready():raise agentd.WorkstationError('unavailable','Android has no live display.')
                    if phone.watchers>=4:raise agentd.WorkstationError('busy','Too many phone viewers.')
                    phone.watchers+=1
                session=secrets.token_hex(16)
                try:
                    self.deadline.cancel()
                    self.protocol_version='HTTP/1.1';self.close_connection=True
                    self.send_response(101);self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade')
                    self.send_header('Sec-WebSocket-Accept',base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode())
                    self.send_header('Sec-WebSocket-Protocol',P.DESKTOP_SUBPROTOCOL);self.end_headers();upgraded=True
                    self.connection.settimeout(45)
                    serve(WebSocketBytes(self.rfile,self.wfile),phone.screen.frame,
                          lambda event:phone.screen.rfb_event(event,session,lambda:self.station.holder(account)['holder']) if viewer=='person' else None,
                          lambda:phone.screen.release(session))
                finally:
                    with phone.lock:phone.watchers-=1;phone.touch()
                return
            raise agentd.WorkstationError('not_found','No such Android route.')
        except agentd.WorkstationError as error:
            if not upgraded:self._fail(error)
        except PhoneError as error:
            if not upgraded:self._fail(agentd.WorkstationError(error.code,error.message))
        except ProtocolError as error:
            logger.warning('Android viewer protocol rejected: %s', error)
            self.close_connection=True
        except (StreamEnded,OSError,ConnectionError):
            self.close_connection=True
        except Exception:
            logger.exception('Android request failed')
            if not upgraded:self._fail(agentd.WorkstationError('internal','The Android host failed. Inspect its log.'))


def make_server(config):
    host=Host(config)
    token_path=Path(config['token_file'])
    if not token_path.exists():write_private(token_path,secrets.token_urlsafe(48))
    token=token_path.read_text().strip()
    if len(token)<32:raise RuntimeError('Android host token is too short.')
    class Bound(Handler):station=Station(host,token)
    class Server(ThreadingHTTPServer):
        daemon_threads=True;block_on_close=False
        slots=threading.BoundedSemaphore(24)
        def process_request(self,request,address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request);return
            try:super().process_request(request,address)
            except BaseException:self.slots.release();raise
        def process_request_thread(self,request,address):
            try:super().process_request_thread(request,address)
            finally:self.slots.release()
    server=Server((config.get('bind','127.0.0.1'),int(config.get('port',7993))),Bound)
    server.host=host
    if config.get('tls_cert') or config.get('tls_key'):
        if not (config.get('tls_cert') and config.get('tls_key')):
            raise RuntimeError('The Android host needs both TLS certificate and key.')
        context=agentd.server_context(Path(config['tls_cert']),Path(config['tls_key']))
        server.socket=context.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args();logging.basicConfig(level=logging.INFO)
    server=make_server(json.loads(args.config.read_text()))
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:server.serve_forever()
    finally:
        try:server.host.stop_all()
        finally:server.server_close()


if __name__=='__main__':main()
