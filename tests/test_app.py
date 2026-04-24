"""App GUI 単体テスト

TkinterのGUIをheadlessモードで検証する。
App.__init__ の headless=True でウィンドウを非表示にし、
モックを注入して各機能を検証する。
"""

import datetime
import sys
import time
import unittest
import unittest.mock as mock
from pathlib import Path

# src/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import App, AppState


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

def make_app(**kwargs):
    """テスト用 App インスタンスを生成する。

    デフォルトでモックを注入し、headless=True で起動する。
    追加キーワード引数で各モックを上書きできる。
    """
    obs = mock.MagicMock()
    zoom = mock.MagicMock()
    youtube = mock.MagicMock()
    thumb = mock.MagicMock()

    defaults = dict(
        obs_client=obs,
        zoom_controller=zoom,
        youtube_uploader=youtube,
        thumbnail_generator=thumb,
        headless=True,
    )
    defaults.update(kwargs)
    a = App(**defaults)
    return a


def wait_for_threads(timeout=2.0):
    """バックグラウンドスレッドが完了するまで待機する。"""
    import threading
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # daemon スレッド以外が残っていなければ終了
        non_daemon = [
            t for t in threading.enumerate()
            if not t.daemon and t is not threading.current_thread()
        ]
        if not non_daemon:
            break
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# 初期化テスト
# ---------------------------------------------------------------------------

class TestInitialization(unittest.TestCase):

    def setUp(self):
        self.app = make_app()

    def tearDown(self):
        self.app.destroy()

    def test_initial_state_is_idle(self):
        self.assertEqual(self.app.state, AppState.IDLE)

    def test_initial_date_is_today(self):
        today = datetime.date.today()
        expected = f"{today.year}年{today.month}月{today.day}日"
        self.assertEqual(self.app.entry_date.get(), expected)

    def test_initial_btn_start_enabled(self):
        self.assertEqual(str(self.app.btn_start["state"]), "normal")

    def test_initial_btn_stop_disabled(self):
        self.assertEqual(str(self.app.btn_stop["state"]), "disabled")

    def test_initial_visibility_is_public(self):
        self.assertEqual(self.app.var_visibility.get(), "public")


# ---------------------------------------------------------------------------
# バリデーションテスト
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):

    def setUp(self):
        self.app = make_app()

    def tearDown(self):
        self.app.destroy()

    @mock.patch("tkinter.messagebox.showwarning")
    def test_start_validation_empty_title_shows_warning(self, mock_warn):
        # entry_date に値あり、title は空のまま
        self.app.entry_scripture.delete(0, "end")
        self.app.entry_scripture.insert(0, "テスト箇所")
        self.app.entry_preacher.delete(0, "end")
        self.app.entry_preacher.insert(0, "テスト説教者")
        # title は空のまま
        self.app.on_start_click()
        mock_warn.assert_called_once()
        self.assertEqual(self.app.state, AppState.IDLE)

    @mock.patch("tkinter.messagebox.showwarning")
    def test_start_validation_empty_date_shows_warning(self, mock_warn):
        self.app.entry_date.delete(0, "end")
        # date を空にして呼び出す
        self.app.on_start_click()
        mock_warn.assert_called_once()

    @mock.patch("tkinter.messagebox.showwarning")
    def test_start_validation_all_filled_proceeds(self, mock_warn):
        self.app.entry_date.delete(0, "end")
        self.app.entry_date.insert(0, "2026年4月25日")
        self.app.entry_title.delete(0, "end")
        self.app.entry_title.insert(0, "テストタイトル")
        self.app.entry_scripture.delete(0, "end")
        self.app.entry_scripture.insert(0, "テスト箇所")
        self.app.entry_preacher.delete(0, "end")
        self.app.entry_preacher.insert(0, "テスト説教者")
        self.app.on_start_click()
        mock_warn.assert_not_called()
        # 状態が RECORDING に遷移していること
        self.assertEqual(self.app.state, AppState.RECORDING)


# ---------------------------------------------------------------------------
# 状態遷移テスト
# ---------------------------------------------------------------------------

