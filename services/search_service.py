"""Search enrichment service — ft-osint Phase 1 & 3.
Pre-scoring web search: find company footprint, trade data, news.
Uses DuckDuckGo Lite (no API key required) as primary, falls back to direct web_search.
"""

import logging
import urllib.parse
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# DuckDuckGo Lite — returns plain HTML, easy to parse, no JS required
DDG_LITE = "https://lite.duckduckgo.com/lite/"


async def _search_ddg(query: str, max_results: int = 8, timeout: float = 10.0) -> list[dict]:
    """Search DuckDuckGo Lite and return list of {title, snippet, url}."""
    results = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                DDG_LITE,
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.select("table.result, tr.result, .result, tr"):
                    title_el = row.select_one("a.result-link, .result-title a, a")
                    snippet_el = row.select_one("td.result-snippet, .result-snippet, .snippet")
                    if title_el and title_el.get("href"):
                        url = title_el.get("href")
                        if url.startswith("//"):
                            url = "https:" + url
                        if url.startswith("/"):
                            continue  # skip relative links (nav)
                        results.append({
                            "title": title_el.get_text(strip=True),
                            "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                            "url": url,
                        })
                        if len(results) >= max_results:
                            break
    except Exception as e:
        logger.warning("DDG search failed for '%s': %s", query[:60], e)
    return results


async def enrichment_search(company: str, country: str = "", website: str = "") -> dict:
    """Run pre-scoring web searches and return structed enrichment data.

    Returns dict with:
      - google_footprint: list of {title, snippet, url} from company search
      - linkedin_mentions: list of {title, snippet, url}
      - customs_hints: list of {title, snippet, url} from trade data search
      - negative_news: list of {title, snippet, url}
      - raw_summary: short text summary for the AI prompt
    """
    if not company:
        return {"google_footprint": [], "raw_summary": ""}

    # ── Phase 1: Google footprint ──
    # Search 1: Company name + official site
    q1 = f'"{company}" official site'
    r1 = await _search_ddg(q1, max_results=5)

    # Search 2: Company + country + importer/manufacturer
    loc = country or ""
    q2 = f'"{company}" {loc} importer OR distributor OR optical'
    r2 = await _search_ddg(q2, max_results=5)

    # Search 3: Company + LinkedIn
    q3 = f'"{company}" CEO OR founder OR manager LinkedIn'
    r3 = await _search_ddg(q3, max_results=5)

    # Search 4: Company + news 2025/2026
    q4 = f'"{company}" news 2025 OR 2026'
    r4 = await _search_ddg(q4, max_results=5)

    google_footprint = r1 + r2
    linkedin_mentions = r3

    # ── Phase 3: Customs / trade data hints ──
    customs_hints = []
    for q in [f'"{company}" import OR shipment OR "bill of lading"',
              f'"{company}" optical OR lens OR endoscope supplier']:
        customs_hints.extend(await _search_ddg(q, max_results=4))

    # ── Negative news check ──
    negative_news = await _search_ddg(f'"{company}" lawsuit OR scam OR complaint OR fraud', max_results=3)

    # Build summary for AI prompt
    summary_parts = []
    all_urls = set()

    if google_footprint:
        summary_parts.append(f"\n=== 搜索引擎足迹 ({len(google_footprint)}条结果) ===")
        for r in google_footprint[:6]:
            if r["url"] not in all_urls:
                all_urls.add(r["url"])
                summary_parts.append(f"- {r['title']} | {r['snippet'][:200]}")

    if linkedin_mentions:
        summary_parts.append(f"\n=== LinkedIn提及 ===")
        for r in linkedin_mentions[:3]:
            if r["url"] not in all_urls:
                all_urls.add(r["url"])
                summary_parts.append(f"- {r['title']} | {r['snippet'][:200]}")

    if customs_hints:
        summary_parts.append(f"\n=== 海关/贸易信号 ===")
        for r in customs_hints[:5]:
            if r["url"] not in all_urls:
                all_urls.add(r["url"])
                summary_parts.append(f"- {r['title']} | {r['snippet'][:200]}")

    if negative_news:
        summary_parts.append(f"\n=== ⚠️ 负面信息 ===")
        for r in negative_news[:3]:
            if r["url"] not in all_urls:
                all_urls.add(r["url"])
                summary_parts.append(f"- {r['title']} | {r['snippet'][:200]}")

    return {
        "google_footprint": google_footprint,
        "linkedin_mentions": linkedin_mentions,
        "customs_hints": customs_hints,
        "negative_news": negative_news,
        "raw_summary": "\n".join(summary_parts)[:3000],
    }
