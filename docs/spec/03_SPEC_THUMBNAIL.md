# SPEC_THUMBNAIL.md — サムネイル自動生成モジュール仕様書

バージョン: 1.0.0
作成日: 2026-04-24
対応 GitHub Issue: #3
ステータス: 仕様策定完了（実装未着手）

---

## 概要

礼拝情報（日付・タイトル・聖書箇所・説教者）を受け取り、調布南キリスト教会デザインのテンプレート画像の上にテキストを合成して YouTube 推奨サイズの PNG サムネイル画像を生成し、指定パスに保存するモジュール。

本モジュールは `thumbnail.py`（仮）として実装し、アプリコントローラーから呼び出される。

---

## 1. モジュール概要

### 責務の範囲

- テンプレート画像の読み込み
- テキスト要素（日付・タイトル・聖書箇所・説教者）のフォント描画
- 出力先ディレクトリへの PNG ファイル保存
- フォントファイルの存在確認・フォールバック処理
- テンプレート画像が存在しない場合のエラーハンドリング

### 責務の範囲外

- 録画ファイルのパス管理（コントローラー側の責務）
- YouTube へのアップロード（`SPEC_YOUTUBE.md` の責務）
- GUI への状態通知（コントローラー経由）

---

## 2. サムネイル仕様

| 項目 | 値 |
|------|-----|
| 出力サイズ | 1280 × 720 px（YouTube 推奨解像度） |
| フォーマット | PNG |
| カラーモード | RGB |
| デザイン | 調布南キリスト教会デザイン（2026-04-20 に動作確認済み） |
| ベース | テンプレート画像（`assets/thumbnail_template.png`）に文字を重ね描き |

---

## 3. テンプレートシステム

### 3.1 テンプレート画像の配置

テンプレート画像の配置場所:

```
zoom-youtube-automator/
|-- assets/
    |-- thumbnail_template.png   <- ベーステンプレート画像（1280x720px）
```

- テンプレート画像は事前に用意し、リポジトリに含める（gitignore 対象外）
- 画像形式: PNG または JPEG（Pillow が対応している形式であれば可）
- サイズ: 1280 × 720 px を推奨（他サイズの場合はコード側でリサイズする。詳細は「7. エラーハンドリング」を参照）

### 3.2 テンプレート上に描画するテキスト要素

| フィールド | 内容 | 入力例 |
|-----------|------|--------|
| 日付 | 礼拝日（フォーマット自由） | 2026年4月19日 |
| タイトル | 説教タイトル | 忘れ得じ、彼のパリサイびと |
| 聖書箇所 | 聖書の書名・章・節 | ヨハネの福音書 3章1〜15節 |
| 説教者 | 説教者の氏名 | 前田 重雄 師 |

### 3.3 テキスト要素の位置・フォントサイズ・色の定義方法

テキストの描画パラメータは `config.yaml` の `thumbnail.*` セクションで定義する（「8. 設定キー一覧」参照）。

設定が存在しない場合はコード内のデフォルト値を使用する（ハードコードフォールバック）。

---

## 4. インターフェース定義

### 4.1 主要関数

#### `generate_thumbnail`

```python
from pathlib import Path

def generate_thumbnail(
    date: str,
    title: str,
    scripture: str,
    preacher: str,
    output_dir: Path,
    config: dict | None = None,
) -> Path:
    """
    礼拝情報からサムネイル画像を生成し、output_dir に thumbnail.png として保存する。

    Parameters
    ----------
    date : str
        礼拝日の文字列。例: "2026年4月19日"
    title : str
        説教タイトル。例: "忘れ得じ、彼のパリサイびと"
    scripture : str
        聖書箇所。例: "ヨハネの福音書 3章1〜15節"
    preacher : str
        説教者名。例: "前田 重雄 師"
    output_dir : Path
        サムネイル PNG を保存するディレクトリ。
        存在しない場合は FileNotFoundError を送出する。
    config : dict | None
        config.yaml の thumbnail セクション（辞書）。
        None の場合はデフォルト設定で動作する。

    Returns
    -------
    Path
        生成した thumbnail.png の絶対パス。

    Raises
    ------
    FileNotFoundError
        テンプレート画像が存在しない場合。
        output_dir が存在しない場合。
    OSError
        フォントファイルの読み込みに失敗し、フォールバックも失敗した場合。
    """
```

