# SPEC_ZOOM.md — Zoom自動起動・仮想カメラ連携モジュール仕様書

バージョン: 1.0.0
作成日: 2026-04-24
ステータス: 設計フェーズ（実装未着手）
対応 GitHub Issue: #2, #6

---

## 概要

Zoom クライアントを `zoommtg://` URL スキームで自動起動・ミーティング参加させ、
pywin32 でウィンドウの前面表示・配置制御を行うモジュール。
OBS 仮想カメラの映像を Zoom のカメラ映像として提供する前提で動作する。

---

## 1. モジュール概要

### 1.1 役割

本モジュール（`zoom_controller.py`）は以下の責務を持つ。

- `zoommtg://` URL を生成し、Zoom クライアントを自動起動してミーティングに参加する
- pywin32 を使用して Zoom ウィンドウを前面表示・任意位置・サイズに配置する
- ミーティング終了時に Zoom ウィンドウを閉じる

### 1.2 役割の境界（このモジュールが担わないこと）

- OBS の制御（OBS WebSocket 連携は `SPEC_OBS.md` が担当）
- OBS 仮想カメラの有効化（ユーザーによる事前手動設定を前提とする）
- YouTube アップロード（`SPEC_YOUTUBE.md` が担当）
- GUI 表示（`SPEC_GUI.md` が担当）
- Zoom RTMP / カスタムライブストリーミング設定（本プロジェクトでは採用しない）

---

## 2. Zoom 連携方式（確定）

### 2.1 採用方式: zoommtg:// URL スキーム + pywin32

以下の理由で決定済み（`handover-2026-04-20.md` および `SPEC_OVERVIEW.md` で確定）。

| 項目 | 内容 |
|------|------|
| Zoom 起動方式 | `zoommtg://` URL スキーム（Windows のプロトコルハンドラー経由） |
| ウィンドウ制御 | pywin32（`win32gui`, `win32con`） |
| カメラ映像提供 | OBS 仮想カメラ（Zoom がカメラとして認識） |
| RTMP 設定 | 不要（採用しない） |
| Zoom SDK | 使用しない（インストール・設定の複雑さを避けるため） |

### 2.2 採用しない方式

- **Zoom RTMP カスタムライブストリーミング**: Zoom → 外部方向の配信であり、OBS→Zoom の映像提供には使えない
- **Zoom REST API**: ミーティング管理用であり、クライアントの自動操作には使えない
- **Zoom SDK**: インストール・認証要件が複雑

---

## 3. zoommtg:// URL スキーム仕様

### 3.1 URL フォーマット

```
zoommtg://zoom.us/join?action=join&confno={MEETING_ID}&pwd={PASSWORD}&uname={DISPLAY_NAME}&zc=0
```

### 3.2 パラメーター一覧

| パラメーター | 必須 | 型 | 説明 | 例 |
|------------|------|----|----|-----|
| `action` | 必須 | string | 操作種別。常に `join` を指定 | `join` |
| `confno` | 必須 | string | ミーティング番号。ハイフン除去した数字列 | `1234567890` |
| `pwd` | 任意 | string | ミーティングパスコード。URLエンコード済み文字列 | `abc123` |
| `uname` | 任意 | string | 表示名。URLエンコード必須 | `%E9%85%8D%E4%BF%A1` |
| `zc` | 任意 | integer | Zoom Companion の無効化フラグ。`0` を指定して非表示 | `0` |

### 3.3 ミーティング番号の正規化ルール

`config.yaml` の `zoom.meeting_id` にはハイフン区切り形式（例: `123-456-7890`）で保存する。
URL 生成時はハイフンを除去した数字列（例: `1234567890`）に変換する。

```
入力: "123-456-7890"
変換: meeting_id.replace("-", "").replace(" ", "")
出力: "1234567890"
```

### 3.4 URL の起動方法

`subprocess.Popen` または `os.startfile` でプロトコルハンドラーを起動する。

```
os.startfile("zoommtg://zoom.us/join?action=join&confno=...")
```

