from __future__ import annotations

import atexit
import ctypes
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from app.core.settings import settings
from desktop.controller import DesktopController
from desktop.gui import BackendWindow
from desktop.tray import TrayIcon

ERROR_ALREADY_EXISTS = 183
RUNTIME_MUTEX_NAME = "Local\\SelfIndexDesktopRuntime"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
PID_FILE = DATA_DIR / "selfindex-service.pid"


def _show_already_running_message() -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "SelfIndex 已经在运行。",
            "SelfIndex",
            0x00000040,
        )
    except Exception:
        pass


def _write_runtime_pid() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")


def _remove_runtime_pid_if_owned() -> None:
    try:
        if not PID_FILE.exists():
            return
        current_pid_text = PID_FILE.read_text(encoding="ascii").strip()
        if current_pid_text == str(os.getpid()):
            PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


class DesktopRuntime:
    def __init__(self) -> None:
        self._configure_dpi_awareness()
        self.root = tk.Tk()
        self._configure_root_scaling()
        self.root.withdraw()

        self.controller = DesktopController(
            project_root=Path(__file__).resolve().parents[1],
            host=settings.host,
            port=settings.port,
        )
        self.backend_window = BackendWindow(self.root, self.controller)
        self.tray = TrayIcon(
            on_open_backend=self._schedule(self.backend_window.show),
            on_open_web=self._schedule(self.controller.open_web),
            on_restart=self._schedule(self.restart_program),
            on_exit=self._schedule(self.quit),
        )

    def run(self) -> None:
        _write_runtime_pid()
        self.controller.start_service()
        self.tray.start()
        self.root.after(150, self._drain_logs)
        self.root.after(500, self._refresh_status)
        self.root.mainloop()

    def quit(self) -> None:
        try:
            self.tray.stop()
        except Exception:
            pass
        self.controller.shutdown()
        self.root.quit()
        self.root.destroy()

    def restart_program(self) -> None:
        self.controller.stop_service()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [sys.executable, "-m", "desktop.main"],
            cwd=PROJECT_ROOT,
            creationflags=creationflags,
        )
        self.quit()

    def _drain_logs(self) -> None:
        while not self.controller.log_queue.empty():
            self.backend_window.append_log(self.controller.log_queue.get())
        self.root.after(150, self._drain_logs)

    def _refresh_status(self) -> None:
        self.backend_window.refresh_status()
        self.root.after(1000, self._refresh_status)

    def _schedule(self, callback):
        def runner():
            self.root.after(0, callback)

        return runner

    def _configure_dpi_awareness(self) -> None:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def _configure_root_scaling(self) -> None:
        try:
            dpi = float(self.root.winfo_fpixels("1i"))
        except Exception:
            dpi = 96.0

        scaling = max(1.0, dpi / 96.0)
        self.root.tk.call("tk", "scaling", scaling)

        default_font = tkfont.nametofont("TkDefaultFont")
        text_font = tkfont.nametofont("TkTextFont")
        heading_font = tkfont.nametofont("TkHeadingFont")

        default_font.configure(size=max(10, round(10 * scaling)))
        text_font.configure(size=max(10, round(10 * scaling)))
        heading_font.configure(size=max(11, round(11 * scaling)))


def main() -> None:
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, RUNTIME_MUTEX_NAME)
    if not mutex:
        raise RuntimeError("Failed to create desktop runtime mutex.")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _show_already_running_message()
        return

    atexit.register(_remove_runtime_pid_if_owned)
    runtime = DesktopRuntime()
    runtime.run()


if __name__ == "__main__":
    main()
