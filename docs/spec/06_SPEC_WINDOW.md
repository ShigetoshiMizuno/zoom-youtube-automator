# 06_SPEC_WINDOW.md — ウィンドウ整列・配置制御モジュール仕様書

バージョン: 1.0.0
作成日: 2026-04-25
ステータス: 仕様策定完了（実装未着手）
対応 GitHub Issue: #6

---

## 概要

礼拝配信アプリ起動時に、アプリ本体・OBS・Zoom の各ウィンドウを自動で整列・配置する新規モジュール `src/window_manager.py` の仕様。
pywin32 を使用し、各ウィンドウを config.yaml で指定した座標・サイズに移動する。

---

## 機能仕様

### 全体の動作

- 「開始」ボタン押下後、バックグラウンドスレッド内で Zoom 起動完了直後に `WindowManager.arrange_all()` を呼び出す
- 整列対象は以下の 3 ウィンドウ:
  1. アプリ本体（Tkinter メインウィンドウ）
  2. OBS Studio ウィンドウ
  3. Zoom ミーティングウィンドウ
- 各ウィンドウが見つからない場合はそのウィンドウをスキップし、見つかったウィンドウのみ整列する（部分成功を許容する）
- 整列失敗はアプリの状態遷移に影響しない（エラーはログ出力のみ）

### アプリ本体ウィンドウの取得と配置

- Tkinter の `App` インスタンス（`tk.Tk` のサブクラス）から `winfo_id()` で HWND を取得する
- `WindowManager` のコンストラクタに `app_hwnd: int` として渡す
- `win32gui.MoveWindow(hwnd, x, y, width, height, True)` で指定座標・サイズに移動する
- デフォルト配置: `x=0, y=0, width=480, height=360`（config.yaml の `window_manager.app.*` で上書き可）

### OBS ウィンドウの検索と配置

- `win32gui.EnumWindows` で全ウィンドウを列挙する
- タイトルに `"OBS "` を含む（末尾スペース付き）かつ `win32gui.IsWindowVisible(hwnd)` が `True` のウィンドウを OBS とみなす
  - クラス名による絞り込みは TBD（実機確認が必要なため現時点はタイトルマッチのみ）
  - タイトル例: `"OBS Studio"`, `"OBS 30.0.0"`
- 複数ヒットした場合は最初の 1 件を使用する
- `win32gui.MoveWindow` で指定座標・サイズに移動する
- デフォルト配置: config.yaml の `window_manager.obs.*` で設定（デフォルト値なし。省略時は移動しない）

### Zoom ウィンドウの検索と配置

- 既存の `zoom_controller.py` 内 `_find_zoom_hwnd()` モジュールレベル関数を **直接呼び出さず**、`zoom_controller` モジュールの公開 API を通じて hwnd を取得する方針とする
  - 理由: `_find_zoom_hwnd()` はモジュールプライベート関数（アンダースコア接頭辞）であり、外部から直接呼び出すのは設計上不適切
  - 採用する方針: `ZoomController.get_window_hwnd() -> Optional[int]` を新たに追加し、`WindowManager` はこれを呼び出す（後述のインターフェース定義を参照）
- Zoom ウィンドウの判定基準は `zoom_controller.py` の `_is_zoom_window()` と同一にすること（`_ZOOM_TITLE_PATTERNS` の参照）
- 配置座標は config.yaml の `zoom.window_position.*`（既存キー）を使用する。`WindowManager` は `ZoomController.set_window_position()` を呼び出すことで Zoom の配置を行う

### Zoom「ミニ会議ビュー」強制解除

- Zoom が「ミニ会議ビュー（Mini Meeting View）」で起動した場合、ウィンドウが極端に小さくなる
- 判定基準: ウィンドウ幅が閾値（デフォルト: 400px）未満の場合を「ミニ会議ビュー」とみなす
  - 判定には `win32gui.GetWindowRect(hwnd)` で取得したウィンドウ矩形を使用する
  - `GetWindowRect` は `(left, top, right, bottom)` のタプルを返す。幅は `right - left`
- 強制解除の方法: `win32gui.MoveWindow` で config.yaml の `zoom.window_position.*` が指定する幅・高さにリサイズする
  - `zoom.window_position.*` が未設定の場合のデフォルトリサイズ先: `width=1280, height=720`
- 閾値は config.yaml の `window_manager.zoom_mini_view_threshold` で上書き可能（デフォルト: 400）