`subprocess.Popen` を使う場合は Windows の `start` コマンド経由とする。

---

## 4. pywin32 ウィンドウ操作仕様

### 4.1 使用する pywin32 API

| pywin32 関数 | 用途 |
|-------------|------|
| `win32gui.EnumWindows(callback, extra)` | 全ウィンドウを列挙して Zoom ウィンドウを特定する |
| `win32gui.GetWindowText(hwnd)` | ウィンドウのタイトル文字列を取得する |
| `win32gui.IsWindowVisible(hwnd)` | ウィンドウの表示状態を確認する |
| `win32gui.SetForegroundWindow(hwnd)` | ウィンドウを前面に表示する |
| `win32gui.MoveWindow(hwnd, x, y, w, h, True)` | ウィンドウを指定座標・サイズに移動する |
| `win32gui.GetClassName(hwnd)` | ウィンドウクラス名を取得する（タイトルマッチングの補助に使用） |
| `win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)` | ウィンドウにクローズメッセージを送る（非同期） |
| `win32gui.SendMessage(hwnd, WM_CLOSE, 0, 0)` | ウィンドウにクローズメッセージを送る（同期。Alt+F4 相当） |
| `win32con.WM_CLOSE` | ウィンドウクローズ用の Windows メッセージ定数 |
| `win32process.TerminateProcess(handle, exit_code)` | プロセスを強制終了する（最終手段） |

### 4.2 Zoom ウィンドウの特定方法

`EnumWindows` で全ウィンドウを列挙し、以下の条件でZoomのミーティングウィンドウを特定する。

1. `win32gui.IsWindowVisible(hwnd)` が `True`
2. `win32gui.GetWindowText(hwnd)` が以下のパターンにマッチする
   - `"Zoom Meeting"` を含む
   - または `"Zoom"` を含む（ミーティング参加後のウィンドウタイトル）
   - または `"Zoom Workplace"` を含む（Zoom 6.x 以降でのタイトル変更に対応）
3. `win32gui.GetClassName(hwnd)` で取得したウィンドウクラス名が Zoom 固有のクラスに一致する
   - **クラス名: TBD（実機確認が必要）**
   - 確認手順: Windows の Spy++ または `win32gui.GetClassName` を使い、Zoom ミーティング中のウィンドウのクラス名を記録する
   - 暫定的に既知クラス名候補: `"ZPContentViewWndClass"`, `"VideoFrameWndClass"`（要実機検証）

> 注意: タイトルの部分文字列マッチ（`"Zoom" in title`）のみでは「Zoom Player」等の無関係なアプリと
> 誤マッチする可能性がある。クラス名チェックを必ず併用すること。
> Zoom のバージョンによるタイトル変更（例: 「Zoom」→「Zoom Workplace」）にも留意すること。

### 4.3 ウィンドウ待機ポーリング

Zoom 起動直後はウィンドウが存在しない。以下のポーリングで待機する。

- ポーリング間隔: 1 秒
- タイムアウト: `config.yaml` の `zoom.join_timeout` 秒（デフォルト: 30 秒）
- タイムアウト到達時: `ZoomJoinTimeoutError` を送出

---

## 5. OBS 仮想カメラとの連携前提条件

### 5.1 前提（本モジュールの責務外）

本モジュールは OBS 仮想カメラの有効化を行わない。以下はユーザーが事前に手動設定する。

1. OBS Studio v28 以上がインストールされていること
2. OBS の「仮想カメラの開始」ボタンをクリックして仮想カメラが有効になっていること
3. Zoom の設定 > ビデオ > カメラ に「OBS Virtual Camera」が表示・選択されていること

### 5.2 仮想カメラ状態の確認（TBD）

OBS WebSocket API v5 で仮想カメラの有効状態を取得できるか調査中。
可能であれば、アプリ起動時に仮想カメラの有効状態をチェックして警告を表示する機能を追加する。
詳細は `SPEC_OBS.md` の TBD 項目を参照。

