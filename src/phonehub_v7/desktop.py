from __future__ import annotations
import sys, json, socket, subprocess, shutil
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QDateTime, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication,QFrame,QHBoxLayout,QLabel,QMainWindow,QProgressBar,QPushButton,QStackedWidget,QVBoxLayout,QWidget,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QComboBox,QCheckBox,QAbstractItemView,QMenu,QFileDialog
from .companion_server import CompanionServer
from .webrtc_stream import WebRtcScreenClient

def gb(n): return f"{n/1073741824:.1f} GB"

class Card(QFrame):
    def __init__(self,title,value="N/A",detail="",progress=False):
        super().__init__();self.setObjectName("card")
        lay=QVBoxLayout(self);lay.setContentsMargins(20,18,20,18);lay.setSpacing(7)
        t=QLabel(title);t.setObjectName("cardTitle");self.value=QLabel(value);self.value.setObjectName("cardValue");self.detail=QLabel(detail);self.detail.setObjectName("cardDetail")
        lay.addWidget(t);lay.addWidget(self.value)
        self.bar=None
        if progress:
            self.bar=QProgressBar();self.bar.setRange(0,100);self.bar.setTextVisible(False);self.bar.setFixedHeight(7);lay.addWidget(self.bar)
        lay.addWidget(self.detail)

class TaskSignals(QObject):
    done=Signal(object,object)

class ScreenSignals(QObject):
    frame=Signal(bytes,int,int)
    state=Signal(str)
class Task(QRunnable):
    def __init__(self,fn,tag):super().__init__();self.fn=fn;self.tag=tag;self.signals=TaskSignals()
    def run(self):
        try:self.signals.done.emit(self.tag,self.fn())
        except Exception as e:self.signals.done.emit(self.tag,e)

