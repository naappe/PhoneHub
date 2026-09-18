import threading
from dataclasses import dataclass


DIAGNOSTIC_SCRIPT = r"""
Java.perform(function () {
    var System = Java.use('java.lang.System');
    var originalExit = System.exit.overload('int');

    originalExit.implementation = function (code) {
        console.log('[exit] System.exit(' + code + ')');
        try {
            var Log = Java.use('android.util.Log');
            var Throwable = Java.use('java.lang.Throwable');
            console.log(Log.getStackTraceString(Throwable.$new()));
        } catch (e) {
            console.log('[exit] stack trace unavailable: ' + e);
        }
        return originalExit.call(this, code);
    };

    var Process = Java.use('android.os.Process');
    var originalKill = Process.killProcess.overload('int');

    originalKill.implementation = function (pid) {
        console.log('[exit] Process.killProcess(' + pid + ')');
        try {
            var Log = Java.use('android.util.Log');
            var Throwable = Java.use('java.lang.Throwable');
            console.log(Log.getStackTraceString(Throwable.$new()));
        } catch (e) {
            console.log('[exit] stack trace unavailable: ' + e);
        }
        return originalKill.call(this, pid);
    };
});

function watchPathFunction(name, pathArg) {
    var p = Module.findGlobalExportByName(name);
    if (!p) {
        console.log('[hook] ' + name + ' not exported');
        return;
    }

    Interceptor.attach(p, {
        onEnter: function (args) {
            try {
                var s = args[pathArg].readCString();
                if (!s) return;

                if (/frida|gum-js|gmain|2704[23]|\/proc\/self\/maps|\/proc\/net\/tcp|\/proc\/net\/unix|\/proc\/self\/status/i.test(s)) {
                    console.log('[detect?] ' + name + ': ' + s);
                }
            } catch (e) {}
        }
    });
}

watchPathFunction('fopen', 0);
watchPathFunction('open', 0);
watchPathFunction('access', 0);
watchPathFunction('stat', 0);
watchPathFunction('lstat', 0);
watchPathFunction('openat', 1);
"""


@dataclass
class RuntimeStatus:
    connected: bool
    device: str
    process: str
    detail: str


class FridaRuntimeSession:
    def __init__(self, on_line=None, on_status=None):
        self.on_line = on_line or (lambda text: None)
        self.on_status = on_status or (lambda status: None)
        self.device = None
        self.session = None
        self.script = None
        self.process_name = ""

    @staticmethod
    def import_frida():
        try:
            import frida
            return frida
        except Exception:
            return None

    def tool_status(self):
        frida = self.import_frida()
        if frida is None:
            return {
                "installed": False,
                "version": "",
                "detail": "Python package 'frida' is not installed."
            }
        return {
            "installed": True,
            "version": getattr(frida, "__version__", "unknown"),
            "detail": "Frida Python bindings are available."
        }

    def list_usb_processes(self):
        frida = self.import_frida()
        if frida is None:
            raise RuntimeError("Frida Python bindings are not installed.")

        device = frida.get_usb_device(timeout=5)
        self.device = device
        rows = []
        for proc in device.enumerate_processes():
            rows.append((proc.pid, proc.name))
        rows.sort(key=lambda item: item[1].lower())
        return device.name, rows

    def attach(self, target):
        frida = self.import_frida()
        if frida is None:
            raise RuntimeError("Frida Python bindings are not installed.")

        device = frida.get_usb_device(timeout=5)
        self.device = device

        value = str(target).strip()
        if not value:
            raise RuntimeError("Enter a PID or exact process/package name.")

        attach_target = int(value) if value.isdigit() else value
        session = device.attach(attach_target)
        script = session.create_script(DIAGNOSTIC_SCRIPT)

        def on_message(message, data):
            msg_type = message.get("type")
            if msg_type == "send":
                self.on_line(str(message.get("payload")))
            elif msg_type == "log":
                self.on_line(str(message.get("payload") or message.get("message") or ""))
            elif msg_type == "error":
                desc = message.get("description") or "Frida script error"
                stack = message.get("stack")
                self.on_line("[frida-error] " + desc)
                if stack:
                    self.on_line(stack)

        script.on("message", on_message)
        script.load()

        self.session = session
        self.script = script
        self.process_name = value
        self.on_status(RuntimeStatus(
            True,
            getattr(device, "name", "USB device"),
            value,
            "Diagnostic hooks loaded. Exit behavior is preserved; detection-related reads are logged only."
        ))

    def detach(self):
        try:
            if self.script is not None:
                self.script.unload()
        except Exception:
            pass
        try:
            if self.session is not None:
                self.session.detach()
        except Exception:
            pass

        self.script = None
        self.session = None
        self.process_name = ""
        self.on_status(RuntimeStatus(False, "", "", "Detached."))


def run_async(fn, callback, errback):
    def worker():
        try:
            callback(fn())
        except Exception as exc:
            errback(str(exc))

    threading.Thread(target=worker, daemon=True).start()
