"""OBSClient 単体テスト

OBS が未起動の環境でも実行できるよう、obsws_python の通信処理はすべてモックする。
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# src/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exceptions import (
    OBSConnectionError,
    OBSRecordingError,
    OBSSceneNotFoundError,
    OBSVirtualCamError,
)
from obs_client import OBSClient


# ---------------------------------------------------------------------------
# ヘルパー: 接続済み OBSClient を返す
# ---------------------------------------------------------------------------

def _make_connected_client(ws_mock=None) -> OBSClient:
    """接続済み状態の OBSClient を作成して返す。

    obsws_python の ReqClient を ws_mock で差し替える。
    ws_mock が None の場合は新規 MagicMock を使用する。
    """
    client = OBSClient(host="localhost", port=4455, password="test")
    if ws_mock is None:
        ws_mock = MagicMock()

    # イベントループスレッドを起動してから接続済み状態に強制設定する
    client._start_event_loop_thread()
    client._ws_client = ws_mock
    client._connected = True
    return client, ws_mock


# ---------------------------------------------------------------------------
# __init__ / is_connected
# ---------------------------------------------------------------------------

class TestInit(unittest.TestCase):
    def test_parameters_stored(self):
        """コンストラクタで渡したパラメータが保持されること"""
        client = OBSClient(host="192.168.1.10", port=1234, password="secret")
        self.assertEqual(client._host, "192.168.1.10")
        self.assertEqual(client._port, 1234)
        self.assertEqual(client._password, "secret")

    def test_is_connected_initial_false(self):
        """初期状態で is_connected() が False を返すこと"""
        client = OBSClient(host="localhost", port=4455, password="")
        self.assertFalse(client.is_connected())


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------

class TestConnect(unittest.TestCase):
    def test_connect_success(self):
        """connect() 成功時に is_connected() が True になること"""
        client = OBSClient(host="localhost", port=4455, password="pass")
        mock_req_client = MagicMock()

        mock_obs_module = MagicMock()
        mock_obs_module.ReqClient.return_value = mock_req_client

        with patch("obs_client.obsws_python", mock_obs_module):
            client.connect()

        self.assertTrue(client.is_connected())

    def test_connect_failure_raises_connection_error(self):
        """connect() 失敗時に OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="wrong")

        mock_obs_module = MagicMock()
        mock_obs_module.ReqClient.side_effect = ConnectionRefusedError("接続拒否")

        with patch("obs_client.obsws_python", mock_obs_module):
            with self.assertRaises(OBSConnectionError):
                client.connect()

    def test_disconnect_sets_flag_false(self):
        """disconnect() 後に is_connected() が False になること"""
        client, ws_mock = _make_connected_client()
        client.disconnect()
        self.assertFalse(client.is_connected())

    def test_disconnect_no_raise_on_error(self):
        """disconnect() 中にエラーが発生しても例外を raise しないこと"""
        client, ws_mock = _make_connected_client()
        ws_mock.disconnect.side_effect = RuntimeError("予期せぬエラー")
        # 例外が外に出ないことを確認
        client.disconnect()
        self.assertFalse(client.is_connected())

    def tearDown(self):
        pass


# ---------------------------------------------------------------------------
# start_recording
# ---------------------------------------------------------------------------

