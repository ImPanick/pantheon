# SPDX-License-Identifier: AGPL-3.0-or-later
"""One pixel transform for streamed frames, agent screenshots, marks and input."""
from __future__ import annotations
import io
import threading
import time
import re
from workstation.phone import PhoneError
from .adb import AdbError
from .control import raw_capture, MAX_PIXELS
from workstation import protocol as P

# X11 keysyms to Android keycodes; printable Unicode uses the same clipboard
# transport as agent typing. Modifiers remain key events for shortcuts.
KEYS = {0xff08:67,0xff09:61,0xff0d:66,0xff1b:111,0xffff:112,0xff50:122,0xff57:123,
        0xff51:21,0xff52:19,0xff53:22,0xff54:20,0xff55:92,0xff56:93,
        0xffe1:59,0xffe2:60,0xffe3:113,0xffe4:114,0xffe9:57,0xffea:58,
        0xffeb:117,0xffec:118}
NAMES={'Return':66,'Enter':66,'Tab':61,'Escape':111,'BackSpace':67,'Delete':112,
       'Left':21,'Right':22,'Up':19,'Down':20,'Home':122,'End':123,'space':62}
MODIFIERS={'ctrl':(113,0x1000),'Control_L':(113,0x1000),'alt':(57,2),'shift':(59,1),'super':(117,0x10000)}


def normalize_viewport(image, text):
    """Map SurfaceFlinger pixels onto the default logical input display."""
    lines=[line for line in text.splitlines() if 'Viewport INTERNAL: displayId=0,' in line and 'isActive=[1]' in line]
    if not lines:raise ValueError('Android has no active default display viewport.')
    line=lines[0]
    def values(label,count):
        match=re.search(re.escape(label)+r'=\[([0-9, ]+)\]',line)
        result=[int(value.strip()) for value in match[1].split(',')] if match else []
        if len(result)!=count:raise ValueError('Invalid Android viewport geometry.')
        return result
    l,t,r,b=values('physicalFrame',4);x,y,right,bottom=values('logicalFrame',4)
    w,h=values('deviceSize',2)
    found=re.search(r'orientation=([0-3])(?:,| )',line)
    if not found or not (0<=l<r<=w and 0<=t<b<=h and x==y==0 and 0<right<=8192 and 0<bottom<=8192 and right*bottom<=MAX_PIXELS):
        raise ValueError('Android viewport leaves its physical display.')
    # Recent screencap emits the logical display after wm size; older builds
    # emit the physical panel with letterboxing. Both share logical input coords.
    if image.size==(right,bottom):return image.copy()
    # Android already rotates deviceSize and physicalFrame into display space.
    if image.size!=(w,h):raise ValueError('Android capture and input display disagree.')
    return image.crop((l,t,r,b)).resize((right,bottom))