#### `load_font`

```python
from PIL import ImageFont

def load_font(
    font_path: str,
    size: int,
    fallback: bool = True,
) -> ImageFont.FreeTypeFont:
    """
    指定パスのフォントを読み込む。フォントが存在しない場合は
    fallback=True のときシステムデフォルトフォントを返す。

    Parameters
    ----------
    font_path : str
        フォントファイルの絶対パス。
    size : int
        フォントサイズ（ピクセル）。
    fallback : bool
        True の場合、フォントファイルが存在しなければ
        ImageFont.load_default() を返す（日本語は描画不可になる旨を警告ログ出力）。
        False の場合、OSError を送出する。

    Returns
    -------
    ImageFont.FreeTypeFont
        読み込んだフォントオブジェクト。

    Raises
    ------
    OSError
        fallback=False かつフォントファイルが存在しない場合。
    """
```

#### `draw_text_wrapped`

```python
def draw_text_wrapped(
    draw: "PIL.ImageDraw.ImageDraw",
    text: str,
    position: tuple[int, int],
    font: "PIL.ImageFont.FreeTypeFont",
    fill: tuple[int, int, int],
    max_width: int,
    line_spacing: int = 8,
) -> None:
    """
    テキストを指定幅で折り返して描画する。

    Parameters
    ----------
    draw : ImageDraw.ImageDraw
        描画対象の ImageDraw オブジェクト。
    text : str
        描画するテキスト。
    position : tuple[int, int]
        描画開始座標 (x, y)。左上基準。
    font : ImageFont.FreeTypeFont
        描画に使用するフォント。
    fill : tuple[int, int, int]
        テキスト色 (R, G, B)。
    max_width : int
        折り返しを行う最大幅（ピクセル）。
    line_spacing : int
        行間の追加ピクセル数（デフォルト: 8px）。
    """
```

---

## 5. フォント仕様

### 5.1 使用フォント

| 優先度 | フォント名 | ファイルパス | 備考 |
|--------|-----------|------------|------|
| 1（優先） | Meiryo Bold | `C:/Windows/Fonts/meiryob.ttc` | Windows 標準搭載・日本語対応・動作確認済み |
| 2（フォールバック） | システムデフォルトフォント | `ImageFont.load_default()` | 日本語描画不可。警告ログを出力する |

フォントパスは `config.yaml` の `thumbnail.font_path` で上書き可能。

### 5.2 フォントサイズ一覧（デフォルト値）

| フィールド | デフォルトサイズ（px） |
|-----------|----------------------|
| 日付 | 48 |
| タイトル | 64 |
| 聖書箇所 | 40 |
| 説教者 | 40 |

### 5.3 Gotcha: 日本語フォントと Pillow の注意点

- 日本語フォントを指定せず `ImageFont.load_default()` を使用した場合、日本語文字を `draw.text()` に渡すと `UnicodeEncodeError` または文字化けが発生する。
- **必ず `meiryob.ttc` または他の日本語対応 TrueType / OpenType フォントを指定すること。**
- フォントファイルのパスは Windows パス形式（`C:/Windows/Fonts/meiryob.ttc`）で渡す。Pillow は Windows パス・POSIX パスの両方を受け付ける。
- TTC（TrueType Collection）ファイルの場合、`ImageFont.truetype(path, size, index=0)` の `index` 引数でフォントを選択できる（`meiryob.ttc` は `index=0` で Meiryo Bold が得られることを確認済み）。

---

## 6. ファイル出力仕様

### 6.1 保存パスとファイル名規則

```
{output_dir}/thumbnail.png
```

- ファイル名は常に `thumbnail.png` 固定。
- `output_dir` は `config.yaml` の `obs.output_dir` と同一ディレクトリを使用する（コントローラーが `Path` オブジェクトとして渡す）。

### 6.2 上書き挙動

- 同名ファイルが既に存在する場合は **上書きする**（礼拝日ごとに新しく生成するため、上書きが正常動作）。
- 上書き前にバックアップは行わない。

---

## 7. エラーハンドリング

