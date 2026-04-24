"""
window_manager.py — ウィンドウ整列・配置制御モジュール

アプリ本体・OBS・Zoom の各ウィンドウを指定座標・サイズに移動する。
Windows 専用モジュール（pywin32 依存）。
"""

import logging
from typing import Optional

try:
    import win32gui
except ImportError:
    win32gui = None  # type: ignore

from src.zoom_controller import WindowPosition, ZoomController

logger = logging.getLogger(__name__)


class WindowManager:
    def __init__(
        self,
        app_hwnd: int,
        zoom_controller: ZoomController,
        app_layout: Optional[WindowPosition] = None,
        obs_layout: Optional[WindowPosition] = None,
        zoom_layout: Optional[WindowPosition] = None,
        zoom_mini_view_threshold: int = 400,
    ) -> None:
        self._app_hwnd = app_hwnd
        self._zoom_controller = zoom_controller
        self._app_layout = app_layout
        self._obs_layout = obs_layout
        self._zoom_layout = zoom_layout
        self._zoom_mini_view_threshold = zoom_mini_view_threshold

    def arrange_all(self) -> None:
        """3ウィンドウを整列する。各ステップが失敗しても次を実行する。"""
        for fn in (self.arrange_app, self.arrange_obs, self.arrange_zoom):
            try:
                fn()
            except Exception as exc:
                logger.warning("ウィンドウ整列ステップ失敗: %s", exc)

    def arrange_app(self) -> None:
        """アプリ本体ウィンドウを指定座標・サイズに移動する。"""
        if not self._app_hwnd or self._app_layout is None:
            return
        if win32gui is None:
            return
        p = self._app_layout
        win32gui.MoveWindow(self._app_hwnd, p.x, p.y, p.width, p.height, True)

    def arrange_obs(self) -> None:
        """OBSウィンドウを指定座標・サイズに移動する。"""
        if self._obs_layout is None:
            return
        hwnd = self._find_obs_hwnd()
        if hwnd is None:
            return
        p = self._obs_layout
        if win32gui is not None:
            win32gui.MoveWindow(hwnd, p.x, p.y, p.width, p.height, True)

    def arrange_zoom(self) -> None:
        """Zoomウィンドウを整列する。ミニ会議ビューの場合は通常サイズに強制リサイズする。"""
        hwnd = self._zoom_controller.get_window_hwnd()
        if hwnd is None:
            return
        if self._zoom_layout is None:
            # ミニ会議ビューチェックのみ
            if win32gui is not None:
                rect = win32gui.GetWindowRect(hwnd)
                current_width = rect[2] - rect[0]
                if current_width < self._zoom_mini_view_threshold:
                    logger.warning(
                        "Zoom ミニ会議ビューを検出しましたが zoom_layout が未設定のためリサイズできません。"
                    )
            return
        if win32gui is not None:
            rect = win32gui.GetWindowRect(hwnd)
            current_width = rect[2] - rect[0]
            if current_width < self._zoom_mini_view_threshold:
                logger.info("Zoom ミニ会議ビューを検出。通常サイズに強制リサイズします。")
        self._zoom_controller.set_window_position(self._zoom_layout)

    def _find_obs_hwnd(self) -> Optional[int]:
        """タイトルに 'OBS ' を含む可視ウィンドウの hwnd を返す。"""
        if win32gui is None:
            return None
        result: list[int] = []

        def callback(hwnd: int, _: object) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "OBS " in title:
                    result.append(hwnd)

        win32gui.EnumWindows(callback, None)
        return result[0] if result else None
