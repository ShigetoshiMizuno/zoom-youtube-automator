# SPEC_OBS.md — OBS WebSocket連携モジュール仕様書

バージョン: 1.1.0
作成日: 2026-04-24
更新日: 2026-04-24
ステータス: 仕様策定完了（実装未着手）
対応 GitHub Issue: #1

---

## 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| 1.0.0 | 2026-04-24 | 初版 |
| 1.1.0 | 2026-04-24 | asyncio/threading設計の明確化、stop_recording()ファイル確定待ち仕様を必須化、OBS状態ポーリング仕様を追加 |

---

## 概要

OBS WebSocket API v5 を通じて OBS Studio を遠隔制御するモジュール。
コントローラー（`app.py`）からの指示を受け、録画開始・停止・録画ファイルパス取得・仮想カメラ制御を担う。
OBS の内部状態への直接アクセスは行わず、すべて WebSocket リクエスト経由で操作する。

---

## 機能仕様

- OBS WebSocket サーバーへの接続・切断・再接続を管理する
- 録画開始時にシーン名を確認し、指定シーンへ切り替えてから録画を開始する
- 録画停止後に録画ファイルの書き込み完了を確認してからファイルの絶対パスを返す
- 録画中かどうかの状態を問い合わせる
- OBS 仮想カメラの起動・停止を行う
- 30秒ごとに録画状態をポーリングし、意図しない録画停止をコールバックで通知する
- 上記すべてにおいて、処理失敗時は具体的なエラー情報を例外として呼び出し元に伝える

---

## 前提条件

### OBS 側の準備（ユーザーが事前設定）

1. OBS Studio v28 以上がインストールされていること
   - v28 未満の場合は `obs-websocket` プラグイン（v5.x）を別途インストールすること
2. OBS の WebSocket サーバーを有効化すること
   - 設定手順: OBS > `ツール` > `obs-websocket 設定` > `WebSocketサーバーを有効にする` にチェック
   - ポート: 4455（デフォルト）
   - パスワード: 任意の文字列を設定し `config.yaml` の `obs.password` に記載する
3. 録画に使用するシーンが事前に作成されていること（シーン名は `config.yaml` の `obs.scene` に記載）
4. 録画保存先を OBS の設定ファイル出力先（または `obs.output_dir`）に合わせて設定しておくこと

### Python 環境

- Python 3.9 以上
- `obs-websocket-py` がインストール済みであること（インストール方法は「依存ライブラリ」節を参照）

---

## スレッド・非同期設計

### 設計方針

`obs-websocket-py` 1.0 系は **threading ベース**（asyncio 非対応）のライブラリであり、同期的に呼び出せる。
`asyncio.run()` は不要。Tkinter の threading.Thread からそのまま呼び出し可能。

> **ライブラリ選択肢:**
> - `obs-websocket-py` 1.0（threading ベース、シンプル）
> - `obsws-python` 1.8.0（推奨：最新・活発保守・snake_case API）
> どちらも WebSocket v5 対応。`obsws-python` を優先的に採用することを推奨する。

本モジュールは以下の方式を採用する：

```
┌─────────────────────────────────────────┐
│  GUI スレッド（Tkinter メインスレッド）    │
│  ボタン操作                              │
│       │ asyncio.run_coroutine_threadsafe() │
└───────┼──────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│  OBS専用スレッド（デーモンスレッド）             │
│  asyncio イベントループを常駐させる              │
│  （loop.run_forever()）                       │
│  coroutine を実行し、結果を Future 経由で返す   │
└──────────────────────────────────────────────┘
```

### 実装要件

1. `OBSClient` の初期化時（または `connect()` 呼び出し時）に OBS専用スレッドを1本起動する
2. そのスレッド内で asyncio イベントループを生成し `loop.run_forever()` で常駐させる
3. GUI スレッドから OBSClient のメソッドを呼び出すと、内部で `asyncio.run_coroutine_threadsafe()` を使って coroutine をイベントループに投入する
4. GUI スレッド側では `concurrent.futures.Future.result(timeout=...)` でブロッキング待ちする
5. OBS専用スレッドは `daemon=True` で起動し、アプリ終了時に自動停止する

### スレッド間の結果受け渡し

