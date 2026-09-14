import subprocess
import json
import os

CONFIG = os.path.expanduser(r"~\.phone_remote\config.json")

def adb(cmd):
    try:
        return subprocess.check_output(["adb"] + cmd, text=True).strip()
    except:
        return ""

def get_device():

    data = {
        "connected": False,
        "device": "Unknown",
        "android": "",
        "battery": "",
        "ip": "",
        "target": ""
    }

    if not os.path.exists(CONFIG):
        return data

    cfg = json.load(open(CONFIG,"r"))

    ip = cfg["phone_ip"]
    port = cfg["adb_port"]

    target = f"{ip}:{port}"

    data["ip"] = ip
    data["target"] = target

    subprocess.run(
        ["adb","connect",target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    data["device"] = adb(["shell","getprop","ro.product.model"])
    data["android"] = adb(["shell","getprop","ro.build.version.release"])

    battery = adb(["shell","dumpsys","battery"])

    for line in battery.splitlines():
        if "level:" in line:
            data["battery"] = line.split(":")[1].strip()

    data["connected"] = data["device"] != ""

    return data


if __name__ == "__main__":
    print(get_device())
