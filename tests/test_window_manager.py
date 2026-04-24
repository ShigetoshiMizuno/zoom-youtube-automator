"""
WindowManager の単体テスト。

win32gui は unittest.mock.patch でモックする。
Windows 実機なしで実行できること。
"""
import sys
import types
import unittest.mock as mock

import pytest

# win32gui スタブを差し込む（実際の pywin32 がなくても import できる）
for _name in ("win32gui",):
    if _name not in sys.modules:
        mod = types.ModuleType(_name)
        sys.modules[_name] = mod

from src.window_manager import WindowManager  # noqa: E402
from src.zoom_controller import WindowPosition  # noqa: E402


@pytest.fixture
def zoom_ctrl():
    ctrl = mock.MagicMock()
    ctrl.get_window_hwnd.return_value = 12345
    return ctrl


# ---------------------------------------------------------------------------
# 基本初期化
# ---------------------------------------------------------------------------

def test_window_manager_init(zoom_ctrl):
    wm = WindowManager(app_hwnd=100, zoom_controller=zoom_ctrl)
    assert wm._app_hwnd == 100


# ---------------------------------------------------------------------------
# arrange_app
# ---------------------------------------------------------------------------

def test_arrange_app_skips_when_hwnd_zero(zoom_ctrl):
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl,
                       app_layout=WindowPosition(0, 0, 480, 360))
    with mock.patch("src.window_manager.win32gui") as m:
        wm.arrange_app()
        m.MoveWindow.assert_not_called()


def test_arrange_app_skips_when_layout_none(zoom_ctrl):
    wm = WindowManager(app_hwnd=100, zoom_controller=zoom_ctrl, app_layout=None)
    with mock.patch("src.window_manager.win32gui") as m:
        wm.arrange_app()
        m.MoveWindow.assert_not_called()


def test_arrange_app_calls_move_window(zoom_ctrl):
    layout = WindowPosition(10, 20, 480, 360)
    wm = WindowManager(app_hwnd=100, zoom_controller=zoom_ctrl, app_layout=layout)
    with mock.patch("src.window_manager.win32gui") as m:
        wm.arrange_app()
        m.MoveWindow.assert_called_once_with(100, 10, 20, 480, 360, True)


# ---------------------------------------------------------------------------
# arrange_obs
# ---------------------------------------------------------------------------

def test_arrange_obs_skips_when_layout_none(zoom_ctrl):
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, obs_layout=None)
    with mock.patch("src.window_manager.win32gui") as m:
        wm.arrange_obs()
        m.MoveWindow.assert_not_called()


def test_arrange_obs_skips_when_obs_not_found(zoom_ctrl):
    layout = WindowPosition(0, 400, 1280, 720)
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, obs_layout=layout)
    with mock.patch("src.window_manager.win32gui") as m:
        m.EnumWindows.side_effect = lambda cb, _: None  # コールバック呼ばれない
        wm.arrange_obs()
        m.MoveWindow.assert_not_called()


def test_arrange_obs_calls_move_window_when_found(zoom_ctrl):
    layout = WindowPosition(0, 400, 1280, 720)
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, obs_layout=layout)
    with mock.patch("src.window_manager.win32gui") as m:
        def enum_side_effect(cb, _):
            cb(9999, None)
        m.EnumWindows.side_effect = enum_side_effect
        m.IsWindowVisible.return_value = True
        m.GetWindowText.return_value = "OBS Studio"
        wm.arrange_obs()
        m.MoveWindow.assert_called_once_with(9999, 0, 400, 1280, 720, True)


# ---------------------------------------------------------------------------
# _find_obs_hwnd
# ---------------------------------------------------------------------------

def test_find_obs_hwnd_returns_matching_hwnd(zoom_ctrl):
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl)
    with mock.patch("src.window_manager.win32gui") as m:
        def enum_side_effect(cb, _):
            cb(111, None)
            cb(222, None)
        m.EnumWindows.side_effect = enum_side_effect
        m.IsWindowVisible.return_value = True
        m.GetWindowText.side_effect = ["OBS Studio", "Notepad"]
        result = wm._find_obs_hwnd()
        assert result == 111


