from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .events import GatewayEvent


class EventLedger:
    """Append-only JSONL evidence ledger.

    The ledger keeps original structured evidence so AI reasoning can be traced
    back to observations instead of relying only on compressed tokens.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, event: GatewayEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def read_recent(self, limit: int = 100) -> list[dict]:
        if limit <= 0 or not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