### 5.3 Zoom 側のカメラ設定

Zoom で OBS 仮想カメラを使用するには、Zoom の設定を一度手動で行う必要がある。

1. Zoom を起動する
2. 設定 > ビデオ > カメラ で「OBS Virtual Camera」を選択する
3. この設定は Zoom が記憶するため、以降は自動で OBS 仮想カメラが使われる

---

## 6. エラーハンドリング仕様

### 6.1 例外クラス階層

```
ZoomError（基底例外）
├── ZoomNotInstalledError     - Zoom クライアントがインストールされていない
├── ZoomSchemeNotRegisteredError - zoommtg:// スキームがレジストリに未登録
├── ZoomJoinTimeoutError      - 指定時間内にウィンドウが現れなかった
└── ZoomWindowNotFoundError   - ウィンドウ操作対象が見つからない
```

### 6.2 エラー条件と対応

| エラー条件 | 送出例外 | GUI 表示メッセージ |
|-----------|---------|----------------|
| Zoom が未インストール（レジストリに `zoommtg` キーなし） | `ZoomNotInstalledError` | 「Zoom がインストールされていません。Zoom をインストールしてください。」 |
| `zoommtg://` スキームが未登録 | `ZoomSchemeNotRegisteredError` | 「Zoom のプロトコル登録が確認できません。Zoom を一度手動で起動してください。」 |
| ミーティング参加後のウィンドウが現れない（タイムアウト） | `ZoomJoinTimeoutError` | 「Zoom の起動がタイムアウトしました。手動でミーティングに参加してください。」 |
| ウィンドウ操作対象が見つからない | `ZoomWindowNotFoundError` | 「Zoom ウィンドウが見つかりません。Zoom が起動しているか確認してください。」 |

### 6.3 Zoom 起動失敗時の録画への影響

Zoom の起動・参加に失敗しても OBS 録画は継続する。
録画とZoom配信は独立した処理であり、一方の失敗が他方を中断しない。

---

## 7. インターフェース定義

### 7.1 データクラス

#### WindowPosition

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class WindowPosition:
    x: int       # ウィンドウ左端の画面X座標（ピクセル）
    y: int       # ウィンドウ上端の画面Y座標（ピクセル）
    width: int   # ウィンドウ幅（ピクセル）
    height: int  # ウィンドウ高さ（ピクセル）
```

#### ZoomConfig

```python
@dataclass
class ZoomConfig:
    meeting_id: str                         # ミーティングID（ハイフン区切り可）
    password: str = ""                      # ミーティングパスコード
    display_name: str = "配信"              # Zoom 参加時の表示名
    join_timeout: int = 30                  # ウィンドウ出現待機タイムアウト（秒）
    window_position: Optional[WindowPosition] = None  # ウィンドウ配置設定（None = 移動しない）
```

### 7.2 例外クラス

```python
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
```

### 7.3 ZoomController クラス

```python
class ZoomController:
    def __init__(self, config: ZoomConfig) -> None:
        ...

    def join_meeting(self) -> None:
        ...

    def leave_meeting(self) -> None:
        ...

    def set_window_position(self, position: WindowPosition) -> None:
        ...

    def is_meeting_active(self) -> bool:
        ...

    def build_zoom_url(self) -> str:
        ...
```

#### join_meeting() の処理フロー

1. Zoom インストール確認（レジストリチェック）
2. `zoommtg://` URL を生成して `os.startfile` で起動
3. Zoom ウィンドウが表示されるまでポーリング待機（`join_timeout` 秒）
4. `window_position` が設定されていれば `set_window_position` を呼ぶ

**送出例外:**
- `ZoomNotInstalledError`: Zoom がインストールされていない
- `ZoomSchemeNotRegisteredError`: `zoommtg://` スキームが未登録
- `ZoomJoinTimeoutError`: タイムアウト内にウィンドウが現れなかった

#### leave_meeting() の処理フロー