- `asyncio.run_coroutine_threadsafe(coro, loop)` を使用して GUI スレッドから coroutine をイベントループに投入する
- 戻り値は `concurrent.futures.Future` オブジェクトとして受け取り、タイムアウト付きで `result()` を呼ぶ
- タイムアウトはデフォルト10秒（`obs.request_timeout` で設定可能）
---


## 接続仕様

### 接続パラメータ

接続情報はすべて `config.yaml` の `obs.*` セクションから読み込む。コード中にハードコードしない。

| パラメータ | config.yaml キー | 型 | デフォルト値 | 説明 |
|-----------|----------------|-----|-----------|------|
| host | `obs.host` | str | `"localhost"` | OBS WebSocket サーバーのホスト名または IP アドレス |
| port | `obs.port` | int | `4455` | OBS WebSocket サーバーのポート番号 |
| password | `obs.password` | str | — | OBS WebSocket 認証パスワード（空文字列の場合は認証なし扱い） |
| request_timeout | `obs.request_timeout` | int | `10` | 各 WebSocket リクエストのタイムアウト秒数 |

### 接続フロー

```
1. OBSClient.__init__() でパラメータを保存（接続はしない）
2. connect() 呼び出し
   2-1. OBS専用スレッドが未起動の場合は起動し、asyncio イベントループを常駐させる
   2-2. obs-websocket-py の WebSocketClient を生成
   2-3. host:port に TCP 接続を試みる
   2-4. WebSocket ハンドシェイク + Hello / Identify 認証を完了する
   2-5. 成功時: 接続状態フラグを True にセット
   2-6. 失敗時: OBSConnectionError を raise する
3. 以降のメソッド呼び出しは OBS専用スレッドのイベントループ経由で実行する
```

### 切断フロー

```
1. disconnect() 呼び出し
   1-1. 状態ポーリングが動作中であれば停止する
   1-2. WebSocket コネクションを正常クローズする
   1-3. 接続状態フラグを False にセット
   1-4. エラー時も例外は raise せず、ログに記録してフラグを False にセット
```

### 再接続ロジック

- 再接続は明示的に `reconnect()` を呼び出した場合のみ実行する（自動再接続は行わない）
- `reconnect()` の内部動作: `disconnect()` を呼んでから `connect()` を呼ぶ
- リトライ回数・インターバルはコントローラー側が制御する（本モジュールはリトライループを持たない）

---

## インターフェース定義

### クラス: `OBSClient`

**ファイルパス:** `obs_client.py`

