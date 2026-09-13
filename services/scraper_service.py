"""Web scraper service — Crawl4AI primary, httpx+BS4 fallback.

Crawl4AI gives us clean Markdown for AI analysis even on JS-heavy sites.
When it can't be imported or fails, we fall back to httpx+BeautifulSoup.
"""

import logging
import os
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Proxy support for China users ──
_HTTP_PROXY = os.getenv("HTTPS_PROXY", "") or os.getenv("HTTP_PROXY", "")

# ── Crawl4AI lazy import ──
_crawl4ai_available = False
_AsyncWebCrawler = None
_BrowserConfig = None
_CrawlerRunConfig = None
_CacheMode = None


def _check_crawl4ai():
    """Lazy-load Crawl4AI. Returns True if available."""
    global _crawl4ai_available, _AsyncWebCrawler, _BrowserConfig, _CrawlerRunConfig, _CacheMode
    if _AsyncWebCrawler is not None:
        return _crawl4ai_available
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        _AsyncWebCrawler = AsyncWebCrawler
        _BrowserConfig = BrowserConfig
        _CrawlerRunConfig = CrawlerRunConfig
        _CacheMode = CacheMode
        _crawl4ai_available = True
        logger.info("Crawl4AI loaded successfully")
        return True
    except ImportError:
        logger.info("Crawl4AI not installed — using httpx fallback")
        _crawl4ai_available = False
        return False


class ScrapeError(Exception):
    """Raised when scraping fails with a user-friendly message."""
    pass


_SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}

# Tags to strip entirely (navigation, scripts, etc.)
_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "iframe", "svg"]

# Class/id patterns that indicate non-content elements
_SKIP_PATTERNS = re.compile(
    r"(nav|menu|footer|header|sidebar|cookie|banner|popup|modal|advert|social|share)",
    re.IGNORECASE,
)


async def scrape_website(url: str) -> str:
    """
    Scrape a website and return clean text content (max 5000 chars).

    Uses Crawl4AI (headless browser) when available, falls back to httpx.
    Returns: title + description + headings + body paragraphs.
    Raises ScrapeError with a user-friendly Chinese message on failure.
    """
    if not url:
        raise ScrapeError("No website URL (website field is empty)")

    # Normalize URL
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    logger.info("Scraping: %s", url)

    # Try Crawl4AI first (gives clean Markdown)
    if _check_crawl4ai():
        try:
            content = await _scrape_with_crawl4ai(url)
            if content:
                return _truncate(content, url)
        except Exception as exc:
            logger.warning("Crawl4AI failed for %s: %s, falling back to httpx", url, exc)

    # Fallback to httpx + BeautifulSoup
    return await _scrape_with_httpx(url)


async def _scrape_with_crawl4ai(url: str) -> str | None:
    """Scrape with Crawl4AI headless browser. Returns markdown or None."""
    browser_config = _BrowserConfig(
        headless=True,
        verbose=False,
    )

    # Proxy support
    if _HTTP_PROXY:
        proxy_url = _HTTP_PROXY
        proxy_parts = {}
        # Parse proxy URL for Crawl4AI format
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        proxy_parts["server"] = proxy_url
        if parsed.username:
            proxy_parts["username"] = parsed.username
        if parsed.password:
            proxy_parts["password"] = parsed.password
        browser_config.proxy_config = proxy_parts
        logger.debug("Crawl4AI using proxy: %s", proxy_url)

    run_config = _CrawlerRunConfig(
        word_count_threshold=5,
        remove_overlay_elements=True,
        exclude_external_links=True,
        cache_mode=_CacheMode.BYPASS,
    )

    async with _AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

        if not result or not result.success:
            logger.warning("Crawl4AI returned unsuccessful result for %s", url)
            return None

        # Prefer markdown, fall back to HTML cleaning
        md = result.markdown
        if isinstance(md, str):
            content = md
        elif hasattr(md, "fit_markdown") and md.fit_markdown:
            content = md.fit_markdown
        elif hasattr(md, "raw_markdown") and md.raw_markdown:
            content = md.raw_markdown
        else:
            content = result.cleaned_html or result.html or ""

        if not content:
            return None

        # Prepend title/description from HTML (Crawl4AI markdown may omit them)
        title_prefix = _extract_title_desc(result.html or "", url)
        if title_prefix and title_prefix not in content:
            content = title_prefix + "\n\n" + content

        logger.info("Crawl4AI scraped %d chars from %s", len(content), url)
        return content


