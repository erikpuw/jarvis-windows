"""Thân bài báo cho Reader Card và search_news (ngài 2026-10-19): chỉ lấy bài, bỏ menu/player/tin liên quan/footer."""
from scrapling.parser import Selector

from engine.tools.browser import JarvisScraplingBrowser as B

BODY = ("Tập đoàn bán dẫn Nvidia đang mở rộng mạnh mẽ sang thị trường máy tính cá nhân với dòng chip mới RTX Spark, "
        "trong bối cảnh doanh nghiệp này tìm cách mở rộng cơ sở khách hàng.")
PAGE = f"""<html><head><title>Nvidia ra mắt RTX Spark</title></head><body>
<header><nav><a href="/">Trang chủ</a><a href="/short">Short TINg</a><a href="/radio">Radio TINg</a></nav></header>
<div class="player"><span>Giọng AI Trần Nghĩa</span><span>00:00</span><span>00:00</span></div>
<article><h1>Nvidia ra mắt máy tính xách tay với dòng chip mới RTX Spark</h1>
<p>{BODY}</p>
<p>Theo Nvidia, các máy có thể chạy ứng dụng AI, chỉnh sửa hình ảnh, dựng video và trò chơi điện tử ngay trên thiết bị
mà không cần kết nối Internet. Điều này mở ra khả năng xử lý AI cục bộ, đặc biệt phù hợp với doanh nghiệp nhỏ.</p>
<p>RTX Spark kết hợp ba thành phần chính gồm bộ xử lý trung tâm với 20 đơn vị tính toán, bộ xử lý đồ họa phục vụ
hình ảnh và AI, cùng bộ nhớ dùng chung dung lượng lên tới 128 GB.</p></article>
<aside><h3>Tin trước</h3><ul><li><a href="/a">Anthropic bồi thường 1,5 tỷ USD vì vi phạm bản quyền</a></li></ul></aside>
<footer><p>© 2018. Công ty Cổ phần. Email: lienhe@example.com</p><p>Tải app</p><p>Google Play</p></footer>
</body></html>"""


def test_article_body_keeps_story_drops_page_chrome():
    text = B._extract_article_body(Selector(PAGE))
    assert BODY in text and "128 GB" in text
    for noise in ("00:00", "Short TINg", "Tin trước", "Anthropic bồi thường", "Google Play", "©"):
        assert noise not in text


def test_article_body_empty_when_no_story():
    assert B._extract_article_body(Selector("<html><body><nav>Trang chủ</nav></body></html>")) == ""
