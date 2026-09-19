from __future__ import annotations
from datetime import datetime
from pathlib import Path
import os, subprocess, zipfile
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QFrame,QHBoxLayout,QLabel,QLineEdit,QMainWindow,QPushButton,QStackedWidget,QVBoxLayout,QWidget,QComboBox
from phonehub.core.command import SubprocessRunner
from phonehub.core.state import AppState
from phonehub.core.workers import Worker
from phonehub.domain.models import DeviceSnapshot,ConnectionState
from phonehub.services.config_service import ConfigService,DeviceConfig
from phonehub.services.adb_service import AdbService
from phonehub.services.media_service import MediaSessionManager
from phonehub.services.discovery_service import DiscoveryService
from phonehub.ui.theme import APP_STYLE

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PhoneHub 5.0"); self.resize(1180,760); self.setMinimumSize(960,620); self.setStyleSheet(APP_STYLE)
        self.state=AppState(); self.state.device_changed.connect(self.render)
        self.configs=ConfigService(); self.cfg=self.configs.load(); self.runner=SubprocessRunner(); self.adb=AdbService(self.runner); self.discovery=DiscoveryService(self.runner); self.media=MediaSessionManager()
        self.pool=QThreadPool.globalInstance(); self.workers=set()
        shell=QWidget(); self.setCentralWidget(shell); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(self.sidebar()); root.addWidget(self.content(),1); self.render(self.state.device)
        if self.cfg.serial: self.auto_connect()
        else: self.auto_discover()

    def sidebar(self):
        s=QFrame(); s.setObjectName("Sidebar"); s.setFixedWidth(218); l=QVBoxLayout(s); l.setContentsMargins(18,22,18,18); l.setSpacing(7)
        b=QLabel("PhoneHub"); b.setObjectName("Brand"); l.addWidget(b); q=QLabel("Device Command Center"); q.setObjectName("Muted"); l.addWidget(q); l.addSpacing(22)
        self.stack=QStackedWidget(); self.nav=[]
        pages=[("Overview",self.overview),("Device",self.device_page),("Screen",self.screen_page),("Camera",self.camera_page),("Files",self.files_page),("Security",self.security_page),("Settings",self.settings_page)]
        for i,(name,fn) in enumerate(pages):
            x=QPushButton(name); x.setObjectName("Nav"); x.setCheckable(True); x.clicked.connect(lambda _,n=i:self.select(n)); l.addWidget(x); self.nav.append(x); self.stack.addWidget(fn())
        l.addStretch(); self.badge=QLabel("● Offline"); self.badge.setObjectName("Muted"); l.addWidget(self.badge); self.select(0); return s

    def content(self):
        w=QWidget(); l=QVBoxLayout(w); l.setContentsMargins(28,24,28,20); l.addWidget(self.stack); return w
    def select(self,n):
        self.stack.setCurrentIndex(n)
        for i,b in enumerate(self.nav): b.setChecked(i==n)
    def title(self,l,text,sub):
        h=QLabel(text); h.setObjectName("PageTitle"); l.addWidget(h); s=QLabel(sub); s.setObjectName("Muted"); s.setWordWrap(True); l.addWidget(s)
    def card(self,title,body=""):
        c=QFrame(); c.setObjectName("Card"); l=QVBoxLayout(c); l.setContentsMargins(18,16,18,18); h=QLabel(title); h.setStyleSheet("font-size:16px;font-weight:750;"); l.addWidget(h)
        if body: q=QLabel(body); q.setObjectName("Muted"); q.setWordWrap(True); l.addWidget(q)
        return c,l
    def overview(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(16); self.title(l,"Overview","Phone, transport and media status in one place.")
        c,cl=self.card("Device status"); self.device_metric=QLabel("Not connected"); self.device_metric.setObjectName("Metric"); cl.addWidget(self.device_metric); self.detail=QLabel("Configure Device to begin."); self.detail.setObjectName("Muted"); cl.addWidget(self.detail); l.addWidget(c)
        row=QHBoxLayout()
        for a,b in [("Transport","Tailscale + ADB"),("Media","One session owner"),("Safety","Explicit controls only")]: row.addWidget(self.card(a,b)[0])
        l.addLayout(row); l.addStretch(); return w
    def device_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Device","Connect your phone over its Tailscale IPv4 address.")
        c,cl=self.card("Connection"); self.ip=QLineEdit(self.cfg.phone_ip); self.ip.setPlaceholderText("100.x.x.x"); cl.addWidget(self.ip)
        row=QHBoxLayout(); d=QPushButton("Auto Detect"); d.setObjectName("Primary"); d.clicked.connect(self.auto_discover); row.addWidget(d); a=QPushButton("Save + Connect"); a.setObjectName("Primary"); a.clicked.connect(self.connect); row.addWidget(a); r=QPushButton("Refresh"); r.clicked.connect(self.refresh); row.addWidget(r); row.addStretch(); cl.addLayout(row)
        self.devmsg=QLabel("Ready"); self.devmsg.setObjectName("Muted"); cl.addWidget(self.devmsg); l.addWidget(c); l.addStretch(); return w
    def screen_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Screen","Open one controlled scrcpy screen session.")
        c,cl=self.card("Remote screen"); row=QHBoxLayout()
        for name,fn,obj in [("Open Screen",self.open_screen,"Primary"),("Wake",lambda:self.adb.key(self.cfg,224),""),("Home",lambda:self.adb.key(self.cfg,3),""),("Back",lambda:self.adb.key(self.cfg,4),""),("Close",self.stop_media,"Danger")]:
            b=QPushButton(name); b.setObjectName(obj); b.clicked.connect(fn); row.addWidget(b)
        cl.addLayout(row); self.screenmsg=QLabel("No active screen"); self.screenmsg.setObjectName("Muted"); cl.addWidget(self.screenmsg); l.addWidget(c); l.addStretch(); return w
    def camera_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Camera","Front and rear camera use the same exclusive media owner.")
        c,cl=self.card("Camera session"); row=QHBoxLayout()
        for name,face in [("Back Camera","back"),("Front Camera","front")]:
            b=QPushButton(name); b.setObjectName("Primary"); b.clicked.connect(lambda _,f=face:self.open_camera(f)); row.addWidget(b)
        x=QPushButton("Close"); x.setObjectName("Danger"); x.clicked.connect(self.stop_media); row.addWidget(x); row.addStretch(); cl.addLayout(row); self.cameramsg=QLabel("No active camera"); self.cameramsg.setObjectName("Muted"); cl.addWidget(self.cameramsg); l.addWidget(c); l.addStretch(); return w
    def files_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Files","Capture screenshots to your Pictures\\PhoneHub folder.")
        c,cl=self.card("Captures"); b=QPushButton("Take Screenshot"); b.setObjectName("Primary"); b.clicked.connect(self.capture); cl.addWidget(b); self.filemsg=QLabel("No capture yet"); self.filemsg.setObjectName("Muted"); cl.addWidget(self.filemsg); l.addWidget(c); l.addStretch(); return w
    def security_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Security","Read-only transport diagnostics. No hidden monitoring.")
        c,cl=self.card("Diagnostics"); b=QPushButton("Run Check"); b.clicked.connect(self.diagnostics); cl.addWidget(b); self.secmsg=QLabel("Not checked"); self.secmsg.setObjectName("Muted"); self.secmsg.setWordWrap(True); cl.addWidget(self.secmsg); l.addWidget(c); l.addStretch(); return w
    def settings_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Settings","Media quality settings apply to the next screen session.")
        c,cl=self.card("Screen quality"); self.quality=QComboBox(); self.quality.addItems(["720","1080","1440"]); self.quality.setCurrentText("1080"); cl.addWidget(self.quality); self.fps=QComboBox(); self.fps.addItems(["15","30","60"]); self.fps.setCurrentText("30"); cl.addWidget(self.fps); l.addWidget(c); l.addStretch(); return w
    def work(self,fn,done):
        w=Worker(fn); self.workers.add(w); w.signals.result.connect(done); w.signals.error.connect(lambda e:self.devmsg.setText(e)); w.signals.finished.connect(lambda:self.workers.discard(w)); self.pool.start(w)
    def auto_discover(self):
        self.devmsg.setText("Finding Tailscale phones…")
        self.work(self.discovery.adb_candidates,self._discovered)
    def _discovered(self,peers):
        if not peers:
            self.devmsg.setText("No online Tailscale phone found. Use Connect once.")
            return
        self._try_peer(peers,0)
    def _try_peer(self,peers,index):
        if index>=len(peers):
            self.devmsg.setText("Phones found, but none accepted ADB on port 5555.")
            return
        peer=peers[index]; cfg=DeviceConfig(peer.ip,5555)
        self.devmsg.setText(f"Trying {peer.name}…")
        self.work(lambda:self.adb.connect(cfg),lambda result:self._peer_result(peers,index,cfg,result))
    def _peer_result(self,peers,index,cfg,result):
        ok,msg=result
        if ok:
            self.cfg=self.configs.save(cfg); self.ip.setText(cfg.phone_ip); self.devmsg.setText("Connected automatically"); self.refresh()
        else:self._try_peer(peers,index+1)
    def auto_connect(self):
        self.devmsg.setText("Connecting remembered phone…")
        self.work(lambda:self.adb.connect(self.cfg),self.connected)
    def connect(self):
        try:self.cfg=self.configs.save(DeviceConfig(self.ip.text(),5555))
        except Exception as e:self.devmsg.setText(str(e)); return
        self.devmsg.setText("Connecting…"); self.work(lambda:self.adb.connect(self.cfg),self.connected)
    def connected(self,result):
        ok,msg=result; self.devmsg.setText(msg); self.refresh()
    def refresh(self): self.work(lambda:self.adb.snapshot(self.cfg),self.state.set_device)
    def ready(self):
        snap=self.adb.snapshot(self.cfg)
        if snap.state!=ConnectionState.ONLINE: self.state.set_device(snap); return False
        return True
    def open_screen(self):
        if not self.ready(): self.screenmsg.setText("Connect Device first"); return
        ok,msg=self.media.screen(self.cfg,int(self.quality.currentText()),int(self.fps.currentText())); self.screenmsg.setText(msg)
    def open_camera(self,face):
        if not self.ready(): self.cameramsg.setText("Connect Device first"); return
        ok,msg=self.media.camera(self.cfg,face); self.cameramsg.setText(msg)
    def stop_media(self):
        self.media.stop(); self.screenmsg.setText("Closed"); self.cameramsg.setText("Closed")
    def capture(self):
        if not self.ready(): self.filemsg.setText("Connect Device first"); return
        p=Path.home()/"Pictures"/"PhoneHub"/f"capture_{datetime.now():%Y%m%d_%H%M%S}.png"; self.work(lambda:self.adb.screenshot(self.cfg,p),lambda r:self.filemsg.setText(r[1]))
    def diagnostics(self):
        snap=self.adb.snapshot(self.cfg); scr="Found" if self.media.scrcpy else "Missing"; self.secmsg.setText(f"ADB target: {self.cfg.serial or '-'}\nState: {snap.state.value}\nTransport: {snap.transport}\nscrcpy: {scr}")
    def render(self,s:DeviceSnapshot):
        self.device_metric.setText(s.device_name); battery=f" • {s.battery_percent}%" if s.battery_percent is not None else ""; self.detail.setText(f"{s.detail}{battery} • Android {s.android_version}"); self.badge.setText(f"● {s.state.value.title()}")
        if hasattr(self,"devmsg"): self.devmsg.setText(s.detail)
    def closeEvent(self,event):
        self.media.stop(); super().closeEvent(event)
