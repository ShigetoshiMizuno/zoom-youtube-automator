"""
zoom_controller.py — Zoom クライアント自動起動・ウィンドウ制御モジュール

zoommtg:// URL スキームで Zoom を起動し、pywin32 でウィンドウを操作する。
Windows 専用モジュール（pywin32 依存）。
"""

import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

try:
    import win32gui
    import win32con
    import win32process
    import winreg
except ImportError:
    win32gui = None  # type: ignore
    win32con = None  # type: ignore
    win32process = None  # type: ignore
    winreg = None  # type: ignore

# win32process.OpenProcess に渡すフラグ
_PROCESS_TERMINATE = 0x0001


@dataclass
class WindowPosition:
    x: int       # ウィンドウ左端の画面X座標（ピクセル）
    y: int       # ウィンドウ上端の画面Y座標（ピクセル）
    width: int   # ウィンドウ幅（ピクセル）
    height: int  # ウィンドウ高さ（ピクセル）


@dataclass
class ZoomConfig:
    meeting_id: str                               # ミーティングID（ハイフン区切り可）
    password: str = ""                            # ミーティングパスコード
    display_name: str = "配信"                    # Zoom 参加時の表示名
    join_timeout: int = 30                        # ウィンドウ出現待機タイムアウト（秒）
    window_position: Optional[WindowPosition] = None  # ウィンドウ配置設定


class ZoomError(Exception):
    pass


class ZoomNotInstalledError(ZoomError):
    pass


class ZoomSchemeNotRegisteredError(ZoomError):
    pass


class ZoomJoinTimeoutError(ZoomError):
    pass


class ZoomWindowNotFoundError(ZoomError):
    pass


# Zoom ウィンドウとして認識するタイトルパターン
_ZOOM_TITLE_PATTERNS = ("Zoom Meeting", "Zoom Workplace", "Zoom")


def _is_zoom_window(hwnd: int) -> bool:
    """hwnd が Zoom のミーティングウィンドウかどうかを判定する。"""
    if not win32gui.IsWindowVisible(hwnd):
        return False
    title = win32gui.GetWindowText(hwnd)
    return any(pattern in title for pattern in _ZOOM_TITLE_PATTERNS)


def _find_zoom_hwnd() -> Optional[int]:
    """現在表示中の Zoom ウィンドウの hwnd を返す。見つからなければ None。"""
    result: list[int] = []

    def callback(hwnd: int, _extra: object) -> None:
        if _is_zoom_window(hwnd):
            result.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


class ZoomController:
    def __init__(self, config: ZoomConfig) -> None:
        self._config = config

    def build_zoom_url(self) -> str:
        """zoommtg:// URL を生成して返す。"""
        meeting_id = self._config.meeting_id.replace("-", "").replace(" ", "")
        display_name_encoded = quote(self._config.display_name, safe="")
        password_encoded = quote(self._config.password, safe="")

        url = (
            f"zoommtg://zoom.us/join?"
            f"action=join"
            f"&confno={meeting_id}"
            f"&pwd={password_encoded}"
            f"&uname={display_name_encoded}"
            f"&zc=0"
        )
        return url

    def _check_zoom_installed(self) -> None:
        """Zoom がインストールされているか（zoommtg:// スキームがレジストリに存在するか）確認する。

        レジストリキーが存在しない場合は ZoomSchemeNotRegisteredError を送出する。
        """
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "zoommtg")
        except FileNotFoundError:
            raise ZoomSchemeNotRegisteredError(
                "zoommtg:// スキームがレジストリに登録されていません。"
                "Zoom を一度手動で起動してください。"
            )

    def join_meeting(self) -> None:
        """Zoom を起動してミーティングに参加する。

        処理フロー:
        1. Zoom インストール確認
        2. zoommtg:// URL で os.startfile を呼ぶ
        3. ウィンドウが表示されるまでポーリング待機
        4. window_position が設定されていればウィンドウを移動する

        Raises:
            ZoomSchemeNotRegisteredError: zoommtg:// スキームが未登録
            ZoomJoinTimeoutError: join_timeout 秒以内にウィンドウが現れなかった
        """
        self._check_zoom_installed()

        url = self.build_zoom_url()
        os.startfile(url)

        hwnd = self._wait_for_zoom_window()

        if self._config.window_position is not None:
            self._move_window(hwnd, self._config.window_position)

    def _wait_for_zoom_window(self) -> int:
        """Zoom ウィンドウが現れるまでポーリングして hwnd を返す。

        Raises:
            ZoomJoinTimeoutError: タイムアウト到達時
        """
        for _ in range(self._config.join_timeout):
            hwnd = _find_zoom_hwnd()
            if hwnd is not None:
                return hwnd
            time.sleep(1)

        raise ZoomJoinTimeoutError(
            f"Zoom の起動が {self._config.join_timeout} 秒でタイムアウトしました。"
            "手動でミーティングに参加してください。"
        )

    def leave_meeting(self) -> None:
        """Zoom ミーティングを終了する。

        フォールバック順序:
        1. PostMessage(WM_CLOSE) — 非同期
        2. 2.5 秒待機
        3. ウィンドウが残っていれば SendMessage(WM_CLOSE) — 同期
        4. 1 秒待機
        5. それでも残っていれば TerminateProcess で強制終了

        Raises:
            ZoomWindowNotFoundError: Zoom ウィンドウが見つからない
        """
        hwnd = _find_zoom_hwnd()
        if hwnd is None:
            raise ZoomWindowNotFoundError(
                "Zoom ウィンドウが見つかりません。Zoom が起動しているか確認してください。"
            )

        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(2.5)

        if win32gui.IsWindow(hwnd):
            win32gui.SendMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1)

        if win32gui.IsWindow(hwnd):
            pid = win32gui.GetWindowThreadProcessId(hwnd)[1]
            handle = win32process.OpenProcess(_PROCESS_TERMINATE, False, pid)
            win32process.TerminateProcess(handle, 1)

    def set_window_position(self, position: WindowPosition) -> None:
        """Zoom ウィンドウを指定の座標・サイズに移動する。

        Raises:
            ZoomWindowNotFoundError: Zoom ウィンドウが見つからない
        """
        hwnd = _find_zoom_hwnd()
        if hwnd is None:
            raise ZoomWindowNotFoundError(
                "Zoom ウィンドウが見つかりません。Zoom が起動しているか確認してください。"
            )
        self._move_window(hwnd, position)

    def _move_window(self, hwnd: int, position: WindowPosition) -> None:
        """hwnd のウィンドウを前面表示して指定位置・サイズに移動する。"""
        win32gui.SetForegroundWindow(hwnd)
        win32gui.MoveWindow(hwnd, position.x, position.y, position.width, position.height, True)

    def is_meeting_active(self) -> bool:
        """Zoom ミーティングウィンドウが存在すれば True を返す。"""
        return _find_zoom_hwnd() is not None