```python
from typing import Callable, Optional

# 録画が意図せず停止した際に呼ばれるコールバック型
RecordingStoppedCallback = Callable[[], None]

class OBSClient:
    def __init__(self, host: str, port: int, password: str, output_dir: str = "") -> None:
        """
        OBSクライアントを初期化する。接続は行わない。
        内部で OBS専用スレッドを生成するが、connect() が呼ばれるまで起動しない。

        Args:
            host: OBS WebSocket サーバーのホスト名
            port: OBS WebSocket サーバーのポート番号
            password: OBS WebSocket 認証パスワード（空文字列の場合は認証なし）
            output_dir: 録画ファイルの保存先。指定時は録画開始直前にOBSへ注入する。空文字列の場合はOBS側の設定を使用。
        """
        ...

    def connect(self) -> None:
        """
        OBS専用スレッドを起動し、OBS WebSocket サーバーに接続する。
        接続後、asyncio イベントループが常駐した状態になる。

        Raises:
            OBSConnectionError: 接続またはハンドシェイクに失敗した場合
        """
        ...

    def disconnect(self) -> None:
        """
        状態ポーリングを停止してから OBS WebSocket サーバーを切断する。
        エラーが発生しても例外は raise しない。
        """
        ...

    def reconnect(self) -> None:
        """
        切断してから再接続する。

        Raises:
            OBSConnectionError: 再接続に失敗した場合
        """
        ...

    def is_connected(self) -> bool:
        """
        現在 OBS WebSocket サーバーに接続中かどうかを返す。

        Returns:
            接続中であれば True、切断中であれば False
        """
        ...

    def start_recording(self, scene_name: str) -> None:
        """
        指定シーンに切り替えてから録画を開始する。
        すでに録画中の場合は何もしない（冪等）。

        Args:
            scene_name: 録画対象の OBS シーン名（config.yaml の obs.scene）

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSSceneNotFoundError: 指定シーンが存在しない場合
            OBSRecordingError: 録画開始リクエストが失敗した場合
        """
        ...

    def stop_recording(self) -> str:
        """
        録画を停止し、ファイルの書き込み完了を確認してから録画ファイルの絶対パスを返す。
        録画中でない場合は OBSRecordingError を raise する。

        ファイル確定待ち（必須処理）:
            StopRecord レスポンス取得後、os.path.getsize() の変化を監視し、
            ファイルサイズが安定（2回連続で同一値）するまでポーリングする。
            ポーリング間隔: 500ms、最大試行回数: 20回（合計最大10秒）。
            タイムアウト時は OBSRecordingError を raise する。

        Returns:
            録画されたファイルの絶対パス文字列（例: "C:/録画/2026-04-24_礼拝.mp4"）

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSRecordingError: 録画停止リクエストが失敗した場合、録画中でない場合、
                               またはファイル確定待ちがタイムアウトした場合
        """
        ...

    def get_recording_status(self) -> bool:
        """
        現在録画中かどうかを返す。

        Returns:
            録画中であれば True、停止中であれば False

        Raises:
            OBSConnectionError: 接続が切れている場合
        """
        ...

    def start_virtual_cam(self) -> None:
        """
        OBS 仮想カメラを起動する。
        すでに起動中の場合は何もしない（冪等）。

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSVirtualCamError: 仮想カメラ起動リクエストが失敗した場合
        """
        ...

    def stop_virtual_cam(self) -> None:
        """
        OBS 仮想カメラを停止する。
        すでに停止中の場合は何もしない（冪等）。

        Raises:
            OBSConnectionError: 接続が切れている場合
            OBSVirtualCamError: 仮想カメラ停止リクエストが失敗した場合
        """
        ...

    def start_status_polling(self, on_recording_stopped: RecordingStoppedCallback) -> None:
        """
        OBS 録画状態のポーリングを開始する。
        30秒ごとに get_recording_status() を呼び出し、意図しない録画停止を検出した場合に
        on_recording_stopped コールバックを呼ぶ。

        ポーリングは OBS専用スレッドのイベントループ内で asyncio.Task として実行する。
        すでにポーリング中の場合は何もしない（冪等）。

        Args:
            on_recording_stopped: 録画が意図せず停止した場合に呼ばれるコールバック。
                                   Tkinter スレッドへの転送は呼び出し元（コントローラー）の責任とする。
                                   推奨: コントローラー側で root.after(0, gui_update) 経由で転送すること。
        """
        ...

    def stop_status_polling(self) -> None:
        """
        OBS 録画状態のポーリングを停止する。
        ポーリング中でない場合は何もしない（冪等）。
        """
        ...
```

### 例外クラス

```python
class OBSError(Exception):
    """OBS連携モジュールの基底例外クラス"""
    ...

class OBSConnectionError(OBSError):
    """接続・認証失敗（OBSが未起動・パスワード誤り・ポート不一致 等）"""
    ...

class OBSSceneNotFoundError(OBSError):
    """指定シーンが OBS に存在しない"""
    ...

class OBSRecordingError(OBSError):
    """録画開始・停止・ファイルパス取得の失敗"""
    ...

class OBSVirtualCamError(OBSError):
    """仮想カメラ起動・停止の失敗"""
    ...
```

---

## 主要機能の詳細仕様

### `start_recording()` — シーン確認 → 録画開始

```
1. is_connected() で接続確認。False なら OBSConnectionError を raise
2. GetSceneList リクエストでシーン一覧を取得
3. scene_name がシーン一覧に含まれているか確認
   - 含まれていない場合: OBSSceneNotFoundError を raise
4. SetCurrentProgramScene リクエストでシーンを切り替える
5. get_recording_status() で現在の録画状態を確認
   - すでに録画中の場合: 何もせず正常終了（冪等）
6. StartRecord リクエストを送信
7. OBS からのレスポンスコードを確認
   - 失敗コードの場合: OBSRecordingError を raise
```