class TestStateTransitions(unittest.TestCase):

    def setUp(self):
        self.app = make_app()

    def tearDown(self):
        self.app.destroy()

    def _go_to_recording(self):
        """RECORDING状態に遷移させる（バリデーションを通過させる）。"""
        self.app.entry_date.delete(0, "end")
        self.app.entry_date.insert(0, "2026年4月25日")
        self.app.entry_title.delete(0, "end")
        self.app.entry_title.insert(0, "テストタイトル")
        self.app.entry_scripture.delete(0, "end")
        self.app.entry_scripture.insert(0, "テスト箇所")
        self.app.entry_preacher.delete(0, "end")
        self.app.entry_preacher.insert(0, "テスト説教者")
        with mock.patch("tkinter.messagebox.showwarning"):
            self.app.on_start_click()

    def test_transition_to_recording_disables_start_btn(self):
        self._go_to_recording()
        self.assertEqual(str(self.app.btn_start["state"]), "disabled")

    def test_transition_to_recording_enables_stop_btn(self):
        self._go_to_recording()
        self.assertEqual(str(self.app.btn_stop["state"]), "normal")

    def test_transition_to_recording_disables_form(self):
        self._go_to_recording()
        self.assertEqual(str(self.app.entry_title["state"]), "disabled")

    def test_transition_to_uploading_disables_both_btns(self):
        self.app._apply_state(AppState.UPLOADING)
        self.assertEqual(str(self.app.btn_start["state"]), "disabled")
        self.assertEqual(str(self.app.btn_stop["state"]), "disabled")

    def test_transition_to_done_enables_start_btn(self):
        self.app._apply_state(AppState.DONE)
        self.assertEqual(str(self.app.btn_start["state"]), "normal")

    def test_transition_to_done_shows_reset_btn(self):
        self.app._apply_state(AppState.DONE)
        # btn_reset が表示されている（pack/grid されている）こと
        # winfo_ismapped() で確認
        self.app.update_idletasks()
        self.assertTrue(self.app.btn_reset.winfo_ismapped())

    def test_transition_to_error_enables_start_btn(self):
        self.app._apply_state(AppState.ERROR)
        self.assertEqual(str(self.app.btn_start["state"]), "normal")


# ---------------------------------------------------------------------------
# on_start_click テスト
# ---------------------------------------------------------------------------

class TestOnStartClick(unittest.TestCase):

    def setUp(self):
        self.obs = mock.MagicMock()
        self.zoom = mock.MagicMock()
        self.app = make_app(obs_client=self.obs, zoom_controller=self.zoom)
        # フォームを埋める
        self.app.entry_date.delete(0, "end")
        self.app.entry_date.insert(0, "2026年4月25日")
        self.app.entry_title.delete(0, "end")
        self.app.entry_title.insert(0, "テストタイトル")
        self.app.entry_scripture.delete(0, "end")
        self.app.entry_scripture.insert(0, "テスト箇所")
        self.app.entry_preacher.delete(0, "end")
        self.app.entry_preacher.insert(0, "テスト説教者")

    def tearDown(self):
        self.app.destroy()

    def test_on_start_calls_obs_start_recording(self):
        self.app.on_start_click()
        # バックグラウンドスレッドが完了するまで待つ
        time.sleep(0.3)
        self.app.update()
        self.obs.start_recording.assert_called_once()

    def test_on_start_calls_zoom_join_meeting(self):
        self.app.on_start_click()
        time.sleep(0.3)
        self.app.update()
        self.zoom.join_meeting.assert_called_once()


# ---------------------------------------------------------------------------
# on_stop_click テスト
# ---------------------------------------------------------------------------

