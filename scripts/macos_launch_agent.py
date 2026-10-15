"""Manage a per-user launchd service for the current source checkout."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from app.core.settings import settings

LABEL = "com.selfindex.local-service"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = PROJECT_ROOT / ".venv" / "bin" / "python"
AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def agent_config() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(PYTHON_EXE), "-m", "app.service_main"],
        "WorkingDirectory": str(PROJECT_ROOT),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ProcessType": "Background",
        "StandardOutPath": str(settings.data_dir / "selfindex-launchd.out.log"),
        "StandardErrorPath": str(settings.data_dir / "selfindex-launchd.err.log"),
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
        },
    }


def run_launchctl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], check=check, text=True, capture_output=True)


def install() -> None:
    if not PYTHON_EXE.is_file():
        raise SystemExit(f"Virtual environment Python not found: {PYTHON_EXE}")
    AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    target = f"{launchd_domain()}/{LABEL}"
    run_launchctl("bootout", target, check=False)
    temporary_path = AGENT_PATH.with_suffix(".plist.tmp")
    temporary_path.write_bytes(plistlib.dumps(agent_config(), sort_keys=False))
    os.replace(temporary_path, AGENT_PATH)
    AGENT_PATH.chmod(0o644)
    run_launchctl("bootstrap", launchd_domain(), str(AGENT_PATH))
    print(f"Installed and started {LABEL}: {AGENT_PATH}")


def uninstall() -> None:
    run_launchctl("bootout", f"{launchd_domain()}/{LABEL}", check=False)
    AGENT_PATH.unlink(missing_ok=True)
    print(f"Removed {LABEL}")


def status() -> None:
    result = run_launchctl("print", f"{launchd_domain()}/{LABEL}", check=False)
    print(result.stdout if result.returncode == 0 else "SelfIndex LaunchAgent is not loaded.")


def restart() -> None:
    run_launchctl("kickstart", "-k", f"{launchd_domain()}/{LABEL}")
    print(f"Restarted {LABEL}")


def service_is_healthy() -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{settings.port}/api/v1/health", timeout=1) as response:
            payload = json.load(response)
        return isinstance(payload, dict) and payload.get("ok") is True and payload.get("service") == "selfindex"
    except (OSError, URLError, ValueError):
        return False


def wait_for_health(attempts: int = 10) -> bool:
    for attempt in range(attempts):
        if service_is_healthy():
            return True
        if attempt < attempts - 1:
            time.sleep(0.4)
    return False


def ensure() -> None:
    if service_is_healthy():
        return
    target = f"{launchd_domain()}/{LABEL}"
    loaded = run_launchctl("print", target, check=False).returncode == 0
    if loaded:
        if wait_for_health():
            return
        # Without -k, kickstart starts a stopped job without terminating a busy one.
        run_launchctl("kickstart", target)
    elif AGENT_PATH.exists():
        run_launchctl("bootstrap", launchd_domain(), str(AGENT_PATH))
    else:
        install()

    if wait_for_health():
        return
    raise SystemExit(
        "SelfIndex service is not responding. Check launchd status and service logs; "
        "use the explicit restart command only after inspecting the process."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the SelfIndex macOS user service.")
    parser.add_argument("action", choices=["render", "install", "uninstall", "restart", "status", "ensure"])
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("This launchd helper only runs on macOS.")
    if args.action == "render":
        sys.stdout.buffer.write(plistlib.dumps(agent_config(), sort_keys=False))
    elif args.action == "install":
        install()
    elif args.action == "uninstall":
        uninstall()
    elif args.action == "restart":
        restart()
    elif args.action == "ensure":
        ensure()
    else:
        status()


if __name__ == "__main__":
    main()
