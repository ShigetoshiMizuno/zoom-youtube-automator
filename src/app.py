"""app.py — 礼拝配信GUIアプリ本体

Tkinter を使用したデスクトップ GUI アプリ。
礼拝情報の入力フォーム、配信開始／終了ボタン、状態表示を提供し、
OBS・Zoom・サムネイル・YouTube の各モジュールをオーケストレーションする。
"""

import datetime
import logging
import threading
import tkinter as tk
from enum import Enum
from tkinter import messagebox, ttk
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AppState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    UPLOADING = "uploading"
    DONE = "done"
    ERROR = "error"


class App(tk.Tk):
    """礼拝配信アプリのメインウィンドウ。"""

    def __init__(
        self,
        obs_client=None,
        zoom_controller=None,
        youtube_uploader=None,
        thumbnail_generator=None,
        config=None,
        headless=False,
    ):
        super().__init__()

        if headless:
            self.withdraw()

        self._config = config or {}
        self._headless = headless

        # 依存モジュールの注入（None の場合はデフォルト生成）
        if obs_client is None:
            from obs_client import OBSClient
            obs_cfg = self._config.get("obs", {})
            obs_client = OBSClient(
                host=obs_cfg.get("host", "localhost"),
                port=obs_cfg.get("port", 4455),
                password=obs_cfg.get("password", ""),
            )
        self.obs_client = obs_client

        if zoom_controller is None:
            from zoom_controller import ZoomController, ZoomConfig
            zoom_cfg = self._config.get("zoom", {})
            zoom_controller = ZoomController(
                config=ZoomConfig(
                    meeting_id=zoom_cfg.get("meeting_id", ""),
                    password=zoom_cfg.get("password", ""),
                    display_name=zoom_cfg.get("display_name", "配信"),
                )
            )
        self.zoom_controller = zoom_controller

        self.youtube_uploader: Optional[Callable] = youtube_uploader
        self.thumbnail_generator: Optional[Callable] = thumbnail_generator

        # 状態管理
        self.state: AppState = AppState.IDLE
        self._recording_start_time: Optional[datetime.datetime] = None
        self._elapsed_timer_id: Optional[str] = None
        self._obs_poll_id: Optional[str] = None

        self._build_ui()

        self.title("調布南キリスト教会 礼拝配信アプリ")
        self.geometry("480x360")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close_handler)

        if not headless:
            self._check_obs_connection()

    # ------------------------------------------------------------------
    # UI構築
    # ------------------------------------------------------------------

    def _build_ui(self):
        """ウィジェットを生成・配置する。"""
        # OBS接続インジケーター
        self.lbl_obs_status = tk.Label(
            self,
            text="OBS: 確認中...",
            fg="#ffa500",
            anchor="w",
        )
        self.lbl_obs_status.pack(fill="x", padx=8, pady=(4, 0))

        # 入力フォーム
        form_frame = ttk.LabelFrame(self, text="礼拝情報")
        form_frame.pack(fill="x", padx=8, pady=4)

        today = datetime.date.today()
        today_str = f"{today.year}年{today.month}月{today.day}日"

        fields = [
            ("日付", today_str),
            ("タイトル", ""),
            ("聖書箇所", ""),
            ("説教者", ""),
        ]
        self._form_entries = []
        for i, (label_text, default) in enumerate(fields):
            tk.Label(form_frame, text=label_text).grid(
                row=i, column=0, sticky="w", padx=4, pady=2
            )
            entry = ttk.Entry(form_frame, width=34)
            entry.insert(0, default)
            entry.grid(row=i, column=1, sticky="ew", padx=4, pady=2)
            self._form_entries.append(entry)

        form_frame.columnconfigure(1, weight=1)

        self.entry_date = self._form_entries[0]
        self.entry_title = self._form_entries[1]
        self.entry_scripture = self._form_entries[2]
        self.entry_preacher = self._form_entries[3]

        # 公開設定ラジオボタン
        vis_frame = tk.Frame(form_frame)
        vis_frame.grid(row=4, column=0, columnspan=2, sticky="w", padx=4, pady=2)
        tk.Label(vis_frame, text="公開設定").pack(side="left")
        self.var_visibility = tk.StringVar(value="public")
        tk.Radiobutton(
            vis_frame, text="公開", variable=self.var_visibility, value="public"
        ).pack(side="left")
        tk.Radiobutton(
            vis_frame, text="限定公開", variable=self.var_visibility, value="unlisted"
        ).pack(side="left")

        # 開始ボタン
        self.btn_start = tk.Button(
            self,
            text="▶  配信・録画 開始",
            bg="#28a745",
            fg="white",
            command=self.on_start_click,
        )
        self.btn_start.pack(fill="x", padx=8, pady=(4, 0))

        # 状態ラベル
        self.lbl_status = tk.Label(self, text="状態: 待機中", anchor="w")
        self.lbl_status.pack(fill="x", padx=8, pady=2)

        # プログレスバー
        self.progress_bar = ttk.Progressbar(self, mode="determinate")
        self.progress_bar.pack(fill="x", padx=8, pady=2)

        # 停止ボタン
        self.btn_stop = tk.Button(
            self,
            text="■  終了 → YouTubeへアップロード",
            bg="#dc3545",
            fg="white",
            command=self.on_stop_click,
            state="disabled",
        )
        self.btn_stop.pack(fill="x", padx=8, pady=(0, 4))

        # リセットボタン（通常は非表示）
        self.btn_reset = tk.Button(
            self,
            text="次の礼拝の準備をする",
            command=self.on_reset_click,
        )
        # 初期は非表示

    # ------------------------------------------------------------------
    # 状態遷移
    # ------------------------------------------------------------------

    def _apply_state(self, new_state: AppState):
        """状態を更新してウィジェットの有効/無効を切り替える。"""
        self.state = new_state

        if new_state == AppState.IDLE:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self._set_form_state("normal")
            self.btn_reset.pack_forget()

        elif new_state == AppState.RECORDING:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self._set_form_state("disabled")
            self.btn_reset.pack_forget()

        elif new_state == AppState.UPLOADING:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="disabled")
            self._set_form_state("disabled")
            self.btn_reset.pack_forget()

        elif new_state == AppState.DONE:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self._set_form_state("normal")
            # btn_reset を btn_stop の下に表示する
            self.btn_reset.pack(fill="x", padx=8, pady=(0, 4))

        elif new_state == AppState.ERROR:
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self._set_form_state("normal")
            self.btn_reset.pack_forget()

    def _set_form_state(self, state: str):
        """フォーム内の全入力ウィジェットの state を変更する。"""
        for entry in self._form_entries:
            entry.config(state=state)

    # ------------------------------------------------------------------
    # イベントハンドラ
    # ------------------------------------------------------------------

    def on_start_click(self):
        """「配信・録画 開始」ボタン押下ハンドラ。"""
        date_val = self.entry_date.get().strip()
        title_val = self.entry_title.get().strip()
        scripture_val = self.entry_scripture.get().strip()
        preacher_val = self.entry_preacher.get().strip()

        # 空欄バリデーション
        for field_name, value in [
            ("日付", date_val),
            ("タイトル", title_val),
            ("聖書箇所", scripture_val),
            ("説教者", preacher_val),
        ]:
            if not value:
                messagebox.showwarning("入力エラー", f"「{field_name}」が入力されていません")
                return

        self._apply_state(AppState.RECORDING)
        self._recording_start_time = datetime.datetime.now()
        self._start_elapsed_timer()

        def _background():
            try:
                self.obs_client.start_recording()
            except Exception as exc:
                logger.error("OBS録画開始に失敗しました: %s", exc)
                self.after(0, lambda: self._handle_obs_error())
                return

            try:
                self.zoom_controller.join_meeting()
            except Exception as exc:
                logger.warning("Zoom起動に失敗しました: %s", exc)
                self.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Zoom起動失敗",
                        "Zoomの起動に失敗しました。Zoomがインストールされているか確認してください。"
                        "（録画は継続しています）",
                    ),
                )

        t = threading.Thread(target=_background, daemon=True)
        t.start()

    def on_stop_click(self):
        """「終了 → YouTubeへアップロード」ボタン押下ハンドラ。"""
        ok = messagebox.askokcancel(
            "確認",
            "礼拝を終了してYouTubeにアップロードします。よろしいですか？",
        )
        if not ok:
            return

        self._stop_elapsed_timer()
        self._stop_obs_poll()
        self._apply_state(AppState.UPLOADING)

        date_val = self.entry_date.get().strip()
        title_val = self.entry_title.get().strip()
        scripture_val = self.entry_scripture.get().strip()
        preacher_val = self.entry_preacher.get().strip()
        visibility = self.var_visibility.get()

        def _background():
            try:
                video_path = self.obs_client.stop_recording()
            except Exception as exc:
                logger.error("OBS録画停止に失敗しました: %s", exc)
                self.after(
                    0,
                    lambda: self._set_error_status(
                        "録画の停止に失敗しました。OBSを確認してください。"
                    ),
                )
                return

            try:
                thumbnail_path = self.thumbnail_generator(
                    date_val, title_val, scripture_val, preacher_val,
                    output_dir=None,
                )
            except Exception as exc:
                logger.error("サムネイル生成に失敗しました: %s", exc)
                thumbnail_path = None

            def _progress_cb(progress):
                self.after(0, lambda p=progress: self._update_progress(p))

            try:
                description = f"{date_val} {title_val}\n{scripture_val}\n{preacher_val}"
                youtube_url = self.youtube_uploader(
                    service=None,
                    video_path=video_path,
                    title=title_val,
                    description=description,
                    thumbnail_path=thumbnail_path,
                    privacy=visibility,
                    progress_callback=_progress_cb,
                )
                self.after(0, lambda url=youtube_url: self._on_upload_done(url))
            except Exception as exc:
                logger.error("YouTubeアップロードに失敗しました: %s", exc)
                self.after(
                    0,
                    lambda p=video_path: self._on_upload_error(p),
                )

        t = threading.Thread(target=_background, daemon=True)
        t.start()

    def on_reset_click(self):
        """「次の礼拝の準備をする」ボタン押下ハンドラ。"""
        today = datetime.date.today()
        today_str = f"{today.year}年{today.month}月{today.day}日"

        for entry in [self.entry_title, self.entry_scripture, self.entry_preacher]:
            entry.config(state="normal")
            entry.delete(0, "end")

        self.entry_date.config(state="normal")
        self.entry_date.delete(0, "end")
        self.entry_date.insert(0, today_str)

        self.lbl_status.config(text="状態: 待機中", fg="#888888")
        self._apply_state(AppState.IDLE)

    def on_close_handler(self):
        """ウィンドウを閉じるボタン押下ハンドラ。"""
        if self.state in (AppState.IDLE, AppState.DONE, AppState.ERROR):
            self.destroy()

        elif self.state == AppState.RECORDING:
            ok = messagebox.askokcancel("確認", "録画中です。本当に終了しますか？")
            if ok:
                try:
                    self.obs_client.stop_recording()
                except Exception as exc:
                    logger.warning("終了時のOBS停止でエラーが発生しました: %s", exc)
                self.destroy()

        elif self.state == AppState.UPLOADING:
            ok = messagebox.askokcancel("確認", "アップロード中です。本当に終了しますか？")
            if ok:
                self.destroy()

    # ------------------------------------------------------------------
    # 経過時間タイマー
    # ------------------------------------------------------------------

    def _start_elapsed_timer(self):
        """1秒ごとに経過時間を更新するタイマーを開始する。"""
        self._elapsed_timer_id = self.after(1000, self._update_elapsed_time)

    def _stop_elapsed_timer(self):
        """経過時間タイマーを停止する。"""
        if self._elapsed_timer_id is not None:
            self.after_cancel(self._elapsed_timer_id)
            self._elapsed_timer_id = None

    def _update_elapsed_time(self):
        """lbl_status の経過時間表示を更新する（再帰的に呼ばれる）。"""
        if self.state != AppState.RECORDING:
            return
        if self._recording_start_time is None:
            return
        elapsed = datetime.datetime.now() - self._recording_start_time
        total_seconds = int(elapsed.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.lbl_status.config(text=f"状態: 配信中 ({elapsed_str})", fg="#28a745")
        self._elapsed_timer_id = self.after(1000, self._update_elapsed_time)

    # ------------------------------------------------------------------
    # OBSポーリング
    # ------------------------------------------------------------------

    def _start_obs_poll(self):
        """30秒ごとにOBS録画状態をポーリングするタイマーを開始する。"""
        self._obs_poll_id = self.after(30000, self._poll_obs_status)

    def _stop_obs_poll(self):
        """OBSポーリングタイマーを停止する。"""
        if self._obs_poll_id is not None:
            self.after_cancel(self._obs_poll_id)
            self._obs_poll_id = None

    def _poll_obs_status(self):
        """OBS録画状態を確認し、意図せず停止していた場合に警告する。"""
        if self.state != AppState.RECORDING:
            return
        try:
            is_recording = self.obs_client.get_recording_status()
        except Exception as exc:
            logger.warning("OBSポーリング中にエラーが発生しました: %s", exc)
            return

        if not is_recording:
            self.lbl_status.config(text="状態: ⚠ 録画が停止しています", fg="#dc3545")
            messagebox.showwarning(
                "録画停止",
                "録画が停止しています。OBSを確認し、必要に応じて手動で録画を再開してください。",
            )
            return

        # 録画継続中なら次のポーリングをスケジュールする
        self._obs_poll_id = self.after(30000, self._poll_obs_status)

    # ------------------------------------------------------------------
    # OBS接続インジケーター
    # ------------------------------------------------------------------

    def _check_obs_connection(self):
        """起動時に非同期でOBS接続を確認する。"""
        def _worker():
            try:
                self.obs_client.connect()
                virtual_cam_active = False
                try:
                    status = self.obs_client._call_async(
                        self.obs_client._ws_client.get_virtual_cam_status()
                        if False else self.obs_client._get_virtual_cam_status_async()
                    )
                    virtual_cam_active = getattr(status, "output_active", False)
                except Exception:
                    pass

                if virtual_cam_active:
                    self.after(
                        0,
                        lambda: self.lbl_obs_status.config(
                            text="OBS: ✓接続済み", fg="#28a745"
                        ),
                    )
                else:
                    self.after(
                        0,
                        lambda: self.lbl_obs_status.config(
                            text="OBS: ✓接続済み（仮想カメラが無効です）",
                            fg="#ffa500",
                        ),
                    )
                    self.after(
                        0,
                        lambda: messagebox.showwarning(
                            "仮想カメラ未起動",
                            "OBSの仮想カメラが有効になっていません。"
                            "OBSで仮想カメラを起動してから配信を開始してください。",
                        ),
                    )
            except Exception as exc:
                logger.warning("OBS接続確認に失敗しました: %s", exc)
                self.after(
                    0,
                    lambda: self.lbl_obs_status.config(
                        text="OBS: ✗未接続", fg="#dc3545"
                    ),
                )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # 内部ヘルパー
    # ------------------------------------------------------------------

    def _handle_obs_error(self):
        """OBS起動失敗時の処理。"""
        messagebox.showerror(
            "OBS接続エラー",
            "OBSが起動していません。OBSを起動して仮想カメラを有効にしてから、"
            "もう一度「開始」を押してください。",
        )
        self._apply_state(AppState.ERROR)
        self.lbl_status.config(
            text="状態: エラー - OBSが起動していません", fg="#dc3545"
        )

    def _set_error_status(self, message: str):
        """エラー状態に遷移してラベルを更新する。"""
        self._apply_state(AppState.ERROR)
        self.lbl_status.config(text=f"状態: エラー - {message}", fg="#dc3545")

    def _update_progress(self, progress: float):
        """プログレスバーの値を更新する。"""
        self.progress_bar["value"] = progress

    def _on_upload_done(self, youtube_url: str):
        """アップロード完了時の処理。"""
        self._apply_state(AppState.DONE)
        self.lbl_status.config(
            text=f"状態: アップロード完了 ▶ {youtube_url}",
            fg="#007bff",
            cursor="hand2",
        )
        self.lbl_status.bind(
            "<Button-1>",
            lambda _: __import__("webbrowser").open(youtube_url),
        )
        messagebox.showinfo(
            "アップロード完了",
            f"YouTubeへのアップロードが完了しました。\n{youtube_url}",
        )

    def _on_upload_error(self, video_path: str):
        """アップロード失敗時の処理。"""
        self._set_error_status(
            f"アップロードに失敗しました。録画ファイルは {video_path} に保存されています。"
        )


if __name__ == "__main__":
    from src.obs_client import OBSClient
    from src.zoom_controller import ZoomController
    app = App()
    app.mainloop()