class Screen:
    desktop_kind='kasmvnc'  # The pinned Kasm viewer's wire dialect, not a desktop daemon.
    def __init__(self,phone):
        self.phone=phone;self.size=self.physical=None
        self.lock=threading.RLock();self.cache=None;self.cached_at=0
        self.viewport=None;self.viewport_key=None;self.viewport_at=0;self.viewport_signature=None
        self.gestures={};self.key_states={};self.last_point=None

    @property
    def width(self): return (self.size or self.phone.screen_size())[0]
    @property
    def height(self): return (self.size or self.phone.screen_size())[1]

    def refresh(self):
        with self.lock:
            try: image=raw_capture(self.phone.direct)
            except AdbError as error: raise PhoneError('unavailable',str(error)) from error
            device=P.PHONE_DEVICES.get(getattr(self.phone,'device',None),{})
            if device.get('kind')=='foldable' and self.phone.posture=='closed':
                key=(image.size,self.phone.device,self.phone.posture,self.phone.rotation)
                if key!=self.viewport_key or time.monotonic()-self.viewport_at>1:
                    text=self.phone.direct.shell(['dumpsys','input'],timeout=5)
                    try:active=normalize_viewport(image,text)
                    except ValueError as error:raise PhoneError('unavailable',str(error)) from error
                    expected=(device['cover_width'],device.get('cover_height',device['height']))
                    if active.size not in (expected,expected[::-1]):raise PhoneError('unavailable','Android is still changing its cover viewport.')
                    signature=(next(line for line in text.splitlines() if 'Viewport INTERNAL: displayId=0,' in line and 'isActive=[1]' in line),image.size)
                    if self.viewport_signature is not None and signature!=self.viewport_signature:
                        self.release_all()
                        import secrets
                        self.phone.generation=secrets.token_hex(16)
                    self.viewport_signature=signature
                    self.viewport,self.viewport_key,self.viewport_at=text,key,time.monotonic()
                    image=active
                else:
                    try:image=normalize_viewport(image,self.viewport)
                    except ValueError as error:raise PhoneError('unavailable',str(error)) from error
            else:self.viewport_key=None;self.viewport_signature=None
            physical=image.size
            image.thumbnail((1280,1100))
            if self.physical is not None and physical!=self.physical:
                self.physical,self.size=physical,image.size
                self.last_point=None
                self.release_all()
                import secrets
                self.phone.generation=secrets.token_hex(16)
            self.physical,self.size=physical,image.size
            self.cache=image;self.cached_at=time.monotonic()
            return image

    def frame(self):
        with self.phone.lock,self.lock:
            self.phone._active()
            if not self.phone.stream_ready(): raise PhoneError('unavailable','Android has no live display.')
            self.phone.touch()
            image=self.refresh() if time.monotonic()-self.cached_at>.20 else self.cache
            return image.copy(),(self.phone.generation,self.size,self.physical)

    def grab(self,fmt):
        with self.phone.lock,self.lock:
            image,_=self.frame();out=io.BytesIO()
            image.save(out,format='JPEG' if fmt=='jpeg' else 'PNG',**({'quality':85} if fmt=='jpeg' else {}))
            return out.getvalue(),'image/jpeg' if fmt=='jpeg' else 'image/png'

    def point(self,x,y):
        if self.size is None or self.physical is None: self.refresh()
        w,h=self.size;pw,ph=self.physical
        if not (0<=x<w and 0<=y<h): raise PhoneError('bad_request','Touch leaves the Android screen.')
        return min(pw-1,int(x*pw/w)),min(ph-1,int(y*ph/h)),pw,ph

    def touch(self,action,x,y):
        self.phone.control.touch(action,*self.point(x,y))

    def release(self,session):
        with self.lock:
            old=self.gestures.pop(session,None)
            if old and self.phone.control:
                try:self.touch(1,min(self.width-1,old[0]),min(self.height-1,old[1]))
                except (AdbError,PhoneError):pass
            for code in self.key_states.pop(session,set()):
                if self.phone.control:
                    try:self.phone.control.key(code,down=False)
                    except AdbError:pass

    def release_all(self):
        with self.lock:
            for session in set(self.gestures)|set(self.key_states): self.release(session)

    def rfb_event(self,event,session,holder):
        with self.phone.lock,self.lock:
            self.phone._on()
            if event['geometry']!=(self.phone.generation,self.size,self.physical):
                self.release(session);raise PhoneError('unavailable','The Android display changed. Reconnect before touching it.')
            if holder()!='person':
                self.release(session);return
            self.phone.touch()
            control=self.phone.control
            try:
                if event['kind']=='pointer':
                    buttons,x,y=event['buttons'],event['x'],event['y']
                    old=self.gestures.get(session)
                    if buttons&1:
                        self.touch(2 if old else 0,x,y);self.gestures[session]=(x,y)
                    elif old:self.touch(1,x,y);self.gestures.pop(session,None)
                    if buttons&2:control.press(3)
                    if buttons&4:control.press(4)
                    dx,dy=event.get('scroll_x',0),event.get('scroll_y',0)
                    if dx or dy:control.scroll(*self.point(x,y),dx,dy)
                    if buttons&0x78:
                        dx=(1 if buttons&64 else -1 if buttons&32 else 0)
                        dy=(1 if buttons&16 else -1 if buttons&8 else 0)
                        self.swipe(x,y,dx,dy)
                elif event['kind']=='text':control.text(event['text'])
                else:
                    symbol,down=event['keysym'],event['down']
                    code=KEYS.get(symbol)
                    if code is None and (48<=symbol<=57 or 65<=symbol<=90 or 97<=symbol<=122):
                        code=7+symbol-48 if symbol<=57 else 29+ord(chr(symbol).lower())-97
                    if code is not None:
                        state=self.key_states.setdefault(session,set())
                        state.add(code) if down else state.discard(code)
                        meta=(1 if state & {59,60} or 65<=symbol<=90 else 0) | (0x1000 if state & {113,114} else 0) | (2 if state & {57,58} else 0) | (0x10000 if state & {117,118} else 0)
                        control.key(code,down=down,meta=meta)
                    elif down and (32<=symbol<=126 or 160<=symbol<=255 or symbol&0xff000000==0x01000000):
                        value=chr(symbol&0xffffff) if symbol>0xff else chr(symbol)
                        control.text(value)
            except (AdbError,ValueError) as error: raise PhoneError('unavailable',str(error)) from error

    def swipe(self,x,y,dx,dy):
        w,h=self.size
        end_x=max(0,min(w-1,x-int(dx*max(40,w//5))))
        end_y=max(0,min(h-1,y-int(dy*max(40,h//5))))
        self.touch(0,x,y)
        try:
            for step in range(1,9):
                self.touch(2,round(x+(end_x-x)*step/8),round(y+(end_y-y)*step/8));time.sleep(.015)
        finally:self.touch(1,end_x,end_y)

    def send(self,act):
        with self.phone.lock,self.lock:
            self.phone._on();control=self.phone.control
            try:
                name=act['action'];old_x,old_y=self.last_point or (self.width//2,self.height//2)
                x=act.get('x',old_x);y=act.get('y',old_y)
                if 'x' in act or 'y' in act:self.last_point=(x,y)
                if name=='type':control.text(act['text'])
                elif name=='key':
                    parts=act['keys'].split('+');modifiers=parts[:-1];key=parts[-1];meta=0;held=[]
                    try:
                        for modifier in modifiers:
                            if modifier not in MODIFIERS: raise PhoneError('bad_request','This keyboard modifier is not supported on Android.')
                            code,mask=MODIFIERS[modifier];meta|=mask;control.key(code,meta=meta);held.append(code)
                        code=NAMES.get(key)
                        if code is None and len(key)==1 and key.isascii() and key.isalnum():
                            code=7+ord(key)-48 if key.isdigit() else 29+ord(key.lower())-97
                        if code is not None:control.press(code,meta=meta)
                        elif not modifiers and len(key)==1:control.text(key)
                        else:raise PhoneError('bad_request','This key is not supported on Android.')
                    finally:
                        for code in reversed(held):control.key(code,down=False)
                elif name in ('click','double_click','triple_click'):
                    for _ in range({'click':1,'double_click':2,'triple_click':3}[name]):self.touch(0,x,y);self.touch(1,x,y)
                elif name=='right_click':control.press(4)
                elif name=='middle_click':control.press(3)
                elif name=='scroll':self.swipe(x,y,act['dx'],act['dy'])
                elif name=='drag':
                    self.touch(0,x,y)
                    try:
                        for step in range(1,17):
                            self.touch(2,round(x+(act['to_x']-x)*step/16),round(y+(act['to_y']-y)*step/16));time.sleep(.015)
                    finally:self.touch(1,act['to_x'],act['to_y'])
                elif name=='mouse_down':self.touch(0,x,y);self.gestures['agent']=(x,y)
                elif name=='mouse_up':
                    if 'agent' in self.gestures:self.gestures['agent']=(x,y)
                    self.release('agent')
                elif name=='move' and 'agent' in self.gestures:self.touch(2,x,y);self.gestures['agent']=(x,y)
            except AdbError as error:raise PhoneError('unavailable',str(error)) from error
