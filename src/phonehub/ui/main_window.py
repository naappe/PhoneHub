from __future__ import annotations
from datetime import datetime
from pathlib import Path
import os, subprocess, zipfile
from PySide6.QtCore import QThreadPool,QTimer
from PySide6.QtWidgets import QFrame,QHBoxLayout,QLabel,QLineEdit,QMainWindow,QPushButton,QStackedWidget,QVBoxLayout,QWidget,QComboBox
from phonehub.core.command import SubprocessRunner
from phonehub.core.state import AppState
from phonehub.core.workers import Worker
from phonehub.domain.models import DeviceSnapshot,ConnectionState
from phonehub.services.config_service import ConfigService,DeviceConfig
from phonehub.services.adb_service import AdbService
from phonehub.services.media_service import MediaSessionManager
from phonehub.services.discovery_service import DiscoveryService
from phonehub.services.setup_service import SetupService
from phonehub.ui.theme import APP_STYLE

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("PhoneHub 6.0"); self.resize(1180,760); self.setMinimumSize(960,620); self.setStyleSheet(APP_STYLE)
        self.state=AppState(); self.state.device_changed.connect(self.render)
        self.configs=ConfigService(); self.cfg=self.configs.load(); self.runner=SubprocessRunner(); self.adb=AdbService(self.runner); self.discovery=DiscoveryService(self.runner); self.setup=SetupService(self.adb); self.media=MediaSessionManager()
        self.pool=QThreadPool.globalInstance(); self.workers=set(); self.screen_wanted=False; self.screen_watch_busy=False; self.screen_restarting=False; self.screen_user_closed=False; self.screen_started_once=False
        self.screen_watch=QTimer(self); self.screen_watch.setInterval(2500); self.screen_watch.timeout.connect(self._watch_screen)
        self.connection_watch=QTimer(self); self.connection_watch.setInterval(5000); self.connection_watch.timeout.connect(self.refresh); self.connection_watch.start()
        shell=QWidget(); self.setCentralWidget(shell); root=QHBoxLayout(shell); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(self.sidebar()); root.addWidget(self.content(),1); self.render(self.state.device)
        QTimer.singleShot(500,self.auto_setup)

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
        for a,b in [("Transport","Tailscale / PhoneHub Agent"),("ADB","Optional engineering tool"),("Safety","Protected controls")]: row.addWidget(self.card(a,b)[0])
        l.addLayout(row); l.addStretch(); return w
    def device_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Device","Automatic phone setup and connection.")
        c,cl=self.card("Connection"); self.ip=QLineEdit(self.cfg.phone_ip); self.ip.setPlaceholderText("100.x.x.x"); cl.addWidget(self.ip)
        row=QHBoxLayout(); d=QPushButton("Auto Detect"); d.setObjectName("Primary"); d.clicked.connect(self.auto_discover); row.addWidget(d); a=QPushButton("Save + Connect"); a.setObjectName("Primary"); a.clicked.connect(self.connect); row.addWidget(a); r=QPushButton("Refresh"); r.clicked.connect(self.refresh); row.addWidget(r); row.addStretch(); cl.addLayout(row)
        self.devmsg=QLabel("Ready"); self.devmsg.setObjectName("Muted"); cl.addWidget(self.devmsg); l.addWidget(c)
        sc,sl=self.card("PhoneHub 6 Auto Setup","PhoneHub checks Tailscale on this PC, detects the Android phone, and guides phone-side setup. USB/ADB are optional.")
        self.setupstep=QLabel("PhoneHub will check Tailscale and discover your phone automatically."); self.setupstep.setWordWrap(True); sl.addWidget(self.setupstep)
        sr=QHBoxLayout(); chk=QPushButton("Run Auto Setup"); chk.setObjectName("Primary"); chk.clicked.connect(self.auto_setup); sr.addWidget(chk)
        agent=QPushButton("Install / Update Agent"); agent.setObjectName("Primary"); agent.clicked.connect(self.install_agent_to_phone); sr.addWidget(agent)
        tailscale=QPushButton("Install Tailscale to Phone"); tailscale.setObjectName("Primary"); tailscale.clicked.connect(self.install_tailscale_to_phone); sr.addWidget(tailscale)
        sr.addStretch(); sl.addLayout(sr)
        self.agentmsg=QLabel("Connect and unlock the phone. PhoneHub will direct-install when an authorized service link exists; otherwise it will copy the Agent automatically over USB."); self.agentmsg.setObjectName("Muted"); self.agentmsg.setWordWrap(True); sl.addWidget(self.agentmsg)
        l.addWidget(sc); l.addStretch(); return w
    def screen_page(self):
        w=QWidget(); l=QVBoxLayout(w); self.title(l,"Screen","Optional engineering screen tool. ADB/scrcpy are only required when this feature is used.")
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
    def auto_setup(self):
        self.setupstep.setText("Auto Setup: checking Tailscale on this PC…")
        self.work(self._ensure_pc_tailscale,self._pc_tailscale_ready)

    def _ensure_pc_tailscale(self):
        check=self.runner.run(["where.exe","tailscale"],8)
        if check.ok:
            return True,"Tailscale is installed on this PC."
        winget=self.runner.run(["where.exe","winget"],8)
        if not winget.ok:
            return False,"Tailscale is missing and winget is unavailable. Install Tailscale on the PC, then run Auto Setup again."
        install=self.runner.run(["winget","install","--id","Tailscale.Tailscale","-e","--accept-package-agreements","--accept-source-agreements"],180)
        if not install.ok:
            return False,install.stderr or install.stdout or "Automatic Tailscale installation failed."
        return True,"Tailscale installed successfully on this PC."

    def install_tailscale_to_phone(self):
        self.setupstep.setText("Checking authorized phone link for Tailscale install…")
        self.work(self.setup.inspect_usb,self._tailscale_usb_ready)

    def _tailscale_usb_ready(self,status):
        if status.stage!="ready":
            self.setupstep.setText(status.message)
            return
        serial=status.serial
        self.setupstep.setText("Downloading official Tailscale APK, verifying it, and installing to phone…")
        self.work(lambda:self.setup.install_tailscale(serial),lambda result:self._tailscale_phone_done(serial,result))

    def _tailscale_phone_done(self,serial,result):
        ok,msg=result
        if not ok:
            self.setupstep.setText("Tailscale install failed: "+msg)
            return
        self.setupstep.setText("✓ "+msg+" Opening Tailscale on phone…")
        self.work(lambda:self.setup.open_tailscale(serial),lambda opened:self._tailscale_opened(opened))

    def _tailscale_opened(self,opened):
        if opened:
            self.setupstep.setText("✓ Tailscale installed and opened on phone. Approve VPN/sign-in on the phone if Android asks, then Auto Detect.")
        else:
            self.setupstep.setText("Tailscale installed. Open it on the phone once, then press Auto Detect.")

    def install_agent_to_phone(self):
        self.agentmsg.setText("Sending PhoneHub Agent 6.1 to the connected phone…")
        self.work(self._run_agent_bootstrap,self._agent_bootstrap_done)

    def _run_agent_bootstrap(self):
        root=Path(__file__).resolve().parents[3]
        script=root/"AUTO_BOOTSTRAP_PHONE.ps1"
        if not script.exists():
            return False,"PhoneHub bootstrap script is missing."
        apk=root/"PhoneHub-Agent-6.1.0"/"PhoneHub-Agent-6.1.0-debug.apk"
        if not apk.exists():
            return False,"PhoneHub Agent APK is missing. Extract PhoneHub-Agent-6.1.0.zip into C:\\PhoneHub first."
        result=subprocess.run(
            ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),"-ApkPath",str(apk),"-NoPause"],
            capture_output=True,text=True,timeout=90
        )
        output=(result.stdout or "")+"\n"+(result.stderr or "")
        if result.returncode==0:
            if "installed/updated successfully" in output.lower():
                return True,"PhoneHub Agent installed/updated directly."
            return True,"Agent copied to the phone. Android still requires one Update / Install confirmation because only USB file transfer is available."
        return False,output.strip() or "Could not send PhoneHub Agent to the phone."

    def _agent_bootstrap_done(self,result):
        ok,msg=result
        self.agentmsg.setText(("✓ " if ok else "⚠ ")+msg)

    def _pc_tailscale_ready(self,result):
        ok,msg=result
        if not ok:
            self.setupstep.setText(msg)
            return
        self.setupstep.setText("✓ "+msg+" Detecting Android phones on Tailscale…")
        self.auto_discover()
    def _auto_usb(self,status):
        self.usb_serial=status.serial
        if status.stage!="ready":
            self.setupstep.setText(status.message)
            if self.cfg.serial: self.auto_connect()
            return
        self.setupstep.setText("✓ USB authorized • checking Tailscale…")
        self.work(lambda:self.setup.package_installed(status.serial,"com.tailscale.ipn"),lambda installed:self._tailscale_checked(status.serial,installed))
    def _tailscale_checked(self,serial,installed):
        if installed:
            self.setupstep.setText("✓ USB authorized • ✓ Tailscale installed • opening Tailscale and detecting remote link…")
            self.work(lambda:self.setup.open_tailscale(serial),lambda _ok:self.auto_discover())
        else:
            self.setupstep.setText("Tailscale missing • downloading official stable APK and verifying checksum…")
            self.work(lambda:self.setup.install_tailscale(serial),lambda result:self._tailscale_installed(serial,result))
    def _tailscale_installed(self,serial,result):
        ok,msg=result
        if not ok:
            self.setupstep.setText(msg)
            return
        self.setupstep.setText("✓ "+msg+" Opening Tailscale…")
        self.work(lambda:self.setup.open_tailscale(serial),lambda _ok:self._after_tailscale_open())
    def _after_tailscale_open(self):
        self.setupstep.setText("Tailscale is ready. If Android asks for VPN/sign-in approval, approve it on the phone. PhoneHub is detecting the remote link…")
        self.auto_discover()
    def check_usb(self):
        self.setupstep.setText("Checking USB and Android authorization…")
        self.work(self.setup.inspect_usb,self._usb_status)
    def _usb_status(self,status):
        self.usb_serial=status.serial
        if status.stage=="ready":
            self.setupstep.setText("✓ USB authorized. Next: open Tailscale. If it is not installed, install the official Tailscale app on the phone, sign in, then press Auto Detect.")
        else:
            self.setupstep.setText(status.message)
    def open_tailscale(self):
        serial=getattr(self,"usb_serial","")
        if not serial:
            self.setupstep.setText("Check USB first.")
            return
        self.work(lambda:self.setup.open_tailscale(serial),lambda ok:self.setupstep.setText("Tailscale opened on phone. Sign in/approve on the phone, then press Auto Detect." if ok else "Tailscale app is not installed yet. Install the official Tailscale app on the phone, then Check USB again."))
    def auto_connect(self):
        self.devmsg.setText("Connecting remembered phone…")
        self.work(lambda:self.adb.connect(self.cfg),self.connected)
    def auto_discover(self):
        self.devmsg.setText("Finding Tailscale devices…")
        self.work(self.discovery.peers,self._discovered)
    def _discovered(self,peers):
        if not peers:
            self.devmsg.setText("No online Android phone found on Tailscale.")
            self.setupstep.setText("PC setup is ready. On the phone: install/open Tailscale, sign in with the same account, turn it ON, then open PhoneHub Agent. PhoneHub will detect it automatically.")
            self.state.set_device(DeviceSnapshot(
                state=ConnectionState.DISCONNECTED,
                device_name="Phone offline",
                transport="Tailscale / PhoneHub Agent",
                detail="PC ready • phone Tailscale/Agent not online"
            ))
            return
        peer=next((p for p in peers if p.os=="android"),peers[0])
        try:
            self.cfg=self.configs.save(DeviceConfig(peer.ip,5555))
            self.ip.setText(peer.ip)
        except Exception:
            pass
        self.devmsg.setText(f"Network online • {peer.name} • {peer.ip}")
        self.setupstep.setText("✓ Tailscale phone detected. Next: open PhoneHub Agent on the phone for full policy and notification sync.")
        self.state.set_device(DeviceSnapshot(
            state=ConnectionState.ONLINE,
            device_name=peer.name or "Android phone",
            transport="Tailscale / PhoneHub Agent",
            detail=f"Network online • {peer.ip}"
        ))
    def _try_peer(self,peers,index):
        if index>=len(peers):
            self.devmsg.setText("No authorized Android phone found on ADB port 5555.")
            return
        peer=peers[index]; cfg=DeviceConfig(peer.ip,5555)
        self.devmsg.setText(f"Checking {peer.name}…")
        self.work(lambda:self.adb.connect(cfg),lambda result:self._peer_result(peers,index,cfg,result))
    def _peer_result(self,peers,index,cfg,result):
        ok,msg=result
        if ok:
            self.cfg=self.configs.save(cfg); self.ip.setText(cfg.phone_ip)
            self.devmsg.setText(f"Connected automatically • {cfg.phone_ip}"); self.refresh()
        else:
            self._try_peer(peers,index+1)
    def connect(self):
        try:self.cfg=self.configs.save(DeviceConfig(self.ip.text(),5555))
        except Exception as e:self.devmsg.setText(str(e)); return
        self.devmsg.setText("Checking Tailscale connection…")
        self.refresh()
    def connected(self,result):
        ok,msg=result
        self.devmsg.setText(msg)
        if ok:
            self.refresh()
        else:
            self.devmsg.setText("Saved phone is unavailable • finding the current online Android phone…")
            self.auto_discover()
    def refresh(self):
        self.work(self._network_snapshot,self.state.set_device)

    def _network_snapshot(self):
        peers=self.discovery.peers()
        peer=next((p for p in peers if p.ip==self.cfg.phone_ip),None)
        if peer is None:
            peer=next((p for p in peers if p.os=="android"),None)
        if peer is not None:
            return DeviceSnapshot(
                state=ConnectionState.ONLINE,
                device_name=peer.name or "Android phone",
                transport="Tailscale / PhoneHub Agent",
                detail=f"Network online • {peer.ip}"
            )
        return DeviceSnapshot(
            state=ConnectionState.DISCONNECTED,
            device_name="Phone offline",
            transport="Tailscale / PhoneHub Agent",
            detail="No online Android phone found on Tailscale"
        )
    def ready(self):
        snap=self.adb.snapshot(self.cfg)
        if snap.state!=ConnectionState.ONLINE: self.state.set_device(snap); return False
        return True
    def open_screen(self):
        self.screen_user_closed=False
        self.screen_wanted=True
        self.screenmsg.setText("Opening screen…")
        self.work(lambda:self.adb.snapshot(self.cfg),self._open_screen_ready)
    def _open_screen_ready(self,snap):
        self.state.set_device(snap)
        if snap.state!=ConnectionState.ONLINE:
            self.screenmsg.setText("Phone unavailable • waiting to reconnect…")
            if not self.screen_watch.isActive(): self.screen_watch.start()
            return
        ok,msg=self.media.screen(self.cfg,int(self.quality.currentText()),int(self.fps.currentText()))
        self.screen_started_once=ok
        self.screenmsg.setText("Remote screen active" if ok else msg)
        if ok and not self.screen_watch.isActive(): self.screen_watch.start()
    def _watch_screen(self):
        if not self.screen_wanted or self.screen_user_closed or self.screen_watch_busy: return
        self.screen_watch_busy=True
        self.work(lambda:(self.adb.snapshot(self.cfg),self.adb.display_state(self.cfg)),self._screen_health)
    def _screen_health(self,result):
        self.screen_watch_busy=False
        snap,display=result
        self.state.set_device(snap)
        if not self.screen_wanted or self.screen_user_closed: return
        if snap.state!=ConnectionState.ONLINE or display in {"offline","screen_off","locked"}:
            self.screenmsg.setText("Phone locked/asleep • waiting for unlock…")
            return
        if not self.media.active and not self.screen_restarting:
            self.screen_restarting=True
            self.screenmsg.setText("Phone unlocked • restoring screen…")
            ok,msg=self.media.screen(self.cfg,int(self.quality.currentText()),int(self.fps.currentText()))
            self.screen_restarting=False
            self.screenmsg.setText("Screen restored" if ok else msg)
    def open_camera(self,face):
        if not self.ready(): self.cameramsg.setText("Connect Device first"); return
        ok,msg=self.media.camera(self.cfg,face); self.cameramsg.setText(msg)
    def stop_media(self):
        self.screen_user_closed=True; self.screen_wanted=False; self.screen_watch.stop(); self.screen_watch_busy=False; self.screen_restarting=False; self.screen_started_once=False
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
        self.screen_wanted=False; self.screen_watch.stop(); self.media.stop(); super().closeEvent(event)
