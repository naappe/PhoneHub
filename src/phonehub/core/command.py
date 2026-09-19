from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner(Protocol):
    def run(self, args: list[str], timeout: float = 8.0) -> CommandResult:
        ...


class SubprocessRunner:
    def run(self, args: list[str], timeout: float = 8.0) -> CommandResult:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=creationflags,
            )
            return CommandResult(
                completed.returncode,
                (completed.stdout or "").strip(),
                (completed.stderr or "").strip(),
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, (exc.stdout or "") if isinstance(exc.stdout, str) else "", "Timed out")
        except Exception as exc:
            return CommandResult(1, "", str(exc))