1. Zoom ウィンドウを特定
2. `win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)` を送信
3. 2〜3 秒待機する（Zoom が「退出しますか？」確認ダイアログを表示するケースへの対応）
4. ウィンドウがまだ存在する場合、`win32gui.SendMessage(hwnd, WM_CLOSE, 0, 0)` を送信する（Alt+F4 相当）
5. それでもウィンドウが残っている場合、`win32process.TerminateProcess` でプロセスを強制終了する
6. `leave_meeting()` の完了コールバックとして、GUI に「Zoomを終了しました」を表示する通知を送る
   （GUI 側の実装方針は `SPEC_GUI.md` を参照。GUI への通知手段はコールバック or イベントで連携すること）

> 注: Zoom は `WM_CLOSE` 受信後に「ミーティングを退出しますか？」ダイアログを出す既知の挙動がある。
> このため `PostMessage` 単体では閉じない場合があり、フォールバック処理を必ず実装すること。

**送出例外:**
- `ZoomWindowNotFoundError`: Zoom ウィンドウが見つからない

#### set_window_position() の処理フロー

1. Zoom ウィンドウを特定
2. `win32gui.SetForegroundWindow` で前面表示
3. `win32gui.MoveWindow` で位置・サイズを設定

**送出例外:**
- `ZoomWindowNotFoundError`: Zoom ウィンドウが見つからない

---

## 8. config.yaml の zoom.* キー仕様

本モジュールが参照する `config.yaml` のキー一覧。

| キー | 型 | 必須 | デフォルト | 説明 |
|------|----|------|-----------|------|
| `zoom.meeting_id` | string | 必須 | — | 固定ミーティングID。ハイフン区切り形式で記載可（例: `123-456-7890`） |
| `zoom.password` | string | 任意 | `""` | ミーティングパスコード。パスコードなしのミーティングでは省略可 |
| `zoom.display_name` | string | 任意 | `"配信"` | Zoom 参加時の表示名 |
| `zoom.join_timeout` | integer | 任意 | `30` | ウィンドウ出現待機のタイムアウト秒数 |
| `zoom.window_position.x` | integer | 任意 | — | ウィンドウ配置 X 座標（ピクセル）。省略時は移動しない |
| `zoom.window_position.y` | integer | 任意 | — | ウィンドウ配置 Y 座標（ピクセル）。省略時は移動しない |
| `zoom.window_position.width` | integer | 任意 | — | ウィンドウ幅（ピクセル）。省略時は移動しない |
| `zoom.window_position.height` | integer | 任意 | — | ウィンドウ高さ（ピクセル）。省略時は移動しない |

### config.yaml 記述例

```yaml
zoom:
  meeting_id: "123-456-7890"
  password: "your_zoom_password"
  display_name: "配信"
  join_timeout: 30
  window_position:
    x: 1920
    y: 0
    width: 1280
    height: 720
```

> `window_position` ブロックを省略した場合、ウィンドウの移動・リサイズは行わない。

---

## 9. 制約・前提条件

### 9.1 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10 / 11（64bit） |
| Python | 3.9 以上（Windows Python。WSL Python は使用しない） |
| Zoom クライアント | インストール済み・`zoommtg://` スキームがレジストリに登録済み |
| pywin32 | インストール済み（`pip install pywin32`） |
| OBS | v28 以上（仮想カメラ対応） |

### 9.2 Zoom インストール確認方法

Windows レジストリの以下のキーで Zoom のインストールを確認する。

```
HKEY_CLASSES_ROOT\zoommtg
```

このキーが存在しない場合、`ZoomNotInstalledError` または `ZoomSchemeNotRegisteredError` を送出する。

### 9.3 非対応事項

- macOS / Linux は対応しない（pywin32 は Windows 専用のため）
- Zoom SDK は使用しない
- Zoom RTMP / カスタムライブストリーミングは使用しない
- OBS 仮想カメラの自動有効化は本モジュールの責務外

### 9.4 既知のリスク

