import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(r"C:\PhoneHub\runtime\security")
EVIDENCE_FILE = EVIDENCE_DIR / "events.jsonl"

PROTECTED_PREFIXES = (
    "android",
    "com.android.",
    "com.google.android.",
    "com.oneplus.",
    "com.oplus.",
    "com.tailscale.ipn",
)


@dataclass
class SecurityFinding:
    timestamp: str
    category: str
    severity: str
    owner: str
    detail: str
    protected: bool
    action: str

    def to_dict(self):
        return asdict(self)


def _run(args, timeout=6):
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return (cp.stdout or cp.stderr or "").strip()
    except Exception:
        return ""


def _adb(serial, *args, timeout=6):
    return _run(["adb", "-s", serial, *args], timeout=timeout)


def is_protected_owner(owner):
    owner = (owner or "").strip()
    return any(owner == p.rstrip(".") or owner.startswith(p) for p in PROTECTED_PREFIXES)


def append_evidence(findings):
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with EVIDENCE_FILE.open("a", encoding="utf-8") as fh:
        for finding in findings:
            fh.write(json.dumps(finding.to_dict(), ensure_ascii=False) + "\n")


def scan_device(serial):
    now = datetime.now(timezone.utc).isoformat()
    findings = []

    usb_config = _adb(serial, "shell", "getprop", "sys.usb.config")
    adb_enabled = _adb(serial, "shell", "settings", "get", "global", "adb_enabled")
    if "adb" in usb_config or adb_enabled == "1":
        findings.append(SecurityFinding(
            now, "ADB", "INFO", "Android debugging service",
            f"ADB enabled; USB config={usb_config or 'unknown'}",
            True, "MONITOR_ONLY"
        ))

    vpn = _adb(serial, "shell", "dumpsys", "connectivity", timeout=8)
    if "com.tailscale.ipn" in vpn:
        findings.append(SecurityFinding(
            now, "VPN", "TRUSTED", "com.tailscale.ipn",
            "Tailscale VPN is active or registered in Android connectivity state.",
            True, "ALLOW_LOG"
        ))

    routes = _adb(serial, "shell", "ip", "route")
    if routes:
        findings.append(SecurityFinding(
            now, "NETWORK", "INFO", "Android network stack",
            "Routing table captured for evidence.",
            True, "MONITOR_ONLY"
        ))

    sockets = _adb(serial, "shell", "ss", "-tunap", timeout=8)
    if not sockets:
        sockets = _adb(serial, "shell", "ss", "-tun", timeout=8)

    if sockets:
        visible = [
            line for line in sockets.splitlines()
            if line.strip()
            and not line.lower().startswith(("netid", "state"))
            and "127.0.0.1:" not in line
            and "[::1]:" not in line
        ]
        findings.append(SecurityFinding(
            now, "CONNECTIONS", "INFO", "Android network stack",
            f"Visible active/listening socket entries: {len(visible)}.",
            True, "INVESTIGATE_FIRST"
        ))

    packages = _adb(serial, "shell", "cmd", "package", "list", "packages", "-3")
    third_party_count = len([x for x in packages.splitlines() if x.startswith("package:")])
    findings.append(SecurityFinding(
        now, "APPS", "INFO", "Package Manager",
        f"Third-party packages visible: {third_party_count}.",
        True, "MONITOR_ONLY"
    ))

    accessibility = _adb(
        serial, "shell", "settings", "get", "secure",
        "enabled_accessibility_services"
    )
    if accessibility and accessibility.lower() not in ("null", "none"):
        owners = [x.split("/")[0] for x in accessibility.split(":") if "/" in x]
        for owner in owners:
            protected = is_protected_owner(owner)
            findings.append(SecurityFinding(
                now, "ACCESSIBILITY", "INFO" if protected else "REVIEW", owner,
                "Accessibility service enabled.", protected,
                "MONITOR_ONLY" if protected else "ASK_USER"
            ))

    if sockets:
        findings.append(SecurityFinding(
            now, "RAW_SOCKET_SNAPSHOT", "EVIDENCE", "Android network stack",
            sockets[:12000], True, "EVIDENCE_ONLY"
        ))
    if routes:
        findings.append(SecurityFinding(
            now, "RAW_ROUTE_SNAPSHOT", "EVIDENCE", "Android network stack",
            routes[:6000], True, "EVIDENCE_ONLY"
        ))

    append_evidence(findings)
    return findings


def summarize_findings(findings):
    visible = [f for f in findings if not f.category.startswith("RAW_")]
    if not visible:
        return "No security telemetry was returned by Android."

    lines = ["PHONEHUB SECURITY REPORT", ""]
    for item in visible:
        protection = "PROTECTED" if item.protected else "REVIEW"
        lines.append(
            f"[{item.severity}] {item.category} | {protection} | "
            f"{item.owner} | {item.detail} | Action: {item.action}"
        )

    lines.extend([
        "",
        "Safety policy:",
        "PhoneHub does not automatically kill processes, disable packages, or alter system services.",
        "Unknown items are captured for review before any action.",
    ])
    return "\n".join(lines)