| エラー状況 | 挙動 |
|-----------|------|
| テンプレート画像（`assets/thumbnail_template.png`）が存在しない | `FileNotFoundError` を送出し、呼び出し元（コントローラー）にエラーを伝播する |
| テンプレート画像のサイズが 1280×720 でない | 警告ログを出力し、Pillow の `Image.resize()` で 1280×720 にリサイズしてから処理を続行する |
| フォントファイル（`meiryob.ttc`）が存在しない | 警告ログを出力し、`ImageFont.load_default()` にフォールバックする。日本語が描画できない旨をログに記録する |
| `output_dir` が存在しない | `FileNotFoundError` を送出する。ディレクトリの自動作成は行わない（呼び出し元が責任を持つ） |
| テキスト文字列が空文字列 | 空文字列として描画する（エラーにしない）。ログに警告を出力する |

---

## 8. 設定キー一覧（config.yaml の thumbnail セクション）

```yaml
thumbnail:
  template_path: "assets/thumbnail_template.png"   # テンプレート画像パス（リポジトリ相対）
  font_path: "C:/Windows/Fonts/meiryob.ttc"         # 使用フォントの絶対パス

  # --- 日付フィールド ---
  date:
    x: 80          # 描画開始 X 座標（px）
    y: 40          # 描画開始 Y 座標（px）
    size: 48       # フォントサイズ（px）
    color: [255, 255, 255]   # テキスト色 [R, G, B]
    max_width: 600 # 折り返し最大幅（px）

  # --- タイトルフィールド ---
  title:
    x: 80
    y: 160
    size: 64
    color: [255, 255, 255]
    max_width: 1100

  # --- 聖書箇所フィールド ---
  scripture:
    x: 80
    y: 400
    size: 40
    color: [220, 220, 220]
    max_width: 900

  # --- 説教者フィールド ---
  preacher:
    x: 80
    y: 480
    size: 40
    color: [220, 220, 220]
    max_width: 600
```

各キーの詳細:

| キー | 型 | デフォルト | 説明 |
|------|----|-----------|------|
| `thumbnail.template_path` | string | `assets/thumbnail_template.png` | テンプレート画像の相対パス（アプリルートからの相対） |
| `thumbnail.font_path` | string | `C:/Windows/Fonts/meiryob.ttc` | フォントファイルの絶対パス |
| `thumbnail.{field}.x` | integer | フィールドごとに異なる | テキスト描画開始 X 座標（px） |
| `thumbnail.{field}.y` | integer | フィールドごとに異なる | テキスト描画開始 Y 座標（px） |
| `thumbnail.{field}.size` | integer | フィールドごとに異なる | フォントサイズ（px） |
| `thumbnail.{field}.color` | list[int] | `[255, 255, 255]` | テキスト色（RGB 配列） |
| `thumbnail.{field}.max_width` | integer | フィールドごとに異なる | 折り返し最大幅（px）。これを超えた場合に改行する |

> `{field}` は `date` / `title` / `scripture` / `preacher` の 4 種類。

---

## 9. 依存ライブラリ

| ライブラリ | 最小バージョン | 用途 |
|-----------|--------------|------|
| `Pillow` | 9.0.0 以上 | 画像読み込み・テキスト描画・PNG 保存 |
| `PyYAML` | — | config.yaml の読み込み（`SPEC_OVERVIEW.md` の共通依存） |

Pillow のインストール:

```
pip install Pillow
```

Python バージョン要件: 3.9 以上（`SPEC_OVERVIEW.md` の共通前提に準拠）

---

## 10. テスト方針

### ユニットテスト（QAちゃんへの指針）

| テストケース | 検証内容 |
|-------------|---------|
| 正常生成テスト | テンプレート画像・フォントが存在する場合に `thumbnail.png` が生成されること |
| 出力ファイルの属性確認 | 生成された PNG のサイズが 1280×720 px であること |
| テキスト描画確認 | 日付・タイトル・聖書箇所・説教者が渡した文字列と一致（目視確認 or 別途 OCR） |
| 上書き動作確認 | 既存の `thumbnail.png` が上書きされること |
| テンプレート欠如 | テンプレート画像が存在しないとき `FileNotFoundError` が発生すること |
| output_dir 欠如 | `output_dir` が存在しないとき `FileNotFoundError` が発生すること |
| フォントフォールバック | `meiryob.ttc` が存在しないとき警告ログが出力され、処理が続行すること（例外にならないこと） |
| 長文タイトルの折り返し | `max_width` を超えるタイトルが複数行に折り返されること |
| 空文字列の入力 | 各フィールドに空文字列を渡しても例外が発生しないこと |

### 手動確認（受け入れテスト）