class TestStartRecording(unittest.TestCase):
    def _make_scene_list_resp(self, scene_names):
        resp = MagicMock()
        resp.scenes = [{"sceneName": name} for name in scene_names]
        return resp

    def _make_record_status_resp(self, output_active: bool):
        resp = MagicMock()
        resp.output_active = output_active
        return resp

    def test_start_recording_success(self):
        """指定シーンが存在する場合に StartRecord リクエストが送信されること"""
        client, ws = _make_connected_client()
        ws.get_scene_list.return_value = self._make_scene_list_resp(["聖日礼拝", "テスト"])
        ws.get_record_status.return_value = self._make_record_status_resp(False)

        client.start_recording("聖日礼拝")

        ws.set_current_program_scene.assert_called_once_with("聖日礼拝")
        ws.start_record.assert_called_once()

    def test_start_recording_scene_not_found(self):
        """指定シーンが存在しない場合に OBSSceneNotFoundError が raise されること"""
        client, ws = _make_connected_client()
        ws.get_scene_list.return_value = self._make_scene_list_resp(["別のシーン"])

        with self.assertRaises(OBSSceneNotFoundError):
            client.start_recording("存在しないシーン")

    def test_start_recording_already_recording_is_idempotent(self):
        """すでに録画中の場合に例外なしで正常終了し start_record が呼ばれないこと"""
        client, ws = _make_connected_client()
        ws.get_scene_list.return_value = self._make_scene_list_resp(["聖日礼拝"])
        ws.get_record_status.return_value = self._make_record_status_resp(True)

        client.start_recording("聖日礼拝")  # 例外が出ないことを確認

        ws.start_record.assert_not_called()

    def test_not_connected_raises_connection_error(self):
        """未接続状態での呼び出しで OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="")
        with self.assertRaises(OBSConnectionError):
            client.start_recording("聖日礼拝")


# ---------------------------------------------------------------------------
# stop_recording
# ---------------------------------------------------------------------------

class TestStopRecording(unittest.TestCase):
    def _make_record_status_resp(self, output_active: bool):
        resp = MagicMock()
        resp.output_active = output_active
        return resp

    def _make_stop_record_resp(self, output_path: str):
        resp = MagicMock()
        resp.output_path = output_path
        return resp

    def test_stop_recording_returns_file_path(self):
        """stop_recording() がファイルパス文字列を返すこと（ファイル確定待ち込み）"""
        client, ws = _make_connected_client()
        client._is_recording_intentionally = True

        ws.get_record_status.return_value = self._make_record_status_resp(True)
        ws.stop_record.return_value = self._make_stop_record_resp("C:/録画/test.mp4")

        call_count = [0]

        def fake_getsize(path):
            call_count[0] += 1
            # 1回目: 1000, 2回目以降: 1000 (安定)
            return 1000

        with patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", side_effect=fake_getsize), \
             patch("time.sleep"):  # sleep を無効化
            result = client.stop_recording()

        self.assertEqual(result, str(Path("C:/録画/test.mp4")))

    def test_stop_recording_not_recording_raises_error(self):
        """録画中でない状態で stop_recording() を呼ぶと OBSRecordingError が raise されること"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(False)

        with self.assertRaises(OBSRecordingError):
            client.stop_recording()

    def test_stop_recording_empty_output_path_raises_error(self):
        """outputPath が空の場合に OBSRecordingError が raise されること"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(True)
        ws.stop_record.return_value = self._make_stop_record_resp("")

        with self.assertRaises(OBSRecordingError):
            client.stop_recording()

    def test_stop_recording_file_stable_timeout_raises_error(self):
        """ファイル確定待ちがタイムアウトした場合に OBSRecordingError が raise されること"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(True)
        ws.stop_record.return_value = self._make_stop_record_resp("C:/録画/test.mp4")

        size_counter = [0]

        def always_changing_size(path):
            # サイズが毎回変わり続けるためファイルが安定しない
            size_counter[0] += 1
            return size_counter[0] * 1000

        with patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", side_effect=always_changing_size), \
             patch("time.sleep"):
            with self.assertRaises(OBSRecordingError) as ctx:
                client.stop_recording()

        self.assertIn("タイムアウト", str(ctx.exception))

    def test_not_connected_raises_connection_error(self):
        """未接続状態での呼び出しで OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="")
        with self.assertRaises(OBSConnectionError):
            client.stop_recording()


# ---------------------------------------------------------------------------
# get_recording_status
# ---------------------------------------------------------------------------

class TestGetRecordingStatus(unittest.TestCase):
    def _make_record_status_resp(self, output_active: bool):
        resp = MagicMock()
        resp.output_active = output_active
        return resp

    def test_get_recording_status_true_when_recording(self):
        """録画中の場合に True を返すこと"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(True)
        self.assertTrue(client.get_recording_status())

    def test_get_recording_status_false_when_stopped(self):
        """停止中の場合に False を返すこと"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(False)
        self.assertFalse(client.get_recording_status())

    def test_not_connected_raises_connection_error(self):
        """未接続状態での呼び出しで OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="")
        with self.assertRaises(OBSConnectionError):
            client.get_recording_status()


# ---------------------------------------------------------------------------
# start_virtual_cam / stop_virtual_cam
# ---------------------------------------------------------------------------

