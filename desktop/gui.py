from __future__ import annotations

import time
import tkinter as tk
from tkinter import scrolledtext
from tkinter import ttk

from desktop.controller import DesktopController


class BackendWindow:
    """基于Tk的后端控制台窗口。"""

    def __init__(self, root: tk.Tk, controller: DesktopController) -> None:
        # 保存根窗口和控制器引用
        self.root = root
        self.controller = controller
        # 创建顶级窗口
        self.window = tk.Toplevel(root)
        self.window.title("SelfIndex Backend")
        self.window.geometry("1080x720")
        self.window.minsize(860, 560)
        self.window.configure(bg="#e8edf5")
        # 设置关闭按钮行为为隐藏而非关闭
        self.window.protocol("WM_DELETE_WINDOW", self.hide)

        # 初始化状态和命令变量
        self.status_var = tk.StringVar(value="Initializing...")
        self.command_var = tk.StringVar(value="")

        # 构建UI布局
        self._build_layout()
        # 初始状态为隐藏
        self.hide()

    def _build_layout(self) -> None:
        """构建窗口布局。"""
        # 配置窗口网格布局
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        # 设置主题样式
        style = ttk.Style(self.window)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        # 创建顶部标题区域
        header = tk.Frame(self.window, bg="#203047", padx=22, pady=18)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 14))
        header.grid_columnconfigure(1, weight=1)

        # 主标题
        title = tk.Label(
            header,
            text="SelfIndex Backend",
            font=("Segoe UI", 18, "bold"),
            fg="#f7fbff",
            bg="#203047",
        )
        title.grid(row=0, column=0, sticky="w")

        # 副标题
        subtitle = tk.Label(
            header,
            text="控制本地服务，检查运行时日志，并运行维护命令。",
            font=("Segoe UI", 10),
            fg="#c8d6e8",
            bg="#203047",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        # 服务状态标签
        status = tk.Label(
            header,
            textvariable=self.status_var,
            font=("Segoe UI", 10, "bold"),
            fg="#f1f6ff",
            bg="#203047",
        )
        status.grid(row=0, column=1, rowspan=2, sticky="e")

        # 创建主体内容区域
        body = ttk.Frame(self.window, padding=(20, 0, 20, 20))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        # 日志显示区域
        log_frame = ttk.LabelFrame(body, text="Runtime Logs", padding=(14, 12))
        log_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 14))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)

        # 日志工具栏
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        log_toolbar.columnconfigure(0, weight=1)

        # 日志提示文本
        log_hint = ttk.Label(
            log_toolbar,
            text="服务事件和网络请求日志会实时显示在这里。",
        )
        log_hint.grid(row=0, column=0, sticky="w")

        # 清空日志按钮
        ttk.Button(log_toolbar, text="Clear Logs", command=self.clear_logs).grid(
            row=0, column=1, sticky="e"
        )

        # 日志文本显示区域（不可编辑）
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

        # 控制按钮区域
        controls_frame = ttk.LabelFrame(body, text="Controls", padding=(14, 12))
        controls_frame.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for index in range(4):
            controls_frame.columnconfigure(index, weight=1)

        # 打开网页按钮
        ttk.Button(controls_frame, text="Open Web", command=self.controller.open_web).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        # 启动服务按钮
        ttk.Button(controls_frame, text="Start Service", command=self.controller.start_service).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        # 重启服务按钮
        ttk.Button(controls_frame, text="Restart Service", command=self.controller.restart_service).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        # 停止服务按钮
        ttk.Button(controls_frame, text="Stop Service", command=self.controller.stop_service).grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )

        # CLI命令输入区域
        command_frame = ttk.LabelFrame(body, text="CLI Command", padding=(14, 12))
        command_frame.grid(row=2, column=0, sticky="ew")
        command_frame.columnconfigure(0, weight=1)

        # 命令输入框
        command_entry = ttk.Entry(command_frame, textvariable=self.command_var)
        command_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        # 绑定回车键执行命令
        command_entry.bind("<Return>", self._run_command)

        # 运行按钮
        ttk.Button(command_frame, text="Run", command=self._run_command).grid(
            row=0, column=1, sticky="ew"
        )

        # 命令输入提示
        tip = ttk.Label(
            command_frame,
            text="支持纯 shell 命令或 Python 模块快捷方式，例如 `-m scripts.build_embeddings`。",
        )
        tip.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def show(self) -> None:
        """显示窗口并将其置于前台。"""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def hide(self) -> None:
        """隐藏窗口。"""
        self.window.withdraw()

    def append_log(self, line: str) -> None:
        """向日志文本框中追加一行内容。"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        # 自动滚动到底部
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        """清空所有日志内容。"""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def refresh_status(self) -> None:
        """刷新服务状态显示。"""
        state = self.controller.get_service_state()
        if state.running:
            if state.pid is not None:
                started = time.strftime("%H:%M:%S", time.localtime(state.started_at or time.time()))
                self.status_var.set(f"Service running | PID {state.pid} | started {started}")
            else:
                self.status_var.set("Service running | attached to existing listener")
        else:
            self.status_var.set("Service stopped")

    def _run_command(self, _event=None) -> None:
        """执行用户输入的CLI命令。"""
        self.controller.run_command(self.command_var.get())