### 仮想デスクトップ対応（将来スコープ）

- pyvda による仮想デスクトップ操作は **本仕様のスコープ外**
- 理由: pyvda は Windows の非公開 API に依存しており、OS バージョンアップで動作が壊れるリスクが高い（SPEC_ZOOM.md §11 参照）
- 将来対応時は本仕様書を改訂すること

---

## インターフェース定義

### WindowManager クラス（新規: `src/window_manager.py`）

```python
from typing import Optional
from zoom_controller import WindowPosition


class WindowManager:
    def __init__(
        self,
        app_hwnd: int,
        zoom_controller,           # ZoomController インスタンス
        app_layout: Optional[WindowPosition] = None,
        obs_layout: Optional[WindowPosition] = None,
        zoom_layout: Optional[WindowPosition] = None,
        zoom_mini_view_threshold: int = 400,
    ) -> None:
        ...

    def arrange_all(self) -> None:
        ...

    def arrange_app(self) -> None:
        ...

    def arrange_obs(self) -> None:
        ...

    def arrange_zoom(self) -> None:
        ...

    def _find_obs_hwnd(self) -> Optional[int]:
        ...
```

#### arrange_all() の処理フロー

1. `arrange_app()` を呼び出す（app_hwnd が 0 の場合はスキップ）
2. `arrange_obs()` を呼び出す（obs_layout が None の場合はスキップ）
3. `arrange_zoom()` を呼び出す（zoom_layout が None かつ Zoom ウィンドウが通常サイズの場合はスキップ）

各ステップは独立した try/except で囲み、1 つが失敗しても次のステップを実行する。

#### _find_obs_hwnd() の処理フロー

1. `win32gui.EnumWindows` で全ウィンドウを列挙する
2. `win32gui.IsWindowVisible(hwnd)` が True のウィンドウのみ対象とする
3. `win32gui.GetWindowText(hwnd)` に `"OBS "` が含まれるウィンドウを返す
4. 複数ヒットした場合は最初の 1 件を返す。ヒットなしは None を返す

### ZoomController への追加メソッド（`src/zoom_controller.py` 変更）

```python
class ZoomController:
    # 既存メソッドは変更なし

    def get_window_hwnd(self) -> Optional[int]:
        """Zoom ミーティングウィンドウの HWND を返す。見つからなければ None。"""
        return _find_zoom_hwnd()
```

### app.py への統合

`App.__init__` 内で `WindowManager` を生成して `self._window_manager` に保持する。
`window_manager` キーが config.yaml に存在しない場合は整列をスキップする（`_window_manager = None`）。

`on_start_click` の `_background()` 内、`zoom_controller.join_meeting()` の完了直後に以下を追加する:

```python
if self._window_manager is not None:
    try:
        self._window_manager.arrange_all()
    except Exception as exc:
        logger.warning("ウィンドウ整列に失敗しました: %s", exc)
```

---

## config.yaml の `window_manager.*` キー定義

| キー | 型 | 必須 | デフォルト | 説明 |
|------|----|------|-----------|------|
| `window_manager.app.x` | integer | 任意 | `0` | アプリ本体ウィンドウの X 座標 |
| `window_manager.app.y` | integer | 任意 | `0` | アプリ本体ウィンドウの Y 座標 |
| `window_manager.app.width` | integer | 任意 | `480` | アプリ本体ウィンドウの幅 |
| `window_manager.app.height` | integer | 任意 | `360` | アプリ本体ウィンドウの高さ |
| `window_manager.obs.x` | integer | 任意 | — | OBS ウィンドウの X 座標。省略時は OBS を移動しない |
| `window_manager.obs.y` | integer | 任意 | — | OBS ウィンドウの Y 座標。省略時は OBS を移動しない |
| `window_manager.obs.width` | integer | 任意 | — | OBS ウィンドウの幅。省略時は OBS を移動しない |
| `window_manager.obs.height` | integer | 任意 | — | OBS ウィンドウの高さ。省略時は OBS を移動しない |
| `window_manager.zoom_mini_view_threshold` | integer | 任意 | `400` | Zoom ミニ会議ビュー判定の幅閾値（px） |

Zoom のウィンドウ配置は既存の `zoom.window_position.*` キー（SPEC_ZOOM.md §8）を引き続き使用する。`window_manager` に Zoom 配置用の重複キーは設けない。