class TestOnStopClick(unittest.TestCase):

    def setUp(self):
        self.obs = mock.MagicMock()
        self.obs.stop_recording.return_value = "/tmp/test.mp4"
        self.youtube = mock.MagicMock()
        self.youtube.return_value = "https://www.youtube.com/watch?v=TEST"
        self.thumb = mock.MagicMock()
        self.thumb.return_value = "/tmp/thumbnail.png"
        self.app = make_app(
            obs_client=self.obs,
            youtube_uploader=self.youtube,
            thumbnail_generator=self.thumb,
        )
        # RECORDING状態に直接設定する
        self.app._apply_state(AppState.RECORDING)
        self.app._recording_start_time = datetime.datetime.now()

    def tearDown(self):
        self.app.destroy()

    @mock.patch("tkinter.messagebox.askokcancel", return_value=False)
    def test_on_stop_cancelled_when_dialog_returns_false(self, mock_dialog):
        self.app.on_stop_click()
        self.assertEqual(self.app.state, AppState.RECORDING)

    @mock.patch("tkinter.messagebox.askokcancel", return_value=True)
    def test_on_stop_calls_obs_stop_recording(self, mock_dialog):
        self.app.on_stop_click()
        time.sleep(0.3)
        self.app.update()
        self.obs.stop_recording.assert_called_once()


# ---------------------------------------------------------------------------
# on_reset_click テスト
# ---------------------------------------------------------------------------

class TestOnResetClick(unittest.TestCase):

    def setUp(self):
        self.app = make_app()
        # DONE状態にして btn_reset を表示させる
        self.app._apply_state(AppState.DONE)
        self.app.update_idletasks()
        # フィールドに値を設定する
        self.app.entry_title.config(state="normal")
        self.app.entry_title.delete(0, "end")
        self.app.entry_title.insert(0, "テストタイトル")
        self.app.entry_scripture.config(state="normal")
        self.app.entry_scripture.delete(0, "end")
        self.app.entry_scripture.insert(0, "テスト箇所")
        self.app.entry_preacher.config(state="normal")
        self.app.entry_preacher.delete(0, "end")
        self.app.entry_preacher.insert(0, "テスト説教者")

    def tearDown(self):
        self.app.destroy()

    def test_on_reset_clears_title(self):
        self.app.on_reset_click()
        self.assertEqual(self.app.entry_title.get(), "")

    def test_on_reset_clears_scripture(self):
        self.app.on_reset_click()
        self.assertEqual(self.app.entry_scripture.get(), "")

    def test_on_reset_restores_idle_state(self):
        self.app.on_reset_click()
        self.assertEqual(self.app.state, AppState.IDLE)

    def test_on_reset_hides_reset_btn(self):
        self.app.on_reset_click()
        self.app.update_idletasks()
        self.assertFalse(self.app.btn_reset.winfo_ismapped())


# ---------------------------------------------------------------------------
# on_close_handler テスト
# ---------------------------------------------------------------------------

class TestOnCloseHandler(unittest.TestCase):

    def setUp(self):
        self.obs = mock.MagicMock()
        self.app = make_app(obs_client=self.obs)

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    @mock.patch("tkinter.messagebox.askokcancel")
    def test_close_in_idle_destroys_without_dialog(self, mock_dialog):
        with mock.patch.object(self.app, "destroy") as mock_destroy:
            self.app.on_close_handler()
            mock_dialog.assert_not_called()
            mock_destroy.assert_called_once()

    @mock.patch("tkinter.messagebox.askokcancel", return_value=False)
    def test_close_in_recording_asks_confirmation(self, mock_dialog):
        self.app._apply_state(AppState.RECORDING)
        self.app._recording_start_time = datetime.datetime.now()
        with mock.patch.object(self.app, "destroy"):
            self.app.on_close_handler()
        mock_dialog.assert_called_once()

    @mock.patch("tkinter.messagebox.askokcancel", return_value=True)
    def test_close_in_recording_stops_obs_on_confirm(self, mock_dialog):
        self.app._apply_state(AppState.RECORDING)
        self.app._recording_start_time = datetime.datetime.now()
        with mock.patch.object(self.app, "destroy"):
            self.app.on_close_handler()
        self.obs.stop_recording.assert_called_once()


# ---------------------------------------------------------------------------
# OBSステータスラベルテスト
# ---------------------------------------------------------------------------

class TestObsStatusLabel(unittest.TestCase):

    def setUp(self):
        self.app = make_app()

    def tearDown(self):
        self.app.destroy()

    def test_obs_status_label_exists(self):
        self.assertIsNotNone(self.app.lbl_obs_status)


if __name__ == "__main__":
    unittest.main()