### `stop_recording()` — 録画停止 → ファイル確定待ち → ファイルパス取得

**ファイル確定待ちは必須処理（High優先度）。省略不可。**

```
1. is_connected() で接続確認。False なら OBSConnectionError を raise
2. get_recording_status() で録画状態を確認
   - 録画中でない場合: OBSRecordingError を raise
3. StopRecord リクエストを送信
4. OBS からのレスポンス内 outputPath フィールドからファイルパスを取得
   - outputPath が空文字列または None の場合: OBSRecordingError を raise
5. ファイル確定待ちポーリング（必須）:
   a. 前回サイズを -1 に初期化
   b. 最大20回ループ（500ms間隔）:
      - os.path.exists(path) が False の場合: 500ms 待機して継続
      - size = os.path.getsize(path) を取得
      - size > 0 かつ size == 前回サイズ の場合: ファイル確定とみなしてループ脱出
      - 前回サイズ = size を更新して 500ms 待機
   c. 20回ループを抜けてもファイル確定しない場合: OBSRecordingError を raise
6. 確定したファイルパスを pathlib.Path で正規化して str として返す
```

### `get_recording_status()` — 録画状態確認

```
1. is_connected() で接続確認。False なら OBSConnectionError を raise
2. GetRecordStatus リクエストを送信
3. レスポンスの outputActive フィールドを bool で返す
```

### `start_virtual_cam()` — 仮想カメラ起動

```
1. is_connected() で接続確認。False なら OBSConnectionError を raise
2. GetVirtualCamStatus リクエストで現在の状態を確認
   - すでに outputActive = true の場合: 何もせず正常終了（冪等）
3. StartVirtualCam リクエストを送信
4. OBS からのレスポンスコードを確認
   - 失敗コードの場合: OBSVirtualCamError を raise
```

### `stop_virtual_cam()` — 仮想カメラ停止

```
1. is_connected() で接続確認。False なら OBSConnectionError を raise
2. GetVirtualCamStatus リクエストで現在の状態を確認
   - すでに outputActive = false の場合: 何もせず正常終了（冪等）
3. StopVirtualCam リクエストを送信
4. OBS からのレスポンスコードを確認
   - 失敗コードの場合: OBSVirtualCamError を raise
```

---

## OBS状態監視（ポーリング）

### 目的

礼拝中に OBS がクラッシュする・録画が意図せず停止するといった状況を検知し、GUI に通知する。

### 仕様

| 項目 | 内容 |
|------|------|
| 監視間隔 | 30秒ごと |
| 監視方法 |  を定期呼び出し |
| 検知条件 |  が成功した後、 が  を返した場合 |
| 通知方法 |  に渡した  コールバックを呼び出す |
| ポーリング停止タイミング |  が正常完了した後（正常終了）または  呼び出し時 |

### 状態遷移とポーリング



### コントローラーの責任

-  コールバック内で Tkinter の  を使って GUI スレッドへ安全に転送する
- GUI 上でアラートダイアログ等を表示してユーザーに通知する
- 通知内容（案）: 「OBSの録画が予期せず停止しました。OBSの状態を確認してください。」

---

## OBS WebSocket v5 API マッピング

本モジュールで使用する OBS WebSocket v5 のリクエスト一覧。

| 本モジュールの操作 | WebSocket リクエスト名 | 主要な入力フィールド | 主要な出力フィールド |
|-----------------|---------------------|------------------|------------------|
| シーン一覧取得 | `GetSceneList` | なし | `scenes[]`, `currentProgramSceneName` |
| シーン切り替え | `SetCurrentProgramScene` | `sceneName: str` | なし（レスポンスコードのみ） |
| 録画開始 | `StartRecord` | なし | なし（レスポンスコードのみ） |
| 録画停止 | `StopRecord` | なし | `outputPath: str` |
| 録画状態取得 | `GetRecordStatus` | なし | `outputActive: bool` |
| 仮想カメラ状態取得 | `GetVirtualCamStatus` | なし | `outputActive: bool` |
| 仮想カメラ起動 | `StartVirtualCam` | なし | なし（レスポンスコードのみ） |
| 仮想カメラ停止 | `StopVirtualCam` | なし | なし（レスポンスコードのみ） |

### レスポンスコード