### config.yaml 記述例（追加分）

```yaml
window_manager:
  app:
    x: 0
    y: 0
    width: 480
    height: 360
  obs:
    x: 0
    y: 400
    width: 1280
    height: 720
  zoom_mini_view_threshold: 400

zoom:
  meeting_id: "123-456-7890"
  password: "your_zoom_password"
  window_position:
    x: 1300
    y: 400
    width: 1280
    height: 720
```

> モニター構成（シングル/デュアル等）によって最適な座標が異なるため、上記の数値は例示であり各環境で調整すること。
> `window_manager.obs.*` ブロック全体を省略した場合、OBS ウィンドウの移動は行わない。

---

## 制約・前提条件

### 動作環境

| 項目 | 要件 |
|------|------|
| OS | Windows 10 / 11（64bit） |
| Python | 3.9 以上（Windows Python） |
| pywin32 | インストール済み（`pip install pywin32`） |
| 依存モジュール | `zoom_controller.py`（同プロジェクト内） |

### 非対応事項

- macOS / Linux は対応しない（pywin32 は Windows 専用）
- pyvda による仮想デスクトップ操作は対応しない（将来スコープ）
- OBS ウィンドウのクラス名によるフィルタリングは TBD（実機確認が必要）
- 整列実行はアプリ起動時の「開始」ボタン押下時のみ。任意タイミングでの手動再整列ボタンは MVP スコープ外

### 既存実装との整合性

- `zoom_controller.py` の `WindowPosition` データクラスを `window_manager.py` 内でも使用する（再定義しない）
- `ZoomController.set_window_position()` を Zoom ウィンドウの配置に活用する（重複実装しない）
- Zoom ウィンドウのミニ会議ビュー強制解除は、`ZoomController.set_window_position()` を呼び出すことで実現する

---

## テスト方針

### 単体テスト対象（モック使用）

| テスト対象 | テスト方法 |
|-----------|----------|
| `_find_obs_hwnd()` | `win32gui.EnumWindows` と `win32gui.GetWindowText` をモックし、OBS タイトルを持つウィンドウが正しく検出されることを検証する |
| Zoom ミニ会議ビュー判定ロジック | `win32gui.GetWindowRect` をモックし、幅が閾値未満のとき `ZoomController.set_window_position()` が呼ばれることを検証する |
| `arrange_all()` の部分成功 | 一部ウィンドウが見つからない状態（`_find_obs_hwnd()` が None を返す）でも例外が送出されないことを検証する |
| `obs_layout=None` 時の動作 | `obs_layout=None` のとき `arrange_obs()` がウィンドウ移動をスキップすることを検証する |

### 結合テスト・手動テスト対象

| テスト内容 | 確認方法 |
|-----------|----------|
| OBS ウィンドウ検出 | OBS 起動状態で `_find_obs_hwnd()` が正しく hwnd を返すことを目視確認する |
| 全ウィンドウ整列 | 「開始」ボタン押下後に 3 ウィンドウが指定座標に移動することを目視確認する |
| Zoom ミニ会議ビュー強制解除 | Zoom をミニ会議ビューで起動した状態で整列実行後に通常サイズに復元されることを目視確認する |
| 部分成功（OBS 未起動） | OBS 未起動状態で「開始」を押してもアプリがクラッシュしないことを確認する |

### モック方針

`win32gui` は実機なしでは実行不可のため、単体テストでは `unittest.mock.patch` でモックする。
`ZoomController` はテスト用モッククラスに差し替えて使用する。

---

## 受け入れ条件

- [ ] OBS が起動中のとき `_find_obs_hwnd()` がタイトルに `"OBS "` を含むウィンドウの hwnd を返すこと
- [ ] `arrange_all()` 呼び出し後、アプリ本体ウィンドウが config.yaml の `window_manager.app.*` で指定した座標・サイズに移動すること（実機テスト）
- [ ] `arrange_all()` 呼び出し後、OBS ウィンドウが config.yaml の `window_manager.obs.*` で指定した座標・サイズに移動すること（実機テスト）
- [ ] `arrange_all()` 呼び出し後、Zoom ウィンドウが `zoom.window_position.*` で指定した座標・サイズに移動すること（実機テスト）
- [ ] Zoom がミニ会議ビュー（幅 400px 未満）で起動した場合、整列後に `zoom.window_position.*` のサイズに強制リサイズされること（実機テスト）
- [ ] OBS が未起動の状態で `arrange_all()` を呼び出しても例外が送出されず、アプリ本体および Zoom のみが整列されること
- [ ] `window_manager.obs.*` ブロックが config.yaml に存在しない場合、OBS ウィンドウの移動が行われないこと
- [ ] `arrange_all()` は「開始」ボタン押下後の Zoom 起動完了直後に実行されること（app.py 統合確認）
- [ ] `_find_obs_hwnd()` の単体テストで `win32gui` をモックしてタイトルマッチングが正しく動作することを確認すること
- [ ] `arrange_all()` の単体テストで、一部ウィンドウが None のとき残りのウィンドウだけ整列が実行されることを確認すること

