"""
ZoomController の単体テスト。

pywin32 / winreg / os.startfile はすべて unittest.mock.patch でモックする。
Windows 実機なしで実行できること。
"""
import time
import unittest
from unittest.mock import MagicMock, patch, call
import sys
import types


def _make_stub(name: str) -> types.ModuleType:
    """pywin32 モジュールのスタブを作成する。"""
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# テスト実行前にスタブを差し込む（実際の pywin32 がなくても import できる）
for _name in ("win32gui", "win32con", "win32process", "winreg"):
    if _name not in sys.modules:
        _make_stub(_name)

# win32con.WM_CLOSE に値をセット
sys.modules["win32con"].WM_CLOSE = 16  # type: ignore


from src.zoom_controller import (  # noqa: E402
    WindowPosition,
    ZoomConfig,
    ZoomController,
    ZoomError,
    ZoomJoinTimeoutError,
    ZoomNotInstalledError,
    ZoomSchemeNotRegisteredError,
    ZoomWindowNotFoundError,
)


class TestWindowPosition(unittest.TestCase):
    def test_fields(self) -> None:
        pos = WindowPosition(x=100, y=200, width=1280, height=720)
        self.assertEqual(pos.x, 100)
        self.assertEqual(pos.y, 200)
        self.assertEqual(pos.width, 1280)
        self.assertEqual(pos.height, 720)


class TestZoomConfigDefaults(unittest.TestCase):
    def test_display_name_default(self) -> None:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        self.assertEqual(cfg.display_name, "配信")

    def test_join_timeout_default(self) -> None:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        self.assertEqual(cfg.join_timeout, 30)

    def test_password_default_empty(self) -> None:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        self.assertEqual(cfg.password, "")

    def test_window_position_default_none(self) -> None:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        self.assertIsNone(cfg.window_position)


class TestBuildZoomUrl(unittest.TestCase):
    def _make_controller(self, **kwargs: object) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890", **kwargs)  # type: ignore[arg-type]
        return ZoomController(cfg)

    def test_hyphen_removed_from_meeting_id(self) -> None:
        ctrl = self._make_controller()
        url = ctrl.build_zoom_url()
        self.assertIn("confno=1234567890", url)

    def test_url_contains_action_join(self) -> None:
        ctrl = self._make_controller()
        url = ctrl.build_zoom_url()
        self.assertIn("action=join", url)

    def test_url_starts_with_zoommtg(self) -> None:
        ctrl = self._make_controller()
        url = ctrl.build_zoom_url()
        self.assertTrue(url.startswith("zoommtg://zoom.us/join?"))

    def test_display_name_url_encoded(self) -> None:
        ctrl = self._make_controller(display_name="配信")
        url = ctrl.build_zoom_url()
        # "配信" の URL エンコード結果
        self.assertIn("uname=%E9%85%8D%E4%BF%A1", url)

    def test_password_included_when_set(self) -> None:
        ctrl = self._make_controller(password="abc123")
        url = ctrl.build_zoom_url()
        self.assertIn("pwd=abc123", url)

    def test_zc_zero_appended(self) -> None:
        ctrl = self._make_controller()
        url = ctrl.build_zoom_url()
        self.assertIn("zc=0", url)

    def test_meeting_id_normalization_spaces(self) -> None:
        cfg = ZoomConfig(meeting_id="123 456 7890")
        ctrl = ZoomController(cfg)
        url = ctrl.build_zoom_url()
        self.assertIn("confno=1234567890", url)


class TestExceptionHierarchy(unittest.TestCase):
    def test_zoom_not_installed_is_zoom_error(self) -> None:
        self.assertTrue(issubclass(ZoomNotInstalledError, ZoomError))

    def test_zoom_scheme_not_registered_is_zoom_error(self) -> None:
        self.assertTrue(issubclass(ZoomSchemeNotRegisteredError, ZoomError))

    def test_zoom_join_timeout_is_zoom_error(self) -> None:
        self.assertTrue(issubclass(ZoomJoinTimeoutError, ZoomError))

    def test_zoom_window_not_found_is_zoom_error(self) -> None:
        self.assertTrue(issubclass(ZoomWindowNotFoundError, ZoomError))