- `zoommtg://` スキームの仕様は Zoom 公式に明文化されていない。Zoom のバージョンアップで挙動が変わる可能性がある
- Zoom のウィンドウタイトルはロケール・バージョンによって異なる可能性がある（「Zoom Workplace」への改名等）。クラス名チェックを併用することで誤検出リスクを軽減する
- `win32gui.PostMessage(WM_CLOSE)` でウィンドウが閉じない場合がある（Zoom が確認ダイアログを表示するケース）。セクション 7.3 のフォールバック手順で対応する

---

## 10. テスト方針

### 10.1 単体テスト対象

| テスト対象 | テスト方法 |
|-----------|----------|
| `build_zoom_url()` | ミーティングID・パスワード・表示名が正しく URL エンコードされた URL を生成することを検証する |
| ミーティング番号の正規化 | ハイフン区切り入力が数字列のみに変換されることを検証する |
| `ZoomConfig` のデフォルト値 | 各フィールドのデフォルト値が仕様通りであることを検証する |

### 10.2 結合テスト・手動テスト対象

以下は実機（Windows + Zoom クライアントインストール済み環境）でのみ検証可能。

| テスト内容 | 確認方法 |
|-----------|---------|
| `join_meeting()` 正常系 | Zoom が起動してミーティングに参加することを目視確認する |
| `join_meeting()` タイムアウト | Zoom を意図的に起動できない状態で `ZoomJoinTimeoutError` が送出されることを確認する |
| `set_window_position()` | ウィンドウが指定座標・サイズに移動することを目視確認する |
| `leave_meeting()` | Zoom ウィンドウが閉じることを目視確認する |
| `is_meeting_active()` | 起動前・参加中・終了後の状態変化を確認する |

### 10.3 モック方針

`win32gui` および `os.startfile` は実機なしでは実行不可のため、単体テストでは `unittest.mock.patch` でモックする。

---

## 11. TBD（未決事項）

| 項目 | 内容 | 優先度 |
|------|------|--------|
| Zoom バージョン確認 | 実機 Zoom のバージョンを確認し、`zoommtg://` スキームの動作を検証する | High |
| ウィンドウタイトルパターン | 実際の Zoom ウィンドウタイトル文字列を実機で確認する | High |
| OBS 仮想カメラ自動有効化 | OBS WebSocket v5 で仮想カメラの有効化ができるか調査する（`SPEC_OBS.md` と連携） | Medium |
| ~~Zoom 自動終了~~ | **確定仕様に格上げ（→ セクション 7.3 leave_meeting() を参照）**。「終了」ボタン押下後に `leave_meeting()` を呼び、GUI には「Zoomを終了しました」を表示する | — |
| display_name の設定方法 | `config.yaml` で固定 vs GUI で入力可能にする、どちらにするか確認する | Low |
| ウィンドウ整列・仮想デスクトップ | 起動時に OBS・Zoom・アプリ本体を自動整列する機能。**仮想デスクトップ連携（pyvda）は MVP 必須要件から除外し将来スコープとする。** pyvda は Windows の非公開 API に依存しており、OS バージョンアップで動作が壊れるリスクが高いため。（→ issue #6） | 将来スコープ |
| Zoom の変なウィンドウモード強制解除 | ミニ会議ビュー等の非標準モードを通常ウィンドウに強制する方法（ウィンドウタイトル・クラス名で判別）| Medium |

---

## 付録 A: 関連ファイル

| ファイル | 説明 |
|---------|------|
| `src/zoom_controller.py` | 本仕様の実装ファイル（未作成） |
| `config.yaml` | 実運用設定ファイル（gitignore対象） |
| `config.yaml.example` | 設定テンプレート（リポジトリに含める） |
| `docs/spec/SPEC_OVERVIEW.md` | 総合仕様書 |
| `docs/spec/SPEC_OBS.md` | OBS WebSocket 連携仕様書 |

---

## 受け入れ条件

