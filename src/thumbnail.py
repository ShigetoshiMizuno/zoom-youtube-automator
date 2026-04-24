"""サムネイル自動生成モジュール

礼拝情報（日付・タイトル・聖書箇所・説教者）をテンプレート画像に
テキスト合成して YouTube 推奨サイズ（1280×720px）の PNG を生成する。
"""

import logging
import warnings
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# デフォルト設定値
_DEFAULT_TEMPLATE_PATH = "assets/thumbnail_template.png"
_DEFAULT_FONT_PATH = "C:/Windows/Fonts/meiryob.ttc"
_OUTPUT_SIZE = (1280, 720)
_OUTPUT_FILENAME = "thumbnail.png"

_DEFAULTS: dict = {
    "template_path": _DEFAULT_TEMPLATE_PATH,
    "font_path": _DEFAULT_FONT_PATH,
    "date": {"x": 80, "y": 40, "size": 48, "color": [255, 255, 255], "max_width": 600},
    "title": {"x": 80, "y": 160, "size": 64, "color": [255, 255, 255], "max_width": 1100},
    "scripture": {"x": 80, "y": 400, "size": 40, "color": [220, 220, 220], "max_width": 900},
    "preacher": {"x": 80, "y": 480, "size": 40, "color": [220, 220, 220], "max_width": 600},
}


def generate_thumbnail(
    date: str,
    title: str,
    scripture: str,
    preacher: str,
    output_dir: Path,
    config: Optional[dict] = None,
) -> Path:
    """礼拝情報からサムネイル画像を生成し、output_dir に thumbnail.png として保存する。

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
        サムネイル PNG を保存するディレクトリ。存在しない場合は FileNotFoundError を送出する。
    config : dict | None
        config.yaml の thumbnail セクション（辞書）。None の場合はデフォルト設定で動作する。

    Returns
    -------
    Path
        生成した thumbnail.png の絶対パス。

    Raises
    ------
    FileNotFoundError
        テンプレート画像が存在しない場合、または output_dir が存在しない場合。
    OSError
        フォントファイルの読み込みに失敗し、フォールバックも失敗した場合。
    """
    cfg = config or {}

    # output_dir の存在確認
    output_dir = Path(output_dir)
    if not output_dir.exists():
        raise FileNotFoundError(f"output_dir が存在しません: {output_dir}")

    # テンプレートパスの解決
    template_path_str = cfg.get("template_path", _DEFAULTS["template_path"])
    template_path = Path(template_path_str)
    if not template_path.is_absolute():
        # リポジトリルート（src の親）からの相対パスとして解決する
        repo_root = Path(__file__).parent.parent
        template_path = repo_root / template_path
    if not template_path.exists():
        raise FileNotFoundError(f"テンプレート画像が存在しません: {template_path}")

    # テンプレート画像の読み込み
    img = Image.open(template_path).convert("RGB")

    # サイズが 1280×720 でない場合はリサイズ
    if img.size != _OUTPUT_SIZE:
        logger.warning(
            "テンプレート画像のサイズが %s です。%s にリサイズします。",
            img.size,
            _OUTPUT_SIZE,
        )
        img = img.resize(_OUTPUT_SIZE, Image.LANCZOS)

    draw = ImageDraw.Draw(img)

    # フォントパスの取得
    font_path = cfg.get("font_path", _DEFAULTS["font_path"])

    # 各フィールドの描画
    fields = [
        ("date", date),
        ("title", title),
        ("scripture", scripture),
        ("preacher", preacher),
    ]

    for field_name, text in fields:
        field_defaults = _DEFAULTS[field_name]
        field_cfg = cfg.get(field_name, {})

        x = field_cfg.get("x", field_defaults["x"])
        y = field_cfg.get("y", field_defaults["y"])
        size = field_cfg.get("size", field_defaults["size"])
        color = field_cfg.get("color", field_defaults["color"])
        max_width = field_cfg.get("max_width", field_defaults["max_width"])

        font = load_font(font_path, size, fallback=True)
        fill = tuple(color)

        if not text:
            logger.warning("フィールド '%s' が空文字列です。", field_name)

        draw_text_wrapped(
            draw=draw,
            text=text,
            position=(x, y),
            font=font,
            fill=fill,
            max_width=max_width,
        )

    # PNG として保存
    output_path = output_dir / _OUTPUT_FILENAME
    img.save(output_path, format="PNG")
    logger.info("サムネイルを保存しました: %s", output_path)

    return output_path.resolve()


def load_font(
    font_path: str,
    size: int,
    fallback: bool = True,
) -> ImageFont.FreeTypeFont:
    """指定パスのフォントを読み込む。

    Parameters
    ----------
    font_path : str
        フォントファイルの絶対パス。
    size : int
        フォントサイズ（ピクセル）。
    fallback : bool
        True の場合、フォントファイルが存在しなければ ImageFont.load_default() を返す。
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
    try:
        return ImageFont.truetype(font_path, size, index=0)
    except (OSError, IOError) as e:
        if not fallback:
            raise OSError(f"フォントの読み込みに失敗しました: {font_path}") from e
        logger.warning(
            "フォント '%s' が読み込めません。システムデフォルトフォントにフォールバックします。"
            "日本語は描画できない場合があります。エラー: %s",
            font_path,
            e,
        )
        # Pillow 10.0 以降では load_default() が FreeTypeFont を返す
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ImageFont.load_default()


def draw_text_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: tuple,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    max_width: int,
    line_spacing: int = 8,
) -> None:
    """テキストを指定幅で折り返して描画する。

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
    if not text:
        return

    x, y = position

    # フォントの行高を取得
    try:
        # Pillow 10.0 以降は getbbox を使う
        bbox = font.getbbox("A")
        line_height = bbox[3] - bbox[1]
    except AttributeError:
        # 旧 Pillow のフォールバック
        line_height = size if hasattr(font, "size") else 16  # type: ignore[attr-defined]

    # 1文字ずつ処理してmax_widthを超えたら改行する
    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        try:
            line_width = font.getlength(test_line)
        except AttributeError:
            # Pillow < 9.2.0 のフォールバック
            line_width = draw.textlength(test_line, font=font)  # type: ignore[attr-defined]

        if line_width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char

    if current_line:
        lines.append(current_line)

    # 行ごとに描画
    current_y = y
    for line in lines:
        draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_height + line_spacing