- 生成した `thumbnail.png` を目視確認し、調布南キリスト教会デザインとして見栄えが適切であること
- YouTube Studio でサムネイルとして設定し、正常に表示されること

---

## 11. 受け入れ条件

- [ ] `generate_thumbnail()` を呼び出すと `output_dir/thumbnail.png` が生成される
- [ ] 生成された画像のサイズが 1280 × 720 px である
- [ ] 日付・タイトル・聖書箇所・説教者の文字列が画像内に描画されている（日本語含む）
- [ ] 同名ファイルが既存でも上書きして正常終了する
- [ ] テンプレート画像が存在しない場合、`FileNotFoundError` が発生する
- [ ] フォントファイルが存在しない場合、例外にならず警告ログを出力してフォールバックする
- [ ] テキスト描画パラメータ（位置・サイズ・色）を `config.yaml` で変更でき、反映される
- [ ] `config.yaml` の `thumbnail` セクションがない場合もデフォルト値で動作する

---

## 12. TBD・未決事項

| 項目 | 内容 | 優先度 |
|------|------|--------|
| テンプレート差し替え可能化 | `config.yaml` の `thumbnail.template_path` で別テンプレートに切り替えられる仕様（設定キーは定義済み、UIからの差し替えは未検討） | Medium |
| テキスト描画パラメータの初期値確定 | 実際のテンプレート画像に合わせた X/Y 座標・サイズ・色の最終値はテンプレート確認後に決定する | High |
| 長文タイトルの最大行数 | 折り返し後の最大行数制限（2行まで等）を設けるか未決定 | Low |
| テンプレート画像のリポジトリ管理 | `assets/thumbnail_template.png` をリポジトリに含めるか（著作権・デザイン資産の扱い）を監督に確認 | Medium |
| 縦書き対応 | 聖書箇所・タイトルの縦書き表示は不要（横書き固定で進める）。変更が生じた場合は本仕様書を改訂する | — |

---

## 実装メモ（PRGちゃんへの引き継ぎ）

### 既存コードとの整合性

- サムネイル生成は 2026-04-20 の作業セッションで実動作確認済み。Pillow + `meiryob.ttc` の組み合わせは問題なく動いている。コードはリポジトリに含まれていないが、実績あり。
- 実装コードはゼロから書くことになるが、設計は実証済みの方式に従うこと。

### 実装上の注意点

1. **フォントパスはフォワードスラッシュで渡す**: Pillow は `C:/Windows/Fonts/meiryob.ttc` 形式で動作する。バックスラッシュは使わない。
2. **TTC インデックス指定**: `ImageFont.truetype()` で `index=0` を指定する。`meiryob.ttc` は `index=0` で Meiryo Bold が得られることを確認済み。
3. **テキスト幅の計算**: Pillow 10.0 以降は `font.getlength(text)` を使う。旧来の `draw.textsize()` は非推奨（Pillow 10 で削除済み）。折り返しロジックでは `font.getlength()` を使って単語または 1 文字ずつ幅を計算すること。
4. **日本語の UnicodeEncodeError の回避**: フォントを指定せず `ImageFont.load_default()` を使った状態で日本語文字を渡すと `UnicodeEncodeError` が発生する。フォールバック時は警告ログを出力し、英数字のみ描画する設計とすること。
5. **`output_dir` の作成は呼び出し元の責任**: `generate_thumbnail()` は `output_dir` が存在しなければ `FileNotFoundError` を送出する。ディレクトリ作成はコントローラー側で行う設計にすること（単一責任の原則）。
6. **テンプレートサイズの不一致**: テンプレート画像が 1280×720 でなくても警告ログ出力後にリサイズして処理を続行する。実際のテンプレートは 1280×720 で作成済みのはずなので、通常は発生しない。
7. **config.yaml の thumbnail セクションがない場合**: `config.get()` でデフォルト空辞書を使い、フィールドごとの値も `dict.get(key, DEFAULT_VALUE)` でフォールバックする。

### モジュールの位置づけ

- ファイル名: `thumbnail.py`（仮）
- 呼び出し元: `app.py`（コントローラー）の「終了 → YouTube アップロード」ボタン押下後の処理ステップ
- 呼び出しタイミング: OBS 録画停止後、YouTube アップロード前（`SPEC_OVERVIEW.md` §3.2 データフロー参照）