- [ ] `build_zoom_url()` がハイフン除去・URLエンコード済みの正しい URL を返すこと
- [ ] `ZoomConfig` のデフォルト値が仕様通り（display_name="配信", join_timeout=30）であること
- [ ] Zoom 未インストール時に `ZoomNotInstalledError` または `ZoomSchemeNotRegisteredError` が送出されること
- [ ] `join_meeting()` 呼び出し後、30 秒以内に Zoom ウィンドウが前面表示されること（実機テスト）
- [ ] `join_timeout` 経過後に `ZoomJoinTimeoutError` が送出されること（実機テスト）
- [ ] `set_window_position()` 呼び出し後、ウィンドウが指定座標・サイズに移動すること（実機テスト）
- [ ] `leave_meeting()` 呼び出し後、Zoom ウィンドウが閉じること（実機テスト）
- [ ] `leave_meeting()` 呼び出し後、Zoom の確認ダイアログが表示されても最終的にプロセスが終了すること（実機テスト）
- [ ] `leave_meeting()` 完了後に GUI に「Zoomを終了しました」の案内が表示されること
- [ ] Zoom 起動失敗時に OBS 録画が継続していること（独立性の確認）
- [ ] `config.yaml` の `window_position` 省略時にウィンドウ移動が行われないこと

---

## 実装メモ（PRGちゃんへの引き継ぎ）

### 実装ファイル

- 実装先: `src/zoom_controller.py`
- 依存ライブラリ: `pywin32`（`pip install pywin32`）

### 重要な実装上の注意点

1. **`os.startfile` を使う**: `subprocess.Popen` で `zoommtg://` URL を起動しようとすると Windows のプロトコルハンドラーが正常に呼び出されないケースがある。`os.startfile(url)` を第一選択とすること。

2. **Windows Python を使う**: このプロジェクトの Python は `python3` = Windows Python 3.12。WSL Python ではない。`pywin32` は Windows Python にのみインストール可能。

3. **日本語パス対策**: ファイルパスに日本語が含まれる場合は `subprocess` でなく `pathlib.Path` と Python の標準 I/O を使うこと（`handover-2026-04-20.md` の Gotchas 参照）。

4. **ウィンドウタイトルのマッチング**: `"Zoom Meeting"` / `"Zoom"` / `"Zoom Workplace"` 等の部分文字列マッチに加え、`win32gui.GetClassName(hwnd)` によるクラス名チェックを必ず併用すること。クラス名は実機で `EnumWindows + GetClassName` を実行して確認すること（候補: `ZPContentViewWndClass` など。TBD）。

4a. **Zoom 終了のフォールバック実装**: `leave_meeting()` では以下の順序で処理すること。
   ```
   PostMessage(WM_CLOSE)
   time.sleep(2.5)
   if IsWindow(hwnd):  # まだ存在する
       SendMessage(WM_CLOSE)
       time.sleep(1)
   if IsWindow(hwnd):  # まだ存在する
       pid = GetWindowThreadProcessId(hwnd)
       handle = OpenProcess(PROCESS_TERMINATE, False, pid)
       win32process.TerminateProcess(handle, 1)
   ```
   `win32process` は `pywin32` に含まれる。`PROCESS_TERMINATE = 0x0001`。

5. **`ZoomConfig` の読み込み**: `config.yaml` の `zoom.*` セクションを PyYAML でロードし、`ZoomConfig` データクラスにマッピングする。`window_position` サブキーが存在しない場合は `None` とする。

6. **レジストリ確認の実装例**:
   ```
   import winreg
   try:
       winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "zoommtg")
   except FileNotFoundError:
       raise ZoomSchemeNotRegisteredError(...)
   ```

7. **ポーリング待機**: `join_meeting()` 内でのウィンドウ出現待機は `time.sleep(1)` + カウンターで実装する。`join_timeout` 秒経過したら `ZoomJoinTimeoutError` を送出する。

8. **録画との独立性**: `join_meeting()` が例外を送出しても OBS 録画を中断してはいけない。呼び出し元（`app.py` のコントローラー）で `try/except ZoomError` として処理すること。