OBS WebSocket v5 ではすべてのレスポンスに `requestStatus.code` が含まれる。

| コード | 意味 |
|-------|------|
| `100` | 成功 |
| `604` | リソース（シーン等）が見つからない |
| `700` 番台 | 操作の前提条件が満たされていない（例: すでに録画中に StartRecord を送った等） |

参照: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

---

## エラーハンドリング

### エラーケースと対応

| 状況 | 発生するタイミング | 本モジュールの動作 | コントローラーへの通知方法 |
|------|----------------|-----------------|----------------------|
| OBS が未起動 | `connect()` | TCP 接続タイムアウト後に `OBSConnectionError` を raise | 例外をそのまま伝搬 |
| パスワード誤り | `connect()` 認証フェーズ | `OBSConnectionError` を raise | 例外をそのまま伝搬 |
| ポート番号誤り | `connect()` | `OBSConnectionError` を raise | 例外をそのまま伝搬 |
| 通信中に接続断 | 各メソッド呼び出し時 | `OBSConnectionError` を raise | 例外をそのまま伝搬 |
| 指定シーンが存在しない | `start_recording()` | `OBSSceneNotFoundError` を raise | 例外をそのまま伝搬 |
| 録画中でないのに停止要求 | `stop_recording()` | `OBSRecordingError` を raise | 例外をそのまま伝搬 |
| 録画停止後にファイルパスが空 | `stop_recording()` | `OBSRecordingError` を raise | 例外をそのまま伝搬 |
| ファイル確定待ちタイムアウト | `stop_recording()` | `OBSRecordingError` を raise | 例外をそのまま伝搬 |
| 仮想カメラ操作失敗 | `start/stop_virtual_cam()` | `OBSVirtualCamError` を raise | 例外をそのまま伝搬 |
| 録画の意図しない停止 | ポーリング検知時 | `on_recording_stopped` コールバックを呼び出す | コールバック経由（非例外） |

### GUI へのエラーメッセージ表示

本モジュールはエラーメッセージを直接 GUI に表示しない。
コントローラー（`app.py`）が例外を catch し、下表のメッセージを GUI に表示する。

| 例外クラス | GUI 表示メッセージ（案） |
|------------|----------------------|
| `OBSConnectionError` | `OBSに接続できません。OBSが起動しているか、設定を確認してください。` |
| `OBSSceneNotFoundError` | `OBSのシーン "{scene_name}" が見つかりません。config.yaml の obs.scene を確認してください。` |
| `OBSRecordingError` | `録画の操作に失敗しました。OBSの状態を確認してください。` |
| `OBSVirtualCamError` | `仮想カメラの操作に失敗しました。OBSの状態を確認してください。` |

---

## 設定キー一覧（config.yaml の `obs.*` セクション）

| キー | 型 | 必須 | デフォルト値 | 説明 |
|------|----|------|-----------|------|
| `obs.host` | string | いいえ | `"localhost"` | OBS WebSocket サーバーのホスト名 |
| `obs.port` | integer | いいえ | `4455` | OBS WebSocket サーバーのポート番号 |
| `obs.password` | string | はい | — | OBS WebSocket 認証パスワード |
| `obs.scene` | string | はい | — | 録画に使用する OBS シーン名 |
| `obs.output_dir` | string | はい | — | 録画ファイルの保存先ディレクトリ（絶対パス） |
| `obs.request_timeout` | integer | いいえ | `10` | 各 WebSocket リクエストのタイムアウト秒数 |

`obs.output_dir` は OBS の録画出力先設定と一致させること。
本モジュールはこのディレクトリに直接書き込まない（OBS が書き込む）。
録画ファイルパスは `stop_recording()` の戻り値から取得する。

---

## 依存ライブラリ

| ライブラリ | PyPI パッケージ名 | バージョン要件 | 用途 |
|-----------|----------------|-------------|------|
| obsws-python（推奨） | `obsws-python` | 1.8.0 以上 | OBS WebSocket v5 クライアント（最新・活発保守・snake_case） |
| obs-websocket-py（代替） | `obs-websocket-py` | 1.0 以上（WebSocket v5 対応版） | OBS WebSocket v5 クライアント（threading ベース・シンプル） |

