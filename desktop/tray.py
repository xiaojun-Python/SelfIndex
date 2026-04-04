from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

HANDLE = wintypes.HANDLE
HCURSOR = HANDLE
HBRUSH = HANDLE
LRESULT = ctypes.c_ssize_t


WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_APP_NOTIFY = WM_USER + 1

NIF_MESSAGE = 0x0001
NIF_ICON = 0x0002
NIF_TIP = 0x0004
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

TPM_LEFTALIGN = 0x0000
TPM_BOTTOMALIGN = 0x0020
TPM_RIGHTBUTTON = 0x0002

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_DEFAULTSIZE = 0x0040
LR_SHARED = 0x8000

CS_VREDRAW = 0x0001
CS_HREDRAW = 0x0002

CW_USEDEFAULT = 0x80000000

MENU_OPEN_BACKEND = 1001
MENU_OPEN_WEB = 1002
MENU_RESTART = 1003
MENU_EXIT = 1004


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class TrayIcon:
    """Minimal native Windows tray icon with a popup menu."""

    def __init__(
        self,
        *,
        on_open_backend,
        on_open_web,
        on_restart,
        on_exit,
    ) -> None:
        self.on_open_backend = on_open_backend
        self.on_open_web = on_open_web
        self.on_restart = on_restart
        self.on_exit = on_exit

        self.user32 = ctypes.windll.user32
        self.shell32 = ctypes.windll.shell32
        self.kernel32 = ctypes.windll.kernel32
        self.hinstance = self.kernel32.GetModuleHandleW(None)
        self.user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self.user32.DefWindowProcW.restype = LRESULT

        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._hwnd = None
        self._notify_id = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._thread_ready.wait(timeout=5)

    def stop(self) -> None:
        if self._hwnd:
            self.user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        wnd_proc_type = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        wnd_proc = wnd_proc_type(self._wnd_proc)
        class_name = "SelfIndexTrayWindow"

        wnd_class = WNDCLASS()
        wnd_class.style = CS_HREDRAW | CS_VREDRAW
        wnd_class.lpfnWndProc = ctypes.cast(wnd_proc, ctypes.c_void_p).value
        wnd_class.hInstance = self.hinstance
        wnd_class.lpszClassName = class_name

        self.user32.RegisterClassW(ctypes.byref(wnd_class))

        hwnd = self.user32.CreateWindowExW(
            0,
            class_name,
            "SelfIndex Tray",
            0,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            None,
            None,
            self.hinstance,
            None,
        )
        self._hwnd = hwnd
        self._wnd_proc_ref = wnd_proc

        hicon = self.user32.LoadIconW(None, IDI_APPLICATION)
        notify_id = NOTIFYICONDATA()
        notify_id.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        notify_id.hWnd = hwnd
        notify_id.uID = 1
        notify_id.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        notify_id.uCallbackMessage = WM_APP_NOTIFY
        notify_id.hIcon = hicon
        notify_id.szTip = "SelfIndex"
        self._notify_id = notify_id
        self.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(notify_id))

        self._thread_ready.set()
        msg = MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            self.user32.TranslateMessage(ctypes.byref(msg))
            self.user32.DispatchMessageW(ctypes.byref(msg))

        self.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notify_id))
        self.user32.DestroyWindow(hwnd)
        self.user32.UnregisterClassW(class_name, self.hinstance)

    def _show_menu(self) -> None:
        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, 0, MENU_OPEN_BACKEND, "Open Backend")
        self.user32.AppendMenuW(menu, 0, MENU_OPEN_WEB, "Open Web")
        self.user32.AppendMenuW(menu, 0, MENU_RESTART, "Restart Program")
        self.user32.AppendMenuW(menu, 0, MENU_EXIT, "Exit")

        point = POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        self.user32.SetForegroundWindow(self._hwnd)
        self.user32.TrackPopupMenu(
            menu,
            TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            self._hwnd,
            None,
        )
        self.user32.DestroyMenu(menu)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_APP_NOTIFY:
            if lparam == WM_LBUTTONUP:
                self.on_open_backend()
            elif lparam in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            return 0

        if msg == WM_COMMAND:
            command_id = wparam & 0xFFFF
            if command_id == MENU_OPEN_BACKEND:
                self.on_open_backend()
            elif command_id == MENU_OPEN_WEB:
                self.on_open_web()
            elif command_id == MENU_RESTART:
                self.on_restart()
            elif command_id == MENU_EXIT:
                self.on_exit()
            return 0

        if msg == WM_DESTROY:
            self.user32.PostQuitMessage(0)
            return 0

        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
