from __future__ import annotations
import sys, json, base64
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QDateTime, QObject, Signal, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication,QFrame,QHBoxLayout,QLabel,QMainWindow,QProgressBar,QPushButton,QStackedWidget,QVBoxLayout,QWidget,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QComboBox,QCheckBox,QAbstractItemView,QMenu
from .companion_server import CompanionServer

def gb(n): return f"{n/1073741824:.1f} GB"

class Card(QFrame):
    def __init__(self,title,value="—",detail="",progress=False):
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
class Task(QRunnable):
    def __init__(self,fn,tag):super().__init__();self.fn=fn;self.tag=tag;self.signals=TaskSignals()
    def run(self):
        try:self.signals.done.emit(self.tag,self.fn())
        except Exception as e:self.signals.done.emit(self.tag,e)

class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.server=CompanionServer();self.server.start();self.current=None;self.pool=QThreadPool.globalInstance();self._busy=False;self._apps_loading=False;self._screen_busy=False;self._screen_pixmap=None
        self.setWindowTitle("PhoneHub 7");self.resize(1100,700);self.setMinimumSize(820,560)
        root=QWidget();self.setCentralWidget(root);outer=QHBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        nav=QFrame();nav.setObjectName("nav");nav.setFixedWidth(220);nl=QVBoxLayout(nav);nl.setContentsMargins(18,24,18,24)
        brand=QLabel("PhoneHub 7");brand.setObjectName("brand");nl.addWidget(brand);nl.addSpacing(22)
        self.stack=QStackedWidget()
        names=["Home","Screen","Apps","App Policy","Policies","Notifications","Settings"]
        for i,name in enumerate(names):
            b=QPushButton(name);b.setCheckable(True);b.setAutoExclusive(True);b.clicked.connect(lambda _,x=i:self.stack.setCurrentIndex(x));nl.addWidget(b)
            if i==0:b.setChecked(True)
        nl.addStretch();nl.addWidget(QLabel("Secure Companion"))
        outer.addWidget(nav);outer.addWidget(self.stack,1)
        self.stack.addWidget(self.home());self.stack.addWidget(self.screen_page());self.stack.addWidget(self.apps_page());self.stack.addWidget(self.policy_page())
        self.stack.addWidget(self.info_page("Policies","Reusable policy profiles will be applied to selected apps."))
        self.stack.addWidget(self.info_page("Notifications","Notification forwarding will appear here after Android notification access is enabled."))
        self.stack.addWidget(self.info_page("Settings","Connection, protection, backup, logs and new-phone setup will live here."))
        self.apply_style();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(5000);self.screen_timer=QTimer(self);self.screen_timer.timeout.connect(self.screen_refresh);self.screen_timer.start(3000);QTimer.singleShot(400,self.refresh)

    def home(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(18)
        top=QHBoxLayout();h=QLabel("Home");h.setObjectName("heading");self.updated=QLabel("Waiting for device");self.updated.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.updated)
        self.connection=QLabel("●  Looking for your phone…");self.connection.setObjectName("status")
        l.addLayout(top);l.addWidget(self.connection)
        row1=QHBoxLayout();self.device=Card("DEVICE");self.battery=Card("BATTERY",progress=True);self.network=Card("NETWORK")
        for x in [self.device,self.battery,self.network]:row1.addWidget(x)
        l.addLayout(row1)
        row2=QHBoxLayout();self.storage=Card("STORAGE",progress=True);self.memory=Card("MEMORY",progress=True);self.android=Card("ANDROID")
        for x in [self.storage,self.memory,self.android]:row2.addWidget(x)
        l.addLayout(row2);l.addStretch();return p

    def screen_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(12)
        top=QHBoxLayout();h=QLabel("Screen");h.setObjectName("heading");self.screen_status=QLabel("Waiting for phone");self.screen_status.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.screen_status);l.addLayout(top)
        self.screen_help=QLabel("Android requires screen-capture consent. On the phone, open PhoneHub Companion and tap Start screen sharing once for this capture session.");self.screen_help.setWordWrap(True);l.addWidget(self.screen_help)
        self.screen_view=QLabel("Screen preview will appear here");self.screen_view.setObjectName("screenView");self.screen_view.setAlignment(Qt.AlignCenter);self.screen_view.setMinimumHeight(360);l.addWidget(self.screen_view,1)
        b=QPushButton("Refresh screen");b.clicked.connect(self.screen_refresh);l.addWidget(b)
        return p

    def screen_refresh(self):
        if not hasattr(self,"screen_view") or self.stack.currentIndex()!=1 or self._screen_busy:return
        ds=self.server.devices()
        if not ds:self.screen_status.setText("Phone offline");return
        self._screen_busy=True;self.screen_status.setText("Requesting encrypted screen frame…");self.run_task("screen_snapshot",lambda:self.server.screen_snapshot(ds[0]))

    def info_page(self,title,body):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,32,36,32);h=QLabel(title);h.setObjectName("heading");l.addWidget(h);d=QLabel(body);d.setWordWrap(True);l.addWidget(d);l.addStretch();return p

    def apps_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);l.setSpacing(14)
        top=QHBoxLayout();h=QLabel("Apps");h.setObjectName("heading");self.app_count=QLabel("Waiting for phone");self.app_count.setObjectName("updated");top.addWidget(h);top.addStretch();top.addWidget(self.app_count);l.addLayout(top)
        tools=QHBoxLayout();self.app_search=QLineEdit();self.app_search.setPlaceholderText("Search apps or package…");self.app_search.textChanged.connect(self.filter_apps);self.app_filter=QComboBox();self.app_filter.addItems(["All apps","User apps","System apps"]);self.app_filter.currentIndexChanged.connect(self.filter_apps);tools.addWidget(self.app_search,1);tools.addWidget(self.app_filter);l.addLayout(tools)
        self.app_table=QTableWidget(0,4);self.app_table.setHorizontalHeaderLabels(["App","Package","Type","State"]);self.app_table.verticalHeader().setVisible(False);self.app_table.setSelectionBehavior(QAbstractItemView.SelectItems);self.app_table.setSelectionMode(QAbstractItemView.ExtendedSelection);self.app_table.setEditTriggers(QAbstractItemView.NoEditTriggers);self.app_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents);self.app_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);self.app_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeToContents);self.app_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeToContents);self.app_table.setContextMenuPolicy(Qt.CustomContextMenu);self.app_table.customContextMenuRequested.connect(self.app_menu);self.app_table.cellDoubleClicked.connect(self.open_policy);l.addWidget(self.app_table,1)
        self._apps=[];self.load_app_cache();return p

    def policy_page(self):
        p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,30,36,30);h=QLabel("App Policy");h.setObjectName("heading");l.addWidget(h);self.policy_title=QLabel("Select an app");self.policy_title.setObjectName("policyTitle");self.policy_package=QLabel("Choose an app from Apps, then double-click it or use Open App Policy.");self.policy_package.setObjectName("updated");l.addWidget(self.policy_title);l.addWidget(self.policy_package)
        self.policy_status=QLabel("Policies are stored on the phone and synchronized through the encrypted Companion channel.");self.policy_status.setWordWrap(True);l.addWidget(self.policy_status)
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
            self._apps=json.loads(self.cache_path().read_text(encoding="utf-8"));self.app_count.setText(f"{len(self._apps)} cached • refreshing…");self.filter_apps()
        except Exception:pass
    def save_app_cache(self):
        try:self.cache_path().write_text(json.dumps(self._apps,ensure_ascii=False),encoding="utf-8")
        except Exception:pass
    def load_apps(self,d):
        if self._apps_loading:return
        self._apps_loading=True;self.app_count.setText("Loading apps…");self.run_task("apps",lambda:self.server.apps(d))
    def task_done(self,tag,result):
        if tag=="status":
            self._busy=False
            if isinstance(result,Exception):self.connection.setText(f"● Connected • status unavailable: {result}");return
            d,s=result
            if s.get("type")!="device_status":return
            self.connection.setText(f"●  Connected securely  •  {d.address}  •  AES-256-GCM");self.updated.setText("Updated "+QDateTime.currentDateTime().toString("h:mm:ss AP"))
            self.device.value.setText(s.get("device_name","Android"));self.device.detail.setText("Encrypted Companion")
            bp=s.get("battery_percent",0);self.battery.value.setText(f"{bp}%");self.battery.bar.setValue(bp);self.battery.detail.setText("Charging" if s.get("charging") else "Not charging")
            self.network.value.setText(s.get("network","—"));self.network.detail.setText("Active connection")
            total=s.get("storage_total",0);free=s.get("storage_free",0);used=max(0,total-free);self.storage.value.setText(gb(free));self.storage.bar.setValue(int(used*100/total) if total else 0);self.storage.detail.setText(f"free of {gb(total)}")
            mt=s.get("memory_total",0);mf=s.get("memory_free",0);self.memory.value.setText(gb(mf));self.memory.bar.setValue(int((mt-mf)*100/mt) if mt else 0);self.memory.detail.setText(f"available of {gb(mt)}")
            self.android.value.setText(str(s.get("android_version","—")));self.android.detail.setText(f"SDK {s.get('sdk','—')}")
            if self.current!=d.device_id:self.current=d.device_id;self.load_apps(d)
        elif tag=="screen_snapshot":
            self._screen_busy=False
            if isinstance(result,Exception):self.screen_status.setText(f"Screen unavailable: {result}");return
            if result.get("type")!="screen_snapshot":
                self.screen_status.setText("Screen sharing permission required on phone");self.screen_view.setText(result.get("message","Open PhoneHub Companion and start screen sharing."));return
            try:
                raw=base64.b64decode(result.get("image",""));pix=QPixmap();pix.loadFromData(raw,"JPEG");self._screen_pixmap=pix
                self.screen_view.setPixmap(pix.scaled(self.screen_view.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation));self.screen_status.setText(f"Encrypted preview • {result.get('width','?')}×{result.get('height','?')}")
            except Exception as e:self.screen_status.setText(f"Frame decode failed: {e}")
        elif tag=="policy_get":
            if isinstance(result,Exception):self.policy_status.setText(f"Policy unavailable: {result}");return
            p=result.get("policy",{})
            for key,cb in self.policy_checks.items():cb.setChecked(bool(p.get(key,cb.isChecked())));cb.setEnabled(True)
            self.policy_save.setEnabled(True);self.policy_status.setText("Policy loaded from phone • remote encrypted sync ready")
        elif tag=="policy_set":
            self.policy_save.setEnabled(True)
            if isinstance(result,Exception):self.policy_status.setText(f"Save failed: {result}");return
            self.policy_status.setText("Saved on phone • Android-restricted controls are stored but are not silently enforced")
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
        self.policy_title.setText(app);self.policy_package.setText(pkg);self.stack.setCurrentIndex(3);self.policy_status.setText("Loading policy from phone…")
        for cb in self.policy_checks.values():cb.setEnabled(False)
        self.policy_save.setEnabled(False)
        ds=self.server.devices()
        if ds:self.run_task("policy_get",lambda:self.server.policy_get(ds[0],pkg))
    def save_policy(self):
        pkg=self.policy_package.text().strip()
        if not pkg or "." not in pkg:return
        ds=self.server.devices()
        if not ds:self.policy_status.setText("Phone is offline");return
        policy={key:cb.isChecked() for key,cb in self.policy_checks.items()};self.policy_save.setEnabled(False);self.policy_status.setText("Saving encrypted policy to phone…")
        self.run_task("policy_set",lambda:self.server.policy_set(ds[0],pkg,policy))
    def refresh(self):
        ds=self.server.devices()
        if not ds:
            self.connection.setText("●  Waiting for PhoneHub Companion");self.updated.setText("Offline");return
        if self._busy:return
        d=ds[0];self._busy=True;self.run_task("status",lambda:(d,self.server.device_status(d)))

    def apply_style(self):
        self.setStyleSheet("""
        QWidget{background:#f5f7fb;color:#172033;font-family:'Segoe UI';font-size:14px}
        QLabel{background:transparent}
        #nav{background:#ffffff;border-right:1px solid #e4e9f1}
        #brand{font-size:22px;font-weight:700;color:#111827}
        #nav QPushButton{text-align:left;border:0;border-radius:9px;padding:11px 14px;background:transparent;color:#536078}
        #nav QPushButton:hover{background:#f1f5fb} #nav QPushButton:checked{background:#eaf2ff;color:#2563eb;font-weight:600}
        #heading{font-size:30px;font-weight:700;color:#111827} #policyTitle{font-size:22px;font-weight:700;color:#182033} #status{color:#16803a;font-weight:600;padding:2px 0 8px 0} #updated{color:#8490a4;font-size:12px}
        #card{background:#ffffff;border:1px solid #e1e7ef;border-radius:16px;min-height:142px}
        #cardTitle{background:transparent;color:#7a8599;font-size:11px;font-weight:700} #cardValue{background:transparent;font-size:24px;font-weight:700;color:#182033} #cardDetail{background:transparent;color:#6b768a}
        #screenView{background:#111827;border:1px solid #d9e0ea;border-radius:14px;color:#94a3b8}
        QProgressBar{background:#edf1f6;border:0;border-radius:3px} QProgressBar::chunk{background:#2563eb;border-radius:3px}\n        QLineEdit,QComboBox{background:#fff;border:1px solid #dfe5ee;border-radius:9px;padding:9px} QTableWidget{background:#fff;border:1px solid #e1e7ef;border-radius:12px;gridline-color:#eef1f5} QHeaderView::section{background:#f7f9fc;border:0;border-bottom:1px solid #e5eaf1;padding:9px;font-weight:600}
        """)

def main():
    app=QApplication(sys.argv);w=Window();w.show();sys.exit(app.exec())
if __name__=="__main__":main()
