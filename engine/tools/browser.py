"""
JARVIS Scrapling Browser — High-performance web browsing via Scrapling.

Replaces Playwright-based JarvisBrowser with Scrapling Fetchers:
- AsyncFetcher: HTTP/2 requests with TLS fingerprint spoofing (fast, no browser)
- StealthyFetcher: Full browser automation with Cloudflare Turnstile bypass

Same interface as browser.py — drop-in replacement.
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, parse_qs, unquote, quote

from scrapling.fetchers import AsyncFetcher, StealthyFetcher

log = logging.getLogger("jarvis.browser")

TIMEOUT_MS = 30_000

# Chromium-based browsers to prefer over patchright's own bundled
# "Chrome for Testing" build for StealthyFetcher. On this machine that
# bundled build fails to launch (Windows SideBySide/Fusion activation
# error, Event ID 33 — its embedded manifest can't resolve as a private
# assembly), while an already-installed system browser launches fine.
_SYSTEM_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def stealth_executable_path() -> str | None:
    """Return a system-installed Chromium browser path for StealthyFetcher, if any."""
    for path in _SYSTEM_BROWSER_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def stealth_fetch_kwargs() -> dict:
    """Extra kwargs to merge into StealthyFetcher.fetch() calls."""
    exe = stealth_executable_path()
    return {"executable_path": exe} if exe else {}

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    # Real publisher host, when known separately from `url` (e.g. Google News
    # RSS wraps every link behind news.google.com — the true source domain
    # comes from the feed's <source url="..."> instead).
    source_host: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class PageContent:
    title: str
    url: str
    text_content: str
    word_count: int
    image_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class ResearchResult:
    topic: str
    sources: list[str]
    summary: str
    key_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

class JarvisScraplingBrowser:
    """Scrapling-based web browsing for JARVIS.

    Tiered fetching:
      1. AsyncFetcher (HTTP, no browser) — fast, stealthy headers
      2. StealthyFetcher (browser, stealth) — Cloudflare bypass fallback
    """

    def __init__(self):
        self._stealth = None  # Lazy-initialised StealthyFetcher ref
        self._timed_out_urls: set[str] = set()  # URLs đã timeout — không gọi lại

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """Phát hiện lỗi timeout từ nhiều nguồn khác nhau.

        - asyncio.TimeoutError / TimeoutError (builtin)
        - curl_cffi Timeout, ConnectTimeout, ReadTimeout
        """
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True
        return exc.__class__.__name__ in ("Timeout", "ConnectTimeout", "ReadTimeout")

    # ------------------------------------------------------------------
    # DDG URL resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_ddg_url(raw_url: str) -> str:
        """Extract real URL from DuckDuckGo redirect link."""
        if "duckduckgo.com/y.js" in raw_url:
            return ""
        if "duckduckgo.com/l/" in raw_url:
            qs = parse_qs(urlparse(raw_url).query)
            if "uddg" in qs:
                return unquote(qs["uddg"][0])
        return raw_url

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        locale: str | None = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search DuckDuckGo and return top results (HTTP, no browser)."""
        max(10, min(max_results, 30))
        url = f"https://html.duckduckgo.com/html/?q={quote(query)}"
        if locale:
            url += f"&kl={quote(locale)}"

        page = await self._fetch_search_page(url)
        if page is None:
            log.warning("DDG search failed for '%s': no page fetched", query)
            return []

        results: list[SearchResult] = []
        for item in page.css(".result"):
            if len(results) >= max_results:
                break

            classes = (item.css("::attr(class)").get() or "")
            if "result--ad" in classes:
                continue

            title_el = item.css(".result__title a, .result__a")
            title = title_el.css("::text").get()
            link = title_el.css("::attr(href)").get()
            snippet = item.css(".result__snippet::text").get()

            if not title or not link:
                continue

            real_url = self._resolve_ddg_url(link)
            if not real_url:
                continue

            results.append(SearchResult(
                title=title.strip(),
                url=real_url,
                snippet=(snippet or "").strip(),
            ))

        log.info("Search '%s' returned %d results", query, len(results))
        return results

    # ------------------------------------------------------------------
    # Visit URL
    # ------------------------------------------------------------------

    _CF_CHALLENGE_RE = re.compile(
        r"(?:checking.+browser|cf-browser-verification|"
        r"challenge-platform|turnstile|just a moment|"
        r"ddos protection|attention required)",
        re.IGNORECASE,
    )

    _MAINTENANCE_RE = re.compile(
        r"(?:website đang được bảo trì|website đang bảo trì|đang được tân trang một chút|"
        r"cam kết sẽ sớm quay trở lại|chúng tôi sẽ sớm quay trở lại|maintenance mode|"
        r"under maintenance|site under construction|scheduled maintenance|"
        r"website is under maintenance|xin lỗi vì sự bất tiện này)",
        re.IGNORECASE,
    )

    # DDG/Google serve these instead of real results when the plain HTTP
    # fetcher gets flagged as a bot (no cookies/JS = easy to fingerprint).
    _SEARCH_BOT_CHALLENGE_RE = re.compile(
        r"(?:select all squares|complete the following challenge|"
        r"unusual traffic|our systems have detected|recaptcha|"
        r"verify you are human|prove you're not a robot|/sorry/)",
        re.IGNORECASE,
    )

    async def _fetch_search_page(self, url: str):
        """Fetch a search-results URL, escalating to StealthyFetcher when the
        plain AsyncFetcher tier gets a bot-challenge page instead of results.

        Same tiering as _fetch(), but search() and _search_google() previously
        called AsyncFetcher.get() directly with no blocked-page detection, so a
        DDG/Google CAPTCHA response was silently parsed as "0 results" with no
        recovery.
        """
        page = None
        try:
            page = await AsyncFetcher.get(url, stealthy_headers=True, timeout=TIMEOUT_MS)
        except Exception as e:
            log.debug("AsyncFetcher failed for search %s: %s — trying StealthyFetcher", url, e)

        text = (page.get_all_text() or "") if page else ""
        blocked = (
            page is None
            or (page.status and page.status >= 400)
            or len(text) < 500
            or bool(self._CF_CHALLENGE_RE.search(text[:2000]))
            or bool(self._SEARCH_BOT_CHALLENGE_RE.search(text[:2000]))
        )
        if not blocked:
            return page

        log.info("Search fetch blocked (bot challenge) for %s, escalating to StealthyFetcher", url)
        try:
            page = await asyncio.wait_for(
                asyncio.to_thread(
                    StealthyFetcher.fetch,
                    url,
                    headless=True,
                    solve_cloudflare=True,
                    timeout=TIMEOUT_MS,
                    **stealth_fetch_kwargs(),
                ),
                timeout=TIMEOUT_MS / 1000,
            )
            return page
        except Exception as e:
            log.warning("StealthyFetcher also failed for search %s: %s", url, e)
            return page  # fall back to whatever AsyncFetcher got, if anything

    async def _fetch(self, url: str, timeout_ms: int = TIMEOUT_MS) -> tuple:
        """Fetch URL with tiered approach. Returns (Response, used_stealth).

        URL nào đã từng bị timeout sẽ bị bỏ qua hoàn toàn: không fallback
        sang StealthyFetcher, không retry — trang đó không được gọi lại nữa.

        timeout_ms: budget for EACH tier (not the total). Callers with many
        backup candidates (vd. news search với nhiều bài RSS dự phòng) nên
        truyền giá trị nhỏ hơn mặc định để bỏ qua nhanh nguồn bị chặn/chậm.
        """
        if url in self._timed_out_urls:
            log.info("Skipping previously timed-out URL: %s", url)
            raise TimeoutError(f"Skip previously timed-out URL: {url}")

        # Tier 1: AsyncFetcher (HTTP, fast)
        page = None
        try:
            page = await AsyncFetcher.get(url, stealthy_headers=True, timeout=timeout_ms)
            if page:
                text = page.get_all_text() or ""
                # Kiểm tra xem có dấu hiệu trang đang bảo trì hay không
                if self._MAINTENANCE_RE.search(text[:2000]):
                    raise RuntimeError("Website is under maintenance")

                is_blocked = (
                    (page.status and page.status >= 400)
                    or len(text) < 500
                    or bool(self._CF_CHALLENGE_RE.search(text[:2000]))
                )
                if not is_blocked:
                    return page, False
                log.debug("AsyncFetcher got blocked/empty for %s (status=%s, len=%d)",
                          url, page.status, len(text))
        except RuntimeError as re_err:
            if "maintenance" in str(re_err):
                raise re_err
        except Exception as e:
            if self._is_timeout_error(e):
                # Timeout: đánh dấu URL và dừng — không gọi lại trang này nữa
                self._timed_out_urls.add(url)
                log.warning("AsyncFetcher timed out for %s — skipping page", url)
                raise TimeoutError(f"AsyncFetcher timed out for {url}") from e
            log.debug("AsyncFetcher failed for %s: %s — trying StealthyFetcher", url, e)

        # Tier 2: StealthyFetcher (browser, bypasses Cloudflare)
        try:
            log.info("StealthyFetcher fetching %s", url)
            page = await asyncio.wait_for(
                asyncio.to_thread(
                    StealthyFetcher.fetch,
                    url,
                    headless=True,
                    solve_cloudflare=True,
                    timeout=timeout_ms,
                    **stealth_fetch_kwargs(),
                ),
                timeout=timeout_ms / 1000,
            )
            if page:
                text = page.get_all_text() or ""
                if self._MAINTENANCE_RE.search(text[:2000]):
                    raise RuntimeError("Website is under maintenance")
                return page, True
        except RuntimeError as re_err:
            if "maintenance" in str(re_err):
                raise re_err
        except (asyncio.TimeoutError, TimeoutError) as te:
            self._timed_out_urls.add(url)
            log.warning("StealthyFetcher timed out for %s — skipping page", url)
            raise TimeoutError(f"StealthyFetcher timed out for {url}") from te
        except Exception as e:
            log.warning("StealthyFetcher also failed for %s: %s", url, e)

        if page:
            return page, False
        raise RuntimeError(f"All fetchers failed for {url}")

    @staticmethod
    def _extract_image_url(page) -> str | None:
        """Extract a suitable product/lead image URL from page content, skipping logo/banner noise."""
        try:
            # Danh sách các từ khóa rác chỉ logo/banner quảng cáo của shop
            noise_keywords = [
                "logo", "share_fb", "banner", "header", "footer", "avatar", "icon", 
                "placeholder", "facebook", "default", "bg", "background"
            ]
            
            # 1. Thử lấy từ OpenGraph image
            og_img = page.css('meta[property="og:image"]::attr(content)').get()
            if og_img:
                og_img = og_img.strip()
                if not any(noise in og_img.lower() for noise in noise_keywords):
                    return og_img
                    
            # 2. Thử lấy từ twitter image
            twitter_img = page.css('meta[name="twitter:image"]::attr(content)').get()
            if twitter_img:
                twitter_img = twitter_img.strip()
                if not any(noise in twitter_img.lower() for noise in noise_keywords):
                    return twitter_img
                    
            # 3. Quét các thẻ img nổi bật hoặc thuộc các class/id sản phẩm
            img_selectors = [
                # Selector chuyên biệt cho các shop VN
                "img[src*='product.hstatic']::attr(src)",   # GEARVN
                "img[src*='hstatic.net']::attr(src)",        # GEARVN/Haravan
                "img[src*='media/catalog/product']::attr(src)",  # Magento (CellPhones, PhongVu)
                "img[src*='cdn2.cellphones']::attr(src)",    # CellPhones CDN
                # Selector chung
                ".product-image img::attr(src)",
                ".product-img img::attr(src)",
                ".ProductItem img::attr(src)",
                ".ProductCard img::attr(src)",
                ".detail-image img::attr(src)",
                ".main-image img::attr(src)",
                "img[src*='product']::attr(src)",
                "img[src*='uploads/products']::attr(src)",
                "img[class*='product']::attr(src)",
                "img[id*='product']::attr(src)",
                "img[loading='lazy']::attr(src)",
                "img[alt*='RAM']::attr(src)",
                "img[alt*='ram']::attr(src)",
                "img[alt*='Ram']::attr(src)",
                "article img::attr(src)",
                "main img::attr(src)",
                "img::attr(src)"
            ]
            for sel in img_selectors:
                img_srcs = page.css(sel).getall()
                for src in img_srcs:
                    if not src:
                        continue
                    src = src.strip()
                    if src.startswith("http") or src.startswith("//") or src.startswith("/"):
                        if src.startswith("//"):
                            src = "https:" + src
                        # Chỉ lấy ảnh không chứa từ khóa rác
                        if not any(noise in src.lower() for noise in noise_keywords):
                            return src
        except Exception:
            pass
        return None

    async def visit(self, url: str) -> PageContent | None:
        """Visit a URL and extract main text content. Returns None on failure."""
        try:
            page, _ = await self._fetch(url)
            title = (page.css("title::text").get() or "").strip()
            text = self._extract_main_text(page)
            image_url = self._extract_image_url(page)

            return PageContent(
                title=title,
                url=url,
                text_content=text[:5000],
                word_count=len(text.split()) if text else 0,
                image_url=image_url,
            )
        except Exception as e:
            log.warning("Visit failed for '%s': %s", url, e)
            return None

    @staticmethod
    def _extract_main_text(page) -> str:
        """Extract primary content, skipping nav/header/footer noise."""
        for sel in ("article", "main", '[role="main"]', ".post-content", ".entry-content", ".article-body", ".detail-content"):
            el = page.css(sel)
            if el.length:
                candidate = " ".join(el.css("::text").getall()) or ""
                if len(candidate) > 500:
                    return candidate
        return page.get_all_text() or ""

    # ------------------------------------------------------------------
    # Visit Article (news-specific extraction)
    # ------------------------------------------------------------------

    async def visit_article(self, url: str, timeout_ms: int = TIMEOUT_MS) -> PageContent | None:
        """Visit a news page — prioritise article body, strip noise. Returns None on failure.

        timeout_ms: passed through to _fetch(); pass a smaller value (news
        search has several backup candidates) to fail fast on a blocked/slow
        source and move on to the next one instead of waiting the full 30s.
        """
        try:
            page, used_stealth = await self._fetch(url, timeout_ms=timeout_ms)
            title = (page.css("title::text").get() or "").strip()

            article_selectors = [
                "article .article-content",
                "article .detail-content",
                "article .content-detail",
                "article .entry-content",
                "article .post-content",
                ".article-body",
                ".detail-content",
                ".content-detail",
                ".entry-content",
                ".post-content",
                "article",
                "main article",
                '[role="main"]',
                "main",
            ]

            text = ""
            for sel in article_selectors:
                el = page.css(sel)
                if el.length:
                    candidate = " ".join(el.css("::text").getall()) or ""
                    if len(candidate) > 200:
                        text = candidate
                        break

            if not text:
                text = self._extract_main_text(page)
                
            image_url = self._extract_image_url(page)

            return PageContent(
                title=title,
                url=url,
                text_content=text[:5000],
                word_count=len(text.split()) if text else 0,
                image_url=image_url,
            )
        except Exception as e:
            if "maintenance" in str(e).lower():
                raise e
            log.warning("Article visit failed for '%s': %s", url, e)
            if self._is_timeout_error(e):
                # Timeout: không fallback về visit() (sẽ gọi lại cùng trang)
                return None
            return await self.visit(url)

    # ------------------------------------------------------------------
    # CSS-based price extraction (chính xác hơn full-text regex)
    # ------------------------------------------------------------------

    # CSS selectors để lấy giá từ product listing - ưu tiên từ trên xuống
    _PRICE_CSS_SELECTORS = [
        "span[class*='price']",          # GEARVN, Haravan generic
        ".ProductItem__Price",           # Haravan themes
        ".price--highlight",             # Shopify themes
        "p[class*='price']",             # CellPhones Magento
        ".product-price",                # Generic
        ".price",                        # Generic fallback
        ".woocommerce-Price-amount",     # WooCommerce
        "[data-price]",                  # Data attribute
    ]

    @staticmethod
    def _extract_css_price_range(page) -> str | None:
        """Trích xuất khoảng giá sản phẩm từ CSS selector — tránh nhiễu từ menu/nav.
        
        Trả về chuỗi khoảng giá e.g. '3.990.000₫ - 39.990.000₫' hoặc None nếu không tìm được.
        """
        import re
        price_pat = re.compile(
            r"\b\d{1,3}(?:[.,]\d{3})+\s*(?:₫|đ|vnđ|vnd)|"
            r"\b\d+(?:[.,]\d+)?\s*(?:triệu|trieu|tỷ|ty)\b",
            re.IGNORECASE,
        )

        prices_raw: list[str] = []
        for sel in JarvisScraplingBrowser._PRICE_CSS_SELECTORS:
            els = page.css(sel)
            if not els or not els.length:
                continue
            for el in els:
                text = " ".join(el.css("::text").getall() or []).strip()
                matches = price_pat.findall(text)
                for m in matches:
                    m = m.strip()
                    if m:
                        prices_raw.append(m)
            if prices_raw:
                break  # Dùng selector đầu tiên có kết quả

        if not prices_raw:
            return None

        # Chuyển sang số để tìm min/max
        def to_vnd(s: str) -> float:
            s = s.lower().replace("₫", "").replace("đ", "").replace("vnđ", "").replace("vnd", "").strip()
            s = s.replace(".", "").replace(",", "")
            multiplier = 1
            if "triệu" in s or "trieu" in s:
                s = re.sub(r"tri[eệ]u", "", s).strip()
                multiplier = 1_000_000
            elif "tỷ" in s or "ty" in s:
                s = re.sub(r"t[yỷ]", "", s).strip()
                multiplier = 1_000_000_000
            try:
                return float(s.replace(" ", "")) * multiplier
            except ValueError:
                return 0.0

        num_prices = [(to_vnd(p), p) for p in prices_raw if to_vnd(p) > 10_000]
        if not num_prices:
            return None

        num_prices.sort(key=lambda x: x[0])
        min_p = num_prices[0][1]
        max_p = num_prices[-1][1]
        return min_p if min_p == max_p else f"{min_p} - {max_p}"

    async def visit_product_listing(self, url: str) -> PageContent:
        """Cào trang listing sản phẩm dùng StealthyFetcher để đảm bảo JS render đầy đủ.

        Các trang thương mại điện tử như GEARVN, Shopee, Lazada render sản phẩm
        bằng JavaScript, AsyncFetcher chỉ lấy được HTML shell rỗng. Method này
        luôn dùng StealthyFetcher (headless browser) và fallback về visit() nếu lỗi.
        Ngoài ra, giá được trích xuất qua CSS selector (chính xác hơn full-text regex)
        và nhúng vào đầu text_content dưới dạng "CSS_PRICES:<range>".
        """
        try:
            if url in self._timed_out_urls:
                log.info("Skipping previously timed-out listing URL: %s", url)
                return PageContent(
                    title="Error",
                    url=url,
                    text_content="Failed to load page: previously timed out",
                    word_count=0,
                )

            log.info("visit_product_listing (StealthyFetcher): %s", url)
            page = await asyncio.wait_for(
                asyncio.to_thread(
                    StealthyFetcher.fetch,
                    url,
                    headless=True,
                    solve_cloudflare=True,
                    timeout=TIMEOUT_MS,
                    **stealth_fetch_kwargs(),
                ),
                timeout=TIMEOUT_MS / 1000,
            )
            if not page:
                raise RuntimeError("StealthyFetcher returned empty page")

            text = page.get_all_text() or ""
            if self._MAINTENANCE_RE.search(text[:2000]):
                raise RuntimeError("Website is under maintenance")

            title = (page.css("title::text").get() or "").strip()
            image_url = self._extract_image_url(page)

            # Trích xuất giá qua CSS selector — chính xác, không bị nhiễu menu
            css_price_range = self._extract_css_price_range(page)
            # Nhúng vào đầu text_content với prefix đặc biệt để caller parse
            price_prefix = f"CSS_PRICES:{css_price_range}\n" if css_price_range else ""

            return PageContent(
                title=title,
                url=url,
                text_content=price_prefix + text[:8000],
                word_count=len(text.split()) if text else 0,
                image_url=image_url,
            )
        except (asyncio.TimeoutError, TimeoutError) as te:
            # Timeout: đánh dấu URL và dừng — không fallback về visit()
            self._timed_out_urls.add(url)
            log.warning("visit_product_listing timed out for '%s' — skipping page", url)
            return PageContent(
                title="Error",
                url=url,
                text_content=f"Failed to load page: {te}",
                word_count=0,
            )
        except Exception as e:
            log.warning("visit_product_listing failed for '%s': %s — falling back to visit()", url, e)
            return await self.visit(url)

    async def fetch_listing_html(self, url: str) -> str:
        """HTML đã render (StealthyFetcher) của trang liệt kê sản phẩm, để engine/tools/shop_sources đọc đúng
        chỗ chứa dữ liệu. Text thô của trang không dùng được: menu/popup chiếm hết phần đầu, phụ kiện lẫn vào."""
        page = await asyncio.wait_for(
            asyncio.to_thread(
                StealthyFetcher.fetch,
                url,
                headless=True,
                solve_cloudflare=True,
                timeout=TIMEOUT_MS,
                **stealth_fetch_kwargs(),
            ),
            timeout=TIMEOUT_MS / 1000,
        )
        return str(page.html_content) if page else ""

    async def post_json(self, url: str, body: dict, headers: dict | None = None) -> dict:
        """POST JSON tới API công khai của chính trang (không cần trình duyệt), trả về JSON đã parse."""
        page = await AsyncFetcher.post(url, json=body, stealthy_headers=True, headers=headers or {}, timeout=TIMEOUT_MS)
        return json.loads(page.body)

    # ------------------------------------------------------------------
    # Visit & Evaluate (custom JS — adapted for Scrapling parser)
    # ------------------------------------------------------------------

    async def visit_and_evaluate(self, url: str, script: str = "") -> str:
        """Visit URL and return full page text.

        Note: The `script` parameter is kept for backward compatibility with
        search_engine.py's JS snippets. Scrapling's parser extracts the full
        text directly — no JS evaluation needed. The same regex-based parsing
        in search_engine.py continues to work unchanged.
        For Cloudflare-protected sites, StealthyFetcher is used automatically.
        """
        if not url.startswith("http"):
            url = "https://" + url
        try:
            page, _ = await self._fetch(url)
            text = page.get_all_text() or ""
            return text
        except Exception as e:
            log.warning("visit_and_evaluate failed for %s: %s", url, e)
            return ""

    # ------------------------------------------------------------------
    # News search (Google News RSS, falling back to web-SERP scrape)
    # ------------------------------------------------------------------

    async def _search_google_news_rss(
        self, query: str, *, vietnam_only: bool = True, max_results: int = 10
    ) -> list[SearchResult]:
        """Search Google News' RSS feed.

        Far more stable than scraping Google's web SERP for news-shaped
        queries: the web SERP increasingly replaces organic results with an
        "AI Mode" answer panel or a News/Top-Stories carousel whose links are
        opaque tracking tokens with no real URL in the static HTML — neither
        is parseable by CSS selectors. The RSS feed is plain structured XML,
        isn't subject to that, and wasn't bot-challenged in testing.
        """
        hl, gl, ceid = ("vi", "VN", "VN:vi") if vietnam_only else ("en", "US", "US:en")
        url = f"https://news.google.com/rss/search?q={quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"

        page = await self._fetch_search_page(url)
        if page is None:
            return []

        results: list[SearchResult] = []
        for item in page.css("item"):
            if len(results) >= max_results:
                break
            title = (item.css("title::text").get() or "").strip()
            # The <link> element is dropped by the HTML parser (void element
            # in HTML5), so pull the same URL back out of <description>'s
            # embedded <a href="...">.
            desc_html = item.css("description::text").get() or ""
            m = re.search(r'href="([^"]+)"', desc_html)
            link = m.group(1) if m else None
            if not title or not link:
                continue
            source_url = item.css("source::attr(url)").get() or ""
            source_host = urlparse(source_url).netloc.lower().lstrip("www.") if source_url else ""
            # RSS <description> has no real article summary (just title+source
            # re-wrapped in HTML) — leave snippet empty rather than duplicate it.
            results.append(SearchResult(
                title=title, url=link, snippet="", source_host=source_host,
            ))

        log.info("Google News RSS returned %d results for '%s'", len(results), query)
        return results

    async def search_news(
        self, query: str, *, vietnam_only: bool = True
    ) -> list[SearchResult]:
        """Search for news: Google News RSS first, DDG/Google web-SERP scrape as fallback."""
        results = await self._search_google_news_rss(query, vietnam_only=vietnam_only)
        if results:
            return results
        log.info("Google News RSS returned empty, falling back to web search_all...")
        return await self.search_all(query, vietnam_only=vietnam_only)

    # ------------------------------------------------------------------
    # Search All (DDG + Google fallback)
    # ------------------------------------------------------------------

    async def search_all(
        self, query: str, *, vietnam_only: bool = False
    ) -> list[SearchResult]:
        """Search with fallback: DDG -> Google. vietnam_only adds VN locale."""
        locale = "vn-vn" if vietnam_only else None
        max_results = 25 if vietnam_only else 10
        results = await self.search(query, locale=locale, max_results=max_results)
        if results:
            return results
        log.info("DDG search returned empty, trying Google via Scrapling...")
        return await self._search_google(query, vietnam_only=vietnam_only)

    async def _search_google(
        self, query: str, *, vietnam_only: bool = False
    ) -> list[SearchResult]:
        """Search Google using Scrapling AsyncFetcher."""
        q = quote(query, safe="")
        url = f"https://www.google.com/search?q={q}&hl=vi"
        if vietnam_only:
            url += "&gl=vn&cr=countryVN"

        block_limit = 18 if vietnam_only else 8
        result_cap = 25 if vietnam_only else 5

        page = await self._fetch_search_page(url)
        if page is None:
            log.warning("Google search failed for '%s': no page fetched", query)
            return []

        results: list[SearchResult] = []
        blocks = page.css("div.g, div.MjjYud")
        seen: set[str] = set()

        for block in blocks[:block_limit]:
            if len(results) >= result_cap:
                break

            a = block.css('a[href^="http"]')
            href = a.css("::attr(href)").get()
            if not href or href in seen:
                continue

            title = (block.css("h3::text").get() or "").strip()
            snippet_list = block.css("div.VwiC3b::text, span.aCOpRe::text").getall()
            snippet = " ".join(snippet_list).strip()

            if title and href:
                seen.add(href)
                results.append(SearchResult(title=title, url=href, snippet=snippet))

        log.info("Google search returned %d results", len(results))
        return results

    # ------------------------------------------------------------------
    # Research (multi-step)
    # ------------------------------------------------------------------

    async def research(self, topic: str) -> ResearchResult:
        """Multi-step research: search -> visit top results -> compile findings."""
        results = await self.search(topic)
        sources: list[str] = []
        contents: list[str] = []

        for r in results[:3]:
            try:
                page_content = await self.visit(r.url)
                if page_content is None:
                    continue
                sources.append(r.url)
                contents.append(
                    f"## {r.title}\nURL: {r.url}\n\n{page_content.text_content[:1500]}"
                )
            except Exception:
                continue

        summary = "\n\n---\n\n".join(contents) if contents else "No results found."
        return ResearchResult(
            topic=topic,
            sources=sources,
            summary=summary,
            key_findings=[r.title for r in results[:3]],
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        """No persistent browser to shut down — Fetcher is stateless."""
        log.info("JarvisScraplingBrowser closed (no resources to free)")

# Global browser instance (drop-in replacement)
browser = JarvisScraplingBrowser()
