"""OBS WebSocket連携モジュール

OBS WebSocket API v5 を通じて OBS Studio を遠隔制御する。
obsws-python 1.8.0 (ReqClient) を使用。

スレッド設計:
  - OBS専用スレッド（デーモン）内で asyncio イベントループを常駐させる
  - GUI スレッドからは _call_async() 経由で同期的に呼び出す
"""

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Callable, Optional

try:
    import obsws_python
except ImportError:
    # テスト環境など obsws-python 未インストール時も import できるよう対応
    obsws_python = None  # type: ignore[assignment]

from exceptions import (
    OBSConnectionError,
    OBSRecordingError,
    OBSSceneNotFoundError,
    OBSVirtualCamError,
)

logger = logging.getLogger(__name__)

# stop_recording() のファイル確定待ちパラメータ
_FILE_POLL_INTERVAL = 0.5  # 秒
_FILE_POLL_MAX_RETRIES = 20

# start_status_polling() のポーリング間隔
_STATUS_POLL_INTERVAL = 30  # 秒

RecordingStoppedCallback = Callable[[], None]


class OBSClient:
    """OBS WebSocket クライアント。

    使用例:
        client = OBSClient(host="localhost", port=4455, password="pass")
        client.connect()
        client.start_recording("聖日礼拝")
        path = client.stop_recording()
        client.disconnect()
    """

    def __init__(self, host: str, port: int, password: str, output_dir: str = "") -> None:
        """OBSクライアントを初期化する。接続は行わない。

        Args:
            host: OBS WebSocket サーバーのホスト名
            port: OBS WebSocket サーバーのポート番号
            password: OBS WebSocket 認証パスワード（空文字列の場合は認証なし）
            output_dir: 録画ファイルの保存先ディレクトリ。指定した場合は録画開始前に
                        OBS の保存先を上書き設定する。空文字列の場合は OBS 側のデフォルト設定を使う。
        """
        self._host = host
        self._port = port
        self._password = password
        self._output_dir = output_dir

        self._connected = False
        # 録画を意図的に開始したかどうか（ポーリングで意図しない停止を検知するために使用）
        self._is_recording_intentionally = False

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws_client = None  # obsws_python.ReqClient

        self._polling_task: Optional[asyncio.Task] = None
        self._polling_stop_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # 接続管理
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """OBS専用スレッドを起動し、OBS WebSocket サーバーに接続する。

        Raises:
            OBSConnectionError: 接続またはハンドシェイクに失敗した場合
        """
        if self._connected:
            return

        self._start_event_loop_thread()
        try:
            self._call_async(self._connect_async())
        except Exception as exc:
            self._connected = False
            raise OBSConnectionError(f"OBSへの接続に失敗しました: {exc}") from exc

    def disconnect(self) -> None:
        """状態ポーリングを停止してから OBS WebSocket サーバーを切断する。

        エラーが発生しても例外は raise しない。
        """
        self.stop_status_polling()
        try:
            if self._ws_client is not None:
                self._call_async(self._disconnect_async())
        except Exception as exc:
            logger.warning("OBS切断中にエラーが発生しました: %s", exc)
        finally:
            self._connected = False
            self._ws_client = None

    def reconnect(self) -> None:
        """切断してから再接続する。

        Raises:
            OBSConnectionError: 再接続に失敗した場合
        """
        self.disconnect()
        self.connect()

    def is_connected(self) -> bool:
        """現在 OBS WebSocket サーバーに接続中かどうかを返す。

        Returns:
            接続中であれば True、切断中であれば False
        """
        return self._connected

    # ------------------------------------------------------------------
    # 録画制御
    # ------------------------------------------------------------------

    def start_recording(self, scene_name: str) -> None:
        """指定シーンに切り替えてから録画を開始する。

        すでに録画中の場合は何もしない（冪等）。

        Args:
            scene_name: 録画対象の OBS シーン名

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSSceneNotFoundError: 指定シーンが存在しない場合
            OBSRecordingError: 録画開始リクエストが失敗した場合
        """
        self._ensure_connected()
        try:
            self._call_async(self._start_recording_async(scene_name))
        except (OBSConnectionError, OBSSceneNotFoundError, OBSRecordingError):
            raise
        except Exception as exc:
            raise OBSRecordingError(f"録画開始に失敗しました: {exc}") from exc

    def stop_recording(self) -> str:
        """録画を停止し、ファイルの書き込み完了を確認してから絶対パスを返す。

        録画中でない場合は OBSRecordingError を raise する。

        Returns:
            録画されたファイルの絶対パス文字列

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSRecordingError: 録画停止失敗・録画中でない・ファイル確定タイムアウト
        """
        self._ensure_connected()
        try:
            return self._call_async(self._stop_recording_async())
        except (OBSConnectionError, OBSRecordingError):
            raise
        except Exception as exc:
            raise OBSRecordingError(f"録画停止に失敗しました: {exc}") from exc
        finally:
            self._is_recording_intentionally = False

    def get_recording_status(self) -> bool:
        """現在録画中かどうかを返す。

        Returns:
            録画中であれば True、停止中であれば False

        Raises:
            OBSConnectionError: 接続が切れている場合
        """
        self._ensure_connected()
        try:
            return self._call_async(self._get_recording_status_async())
        except OBSConnectionError:
            raise
        except Exception as exc:
            raise OBSConnectionError(f"録画状態の取得に失敗しました: {exc}") from exc

    # ------------------------------------------------------------------
    # 仮想カメラ制御
    # ------------------------------------------------------------------

    def start_virtual_cam(self) -> None:
        """OBS 仮想カメラを起動する。

        すでに起動中の場合は何もしない（冪等）。

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSVirtualCamError: 仮想カメラ起動リクエストが失敗した場合
        """
        self._ensure_connected()
        try:
            self._call_async(self._start_virtual_cam_async())
        except (OBSConnectionError, OBSVirtualCamError):
            raise
        except Exception as exc:
            raise OBSVirtualCamError(f"仮想カメラ起動に失敗しました: {exc}") from exc

    def stop_virtual_cam(self) -> None:
        """OBS 仮想カメラを停止する。

        すでに停止中の場合は何もしない（冪等）。

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSVirtualCamError: 仮想カメラ停止リクエストが失敗した場合
        """
        self._ensure_connected()
        try:
            self._call_async(self._stop_virtual_cam_async())
        except (OBSConnectionError, OBSVirtualCamError):
            raise
        except Exception as exc:
            raise OBSVirtualCamError(f"仮想カメラ停止に失敗しました: {exc}") from exc

    # ------------------------------------------------------------------
    # 状態ポーリング
    # ------------------------------------------------------------------

    def start_status_polling(self, on_recording_stopped: RecordingStoppedCallback) -> None:
        """OBS 録画状態のポーリングを開始する。

        30秒ごとに録画状態を確認し、意図しない停止を検知した場合にコールバックを呼ぶ。
        ポーリングは OBS専用スレッドの asyncio.Task として実行する。
        すでにポーリング中の場合は何もしない（冪等）。

        Args:
            on_recording_stopped: 録画が意図せず停止した際に呼ばれるコールバック。
                                   GUI 転送はコントローラー側の責任とする。
        """
        if self._polling_task is not None:
            return

        if self._loop is None:
            return

        # イベントループ内で Task を作成する
        future = asyncio.run_coroutine_threadsafe(
            self._schedule_polling(on_recording_stopped), self._loop
        )
        # スケジューリング完了を待つが、タスク本体の完了は待たない
        future.result(timeout=5)

    def stop_status_polling(self) -> None:
        """OBS 録画状態のポーリングを停止する。

        ポーリング中でない場合は何もしない（冪等）。
        """
        if self._polling_task is None:
            return

        if self._polling_stop_event is not None and self._loop is not None:
            # イベントループスレッドからイベントをセットし、タスクのキャンセル完了を待つ
            future = asyncio.run_coroutine_threadsafe(
                self._cancel_polling_task(self._polling_task, self._polling_stop_event),
                self._loop,
            )
            try:
                future.result(timeout=5)
            except Exception as exc:
                logger.warning("ポーリングタスクのキャンセル中にエラーが発生しました: %s", exc)

        self._polling_task = None
        self._polling_stop_event = None

    # ------------------------------------------------------------------
    # 内部実装: スレッド・イベントループ管理
    # ------------------------------------------------------------------

    def _start_event_loop_thread(self) -> None:
        """OBS専用スレッドを起動し asyncio イベントループを常駐させる。"""
        if self._thread is not None and self._thread.is_alive():
            return

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OBSEventLoop")
        self._thread.start()

        # ループが起動するまで少し待つ
        timeout = 3.0
        start = time.monotonic()
        while not self._loop.is_running():
            if time.monotonic() - start > timeout:
                raise OBSConnectionError("OBS専用イベントループの起動に失敗しました")
            time.sleep(0.05)

    def _run_loop(self) -> None:
        """OBS専用スレッドのエントリポイント。"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call_async(self, coro, timeout: int = 10):
        """GUI スレッドから asyncio coroutine を同期的に呼び出す。

        Args:
            coro: 実行する coroutine
            timeout: タイムアウト秒数

        Returns:
            coroutine の戻り値
        """
        if self._loop is None:
            raise OBSConnectionError("イベントループが起動していません")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise OBSConnectionError(f"OBSリクエストがタイムアウトしました ({timeout}秒)") from exc

    def _ensure_connected(self) -> None:
        """接続中でなければ OBSConnectionError を raise する。"""
        if not self._connected:
            raise OBSConnectionError("OBSに接続されていません。connect()を呼び出してください。")

    # ------------------------------------------------------------------
    # 内部実装: 非同期メソッド
    # ------------------------------------------------------------------

    async def _connect_async(self) -> None:
        """obsws_python.ReqClient を生成して接続する。"""
        if obsws_python is None:
            raise OBSConnectionError(
                "obsws-python がインストールされていません。`pip install obsws-python` を実行してください。"
            )
        try:
            # ReqClient は接続時に自動的にハンドシェイクを行う
            client = obsws_python.ReqClient(
                host=self._host,
                port=self._port,
                password=self._password,
            )
            self._ws_client = client
            self._connected = True
            logger.info("OBS WebSocket 接続成功: %s:%s", self._host, self._port)
        except Exception as exc:
            raise OBSConnectionError(f"OBSへの接続に失敗しました: {exc}") from exc

    async def _disconnect_async(self) -> None:
        """WebSocket コネクションを正常クローズする。"""
        if self._ws_client is not None:
            try:
                self._ws_client.disconnect()
            except Exception as exc:
                logger.warning("OBS WebSocket 切断時にエラーが発生しました: %s", exc)

    async def _start_recording_async(self, scene_name: str) -> None:
        """シーン切り替え→録画開始の非同期実装。"""
        # シーン一覧を取得して scene_name の存在を確認する
        scene_list_resp = self._ws_client.get_scene_list()
        scenes = [s.get("sceneName", "") for s in scene_list_resp.scenes]
        if scene_name not in scenes:
            raise OBSSceneNotFoundError(
                f"OBSのシーン '{scene_name}' が見つかりません。"
                f"利用可能なシーン: {scenes}"
            )

        # シーンを切り替える
        self._ws_client.set_current_program_scene(scene_name)

        # 冪等性: すでに録画中なら何もしない
        status_resp = self._ws_client.get_record_status()
        if status_resp.output_active:
            logger.info("すでに録画中のため StartRecord をスキップします")
            return

        # output_dir が指定されている場合のみ保存先を設定する（start_record 直前）
        if self._output_dir:
            self._ws_client.set_record_directory(record_directory=self._output_dir)

        # 録画開始
        self._ws_client.start_record()
        self._is_recording_intentionally = True
        logger.info("OBS 録画を開始しました（シーン: %s）", scene_name)

    async def _stop_recording_async(self) -> str:
        """録画停止 → ファイル確定待ち → ファイルパス返却の非同期実装。"""
        # 録画中かどうかを確認する
        status_resp = self._ws_client.get_record_status()
        if not status_resp.output_active:
            raise OBSRecordingError("録画中ではありません。stop_recording()を呼び出す前に録画を開始してください。")

        # 録画停止（outputPath を含むレスポンスが返る）
        stop_resp = self._ws_client.stop_record()
        output_path: str = getattr(stop_resp, "output_path", None) or ""
        if not output_path:
            raise OBSRecordingError("録画停止レスポンスにファイルパスが含まれていませんでした。")

        self._is_recording_intentionally = False
        logger.info("OBS 録画停止。ファイルパス: %s", output_path)

        # ファイル書き込み完了を待つ（ブロッキング処理）
        # asyncio.get_running_loop().run_in_executor を使って別スレッドで待機し、
        # イベントループをブロックしないようにする
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._wait_for_file_stable, output_path)

        return str(Path(output_path))

    async def _get_recording_status_async(self) -> bool:
        """録画状態を取得する非同期実装。"""
        resp = self._ws_client.get_record_status()
        return bool(resp.output_active)

    async def _start_virtual_cam_async(self) -> None:
        """仮想カメラ起動の非同期実装。"""
        status_resp = self._ws_client.get_virtual_cam_status()
        if status_resp.output_active:
            logger.info("仮想カメラはすでに起動中のためスキップします")
            return

        try:
            self._ws_client.start_virtual_cam()
        except Exception as exc:
            raise OBSVirtualCamError(f"仮想カメラの起動に失敗しました: {exc}") from exc

    async def _stop_virtual_cam_async(self) -> None:
        """仮想カメラ停止の非同期実装。"""
        status_resp = self._ws_client.get_virtual_cam_status()
        if not status_resp.output_active:
            logger.info("仮想カメラはすでに停止中のためスキップします")
            return

        try:
            self._ws_client.stop_virtual_cam()
        except Exception as exc:
            raise OBSVirtualCamError(f"仮想カメラの停止に失敗しました: {exc}") from exc

    async def _cancel_polling_task(
        self,
        task: asyncio.Task,
        stop_event: asyncio.Event,
    ) -> None:
        """stop_event をセットしてタスクをキャンセルし、完了を await する。"""
        stop_event.set()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _schedule_polling(self, on_recording_stopped: RecordingStoppedCallback) -> None:
        """ポーリング Task をイベントループ内でスケジュールする。"""
        self._polling_stop_event = asyncio.Event()
        self._polling_task = asyncio.ensure_future(
            self._polling_loop(on_recording_stopped, self._polling_stop_event)
        )

    async def _polling_loop(
        self,
        on_stopped: RecordingStoppedCallback,
        stop_event: asyncio.Event,
    ) -> None:
        """30秒ごとに録画状態を確認し、意図しない停止を on_stopped で通知する。"""
        while True:
            try:
                await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=_STATUS_POLL_INTERVAL)
                # stop_event がセットされた = 正常停止
                break
            except asyncio.TimeoutError:
                pass  # 30秒経過したのでポーリング実行

            if not self._is_recording_intentionally:
                # 録画を意図的に停止済みなのでポーリングを終了する
                break

            try:
                is_active = await self._get_recording_status_async()
            except Exception as exc:
                logger.warning("ポーリング中に録画状態の取得に失敗しました: %s", exc)
                break

            if not is_active:
                logger.warning("録画が意図せず停止しました。コールバックを呼び出します。")
                on_stopped()
                break

    # ------------------------------------------------------------------
    # 内部実装: ファイル確定待ち（同期）
    # ------------------------------------------------------------------

    @staticmethod
    def _wait_for_file_stable(
        path: str,
        interval: float = _FILE_POLL_INTERVAL,
        max_retries: int = _FILE_POLL_MAX_RETRIES,
    ) -> None:
        """ファイルサイズが安定するまでポーリングする。

        OBS は StopRecord レスポンスを返した直後も書き込みを続ける場合があるため、
        2回連続で同一サイズを確認してから処理を進める。

        Args:
            path: 監視対象ファイルのパス
            interval: ポーリング間隔（秒）
            max_retries: 最大試行回数

        Raises:
            OBSRecordingError: タイムアウトした場合
        """
        prev_size = -1
        for _ in range(max_retries):
            if not os.path.exists(path):
                time.sleep(interval)
                continue
            size = os.path.getsize(path)
            if size > 0 and size == prev_size:
                logger.info("録画ファイルの書き込み完了を確認しました: %s (%d bytes)", path, size)
                return
            prev_size = size
            time.sleep(interval)

        raise OBSRecordingError(
            f"録画ファイルの確定待ちがタイムアウトしました（最大{max_retries}回試行）: {path}"
        )