### インストール方法

```
pip install obs-websocket-py
```

### バージョン注意事項

`obs-websocket-py` は 1.0 以降で WebSocket v5 対応となっている。
0.x 系は WebSocket v4 対応のため使用不可。
`pip show obs-websocket-py` でバージョンを確認すること。

---

## テスト方針

### 単体テスト（OBS 未起動環境でも実行可能）

| テスト項目 | 確認内容 | モック対象 |
|-----------|---------|---------|
| `__init__()` のパラメータ保持 | host/port/password が正しく保存されること | なし |
| `is_connected()` 初期値 | 初期状態で False を返すこと | なし |
| `connect()` 成功 | 接続状態フラグが True になること | obs-websocket-py の接続処理 |
| `connect()` 失敗（接続拒否） | OBSConnectionError が raise されること | obs-websocket-py |
| `connect()` 失敗（認証エラー） | OBSConnectionError が raise されること | obs-websocket-py |
| `disconnect()` 正常 | 接続状態フラグが False になること | obs-websocket-py の切断処理 |
| `disconnect()` エラー時 | 例外を raise せずフラグが False になること | obs-websocket-py |
| `start_recording()` シーン存在 | StartRecord リクエストが送信されること | WebSocket リクエスト送信 |
| `start_recording()` シーン不存在 | OBSSceneNotFoundError が raise されること | WebSocket レスポンス |
| `start_recording()` 録画中（冪等） | 例外なしで正常終了すること | WebSocket レスポンス |
| `stop_recording()` 正常 | ファイルパス文字列を返すこと（ファイル確定待ち込み） | WebSocket レスポンス, os.path.getsize |
| `stop_recording()` ファイル確定待ちタイムアウト | OBSRecordingError が raise されること | os.path.getsize（常に変化するモック） |
| `stop_recording()` 録画中でない | OBSRecordingError が raise されること | WebSocket レスポンス |
| `stop_recording()` outputPath が空 | OBSRecordingError が raise されること | WebSocket レスポンス |
| `get_recording_status()` 録画中 | True を返すこと | WebSocket レスポンス |
| `get_recording_status()` 停止中 | False を返すこと | WebSocket レスポンス |
| `start_virtual_cam()` 正常 | StartVirtualCam リクエストが送信されること | WebSocket リクエスト送信 |
| `start_virtual_cam()` 起動中（冪等） | 例外なしで正常終了すること | WebSocket レスポンス |
| `stop_virtual_cam()` 正常 | StopVirtualCam リクエストが送信されること | WebSocket リクエスト送信 |
| 未接続状態でのメソッド呼び出し | OBSConnectionError が raise されること | なし |
| `start_status_polling()` 正常録画継続 | コールバックが呼ばれないこと | get_recording_status（True固定） |
| `start_status_polling()` 異常停止検知 | on_recording_stopped コールバックが呼ばれること | get_recording_status（False返却） |
| `stop_status_polling()` | ポーリングが停止しコールバックが呼ばれなくなること | get_recording_status |

### 結合テスト（OBS 実機が必要）

| テスト項目 | 確認内容 |
|-----------|---------|
| 実際の OBS への接続 | connect() が正常完了し is_connected() が True を返すこと |
| 実際のシーン切り替え | OBS 画面上でシーンが切り替わること |
| 実際の録画開始・停止 | 録画が開始・停止し、stop_recording() が有効なファイルパスを返すこと |
| 返却されたパスのファイル存在確認 | stop_recording() の戻り値パスにファイルが実在し、サイズが 0 より大きいこと |
| ファイル確定待ち動作確認 | stop_recording() がファイル書き込み完了後にパスを返すこと |
| 実際の仮想カメラ起動・停止 | OBS の仮想カメラが起動・停止すること |
| 誤パスワードでの接続試行 | OBSConnectionError が返ること |
| ポーリング動作確認（OBS強制終了） | OBS を強制終了後30秒以内にコールバックが呼ばれること |

---

## TBD・未決事項

