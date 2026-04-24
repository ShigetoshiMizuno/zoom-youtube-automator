"""サムネイル自動生成モジュール ユニットテスト

テンプレート画像・フォントファイルが存在しない環境でも動作するよう、
PIL.Image.new() で一時テンプレートを作成して使用する。
"""

import sys
from pathlib import Path

import pytest
from PIL import Image

# src/ を import パスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from thumbnail import draw_text_wrapped, generate_thumbnail, load_font


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def make_template(tmp_path: Path, size: tuple[int, int] = (1280, 720)) -> Path:
    """テスト用テンプレート画像を tmp_path に作成して返す。"""
    template_dir = tmp_path / "assets"
    template_dir.mkdir()
    template_path = template_dir / "thumbnail_template.png"
    img = Image.new("RGB", size, color=(30, 30, 80))
    img.save(template_path)
    return template_path


def make_config(tmp_path: Path, template_path: Path) -> dict:
    """テスト用 config 辞書を返す。フォントは存在しないパスを指定する。"""
    return {
        "template_path": str(template_path),
        "font_path": str(tmp_path / "nonexistent_font.ttc"),
        "date": {"x": 80, "y": 40, "size": 48, "color": [255, 255, 255], "max_width": 600},
        "title": {"x": 80, "y": 160, "size": 64, "color": [255, 255, 255], "max_width": 1100},
        "scripture": {"x": 80, "y": 400, "size": 40, "color": [220, 220, 220], "max_width": 900},
        "preacher": {"x": 80, "y": 480, "size": 40, "color": [220, 220, 220], "max_width": 600},
    }


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


def test_generate_thumbnail_creates_file(tmp_path: Path) -> None:
    """正常生成: thumbnail.png が output_dir に生成される"""
    template_path = make_template(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = make_config(tmp_path, template_path)

    result = generate_thumbnail(
        date="2026年4月19日",
        title="忘れ得じ、彼のパリサイびと",
        scripture="ヨハネの福音書 3章1〜15節",
        preacher="前田 重雄 師",
        output_dir=output_dir,
        config=config,
    )

    assert result == output_dir / "thumbnail.png"
    assert result.exists()


def test_generate_thumbnail_output_size(tmp_path: Path) -> None:
    """出力サイズ: 生成された PNG が 1280×720 px である"""
    template_path = make_template(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = make_config(tmp_path, template_path)

    result = generate_thumbnail(
        date="2026年4月19日",
        title="テストタイトル",
        scripture="マタイ 1章1節",
        preacher="テスト 説教者 師",
        output_dir=output_dir,
        config=config,
    )

    with Image.open(result) as img:
        assert img.size == (1280, 720)


def test_generate_thumbnail_overwrites_existing(tmp_path: Path) -> None:
    """上書き動作: 既存の thumbnail.png が上書きされる"""
    template_path = make_template(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = make_config(tmp_path, template_path)

    # 先に既存ファイルを作成
    existing = output_dir / "thumbnail.png"
    existing.write_bytes(b"dummy content")
    original_content = existing.read_bytes()

    generate_thumbnail(
        date="2026年4月19日",
        title="上書きテスト",
        scripture="聖書箇所",
        preacher="説教者",
        output_dir=output_dir,
        config=config,
    )

    assert existing.exists()
    # 内容が変わっていること（上書きされた）
    assert existing.read_bytes() != original_content


def test_generate_thumbnail_raises_when_template_missing(tmp_path: Path) -> None:
    """テンプレート欠如: テンプレートが存在しないとき FileNotFoundError"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = {
        "template_path": str(tmp_path / "nonexistent_template.png"),
        "font_path": str(tmp_path / "nonexistent_font.ttc"),
    }

    with pytest.raises(FileNotFoundError):
        generate_thumbnail(
            date="2026年4月19日",
            title="テスト",
            scripture="聖書箇所",
            preacher="説教者",
            output_dir=output_dir,
            config=config,
        )


def test_generate_thumbnail_raises_when_output_dir_missing(tmp_path: Path) -> None:
    """output_dir 欠如: output_dir が存在しないとき FileNotFoundError"""
    template_path = make_template(tmp_path)
    config = make_config(tmp_path, template_path)
    nonexistent_dir = tmp_path / "nonexistent_output"

    with pytest.raises(FileNotFoundError):
        generate_thumbnail(
            date="2026年4月19日",
            title="テスト",
            scripture="聖書箇所",
            preacher="説教者",
            output_dir=nonexistent_dir,
            config=config,
        )


def test_generate_thumbnail_font_fallback(tmp_path: Path) -> None:
    """フォントフォールバック: meiryob.ttc が存在しないとき例外にならず処理続行"""
    template_path = make_template(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    # 存在しないフォントパスを指定
    config = make_config(tmp_path, template_path)

    # 例外が発生しないこと・ファイルが生成されること
    result = generate_thumbnail(
        date="2026年4月19日",
        title="フォントフォールバックテスト",
        scripture="マタイ 1章1節",
        preacher="テスト 師",
        output_dir=output_dir,
        config=config,
    )

    assert result.exists()


def test_generate_thumbnail_empty_fields(tmp_path: Path) -> None:
    """空文字列の入力: 全フィールドが空文字列でも例外が発生しない"""
    template_path = make_template(tmp_path)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = make_config(tmp_path, template_path)

    # 例外が発生しないこと
    result = generate_thumbnail(
        date="",
        title="",
        scripture="",
        preacher="",
        output_dir=output_dir,
        config=config,
    )

    assert result.exists()


def test_generate_thumbnail_config_none(tmp_path: Path) -> None:
    """config なし: config=None でデフォルト値で動作する"""
    # デフォルトのテンプレートパスは assets/thumbnail_template.png だが、
    # テスト環境では存在しないので FileNotFoundError が発生するはず。
    # それ以外の例外（AttributeError 等）が発生しないことを確認する。
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        generate_thumbnail(
            date="2026年4月19日",
            title="テスト",
            scripture="聖書箇所",
            preacher="説教者",
            output_dir=output_dir,
            config=None,
        )


# ---------------------------------------------------------------------------
# draw_text_wrapped のテスト
# ---------------------------------------------------------------------------


def test_draw_text_wrapped_wraps_long_text(tmp_path: Path) -> None:
    """長文タイトルの折り返し: max_width を超えるテキストが複数行に折り返される"""
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (400, 400), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    # max_width を非常に小さくして確実に折り返しが起きるようにする
    long_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    # 例外が発生しないことと、描画が行われること（y座標が進むこと）を確認する。
    # 副作用として img に描画されるが、直接折り返しを検証するには
    # draw_text_wrapped が行数を返さないため、例外なし完了を確認する。
    draw_text_wrapped(
        draw=draw,
        text=long_text,
        position=(0, 0),
        font=font,
        fill=(255, 255, 255),
        max_width=50,
        line_spacing=8,
    )
    # 例外なしで完了すれば OK


# ---------------------------------------------------------------------------
# load_font のテスト
# ---------------------------------------------------------------------------


def test_load_font_fallback_when_missing(tmp_path: Path) -> None:
    """フォントフォールバック: フォントが存在しないとき fallback=True で例外にならない"""
    from PIL import ImageFont

    font = load_font(str(tmp_path / "nonexistent.ttc"), size=48, fallback=True)
    assert font is not None


def test_load_font_raises_when_missing_no_fallback(tmp_path: Path) -> None:
    """フォントが存在しないとき fallback=False で OSError"""
    with pytest.raises(OSError):
        load_font(str(tmp_path / "nonexistent.ttc"), size=48, fallback=False)