class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.server=CompanionServer();self.server.start();self.current=None;self.pool=QThreadPool.globalInstance();self._busy=False;self._apps_loading=False;self._screen_pixmap=None;self._screen_active=False;self._scrcpy_process=None;self._screen_device=None;self._camera_active=False;self._camera_busy=False;self._setup_probe_busy=False;self._setup_serial=None
        self.setWindowTitle("PhoneHub 7");self.resize(1100,700);self.setMinimumSize(820,560)
        root=QWidget();self.setCentralWidget(root);outer=QHBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        nav=QFrame();nav.setObjectName("nav");nav.setFixedWidth(220);nl=QVBoxLayout(nav);nl.setContentsMargins(18,24,18,24)
        brand=QLabel("PhoneHub 7");brand.setObjectName("brand");nl.addWidget(brand);nl.addSpacing(22)
        self.stack=QStackedWidget()
        self.screen_signals=ScreenSignals();self.screen_signals.frame.connect(self.show_screen_frame);self.screen_signals.state.connect(self.show_screen_state)
        self.screen_client=WebRtcScreenClient(self.server,self.screen_signals.frame.emit,self.screen_signals.state.emit)
        names=["Home","Screen","Apps","App Policy","Policies","Notifications","Files","Camera","Automation","Logs","Settings"]
        for i,name in enumerate(names):
            b=QPushButton(name);b.setCheckable(True);b.setAutoExclusive(True);b.clicked.connect(lambda _,x=i:self.stack.setCurrentIndex(x));nl.addWidget(b)
            if i==0:b.setChecked(True)
        nl.addStretch();nl.addWidget(QLabel("PC Control Center"))
        outer.addWidget(nav);outer.addWidget(self.stack,1)
        self.stack.addWidget(self.home());self.stack.addWidget(self.screen_page());self.stack.addWidget(self.apps_page());self.stack.addWidget(self.policy_page())
        self.stack.addWidget(self.info_page("Policies","Reusable policy profiles will be applied to selected apps."))
        self.stack.addWidget(self.notifications_page())
        self.stack.addWidget(self.files_page())
        self.stack.addWidget(self.camera_page())
        self.stack.addWidget(self.info_page("Automation","PC automation engine: device events, schedules, policy actions and workflows will be configured here."))
        self.stack.addWidget(self.info_page("Logs","PC audit log: secure connections, commands, policy changes, transfers and errors will appear here."))
        self.stack.addWidget(self.info_page("Settings","PC-side connection, pairing, protection, backup, updates and new-phone setup will live here."))
        self.stack.currentChanged.connect(self.page_changed);self.apply_style();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000)
        self.camera_timer=QTimer(self);self.camera_timer.timeout.connect(self.request_camera_frame);self.camera_timer.setInterval(900)
        QTimer.singleShot(400,self.refresh)

    def home(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(18)
        top=QHBoxLayout();h=QLabel("Home");h.setObjectName("heading");self.updated=QLabel("Waiting for device");self.updated.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.updated)
        self.connection=QLabel("Looking for your phone...");self.connection.setObjectName("status")
        self.setup_hint=QLabel("PhoneHub will check whether the Companion is installed and configured.");self.setup_hint.setWordWrap(True);self.setup_hint.setObjectName("setupHint")
        setup_actions=QHBoxLayout();self.setup_button=QPushButton("Set up connected phone");self.open_companion_button=QPushButton("Open Companion on phone");self.setup_button.clicked.connect(self.launch_phone_setup);self.open_companion_button.clicked.connect(self.open_companion_on_phone);self.open_companion_button.setEnabled(False);setup_actions.addWidget(self.setup_button);setup_actions.addWidget(self.open_companion_button);setup_actions.addStretch()
        l.addLayout(top);l.addWidget(self.connection);l.addWidget(self.setup_hint);l.addLayout(setup_actions)
        row1=QHBoxLayout();self.device=Card("DEVICE");self.battery=Card("BATTERY",progress=True);self.network=Card("NETWORK")
        for x in [self.device,self.battery,self.network]:row1.addWidget(x)
        l.addLayout(row1)
        row2=QHBoxLayout();self.storage=Card("STORAGE",progress=True);self.memory=Card("MEMORY",progress=True);self.android=Card("ANDROID")
        for x in [self.storage,self.memory,self.android]:row2.addWidget(x)
        l.addLayout(row2);l.addStretch();return p

    def project_root(self):
        here=Path(__file__).resolve()
        for candidate in [Path.cwd(),here.parent,here.parent.parent,here.parent.parent.parent]:
            if (candidate/"PHONEHUB.ps1").exists():return candidate
        return Path.cwd()

    def launch_phone_setup(self):
        script=self.project_root()/"PHONEHUB.ps1"
        if not script.exists():
            self.setup_hint.setText("PHONEHUB.ps1 was not found. Open PhoneHub from the project folder.")
            return
        flags=getattr(subprocess,"CREATE_NEW_CONSOLE",0)
        subprocess.Popen(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),"setup"],cwd=str(self.project_root()),creationflags=flags)
        self.setup_hint.setText("Setup started. Follow the PowerShell window and approve Android prompts on the phone.")

    def open_companion_on_phone(self):
        if not self._setup_serial:
            self.setup_hint.setText("No authorized USB/ADB phone is available. Connect and unlock the phone first.")
            return
        try:
            flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
            subprocess.run(["adb","-s",self._setup_serial,"shell","monkey","-p","com.phonehub.companion","-c","android.intent.category.LAUNCHER","1"],capture_output=True,text=True,timeout=8,creationflags=flags)
            self.setup_hint.setText("PhoneHub Companion opened on the phone. Tap Enable PhoneHub bridge if setup is not complete.")
        except Exception as e:
            self.setup_hint.setText(f"Could not open Companion: {e}")

    def probe_phone_setup(self):
        if not shutil.which("adb"):return {"state":"no_adb"}
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        try:
            result=subprocess.run(["adb","devices"],capture_output=True,text=True,timeout=6,creationflags=flags)
        except Exception as e:return {"state":"error","message":str(e)}
        devices=[]
        for line in (result.stdout or "").splitlines()[1:]:
            parts=line.split()
            if len(parts)>=2 and parts[1]=="device":devices.append(parts[0])
        if not devices:return {"state":"no_phone"}
        usb=[x for x in devices if ":" not in x]
        serial=usb[0] if usb else devices[0]
        try:
            model=subprocess.run(["adb","-s",serial,"shell","getprop","ro.product.model"],capture_output=True,text=True,timeout=5,creationflags=flags).stdout.strip() or "Android phone"
            pkg=subprocess.run(["adb","-s",serial,"shell","pm","path","com.phonehub.companion"],capture_output=True,text=True,timeout=6,creationflags=flags)
            installed="package:" in (pkg.stdout or "")
            return {"state":"installed_not_connected" if installed else "missing","serial":serial,"model":model}
        except Exception as e:return {"state":"error","serial":serial,"message":str(e)}

    def screen_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(12)
        top=QHBoxLayout();h=QLabel("Screen");h.setObjectName("heading");self.screen_status=QLabel("Ready for live screen");self.screen_status.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.screen_status);l.addLayout(top)
        self.screen_help=QLabel("After one-time enrollment, USB is not required. PhoneHub uses the local network when available and the encrypted internet relay when the phone is elsewhere. Screen control uses local scrcpy when authorized, otherwise encrypted WebRTC.");self.screen_help.setWordWrap(True);l.addWidget(self.screen_help)
        self.screen_view=QLabel("Open this page to connect the live screen");self.screen_view.setObjectName("screenView");self.screen_view.setAlignment(Qt.AlignCenter);self.screen_view.setMinimumHeight(360);l.addWidget(self.screen_view,1)
        self.screen_button=QPushButton("Reconnect live screen");self.screen_button.clicked.connect(self.reconnect_live_screen);l.addWidget(self.screen_button)
        return p

    def page_changed(self,index):
        if index==1:
            self.start_live_screen()
        elif index==5:
            self.load_notifications()
        elif index==6:
            self.load_files()
        elif self._screen_active:
            self.stop_live_screen()
        if index==7:
            self.refresh_camera_status()
        elif self._camera_active:
            self.stop_camera()

    def stop_live_screen(self):
        self._screen_active=False
        if self._scrcpy_process is not None:
            try:
                if self._scrcpy_process.poll() is None:self._scrcpy_process.terminate()
            except Exception:pass
            self._scrcpy_process=None
        if self._screen_device is not None:
            self.screen_client.stop(self._screen_device)
        self._screen_device=None

    def reconnect_live_screen(self):
        if self._screen_active:self.stop_live_screen()
        QTimer.singleShot(250,self.start_live_screen)

    def start_live_screen(self):
        if self._screen_active:return
        ds=self.server.devices()
        if not ds:self.screen_status.setText("Phone offline");return
        d=ds[0];self._screen_device=d;self._screen_active=True;self.screen_view.setPixmap(QPixmap())
        self.screen_status.setText("Checking high-performance wireless screen...")
        self.screen_view.setText("Looking for authorized wireless ADB / scrcpy...")
        self.run_task("screen_local",lambda:self._start_scrcpy_local(d))

    def _start_webrtc(self,d):
        self.screen_status.setText("Starting remote WebRTC screen...");self.screen_view.setText("Connecting remote live screen...")
        self.screen_client.start(d)

    def wireless_adb_path(self):
        p=Path.home()/".phonehub";p.mkdir(parents=True,exist_ok=True);return p/"wireless_adb_target.txt"

    def _start_scrcpy_local(self,d):
        if not shutil.which("adb"):return {"ok":False,"reason":"ADB is not installed"}
        if not shutil.which("scrcpy"):return {"ok":False,"reason":"scrcpy is not installed"}
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        devices=subprocess.run(["adb","devices"],capture_output=True,text=True,timeout=5,creationflags=flags)
        connected=[]
        for line in (devices.stdout or "").splitlines()[1:]:
            parts=line.split()
            if len(parts)>=2 and parts[1]=="device" and ":" in parts[0]:
                connected.append(parts[0])

        candidates=[]
        def add(value):
            value=(value or "").strip()
            if value and value not in candidates:candidates.append(value)

        if d.address!="REMOTE":add(f"{d.address}:5555")
        try:add(self.wireless_adb_path().read_text(encoding="utf-8"))
        except Exception:pass
        for value in connected:add(value)

        failures=[]
        for target in candidates:
            try:
                host,port_text=target.rsplit(":",1);port=int(port_text)
            except Exception:
                failures.append(f"{target}: invalid target");continue
            try:
                with socket.create_connection((host,port),timeout=1.0):pass
            except OSError:
                failures.append(f"{target}: unreachable");continue
            if target not in connected:
                try:
                    connect=subprocess.run(["adb","connect",target],capture_output=True,text=True,timeout=8,creationflags=flags)
                    output=((connect.stdout or "")+" "+(connect.stderr or "")).strip()
                    low=output.lower()
                    if connect.returncode!=0 or ("connected to" not in low and "already connected" not in low):
                        failures.append(f"{target}: {output or 'ADB connection failed'}");continue
                except Exception as e:
                    failures.append(f"{target}: {e}");continue
            try:self.wireless_adb_path().write_text(target,encoding="utf-8")
            except Exception:pass
            args=["scrcpy","-s",target,"--window-title=PhoneHub Screen - Local Control","--max-size=1600","--max-fps=60","--video-bit-rate=8M","--no-audio","--stay-awake"]
            process=subprocess.Popen(args,creationflags=flags)
            return {"ok":True,"process":process,"target":target}

        reason="no reachable authorized wireless ADB target"
        if failures:reason+=" ("+"; ".join(failures[:3])+")"
        return {"ok":False,"reason":reason}


    def show_screen_state(self,state):
        self.screen_status.setText(state)
        low=state.lower()
        if "failed:" in low or low.startswith("webrtc failed") or low.startswith("webrtc closed") or "stream ended:" in low:
            self._screen_active=False

    def show_screen_frame(self,raw,width,height):
        try:
            image=QImage(raw,width,height,width*3,QImage.Format_RGB888).copy()
            if image.isNull():raise ValueError("invalid RGB frame")
            pix=QPixmap.fromImage(image);self._screen_pixmap=pix
            self.screen_view.setText("");self.screen_view.setPixmap(pix.scaled(self.screen_view.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        except Exception as e:
            self.screen_status.setText(f"Live frame display failed: {e}");self._screen_active=False




    def files_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(12)
        top=QHBoxLayout();h=QLabel("Files");h.setObjectName("heading");self.files_status=QLabel("Waiting for phone");self.files_status.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.files_status);l.addLayout(top)
        help_text=QLabel("Encrypted transfer area managed from the PC. Files are stored in PhoneHub's Android app-specific transfer folder, so no broad storage permission is required. Current secure transfer limit: 1 MB per file.");help_text.setWordWrap(True);l.addWidget(help_text)
        actions=QHBoxLayout();self.files_refresh=QPushButton("Refresh");self.files_upload=QPushButton("Send file to phone");self.files_download=QPushButton("Save selected to PC");self.files_delete=QPushButton("Delete selected");self.files_refresh.clicked.connect(self.load_files);self.files_upload.clicked.connect(self.upload_file);self.files_download.clicked.connect(self.download_file);self.files_delete.clicked.connect(self.delete_file);actions.addWidget(self.files_refresh);actions.addWidget(self.files_upload);actions.addWidget(self.files_download);actions.addWidget(self.files_delete);actions.addStretch();l.addLayout(actions)
        self.files_table=QTableWidget(0,3);self.files_table.setHorizontalHeaderLabels(["Name","Size","Modified"]);self.files_table.verticalHeader().setVisible(False);self.files_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.files_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.files_table.setSelectionMode(QAbstractItemView.SingleSelection);self.files_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch);self.files_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents);self.files_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents);l.addWidget(self.files_table,1)
        self._file_download_name=None
        return p

    def load_files(self):
        ds=self.server.devices()
        if not ds:self.files_status.setText("Phone offline");return
        self.files_status.setText("Loading...")
        self.run_task("files_list",lambda:self.server.files_list(ds[0]))

    def selected_phone_file(self):
        row=self.files_table.currentRow()
        if row<0:return None
        item=self.files_table.item(row,0)
        return item.text() if item else None

    def upload_file(self):
        ds=self.server.devices()
        if not ds:self.files_status.setText("Phone offline");return
        path,_=QFileDialog.getOpenFileName(self,"Send file to phone")
        if not path:return
        p=Path(path)
        if p.stat().st_size>1048576:
            self.files_status.setText("File is larger than the 1 MB secure transfer limit");return
        self.files_status.setText(f"Sending {p.name}...")
        self.run_task("file_put",lambda:self.server.file_put(ds[0],p.name,p.read_bytes()))

    def download_file(self):
        name=self.selected_phone_file()
        if not name:self.files_status.setText("Select a file first");return
        ds=self.server.devices()
        if not ds:self.files_status.setText("Phone offline");return
        path,_=QFileDialog.getSaveFileName(self,"Save phone file to PC",name)
        if not path:return
        self._file_download_name=path;self.files_status.setText(f"Downloading {name}...")
        self.run_task("file_get",lambda:self.server.file_get(ds[0],name))

    def delete_file(self):
        name=self.selected_phone_file()
        if not name:self.files_status.setText("Select a file first");return
        ds=self.server.devices()
        if not ds:self.files_status.setText("Phone offline");return
        self.files_status.setText(f"Deleting {name}...")
        self.run_task("file_delete",lambda:self.server.file_delete(ds[0],name))

    def notifications_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(12)
        top=QHBoxLayout();h=QLabel("Notifications");h.setObjectName("heading");self.notifications_status=QLabel("Waiting for phone");self.notifications_status.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.notifications_status);l.addLayout(top)
        help_text=QLabel("Notifications are viewed and managed on the PC. Android only supplies notifications after you explicitly enable PhoneHub notification access once.");help_text.setWordWrap(True);l.addWidget(help_text)
        self.notifications_refresh=QPushButton("Refresh notifications");self.notifications_refresh.clicked.connect(self.load_notifications);l.addWidget(self.notifications_refresh)
        self.notifications_table=QTableWidget(0,4);self.notifications_table.setHorizontalHeaderLabels(["App","Title","Notification","Time"]);self.notifications_table.verticalHeader().setVisible(False);self.notifications_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.notifications_table.setSelectionBehavior(QAbstractItemView.SelectRows);self.notifications_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents);self.notifications_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents);self.notifications_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch);self.notifications_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents);l.addWidget(self.notifications_table,1)
        return p

    def load_notifications(self):
        ds=self.server.devices()
        if not ds:self.notifications_status.setText("Phone offline");return
        self.notifications_status.setText("Loading...")
        self.run_task("notifications",lambda:self.server.notifications(ds[0]))

    def camera_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(12)
        top=QHBoxLayout();h=QLabel("Camera");h.setObjectName("heading");self.camera_status_label=QLabel("Camera idle");self.camera_status_label.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.camera_status_label);l.addLayout(top)
        help_text=QLabel("Camera is controlled here on the PC. Android only provides the permission-protected camera bridge and always shows its foreground-service notification while active.");help_text.setWordWrap(True);l.addWidget(help_text)
        controls=QHBoxLayout();self.camera_lens=QComboBox();self.camera_lens.addItems(["Back camera","Front camera"]);self.camera_start_button=QPushButton("Start camera");self.camera_stop_button=QPushButton("Stop camera");self.camera_start_button.clicked.connect(self.start_camera);self.camera_stop_button.clicked.connect(self.stop_camera);controls.addWidget(self.camera_lens);controls.addWidget(self.camera_start_button);controls.addWidget(self.camera_stop_button);controls.addStretch();l.addLayout(controls)
        self.camera_view=QLabel("Start the camera from the PC");self.camera_view.setObjectName("screenView");self.camera_view.setAlignment(Qt.AlignCenter);self.camera_view.setMinimumHeight(360);l.addWidget(self.camera_view,1)
        return p

    def refresh_camera_status(self):
        ds=self.server.devices()
        if not ds:self.camera_status_label.setText("Phone offline");return
        self.run_task("camera_status",lambda:self.server.camera_status(ds[0]))

    def start_camera(self):
        ds=self.server.devices()
        if not ds:self.camera_status_label.setText("Phone offline");return
        lens="front" if self.camera_lens.currentIndex()==1 else "back"
        self.camera_status_label.setText("Starting camera...")
        self.run_task("camera_start",lambda:self.server.camera_start(ds[0],lens))

    def stop_camera(self):
        self.camera_timer.stop();self._camera_active=False
        ds=self.server.devices()
        if ds:self.run_task("camera_stop",lambda:self.server.camera_stop(ds[0]))
        self.camera_view.setPixmap(QPixmap());self.camera_view.setText("Camera stopped")

    def request_camera_frame(self):
        if not self._camera_active or self._camera_busy:return
        ds=self.server.devices()
        if not ds:self.camera_status_label.setText("Phone offline");self.camera_timer.stop();self._camera_active=False;return
        self._camera_busy=True;self.run_task("camera_frame",lambda:self.server.camera_frame(ds[0]))

    def info_page(self,title,body):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,32,36,32);h=QLabel(title);h.setObjectName("heading");l.addWidget(h);d=QLabel(body);d.setWordWrap(True);l.addWidget(d);l.addStretch();return p

    def apps_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(14)
        top=QHBoxLayout();h=QLabel("Apps");h.setObjectName("heading");self.app_count=QLabel("Waiting for phone");self.app_count.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.app_count);l.addLayout(top)
        tools=QHBoxLayout();self.app_search=QLineEdit();self.app_search.setPlaceholderText("Search apps or package...");self.app_search.textChanged.connect(self.filter_apps);self.app_filter=QComboBox();self.app_filter.addItems(["All apps","User apps","System apps"]);self.app_filter.currentIndexChanged.connect(self.filter_apps);tools.addWidget(self.app_search,1);tools.addWidget(self.app_filter);l.addLayout(tools)
        self.app_table=QTableWidget(0,4);self.app_table.setHorizontalHeaderLabels(["App","Package","Type","State"]);self.app_table.verticalHeader().setVisible(False);self.app_table.setSelectionBehavior(QAbstractItemView.SelectItems);self.app_table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.app_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.app_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents);self.app_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.app_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents);self.app_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents);self.app_table.setContextMenuPolicy(Qt.CustomContextMenu);self.app_table.customContextMenuRequested.connect(self.app_menu);self.app_table.cellDoubleClicked.connect(self.open_policy);l.addWidget(self.app_table,1)
        self._apps=[];self.load_app_cache();return p

    def policy_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);h=QLabel("App Policy");h.setObjectName("heading");l.addWidget(h);self.policy_title=QLabel("Select an app");self.policy_title.setObjectName("policyTitle");self.policy_package=QLabel("Choose an app from Apps, then double-click it or use Open App Policy.");self.policy_package.setObjectName("updated");l.addWidget(self.policy_title);l.addWidget(self.policy_package)
        self.policy_status=QLabel("Policies are stored on the phone and synchronized through the encrypted Companion channel.");self.policy_status.setWordWrap(True);l.addWidget(self.policy_status);self.policy_mode=QLabel("Enforcement mode: checking phone...");self.policy_mode.setObjectName("updated");l.addWidget(self.policy_mode)
        self.policy_checks={}
        for key,text,on in [("keep_installed","Keep installed",True),("allow_usage","Allow usage",True),("suspend","Suspend",False),("show_notifications","Show notifications",True),("forward_notifications","Forward to PhoneHub",False),("protect_changes","Protect from changes",False),("auto_apply","Auto apply on sync",True)]:
            cb=QCheckBox(text);cb.setChecked(on);cb.setEnabled(False);self.policy_checks[key]=cb;l.addWidget(cb)
        self.policy_save=QPushButton("Save policy to phone");self.policy_save.setEnabled(False);self.policy_save.clicked.connect(self.save_policy);l.addWidget(self.policy_save);l.addStretch();return p

    def run_task(self,tag,fn):
        t=Task(fn,tag);t.signals.done.connect(self.task_done);self.pool.start(t)
    def cache_path(self):
        p=Path.home()/".phonehub";p.mkdir(parents=True,exist_ok=True);return p/"apps_cache.json"
    def load_app_cache(self):
        try:
            self._apps=json.loads(self.cache_path().read_text(encoding="utf-8"));self.app_count.setText(f"{len(self._apps)} cached | refreshing...");self.filter_apps()
        except Exception:pass
    def save_app_cache(self):
        try:self.cache_path().write_text(json.dumps(self._apps,ensure_ascii=False),encoding="utf-8")
        except Exception:pass
    def load_apps(self,d):
        if self._apps_loading:return
        self._apps_loading=True;self.app_count.setText("Loading apps...");self.run_task("apps",lambda:self.server.apps(d))
    def task_done(self,tag,result):
        if tag=="setup_probe":
            self._setup_probe_busy=False
            if isinstance(result,Exception):
                self.setup_hint.setText(f"Could not check phone setup: {result}");return
            state=result.get("state");self._setup_serial=result.get("serial")
            if state=="missing":
                self.setup_hint.setText(f"{result.get('model','Android phone')} is connected, but PhoneHub Companion is not installed. Click Set up connected phone.")
                self.setup_button.setEnabled(True);self.open_companion_button.setEnabled(False)
            elif state=="installed_not_connected":
                self.setup_hint.setText(f"PhoneHub Companion is installed on {result.get('model','the phone')}, but it is not connected. Click Open Companion, then tap Enable PhoneHub bridge and complete any Android permission prompts.")
                self.setup_button.setEnabled(True);self.open_companion_button.setEnabled(True)
            elif state=="no_phone":
                self.setup_hint.setText("No PhoneHub connection. For first setup or repair, connect the phone by USB, unlock it and allow USB debugging.")
                self.setup_button.setEnabled(True);self.open_companion_button.setEnabled(False)
            elif state=="no_adb":
                self.setup_hint.setText("PhoneHub Companion is offline. ADB is not available for local diagnosis; use PhoneHub Setup for first installation.")
                self.setup_button.setEnabled(True);self.open_companion_button.setEnabled(False)
            else:
                self.setup_hint.setText("PhoneHub is offline. Check the phone internet connection or open the Companion to complete setup.")
                self.setup_button.setEnabled(True);self.open_companion_button.setEnabled(bool(self._setup_serial))
            return
        if tag=="status":
            self._busy=False
            if isinstance(result,Exception):self.connection.setText(f"Status refresh delayed - {result}");self.connection.setStyleSheet("color:#b45309;font-weight:600");return
            d,s=result
            if s.get("type")!="device_status":return
            self.connection.setStyleSheet("");transport="INTERNET RELAY" if d.address=="REMOTE" else "LOCAL NETWORK";self.connection.setText(f"Connected securely | {transport} | AES-256-GCM | USB not required");self.updated.setText("Updated "+QDateTime.currentDateTime().toString("h:mm:ss AP"));self.setup_hint.setText("PhoneHub Companion is installed, enrolled and connected correctly.");self.open_companion_button.setEnabled(False)
            self.device.value.setText(s.get("device_name","Android"));self.device.detail.setText("Encrypted Companion | auto reconnect")
            bp=s.get("battery_percent",0);self.battery.value.setText(f"{bp}%");self.battery.bar.setValue(bp);self.battery.detail.setText("Charging" if s.get("charging") else "Not charging")
            self.network.value.setText(s.get("network","N/A"));self.network.detail.setText("Active connection")
            total=s.get("storage_total",0);free=s.get("storage_free",0);used=max(0,total-free);self.storage.value.setText(gb(free));self.storage.bar.setValue(int(used*100/total) if total else 0);self.storage.detail.setText(f"free of {gb(total)}")
            mt=s.get("memory_total",0);mf=s.get("memory_free",0);self.memory.value.setText(gb(mf));self.memory.bar.setValue(int((mt-mf)*100/mt) if mt else 0);self.memory.detail.setText(f"available of {gb(mt)}")
            self.android.value.setText(str(s.get("android_version","N/A")));self.android.detail.setText(f"SDK {s.get('sdk','N/A')}")
            if self.current!=d.device_id:self.current=d.device_id;self.load_apps(d)
        elif tag=="screen_local":
            if isinstance(result,Exception):
                result={"ok":False,"reason":str(result)}
            if result.get("ok"):
                self._scrcpy_process=result["process"];self.screen_status.setText("LOCAL LIVE CONTROL | scrcpy | up to 60 FPS")
                self.screen_view.setText("PhoneHub Screen is open in the high-performance scrcpy control window.\n\nMouse, keyboard and touch control are active through wireless ADB.\nNo screenshot loop and no WebRTC relay are being used.")
            else:
                d=self._screen_device
                reason=result.get("reason","local scrcpy unavailable")
                self.screen_status.setText(f"Local scrcpy unavailable | {reason} | trying WebRTC")
                if d is not None:self._start_webrtc(d)
        elif tag=="files_list":
            if isinstance(result,Exception):self.files_status.setText(f"Unavailable: {result}");return
            items=result.get("items",[]);self.files_table.setRowCount(len(items))
            for row,item in enumerate(items):
                modified=int(item.get("modified",0) or 0)
                when=QDateTime.fromMSecsSinceEpoch(modified).toString("yyyy-MM-dd h:mm AP") if modified else ""
                size=int(item.get("size",0) or 0)
                vals=[item.get("name",""),f"{size/1024:.1f} KB",when]
                for col,val in enumerate(vals):self.files_table.setItem(row,col,QTableWidgetItem(str(val)))
            self.files_status.setText(f"{len(items)} file(s) | encrypted transfer area")
        elif tag=="file_put":
            if isinstance(result,Exception):self.files_status.setText(f"Send failed: {result}");return
            self.files_status.setText(result.get("message",f"Sent {result.get('name','file')}"))
            QTimer.singleShot(150,self.load_files)
        elif tag=="file_get":
            if isinstance(result,Exception):self.files_status.setText(f"Download failed: {result}");return
            if result.get("type")=="file_error":self.files_status.setText(result.get("message","Download failed"));return
            try:
                Path(self._file_download_name).write_bytes(result.get("bytes",b""))
                self.files_status.setText(f"Saved to {self._file_download_name}")
            except Exception as e:self.files_status.setText(f"Save failed: {e}")
        elif tag=="file_delete":
            if isinstance(result,Exception):self.files_status.setText(f"Delete failed: {result}");return
            self.files_status.setText("Deleted" if result.get("deleted") else result.get("message","Delete failed"))
            QTimer.singleShot(150,self.load_files)
        elif tag=="notifications":
            if isinstance(result,Exception):self.notifications_status.setText(f"Unavailable: {result}");return
            if not result.get("access"):
                self.notifications_status.setText("Notification access not enabled on phone");self.notifications_table.setRowCount(0);return
            items=result.get("items",[]);self.notifications_table.setRowCount(len(items))
            for row,item in enumerate(items):
                posted=int(item.get("posted_at",0) or 0)
                when=QDateTime.fromMSecsSinceEpoch(posted).toString("yyyy-MM-dd h:mm AP") if posted else ""
                vals=[item.get("package",""),item.get("title",""),item.get("text",""),when]
                for col,val in enumerate(vals):self.notifications_table.setItem(row,col,QTableWidgetItem(str(val)))
            self.notifications_status.setText(f"{len(items)} recent")
        elif tag=="camera_status":
            if isinstance(result,Exception):self.camera_status_label.setText(f"Camera unavailable: {result}");return
            active=bool(result.get("active"));self._camera_active=active
            self.camera_status_label.setText(("Active" if active else "Idle")+" | "+str(result.get("lens","back"))+" camera")
            if active and not self.camera_timer.isActive():self.camera_timer.start()
        elif tag=="camera_start":
            if isinstance(result,Exception):self.camera_status_label.setText(f"Start failed: {result}");return
            if result.get("type")=="camera_error":
                self.camera_status_label.setText(result.get("message","Camera permission required"));self.camera_view.setText("Open PhoneHub Companion once and grant Camera permission.");return
            self._camera_active=True;self.camera_status_label.setText("Camera starting...");self.camera_timer.start()
        elif tag=="camera_stop":
            self._camera_active=False;self.camera_timer.stop();self.camera_status_label.setText("Camera stopped")
        elif tag=="camera_frame":
            self._camera_busy=False
            if isinstance(result,Exception):self.camera_status_label.setText(f"Frame failed: {result}");return
            if result.get("type")=="camera_frame":
                image=QImage.fromData(result.get("jpeg_bytes",b""))
                if not image.isNull():
                    pix=QPixmap.fromImage(image);self.camera_view.setPixmap(pix.scaled(self.camera_view.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation));self.camera_status_label.setText("Live | "+str(result.get("lens","back"))+" camera")
            elif result.get("type")=="camera_no_frame":
                self.camera_status_label.setText("Waiting for camera frame...")
        elif tag=="policy_get":
            if isinstance(result,Exception):self.policy_status.setText(f"Policy unavailable: {result}");return
            p=result.get("policy",{});e=result.get("enforcement",{});mode=e.get("mode","standard")
            for key,cb in self.policy_checks.items():cb.setChecked(bool(p.get(key,cb.isChecked())));cb.setEnabled(True)
            self.policy_save.setEnabled(True);self.policy_mode.setText("Enforcement mode: Device Owner" if mode=="device_owner" else "Enforcement mode: Standard Android")
            if mode=="device_owner":self.policy_status.setText("Policy loaded | strong app controls available")
            else:self.policy_status.setText("Policy loaded | settings sync now; Android requires Device Owner for suspend/uninstall protection")
        elif tag=="policy_set":
            self.policy_save.setEnabled(True)
            if isinstance(result,Exception):self.policy_status.setText(f"Save failed: {result}");return
            e=result.get("enforcement",{});a=result.get("apply_result",{});mode=e.get("mode","standard")
            self.policy_mode.setText("Enforcement mode: Device Owner" if mode=="device_owner" else "Enforcement mode: Standard Android")
            self.policy_status.setText(result.get("message","Policy saved on phone"))
        elif tag=="apps":
            self._apps_loading=False
            if isinstance(result,Exception):self.app_count.setText(f"Apps unavailable: {result}");return
            if result.get("type")=="apps":self._apps=result.get("apps",[]);self.app_count.setText(f"{len(self._apps)} installed");self.filter_apps();self.save_app_cache()

    def filter_apps(self):
        if not hasattr(self,"app_table"):return
        q=self.app_search.text().lower().strip();mode=self.app_filter.currentText();rows=[]
        for a in self._apps:
            if q and q not in a.get("name","").lower() and q not in a.get("package","").lower():continue
            if mode=="User apps" and a.get("system"):continue
            if mode=="System apps" and not a.get("system"):continue
            rows.append(a)
        self.app_table.setRowCount(len(rows))
        for row,a in enumerate(rows):
            vals=[a.get("name",""),a.get("package",""),"System" if a.get("system") else "User","Enabled" if a.get("enabled") else "Disabled"]
            for col,val in enumerate(vals):self.app_table.setItem(row,col,QTableWidgetItem(str(val)))

    def app_menu(self,pos):
        item=self.app_table.itemAt(pos)
        if not item:return
        row=item.row();menu=QMenu(self)
        a1=menu.addAction("Copy App Name");a2=menu.addAction("Copy Package");a3=menu.addAction("Copy Row");menu.addSeparator();a4=menu.addAction("Open App Policy")
        chosen=menu.exec(self.app_table.viewport().mapToGlobal(pos))
        app=self.app_table.item(row,0).text();pkg=self.app_table.item(row,1).text()
        if chosen==a1:QApplication.clipboard().setText(app)
        elif chosen==a2:QApplication.clipboard().setText(pkg)
        elif chosen==a3:QApplication.clipboard().setText("\t".join(self.app_table.item(row,i).text() for i in range(4)))
        elif chosen==a4:self.select_policy(row)
    def open_policy(self,row,col):self.select_policy(row)
    def select_policy(self,row):
        app=self.app_table.item(row,0).text();pkg=self.app_table.item(row,1).text()
        self.policy_title.setText(app);self.policy_package.setText(pkg);self.stack.setCurrentIndex(3);self.policy_status.setText("Loading policy from phone...")
        for cb in self.policy_checks.values():cb.setEnabled(False)
        self.policy_save.setEnabled(False)
        ds=self.server.devices()
        if ds:self.run_task("policy_get",lambda:self.server.policy_get(ds[0],pkg))
    def save_policy(self):
        pkg=self.policy_package.text().strip()
        if not pkg or "." not in pkg:return
        ds=self.server.devices()
        if not ds:self.policy_status.setText("Phone is offline");return
        policy={key:cb.isChecked() for key,cb in self.policy_checks.items()};self.policy_save.setEnabled(False);self.policy_status.setText("Saving encrypted policy to phone...")
        self.run_task("policy_set",lambda:self.server.policy_set(ds[0],pkg,policy))
    def refresh(self):
        ds=self.server.devices()
        if not ds:
            self.connection.setStyleSheet("");self.connection.setText("Waiting for PhoneHub Companion");self.updated.setText("Offline")
            if not self._setup_probe_busy:
                self._setup_probe_busy=True;self.run_task("setup_probe",self.probe_phone_setup)
            return
        if self._busy:return
        d=ds[0];self._busy=True;self.run_task("status",lambda:(d,self.server.device_status(d)))

    def apply_style(self):
        self.setStyleSheet("""
        QWidget{background:#f5f7fb;color:#172033;font-family:Arial;font-size:14px}
        QLabel{background:transparent}
        #nav{background:#ffffff;border-right:1px solid #e4e9f1}
        #brand{font-size:22px;font-weight:700;color:#111827}
        #nav QPushButton{text-align:left;border:0;border-radius:9px;padding:11px 14px;background:transparent;color:#536078}
        #nav QPushButton:hover{background:#f1f5fb} #nav QPushButton:checked{background:#eaf2ff;color:#2563eb;font-weight:600}
        #heading{font-size:30px;font-weight:700;color:#111827} #setupHint{color:#536078;padding:4px 0 2px 0} #policyTitle{font-size:22px;font-weight:700;color:#182033} #status{color:#16803a;font-weight:600;padding:2px 0 8px 0} #updated{color:#8490a4;font-size:12px}
        #card{background:#ffffff;border:1px solid #e1e7ef;border-radius:16px;min-height:142px}
        #cardTitle{background:transparent;color:#7a8599;font-size:11px;font-weight:700} #cardValue{background:transparent;font-size:24px;font-weight:700;color:#182033} #cardDetail{background:transparent;color:#6b768a}
        #screenView{background:#111827;border:1px solid #d9e0ea;border-radius:14px;color:#94a3b8}
        QProgressBar{background:#edf1f6;border:0;border-radius:3px} QProgressBar::chunk{background:#2563eb;border-radius:3px}\n        QLineEdit,QComboBox{background:#fff;border:1px solid #dfe5ee;border-radius:9px;padding:9px} QTableWidget{background:#fff;border:1px solid #e1e7ef;border-radius:12px;gridline-color:#eef1f5} QHeaderView::section{background:#f7f9fc;border:0;border-bottom:1px solid #e5eaf1;padding:9px;font-weight:600}
        """)

def main():
    app=QApplication(sys.argv);w=Window();w.show();sys.exit(app.exec())
if __name__=="__main__":main()