class TestVirtualCam(unittest.TestCase):
    def _make_vcam_status_resp(self, output_active: bool):
        resp = MagicMock()
        resp.output_active = output_active
        return resp

    def test_start_virtual_cam_sends_request(self):
        """start_virtual_cam() が StartVirtualCam リクエストを送信すること"""
        client, ws = _make_connected_client()
        ws.get_virtual_cam_status.return_value = self._make_vcam_status_resp(False)

        client.start_virtual_cam()

        ws.start_virtual_cam.assert_called_once()

    def test_start_virtual_cam_already_running_is_idempotent(self):
        """仮想カメラ起動中に start_virtual_cam() を呼んでも例外なしで正常終了すること"""
        client, ws = _make_connected_client()
        ws.get_virtual_cam_status.return_value = self._make_vcam_status_resp(True)

        client.start_virtual_cam()  # 例外が出ないことを確認

        ws.start_virtual_cam.assert_not_called()

    def test_stop_virtual_cam_sends_request(self):
        """stop_virtual_cam() が StopVirtualCam リクエストを送信すること"""
        client, ws = _make_connected_client()
        ws.get_virtual_cam_status.return_value = self._make_vcam_status_resp(True)

        client.stop_virtual_cam()

        ws.stop_virtual_cam.assert_called_once()

    def test_stop_virtual_cam_already_stopped_is_idempotent(self):
        """仮想カメラ停止中に stop_virtual_cam() を呼んでも例外なしで正常終了すること"""
        client, ws = _make_connected_client()
        ws.get_virtual_cam_status.return_value = self._make_vcam_status_resp(False)

        client.stop_virtual_cam()  # 例外が出ないことを確認

        ws.stop_virtual_cam.assert_not_called()

    def test_not_connected_start_raises_connection_error(self):
        """未接続状態での start_virtual_cam() で OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="")
        with self.assertRaises(OBSConnectionError):
            client.start_virtual_cam()

    def test_not_connected_stop_raises_connection_error(self):
        """未接続状態での stop_virtual_cam() で OBSConnectionError が raise されること"""
        client = OBSClient(host="localhost", port=4455, password="")
        with self.assertRaises(OBSConnectionError):
            client.stop_virtual_cam()


# ---------------------------------------------------------------------------
# start_status_polling / stop_status_polling
# ---------------------------------------------------------------------------

class TestStatusPolling(unittest.TestCase):
    def _make_record_status_resp(self, output_active: bool):
        resp = MagicMock()
        resp.output_active = output_active
        return resp

    def test_polling_no_callback_when_recording_active(self):
        """録画が継続中の場合にコールバックが呼ばれないこと"""
        client, ws = _make_connected_client()
        ws.get_record_status.return_value = self._make_record_status_resp(True)
        client._is_recording_intentionally = True

        callback = MagicMock()
        client.start_status_polling(callback)

        # ポーリング間隔（30秒）を待たずに短時間で確認
        time.sleep(0.1)
        client.stop_status_polling()

        callback.assert_not_called()

    def test_polling_calls_callback_on_unexpected_stop(self):
        """録画が意図せず停止した場合にコールバックが呼ばれること"""
        client, ws = _make_connected_client()
        client._is_recording_intentionally = True

        # get_record_status が False を返す（意図しない停止を模擬）
        ws.get_record_status.return_value = self._make_record_status_resp(False)

        callback = MagicMock()

        # ポーリング間隔を短くするためにパッチする
        with patch("obs_client._STATUS_POLL_INTERVAL", 0.1):
            client.start_status_polling(callback)
            time.sleep(0.5)  # ポーリングが動作する時間を確保

        callback.assert_called()

    def test_stop_polling_prevents_further_callbacks(self):
        """stop_status_polling() 後にコールバックが呼ばれなくなること"""
        client, ws = _make_connected_client()
        client._is_recording_intentionally = True
        ws.get_record_status.return_value = self._make_record_status_resp(True)

        callback = MagicMock()
        with patch("obs_client._STATUS_POLL_INTERVAL", 0.1):
            client.start_status_polling(callback)
            client.stop_status_polling()
            time.sleep(0.3)

        callback.assert_not_called()

    def test_start_polling_idempotent(self):
        """すでにポーリング中に start_status_polling() を呼んでも二重起動しないこと"""
        client, ws = _make_connected_client()
        client._is_recording_intentionally = True
        ws.get_record_status.return_value = self._make_record_status_resp(True)

        callback = MagicMock()
        with patch("obs_client._STATUS_POLL_INTERVAL", 60):
            client.start_status_polling(callback)
            task_first = client._polling_task
            client.start_status_polling(callback)  # 2回目
            task_second = client._polling_task

        # 同じタスクが使われていること
        self.assertIs(task_first, task_second)
        client.stop_status_polling()


# ---------------------------------------------------------------------------
# _wait_for_file_stable（スタティックメソッドの直接テスト）
# ---------------------------------------------------------------------------

class TestWaitForFileStable(unittest.TestCase):
    def test_stable_file_returns_normally(self):
        """ファイルサイズが安定したら正常終了すること"""
        call_count = [0]

        def fake_getsize(path):
            call_count[0] += 1
            return 5000  # 常に同じサイズ

        with patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", side_effect=fake_getsize), \
             patch("time.sleep"):
            OBSClient._wait_for_file_stable("C:/test.mp4")

        # 2回目で安定を検知するはず
        self.assertGreaterEqual(call_count[0], 2)

    def test_timeout_raises_recording_error(self):
        """タイムアウトした場合に OBSRecordingError が raise されること"""
        counter = [0]

        def always_changing(path):
            counter[0] += 1
            return counter[0] * 100

        with patch("os.path.exists", return_value=True), \
             patch("os.path.getsize", side_effect=always_changing), \
             patch("time.sleep"):
            with self.assertRaises(OBSRecordingError):
                OBSClient._wait_for_file_stable("C:/test.mp4", max_retries=5)

    def test_file_not_exist_waits_and_retries(self):
        """ファイルが存在しない間は待機してリトライすること"""
        exist_call = [0]
        size_call = [0]

        def fake_exists(path):
            exist_call[0] += 1
            # 最初の3回は False、その後 True
            return exist_call[0] > 3

        def fake_size(path):
            size_call[0] += 1
            return 1000  # 常に同じサイズ

        with patch("os.path.exists", side_effect=fake_exists), \
             patch("os.path.getsize", side_effect=fake_size), \
             patch("time.sleep"):
            OBSClient._wait_for_file_stable("C:/test.mp4")

        # size_call が 0 より大きいことを確認（ファイル存在確認後にサイズ取得が走る）
        self.assertGreater(size_call[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