---

## 実装メモ（PRGちゃんへの引き継ぎ）

### 新規ファイル

- 実装先: `src/window_manager.py`
- 依存ライブラリ: `pywin32`（既存依存。追加インストール不要）

### zoom_controller.py への変更（最小限）

`ZoomController` クラスに `get_window_hwnd() -> Optional[int]` を追加する。
内部で `_find_zoom_hwnd()` を呼ぶだけのラッパー。既存メソッドへの変更は一切不要。

### WindowPosition の再利用

`window_manager.py` 内では `from zoom_controller import WindowPosition` してそのまま利用すること。
新たなデータクラスは定義しない（`WindowPosition` と同じフィールドのため）。

### app.py への統合手順

1. `App.__init__` 内で config.yaml の `window_manager` セクションを読み込む
2. `WindowManager` を生成して `self._window_manager` に保持する
3. `window_manager` キーが存在しない場合は `self._window_manager = None` とする
4. `on_start_click` の `_background()` 内、`zoom_controller.join_meeting()` 完了直後に整列を呼ぶ

config.yaml の読み込みサンプル:

```python
wm_cfg = config.get("window_manager", {})
app_cfg = wm_cfg.get("app", {})
app_layout = WindowPosition(
    x=app_cfg.get("x", 0),
    y=app_cfg.get("y", 0),
    width=app_cfg.get("width", 480),
    height=app_cfg.get("height", 360),
) if wm_cfg else WindowPosition(x=0, y=0, width=480, height=360)

obs_cfg = wm_cfg.get("obs")
obs_layout = WindowPosition(
    x=obs_cfg["x"], y=obs_cfg["y"],
    width=obs_cfg["width"], height=obs_cfg["height"],
) if obs_cfg else None

zoom_cfg = config.get("zoom", {}).get("window_position")
zoom_layout = WindowPosition(
    x=zoom_cfg["x"], y=zoom_cfg["y"],
    width=zoom_cfg["width"], height=zoom_cfg["height"],
) if zoom_cfg else None
```

### Zoom ミニ会議ビュー判定の実装

ミニ会議ビューの強制解除はリサイズと配置を兼ねる（`set_window_position` が両方行う）ため、
判定結果に関わらず `zoom_layout` が設定されていれば常に `set_window_position` を呼べばよい。
Zoom ウィンドウがミニ会議ビューであればその旨をログに記載する（INFO レベル）。

```python
hwnd = self._zoom_controller.get_window_hwnd()
if hwnd is not None and self._zoom_layout is not None:
    rect = win32gui.GetWindowRect(hwnd)
    current_width = rect[2] - rect[0]
    if current_width < self._zoom_mini_view_threshold:
        logger.info("Zoom ミニ会議ビューを検出。通常サイズに強制リサイズします。")
    self._zoom_controller.set_window_position(self._zoom_layout)
```

### SetForegroundWindow のエラー対処

`win32gui.SetForegroundWindow` は別プロセスのウィンドウを前面に持ってこようとするとアクセス拒否になる場合がある（Windows のフォーカス制御ポリシー）。
`ZoomController._move_window()` 内で既に `SetForegroundWindow` を呼んでいるが、失敗しても `MoveWindow` だけは実行されるよう `try/except` を追加することを推奨する。

### OBS タイトルマッチング

末尾スペース付き `"OBS "` でマッチングすること。これにより OBSIDIAN 等の無関係アプリを誤検出しにくくなる。

### headless モード対応

`App(headless=True)` のときは `winfo_id()` が有効な HWND を返さない場合がある。
`WindowManager` の `arrange_app()` は `app_hwnd == 0` のとき移動をスキップする防御コードを入れること。
