from __future__ import annotations

import os
import queue
import shlex
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessState:
    running: bool
    pid: int | None
    started_at: float | None


class DesktopController:
    """Manage the SelfIndex web service and auxiliary CLI commands."""

    def __init__(
        self,
        *,
        project_root: Path,
        host: str,
        port: int,
        python_executable: str | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.host = host
        self.port = port
        self.python_executable = python_executable or sys.executable

        self._service_process: subprocess.Popen | None = None
        self._service_started_at: float | None = None
        self._command_processes: set[subprocess.Popen] = set()
        self._lock = threading.RLock()
        self.log_queue: queue.Queue[str] = queue.Queue()

    @property
    def web_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def get_service_state(self) -> ProcessState:
        with self._lock:
            process = self._service_process
            running = process is not None and process.poll() is None
            pid = process.pid if running and process is not None else None
            return ProcessState(
                running=running,
                pid=pid,
                started_at=self._service_started_at if running else None,
            )

    def start_service(self) -> None:
        with self._lock:
            if self._service_process is not None and self._service_process.poll() is None:
                self._emit("Service already running.")
                return

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            command = [self.python_executable, "-m", "app.main"]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._service_process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=creationflags,
            )
            self._service_started_at = time.time()
            self._emit(f"Starting service: {' '.join(command)}")
            self._emit(f"Web URL: {self.web_url}")
            self._start_reader_thread(self._service_process, prefix="[service]")

    def stop_service(self) -> None:
        with self._lock:
            process = self._service_process
            if process is None or process.poll() is not None:
                self._emit("Service is not running.")
                self._service_process = None
                self._service_started_at = None
                return

            self._emit("Stopping service...")
            process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._emit("Service did not stop in time, killing it.")
            process.kill()
            process.wait(timeout=5)

        with self._lock:
            self._service_process = None
            self._service_started_at = None
        self._emit("Service stopped.")

    def restart_service(self) -> None:
        self._emit("Restarting service...")
        self.stop_service()
        self.start_service()

    def open_web(self) -> None:
        self._emit(f"Opening web page: {self.web_url}")
        webbrowser.open(self.web_url)

    def run_command(self, command_text: str) -> None:
        command_text = (command_text or "").strip()
        if not command_text:
            self._emit("No command entered.")
            return

        self._emit(f"[command] {command_text}")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        if command_text.startswith("-m "):
            args = shlex.split(command_text)
            command = [self.python_executable, *args]
            shell = False
        elif command_text.startswith("python ") or command_text.startswith("python.exe "):
            args = shlex.split(command_text)
            command = [self.python_executable, *args[1:]]
            shell = False
        else:
            command = command_text
            shell = True

        process = subprocess.Popen(
            command,
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
            shell=shell,
        )
        with self._lock:
            self._command_processes.add(process)
        self._start_reader_thread(process, prefix="[command]", cleanup=True)

    def shutdown(self) -> None:
        self._emit("Shutting down desktop runtime...")
        with self._lock:
            command_processes = list(self._command_processes)
        for process in command_processes:
            if process.poll() is None:
                process.terminate()
        self.stop_service()

    def _start_reader_thread(
        self,
        process: subprocess.Popen,
        *,
        prefix: str,
        cleanup: bool = False,
    ) -> None:
        thread = threading.Thread(
            target=self._read_process_output,
            args=(process, prefix, cleanup),
            daemon=True,
        )
        thread.start()

    def _read_process_output(
        self,
        process: subprocess.Popen,
        prefix: str,
        cleanup: bool,
    ) -> None:
        assert process.stdout is not None
        try:
            for raw_line in iter(process.stdout.readline, ""):
                line = raw_line.rstrip()
                if line:
                    self._emit(f"{prefix} {line}")
            process.wait()
            self._emit(f"{prefix} exited with code {process.returncode}.")
        finally:
            if cleanup:
                with self._lock:
                    self._command_processes.discard(process)
            elif process is self._service_process and process.poll() is not None:
                with self._lock:
                    self._service_process = None
                    self._service_started_at = None

    def _emit(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")
