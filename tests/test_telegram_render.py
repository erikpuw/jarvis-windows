"""Telegram replies go out with parse_mode HTML: only <, >, & need escaping, so a stray '.', '-' or '!' can no longer
make Telegram reject the message (MarkdownV2 needed 18 escaped characters and fell back to raw '**' text)."""

from engine.server.telegram_bot import render_telegram_html


def test_plain_punctuation_is_untouched():
    assert render_telegram_html("Giá 61.900đ - tăng 5% (hôm nay)!") == "Giá 61.900đ - tăng 5% (hôm nay)!"


def test_html_characters_are_escaped():
    assert render_telegram_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_inline_formatting():
    assert render_telegram_html("**đậm** và *nghiêng* và `x<y`") == "<b>đậm</b> và <i>nghiêng</i> và <code>x&lt;y</code>"


def test_heading_and_fenced_code():
    out = render_telegram_html("## Tiêu đề\n```python\nif a < b:\n    pass\n```")
    assert out == "<b>Tiêu đề</b>\n<pre>if a &lt; b:\n    pass\n</pre>"


def test_links_and_raw_urls():
    assert render_telegram_html("[Báo](https://x.vn/a?b=1&c=2)") == '<a href="https://x.vn/a?b=1&amp;c=2">Báo</a>'
    assert render_telegram_html("xem https://www.example.com/p.") == 'xem <a href="https://www.example.com/p">example.com</a>.'


def test_nested_bold_link_is_restored():
    assert render_telegram_html("**[Báo](https://x.vn)**") == '<b><a href="https://x.vn">Báo</a></b>'


def test_image_becomes_alt_text_and_table_becomes_lines():
    assert render_telegram_html("![Poster](https://i.vn/p.jpg)") == "Poster"
    table = "| Tên | Giá |\n|---|---|\n| A | 1 |\n"
    assert render_telegram_html(table).strip() == "Tên: A\nGiá: 1"