class TestRegistryCheck(unittest.TestCase):
    def _make_controller(self) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        return ZoomController(cfg)

    def test_raises_scheme_not_registered_when_key_missing(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.winreg") as mock_winreg:
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            with self.assertRaises(ZoomSchemeNotRegisteredError):
                ctrl._check_zoom_installed()

    def test_no_exception_when_key_exists(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.winreg") as mock_winreg:
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.return_value = MagicMock()
            # 例外が発生しないことを確認
            ctrl._check_zoom_installed()

    def test_raises_zoom_not_installed_error(self) -> None:
        """HKEY_CLASSES_ROOT zoommtg が存在しない場合に ZoomNotInstalledError が送出されること。"""
        ctrl = self._make_controller()
        with patch("src.zoom_controller.winreg") as mock_winreg:
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            # zoommtg キー自体が存在しない → ZoomNotInstalledError
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            with self.assertRaises(ZoomNotInstalledError):
                ctrl._check_zoom_installed()


class TestJoinMeeting(unittest.TestCase):
    def _make_controller(self, **kwargs: object) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890", **kwargs)  # type: ignore[arg-type]
        return ZoomController(cfg)

    def _setup_window_found(self, mock_win32gui: MagicMock) -> None:
        """EnumWindows でウィンドウが見つかる状態を設定する。"""
        def enum_windows_side_effect(callback: object, extra: object) -> None:
            callback(1234, extra)  # hwnd=1234 を返す

        mock_win32gui.EnumWindows.side_effect = enum_windows_side_effect
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "Zoom Meeting"

    def test_join_meeting_calls_startfile(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.winreg") as mock_winreg, \
             patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("os.startfile") as mock_startfile, \
             patch("time.sleep"):
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.return_value = MagicMock()
            self._setup_window_found(mock_win32gui)

            ctrl.join_meeting()

            mock_startfile.assert_called_once()
            url = mock_startfile.call_args[0][0]
            self.assertTrue(url.startswith("zoommtg://"))

    def test_join_meeting_succeeds_when_window_found(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.winreg") as mock_winreg, \
             patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("os.startfile"), \
             patch("time.sleep"):
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.return_value = MagicMock()
            self._setup_window_found(mock_win32gui)

            # 例外なく完了することを確認
            ctrl.join_meeting()

    def test_join_meeting_raises_timeout_when_window_not_found(self) -> None:
        ctrl = self._make_controller(join_timeout=1)
        with patch("src.zoom_controller.winreg") as mock_winreg, \
             patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("os.startfile"), \
             patch("time.sleep"):
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.return_value = MagicMock()
            # ウィンドウが見つからない状態
            mock_win32gui.EnumWindows.side_effect = lambda cb, extra: None
            mock_win32gui.IsWindowVisible.return_value = False

            with self.assertRaises(ZoomJoinTimeoutError):
                ctrl.join_meeting()

    def test_join_meeting_no_window_move_when_position_is_none(self) -> None:
        ctrl = self._make_controller(window_position=None)
        with patch("src.zoom_controller.winreg") as mock_winreg, \
             patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("os.startfile"), \
             patch("time.sleep"):
            mock_winreg.HKEY_CLASSES_ROOT = 0x80000000
            mock_winreg.OpenKey.return_value = MagicMock()
            self._setup_window_found(mock_win32gui)

            ctrl.join_meeting()

            mock_win32gui.MoveWindow.assert_not_called()


class TestLeaveMeeting(unittest.TestCase):
    def _make_controller(self) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        return ZoomController(cfg)

    def _setup_window_found(self, mock_win32gui: MagicMock, hwnd: int = 1234) -> None:
        def enum_windows_side_effect(callback: object, extra: object) -> None:
            callback(hwnd, extra)

        mock_win32gui.EnumWindows.side_effect = enum_windows_side_effect
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "Zoom Meeting"

    def test_leave_meeting_sends_post_message_wm_close(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("src.zoom_controller.win32con") as mock_win32con, \
             patch("time.sleep"):
            self._setup_window_found(mock_win32gui)
            mock_win32con.WM_CLOSE = 16
            # PostMessage 後はウィンドウが閉じた状態にする
            mock_win32gui.IsWindow.return_value = False

            ctrl.leave_meeting()

            mock_win32gui.PostMessage.assert_called_once_with(1234, 16, 0, 0)

    def test_leave_meeting_window_gone_after_post_message(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("src.zoom_controller.win32con") as mock_win32con, \
             patch("time.sleep"):
            self._setup_window_found(mock_win32gui)
            mock_win32con.WM_CLOSE = 16
            mock_win32gui.IsWindow.return_value = False

            # 例外なく完了することを確認
            ctrl.leave_meeting()

    def test_leave_meeting_raises_window_not_found_when_no_window(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("time.sleep"):
            mock_win32gui.EnumWindows.side_effect = lambda cb, extra: None
            mock_win32gui.IsWindowVisible.return_value = False

            with self.assertRaises(ZoomWindowNotFoundError):
                ctrl.leave_meeting()

    def test_leave_meeting_fallback_send_message(self) -> None:
        """PostMessage後もウィンドウが残る場合にSendMessageが呼ばれること。

        IsWindow が PostMessage後もTrueを返し、SendMessage後にFalseを返す場合、
        SendMessage は呼ばれ、TerminateProcess は呼ばれないこと。
        """
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("src.zoom_controller.win32con") as mock_win32con, \
             patch("src.zoom_controller.win32process") as mock_win32process, \
             patch("time.sleep"):
            self._setup_window_found(mock_win32gui)
            mock_win32con.WM_CLOSE = 16
            # PostMessage後はTrueを返し、SendMessage後にFalseを返す
            mock_win32gui.IsWindow.side_effect = [True, False]

            ctrl.leave_meeting()

            mock_win32gui.SendMessage.assert_called_once_with(1234, 16, 0, 0)
            mock_win32process.TerminateProcess.assert_not_called()

    def test_leave_meeting_fallback_terminate_process(self) -> None:
        """SendMessage後もウィンドウが残る場合にTerminateProcessが呼ばれること。

        IsWindow が PostMessage後もSendMessage後もTrueを返す場合、
        TerminateProcess が呼ばれること。
        """
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui, \
             patch("src.zoom_controller.win32con") as mock_win32con, \
             patch("src.zoom_controller.win32process") as mock_win32process, \
             patch("time.sleep"):
            self._setup_window_found(mock_win32gui)
            mock_win32con.WM_CLOSE = 16
            # PostMessage後もSendMessage後もTrueを返す
            mock_win32gui.IsWindow.return_value = True
            mock_win32gui.GetWindowThreadProcessId.return_value = (0, 9999)
            mock_win32process.OpenProcess.return_value = MagicMock()

            ctrl.leave_meeting()

            mock_win32process.TerminateProcess.assert_called_once()


class TestSetWindowPosition(unittest.TestCase):
    def _make_controller(self) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        return ZoomController(cfg)

    def test_move_window_called_with_correct_args(self) -> None:
        ctrl = self._make_controller()
        pos = WindowPosition(x=100, y=200, width=1280, height=720)

        with patch("src.zoom_controller.win32gui") as mock_win32gui:
            def enum_windows_side_effect(callback: object, extra: object) -> None:
                callback(1234, extra)

            mock_win32gui.EnumWindows.side_effect = enum_windows_side_effect
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.return_value = "Zoom Meeting"

            ctrl.set_window_position(pos)

            mock_win32gui.SetForegroundWindow.assert_called_once_with(1234)
            mock_win32gui.MoveWindow.assert_called_once_with(1234, 100, 200, 1280, 720, True)

    def test_raises_window_not_found(self) -> None:
        ctrl = self._make_controller()
        pos = WindowPosition(x=0, y=0, width=800, height=600)

        with patch("src.zoom_controller.win32gui") as mock_win32gui:
            mock_win32gui.EnumWindows.side_effect = lambda cb, extra: None
            mock_win32gui.IsWindowVisible.return_value = False

            with self.assertRaises(ZoomWindowNotFoundError):
                ctrl.set_window_position(pos)


class TestIsMeetingActive(unittest.TestCase):
    def _make_controller(self) -> ZoomController:
        cfg = ZoomConfig(meeting_id="123-456-7890")
        return ZoomController(cfg)

    def test_returns_true_when_window_exists(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui:
            def enum_windows_side_effect(callback: object, extra: object) -> None:
                callback(1234, extra)

            mock_win32gui.EnumWindows.side_effect = enum_windows_side_effect
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.return_value = "Zoom Workplace"

            self.assertTrue(ctrl.is_meeting_active())

    def test_returns_false_when_no_window(self) -> None:
        ctrl = self._make_controller()
        with patch("src.zoom_controller.win32gui") as mock_win32gui:
            mock_win32gui.EnumWindows.side_effect = lambda cb, extra: None
            mock_win32gui.IsWindowVisible.return_value = False

            self.assertFalse(ctrl.is_meeting_active())


if __name__ == "__main__":
    unittest.main()