def test_find_obs_hwnd_returns_none_when_not_found(zoom_ctrl):
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl)
    with mock.patch("src.window_manager.win32gui") as m:
        def enum_side_effect(cb, _):
            cb(111, None)
        m.EnumWindows.side_effect = enum_side_effect
        m.IsWindowVisible.return_value = True
        m.GetWindowText.return_value = "Notepad"
        result = wm._find_obs_hwnd()
        assert result is None


def test_find_obs_hwnd_ignores_obsidian(zoom_ctrl):
    """タイトルに 'OBS ' を含まない 'OBSIDIAN' は検出しないこと"""
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl)
    with mock.patch("src.window_manager.win32gui") as m:
        def enum_side_effect(cb, _):
            cb(111, None)
        m.EnumWindows.side_effect = enum_side_effect
        m.IsWindowVisible.return_value = True
        m.GetWindowText.return_value = "OBSIDIAN"
        result = wm._find_obs_hwnd()
        assert result is None


# ---------------------------------------------------------------------------
# arrange_zoom
# ---------------------------------------------------------------------------

def test_arrange_zoom_skips_when_layout_none(zoom_ctrl):
    zoom_ctrl.get_window_hwnd.return_value = None
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, zoom_layout=None)
    wm.arrange_zoom()
    zoom_ctrl.set_window_position.assert_not_called()


def test_arrange_zoom_skips_set_position_when_layout_none_but_hwnd_found(zoom_ctrl):
    """zoom_layout=None だが Zoom ウィンドウが見つかる場合、set_window_position は呼ばれない"""
    zoom_ctrl.get_window_hwnd.return_value = 12345  # hwnd はある
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, zoom_layout=None)
    with mock.patch("src.window_manager.win32gui") as m:
        m.GetWindowRect.return_value = (0, 0, 300, 200)  # ミニビュー相当
        wm.arrange_zoom()
        zoom_ctrl.set_window_position.assert_not_called()


def test_arrange_zoom_calls_set_window_position(zoom_ctrl):
    layout = WindowPosition(1300, 400, 1280, 720)
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, zoom_layout=layout)
    with mock.patch("src.window_manager.win32gui") as m:
        m.GetWindowRect.return_value = (1300, 400, 2580, 1120)  # 幅1280
        wm.arrange_zoom()
        zoom_ctrl.set_window_position.assert_called_once_with(layout)


def test_arrange_zoom_detects_mini_view_and_resizes(zoom_ctrl):
    layout = WindowPosition(1300, 400, 1280, 720)
    wm = WindowManager(app_hwnd=0, zoom_controller=zoom_ctrl, zoom_layout=layout,
                       zoom_mini_view_threshold=400)
    with mock.patch("src.window_manager.win32gui") as m:
        m.GetWindowRect.return_value = (0, 0, 300, 200)  # 幅300 < 400
        wm.arrange_zoom()
        zoom_ctrl.set_window_position.assert_called_once_with(layout)


# ---------------------------------------------------------------------------
# arrange_all
# ---------------------------------------------------------------------------

def test_arrange_all_partial_success(zoom_ctrl):
    layout = WindowPosition(0, 0, 480, 360)
    zoom_ctrl.get_window_hwnd.return_value = None  # Zoomが見つからない
    wm = WindowManager(app_hwnd=100, zoom_controller=zoom_ctrl,
                       app_layout=layout, obs_layout=None, zoom_layout=None)
    with mock.patch("src.window_manager.win32gui") as m:
        wm.arrange_all()  # 例外が発生しないこと
        m.MoveWindow.assert_called_once()  # appだけ移動される


def test_arrange_all_continues_after_exception(zoom_ctrl):
    layout = WindowPosition(0, 0, 480, 360)
    wm = WindowManager(app_hwnd=100, zoom_controller=zoom_ctrl,
                       app_layout=layout, obs_layout=layout, zoom_layout=layout)
    with mock.patch("src.window_manager.win32gui") as m:
        m.MoveWindow.side_effect = [Exception("失敗"), None]  # appで失敗、obsは成功
        m.EnumWindows.side_effect = lambda cb, _: cb(999, None)
        m.IsWindowVisible.return_value = True
        m.GetWindowText.return_value = "OBS Studio"
        m.GetWindowRect.return_value = (0, 0, 1280, 720)
        wm.arrange_all()  # 例外が伝播しないこと
        zoom_ctrl.set_window_position.assert_called_once()  # zoomは実行される
