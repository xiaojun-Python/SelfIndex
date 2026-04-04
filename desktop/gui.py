from __future__ import annotations

import time
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

from desktop.controller import DesktopController


class BackendWindow:
    """Tk-based backend console window."""

    def __init__(self, root: tk.Tk, controller: DesktopController) -> None:
        self.root = root
        self.controller = controller
        self.window = tk.Toplevel(root)
        self.window.title("SelfIndex Backend")
        self.window.geometry("1080x720")
        self.window.minsize(860, 560)
        self.window.configure(bg="#e8edf5")
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        self.status_var = tk.StringVar(value="Initializing...")
        self.command_var = tk.StringVar(value="uv run -m scripts.build_embeddings --max-units 20")

        self._build_layout()
        self.hide()

    def _build_layout(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        style = ttk.Style(self.window)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        header = tk.Frame(self.window, bg="#203047", padx=22, pady=18)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 14))
        header.grid_columnconfigure(1, weight=1)

        title = tk.Label(
            header,
            text="SelfIndex Backend",
            font=("Segoe UI", 18, "bold"),
            fg="#f7fbff",
            bg="#203047",
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = tk.Label(
            header,
            text="Control the local service, inspect runtime logs, and run maintenance commands.",
            font=("Segoe UI", 10),
            fg="#c8d6e8",
            bg="#203047",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        status = tk.Label(
            header,
            textvariable=self.status_var,
            font=("Segoe UI", 10, "bold"),
            fg="#f1f6ff",
            bg="#203047",
        )
        status.grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self.window, padding=(20, 0, 20, 20))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(body, text="Runtime Logs", padding=(14, 12))
        log_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 14))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        log_toolbar.columnconfigure(0, weight=1)

        log_hint = ttk.Label(
            log_toolbar,
            text="Service events and web request logs appear here in real time.",
        )
        log_hint.grid(row=0, column=0, sticky="w")

        ttk.Button(log_toolbar, text="Clear Logs", command=self.clear_logs).grid(
            row=0, column=1, sticky="e"
        )

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            font=("Consolas", 11),
            state="disabled",
            bg="#f7f9fc",
            fg="#182432",
            insertbackground="#182432",
            relief="flat",
            borderwidth=0,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")

        controls_frame = ttk.LabelFrame(body, text="Controls", padding=(14, 12))
        controls_frame.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for index in range(4):
            controls_frame.columnconfigure(index, weight=1)

        ttk.Button(controls_frame, text="Open Web", command=self.controller.open_web).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(controls_frame, text="Start Service", command=self.controller.start_service).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(controls_frame, text="Restart Service", command=self.controller.restart_service).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        ttk.Button(controls_frame, text="Stop Service", command=self.controller.stop_service).grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )

        command_frame = ttk.LabelFrame(body, text="CLI Command", padding=(14, 12))
        command_frame.grid(row=2, column=0, sticky="ew")
        command_frame.columnconfigure(0, weight=1)

        command_entry = ttk.Entry(command_frame, textvariable=self.command_var)
        command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        command_entry.bind("<Return>", self._run_command)

        ttk.Button(command_frame, text="Run", command=self._run_command).grid(
            row=0, column=1, sticky="ew"
        )

        tip = ttk.Label(
            command_frame,
            text="Supports plain shell commands or Python module shortcuts like `-m scripts.build_embeddings`.",
        )
        tip.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def show(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide(self) -> None:
        self.window.withdraw()

    def append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def refresh_status(self) -> None:
        state = self.controller.get_service_state()
        if state.running:
            started = time.strftime("%H:%M:%S", time.localtime(state.started_at or time.time()))
            self.status_var.set(f"Service running | PID {state.pid} | started {started}")
        else:
            self.status_var.set("Service stopped")

    def _run_command(self, _event=None) -> None:
        self.controller.run_command(self.command_var.get())