| 項目 | 内容 | 優先度 |
|------|------|--------|
| OBSシーン名の確定 | ✅ 確定済み：「聖日礼拝」（config.yaml.example に反映済み） | 解決済み |
| 仮想カメラ API の動作確認 | GetVirtualCamStatus / StartVirtualCam / StopVirtualCam が実機 OBS で利用可能かを確認する | Medium |
| connect() のタイムアウト値 | TCP 接続タイムアウトを何秒に設定するか（暫定案: 5秒） | Medium |
| 仮想カメラの事前有効化要件 | OBS WebSocket API 経由で仮想カメラを制御できないバージョンが存在する可能性。その場合はユーザー手動操作にフォールバックする | Medium |

---

## 実装メモ（PRGちゃんへの引き継ぎ）

### ファイル配置

- 本モジュールのファイル名は `obs_client.py` として実装すること
- SPEC_GUI.md に `obs_module.py` という記載が残っているが、本仕様書の `obs_client.py` に統一する
- 例外クラスは同一ファイルに定義してよい（または `exceptions.py` に集約してもよい）

### asyncio / スレッド設計（重要）

`obs-websocket-py` 1.0 系は **threading ベース**（asyncio 非対応）であり、同期的に呼び出せる。
`asyncio.run()` は不要。Tkinter の `threading.Thread` から直接メソッドを呼び出し可能。
**推奨**: `obsws-python` 1.8.0（snake_case API、最新・活発保守）への移行を検討すること。

実装パターン例:

```python
import asyncio
import threading
import concurrent.futures

class OBSClient:
    def __init__(self, ...):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call_async(self, coro, timeout=10):
        # GUI スレッドから asyncio coroutine を同期的に呼び出す
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
```

### `stop_recording()` のファイル確定待ち（必須）

OBS は `StopRecord` レスポンスを返した直後も録画ファイルへの書き込みを続ける場合がある。
ファイルパスを後続の YouTube アップロード処理に渡す前に、必ずファイルサイズが安定するまで待機すること。

実装パターン例:

```python
import os, time

def _wait_for_file_stable(path: str, interval: float = 0.5, max_retries: int = 20) -> None:
    prev_size = -1
    for _ in range(max_retries):
        if not os.path.exists(path):
            time.sleep(interval)
            continue
        size = os.path.getsize(path)
        if size > 0 and size == prev_size:
            return  # ファイル確定
        prev_size = size
        time.sleep(interval)
    raise OBSRecordingError(f"録画ファイルの確定待ちがタイムアウトしました: {path}")
```

### 接続確認タイミング

コントローラー（`app.py`）は「開始」ボタン押下時に `connect()` を呼ぶ設計とする。
アプリ起動時の自動接続は行わない（OBS が未起動の状態でアプリを起動できるようにするため）。

### 状態ポーリングの実装方針

ポーリングは OBS専用スレッドの asyncio イベントループ内で `asyncio.Task` として動かす。

実装パターン例:

```python
async def _polling_loop(self, on_stopped):
    while True:
        await asyncio.sleep(30)
        if not self._is_recording_intentionally:
            break
        try:
            is_active = await self._get_recording_status_async()
        except OBSConnectionError:
            break
        if not is_active:
            on_stopped()  # コントローラーが root.after() で転送する責任を持つ
            break
```

### 冪等性の担保

`start_recording()` と `start_virtual_cam()` は、すでに動作中の場合に再度呼び出してもエラーにならないこと（冪等）。
OBS WebSocket v5 の `StartRecord` は録画中に呼ぶとエラーコードを返すため、`get_recording_status()` による事前確認が必要。

### Windows パス処理

`stop_recording()` が返す `outputPath` は OBS 側の設定に依存する。
Windows 環境ではバックスラッシュ区切りのパスが返る場合があるため、`pathlib.Path` で受け取り正規化して返すこと。

### SPEC_OVERVIEW.md との整合

- SPEC_OVERVIEW.md セクション 3.1 のコンポーネント図で SPEC_OBS と定義済み
- SPEC_OVERVIEW.md セクション 8 の config.yaml 仕様と本書の設定キー一覧は一致している
  （`obs.request_timeout` キーを新規追加したため SPEC_OVERVIEW.md 側の更新が必要）
- SPEC_OVERVIEW.md セクション 10.5 の「OBS仮想カメラの事前有効化」リスクに記載の通り、
  仮想カメラ API が使えない場合はユーザー手動操作にフォールバックする設計とする