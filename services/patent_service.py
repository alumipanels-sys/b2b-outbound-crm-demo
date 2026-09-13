"""Patent search service — find a company's patents via Google Patents.

Free — no API key required. Uses Google Patents search + AI extraction.
Patents are a strong B2B signal: an active portfolio indicates real R&D
capability, whatever the industry.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

async def _search_google_patents(company: str, max_results: int = 15) -> list[dict]:
    """Search Google Patents for a company name. Returns list of patent summaries."""
    query = quote_plus(f'assignee:"{company}"')
    url = f"https://patents.google.com/?q={query}&num={max_results}"

    results = []

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

            # Extract patent data from the page
            # Google Patents renders results as HTML with structured data
            # Look for <result> elements or the patent title/abstract blocks

            # Pattern 1: patent titles and numbers from search-result links
            title_pattern = re.compile(
                r'<h3[^>]*class="[^"]*result-title[^"]*"[^>]*>\s*<a[^>]*href="[^"]*/([A-Z]{2,4}\d+[A-Z]?\d*)[^"]*"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE
            )

            # Pattern 2: patent metadata (dates, inventors)
            meta_pattern = re.compile(
                r'<span[^>]*class="[^"]*patent-date[^"]*"[^>]*>(\d{4}-\d{2}-\d{2})</span>',
                re.IGNORECASE
            )

            # Pattern 3: alternative — look for patent-result blocks containing structured data
            result_blocks = re.findall(
                r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>',
                html, re.DOTALL | re.IGNORECASE
            )

            for match in title_pattern.finditer(html):
                patent_num = match.group(1).strip()
                title_text = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                if title_text and patent_num:
                    results.append({
                        "patent_number": patent_num,
                        "title": title_text[:200],
                    })
                    if len(results) >= max_results:
                        break

            # If no results via HTML parsing, try JSON-LD structured data
            if not results:
                json_ld_pattern = re.compile(
                    r'<script type="application/ld\+json">(.*?)</script>',
                    re.DOTALL
                )
                for jld in json_ld_pattern.finditer(html):
                    try:
                        data = json.loads(jld.group(1))
                        if isinstance(data, list):
                            for item in data:
                                if item.get("@type") == "ScholarlyArticle" or "patent" in str(item.get("name", "")).lower():
                                    results.append({
                                        "patent_number": item.get("identifier", ""),
                                        "title": item.get("name", ""),
                                    })
                    except (json.JSONDecodeError, KeyError):
                        pass

            # If still nothing, try a broader regex for any patent number pattern
            if not results:
                broad_patterns = re.findall(
                    r'(?:US|EP|WO|CN|DE|JP|KR)(\d{4,11}[A-Z]?\d?)',
                    html
                )
                for pnum in broad_patterns[:max_results]:
                    results.append({
                        "patent_number": pnum,
                        "title": "",
                    })

    except httpx.TimeoutException:
        logger.warning("Google Patents search timed out for %s", company)
    except Exception as exc:
        logger.warning("Google Patents search failed for %s: %s", company, exc)

    return results


def _ai_summarize_patents(company: str, patents: list[dict]) -> str | None:
    """Use AI to generate a concise patent summary from results."""
    if not patents:
        return None

    from services.ai_router import call_simple_sync as call_simple

    patent_list = "\n".join(
        f"- {p.get('patent_number', '?')}: {p.get('title', 'unknown')}"[:200]
        for p in patents[:10]
    )

    prompt = f"""Analyze these patents filed by {company}. Summarize in 2-3 sentences: (1) the overall patent portfolio impression, (2) which technical areas their patents cover, (3) what this says about their R&D capability.

Patents found:
{patent_list}

Return ONLY the summary text, no JSON, no markdown."""
    try:
        raw = call_simple(prompt, 0.3, 512)
        return raw.strip()[:500]
    except Exception as exc:
        logger.warning("AI patent summary failed: %s", exc)
        return None


async def lookup_patents(company: str) -> dict:
    """Main entry point — search patents for a company and return structured results.

    Returns dict with:
        patent_count: int (number found)
        patents: list of {patent_number, title}
        related_patent_count: int (all found patents belong to the company)
        ai_summary: str or None
        searched_at: ISO datetime string
    """
    if not company or not company.strip():
        return {
            "patent_count": 0,
            "patents": [],
            "related_patent_count": 0,
            "ai_summary": None,
            "searched_at": datetime.utcnow().isoformat(),
        }

    patents = await _search_google_patents(company, max_results=15)

    # All patents found for the company are relevant to it (no industry filter)

    # AI summary if we found patents
    ai_summary = None
    if patents:
        try:
            ai_summary = _ai_summarize_patents(company, patents)
        except Exception:
            pass

    return {
        "patent_count": len(patents),
        "patents": patents,
        "related_patent_count": len(patents),
        "ai_summary": ai_summary,
        "searched_at": datetime.utcnow().isoformat(),
    }
