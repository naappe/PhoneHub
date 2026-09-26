from __future__ import annotations
import sys
from PySide6.QtCore import QTimer, Qt, QDateTime
from PySide6.QtWidgets import QApplication,QFrame,QHBoxLayout,QLabel,QMainWindow,QProgressBar,QPushButton,QStackedWidget,QVBoxLayout,QWidget
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

class Window(QMainWindow):
    def __init__(self):
        super().__init__();self.server=CompanionServer();self.server.start();self.current=None
        self.setWindowTitle("PhoneHub 7");self.resize(1100,700);self.setMinimumSize(820,560)
        root=QWidget();self.setCentralWidget(root);outer=QHBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        nav=QFrame();nav.setObjectName("nav");nav.setFixedWidth(220);nl=QVBoxLayout(nav);nl.setContentsMargins(18,24,18,24)
        brand=QLabel("PhoneHub 7");brand.setObjectName("brand");nl.addWidget(brand);nl.addSpacing(22)
        self.stack=QStackedWidget()
        names=["Home","Apps","App Policy","Policies","Notifications","Settings"]
        for i,name in enumerate(names):
            b=QPushButton(name);b.setCheckable(True);b.setAutoExclusive(True);b.clicked.connect(lambda _,x=i:self.stack.setCurrentIndex(x));nl.addWidget(b)
            if i==0:b.setChecked(True)
        nl.addStretch();nl.addWidget(QLabel("Secure Companion"))
        outer.addWidget(nav);outer.addWidget(self.stack,1)
        self.stack.addWidget(self.home())
        for name in names[1:]:
            p=QWidget();l=QVBoxLayout(p);l.setContentsMargins(36,32,36,32);h=QLabel(name);h.setObjectName("heading");l.addWidget(h);l.addWidget(QLabel("This section will connect to the Companion in the next feature phase."));l.addStretch();self.stack.addWidget(p)
        self.apply_style();self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(3000);QTimer.singleShot(400,self.refresh)

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

    def refresh(self):
        ds=self.server.devices()
        if not ds:
            self.connection.setText("●  Waiting for PhoneHub Companion");self.updated.setText("Offline");return
        d=ds[0]
        try:
            s=self.server.device_status(d)
            if s.get("type")!="device_status":raise RuntimeError(s.get("message","status unavailable"))
            self.connection.setText(f"●  Connected securely  •  {d.address}  •  AES-256-GCM");self.updated.setText("Updated "+QDateTime.currentDateTime().toString("h:mm:ss AP"))
            self.device.value.setText(s.get("device_name","Android"));self.device.detail.setText("Encrypted Companion")
            bp=s.get("battery_percent",0);self.battery.value.setText(f"{bp}%");self.battery.bar.setValue(bp);self.battery.detail.setText("Charging" if s.get("charging") else "Not charging")
            self.network.value.setText(s.get("network","—"));self.network.detail.setText("Active connection")
            total=s.get("storage_total",0);free=s.get("storage_free",0);used=max(0,total-free);self.storage.value.setText(gb(free));self.storage.bar.setValue(int(used*100/total) if total else 0);self.storage.detail.setText(f"free of {gb(total)}")
            mt=s.get("memory_total",0);mf=s.get("memory_free",0);self.memory.value.setText(gb(mf));self.memory.bar.setValue(int((mt-mf)*100/mt) if mt else 0);self.memory.detail.setText(f"available of {gb(mt)}")
            self.android.value.setText(str(s.get("android_version","—")));self.android.detail.setText(f"SDK {s.get('sdk','—')}")
        except Exception as e:self.connection.setText(f"● Connected • status unavailable: {e}")

    def apply_style(self):
        self.setStyleSheet("""
        QWidget{background:#f5f7fb;color:#172033;font-family:'Segoe UI';font-size:14px}
        QLabel{background:transparent}
        #nav{background:#ffffff;border-right:1px solid #e4e9f1}
        #brand{font-size:22px;font-weight:700;color:#111827}
        #nav QPushButton{text-align:left;border:0;border-radius:9px;padding:11px 14px;background:transparent;color:#536078}
        #nav QPushButton:hover{background:#f1f5fb} #nav QPushButton:checked{background:#eaf2ff;color:#2563eb;font-weight:600}
        #heading{font-size:30px;font-weight:700;color:#111827} #status{color:#16803a;font-weight:600;padding:2px 0 8px 0} #updated{color:#8490a4;font-size:12px}
        #card{background:#ffffff;border:1px solid #e1e7ef;border-radius:16px;min-height:142px}
        #cardTitle{background:transparent;color:#7a8599;font-size:11px;font-weight:700} #cardValue{background:transparent;font-size:24px;font-weight:700;color:#182033} #cardDetail{background:transparent;color:#6b768a}
        QProgressBar{background:#edf1f6;border:0;border-radius:3px} QProgressBar::chunk{background:#2563eb;border-radius:3px}
        """)

def main():
    app=QApplication(sys.argv);w=Window();w.show();sys.exit(app.exec())
if __name__=="__main__":main()