async def _scrape_with_httpx(url: str) -> str:
    """Fallback: scrape with httpx + BeautifulSoup."""
    # Build proxy config if set
    proxy_config = None
    if _HTTP_PROXY:
        proxy_config = _HTTP_PROXY
        logger.debug("Using proxy: %s", _HTTP_PROXY)

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers=_SCRAPER_HEADERS,
            proxy=proxy_config,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
    except httpx.TimeoutException:
        msg = f"连接超时（15秒）— 可能在中国无法访问 {url}，或被对方屏蔽"
        logger.warning("Timeout scraping: %s", url)
        raise ScrapeError(msg)
    except httpx.ConnectError as exc:
        msg = f"无法连接 — DNS解析失败或网站不存在 ({url}): {exc}"
        logger.warning("Connection error scraping %s: %s", url, exc)
        raise ScrapeError(msg)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 404:
            msg = f"网站返回404（页面不存在）— 请检查网址是否正确"
        elif code == 403:
            msg = f"网站返回403（禁止访问）— 该网站可能屏蔽了爬虫"
        elif code >= 500:
            msg = f"网站服务器错误（HTTP {code}）— 对方服务器暂时故障"
        else:
            msg = f"网站返回 HTTP {code}，无法正常访问"
        logger.warning("HTTP %d scraping: %s", code, url)
        raise ScrapeError(msg)
    except Exception as exc:
        msg = f"抓取异常: {type(exc).__name__} — {exc}"
        logger.warning("Scrape failed for %s: %s", url, exc)
        raise ScrapeError(msg)

    return _extract_text(html, url)


def _truncate(result: str, url: str) -> str:
    """Truncate to 5000 chars on a clean boundary."""
    if len(result) <= 5000:
        logger.info("Scraped %d chars (Crawl4AI) from %s", len(result), url)
        return result.strip()
    result = result[:5000].rsplit("\n", 1)[0]
    logger.info("Scraped (truncated) %d chars (Crawl4AI) from %s", len(result), url)
    return result.strip()


def _extract_title_desc(html: str, url: str) -> str:
    """Extract only page title + meta description from HTML. Lightweight, no full BS4 parse."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        parts.append(f"Page Title: {title_tag.get_text(strip=True)}")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        parts.append(f"Description: {meta_desc['content'].strip()}")
    return "\n".join(parts)


def _extract_text(html: str, url: str) -> str:
    """Parse HTML and extract meaningful text content."""
    soup = BeautifulSoup(html, "html.parser")

    # Step 0: Capture noscript content before stripping (JS-rendered sites)
    noscript_texts = []
    for ns in soup.find_all("noscript"):
        txt = ns.get_text(" ", strip=True)
        if len(txt) > 20:
            noscript_texts.append(txt)

    # Remove unwanted tags (noscript stripped after capture)
    for tag in _STRIP_TAGS:
        for el in soup.find_all(tag):
            el.decompose()
    for el in soup.find_all("noscript"):
        el.decompose()

    # Remove elements whose class/id match skip patterns
    for el in list(soup.find_all(True)):
        # Some descendants become detached after a parent is decomposed above.
        # BeautifulSoup leaves those with attrs=None; skip them instead of
        # treating a cleanup issue as a failed intelligence run.
        if getattr(el, "attrs", None) is None:
            continue
        cls_attr = el.get("class", []) or []
        cls = cls_attr if isinstance(cls_attr, str) else " ".join(cls_attr)
        el_id = el.get("id", "") or ""
        if _SKIP_PATTERNS.search(cls) or _SKIP_PATTERNS.search(el_id):
            el.decompose()

    parts = []

    # 1. Page title
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        parts.append(f"Page Title: {title_tag.get_text(strip=True)}")

    # 2. Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content", "").strip():
        parts.append(f"Description: {meta_desc['content'].strip()}")

    # 3. Headings (h1, h2)
    for level in ["h1", "h2"]:
        for h in soup.find_all(level):
            text = h.get_text(" ", strip=True)
            if text and len(text) > 5:
                parts.append(f"[{level}] {text}")

    # 4. Main body paragraphs
    main = soup.find("main") or soup.find("article") or soup
    paragraphs = main.find_all("p")
    body_texts = []
    for p in paragraphs:
        text = p.get_text(" ", strip=True)
        # Skip very short or obviously non-content lines
        if len(text) > 30:
            body_texts.append(text)

    # Fallback: if body_texts empty (JS site), inject noscript content
    if not body_texts and noscript_texts:
        body_texts = noscript_texts

    if body_texts:
        parts.append("\n".join(body_texts))

    result = "\n\n".join(parts)

    # Collapse whitespace
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r" {2,}", " ", result)

    # Fallback for JS-rendered sites (Wix, React, etc.)
    if len(result.strip()) < 80:
        # Headings / body were empty - try noscript content
        noscript_texts = []
        for ns in soup.find_all("noscript"):
            txt = ns.get_text(" ", strip=True)
            if len(txt) > 20:
                noscript_texts.append(txt)
        if noscript_texts:
            parts.append("[noscript fallback]")
            parts.append("\n".join(noscript_texts[:5]))
            result = "\n\n".join(parts)

        # Still too little: extract ALL visible text as last resort
        if len(result.strip()) < 80:
            for tag in soup(["script", "style", "link", "meta", "svg"]):
                tag.decompose()
            raw_text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in raw_text.split("\n") if len(line.strip()) > 15]
            if lines:
                result = result + "\n[raw text]\n" + "\n".join(lines[:30])
                logger.info("Raw text fallback: extracted %d lines from %s", len(lines), url)


    # Truncate to 5000 chars
    if len(result) > 5000:
        result = result[:5000].rsplit("\n", 1)[0]  # cut at last newline

    logger.info("Scraped %d chars from %s", len(result), url)
    return result.strip()
