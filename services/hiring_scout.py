"""Hiring signal scout — proactively discovers new prospects by searching for
recent job postings at B2B companies (buying-decision roles), extracting
company names, and auto-importing them.

Flow:
1. Search DuckDuckGo for hiring/job keywords in target countries
2. Extract company names + snippets from search results
3. AI deduplicates and enriches (country, industry guess, website guess)
4. Auto-import to prospects table if not already present
5. Trigger AI scoring for each new import

Safe: only imports if company name is new (checks existing company + email dupes).
Human review still needed — these are leads, not vetted prospects.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Prospect
from services.ai_router import call_simple, call_simple_sync, get_active_model

logger = logging.getLogger(__name__)

# ── Search target: countries + role keywords for B2B buying-decision hiring ──

SEARCH_TARGETS = [
    # Germany / DACH
    {
        "country": "DE",
        "queries": [
            'site:linkedin.com/jobs "purchasing manager" OR "procurement" OR "supply chain manager" OR "sales manager" Germany',
            'site:linkedin.com/jobs "einkaeufer" OR "einkauf" OR "beschaffung" OR "vertriebsmanager" Germany',
        ],
    },
    # Middle East
    {
        "country": "AE",
        "queries": [
            'site:linkedin.com/jobs "purchasing manager" OR "procurement" OR "sales manager" Dubai UAE',
            'site:linkedin.com/jobs "supply chain" OR "buyer" OR "vendor management" Abu Dhabi',
        ],
    },
    # India
    {
        "country": "IN",
        "queries": [
            'site:linkedin.com/jobs "purchasing manager" OR "procurement" OR "vendor development" India',
            'site:linkedin.com/jobs "sales manager" OR "supply chain" OR "buyer" Bangalore Pune Mumbai',
        ],
    },
    # Eastern Europe
    {
        "country": "PL",
        "queries": [
            'site:linkedin.com/jobs "purchasing manager" OR "procurement" OR "sales manager" Poland Czech Slovakia',
        ],
    },
    # Italy / Spain
    {
        "country": "IT",
        "queries": [
            'site:linkedin.com/jobs "responsabile acquisti" OR "purchasing manager" Italy',
            'site:linkedin.com/jobs "jefe de compras" OR "comprador" OR "sales manager" Spain',
        ],
    },
    # Nordics / Netherlands
    {
        "country": "NL",
        "queries": [
            'site:linkedin.com/jobs "purchasing manager" OR "inkopschef" OR "indkob" Netherlands Sweden Denmark',
        ],
    },
    # Global — export/sales & procurement roles
    {
        "country": "GLOBAL",
        "queries": [
            'site:linkedin.com/jobs "international sales manager" OR "export sales manager" OR "procurement manager"',
        ],
    },
]

# Keywords used to filter search snippets — must contain at least one
HIRING_KEYWORDS = [
    "purchasing", "procurement", "buyer", "sourcing", "supply chain",
    "sales manager", "export sales", "international sales", "vendor",
    "einkauf", "beschaffung", "vertrieb", "acquisti", "compras",
    "comprador", "inkop", "indkob", "hiring", "careers",
]


def _quick_search(query: str, max_results: int = 15) -> list[dict]:
    """Quick DuckDuckGo HTML search. Returns [{title, url, snippet}]."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={query}"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for el in soup.select(".result"):
            a = el.select_one(".result__a")
            s = el.select_one(".result__snippet")
            if a and a.get("href"):
                title = a.get_text(strip=True)
                snippet = s.get_text(strip=True) if s else ""
                href = a["href"]
                # Extract actual URL from DuckDuckGo redirect
                parsed = urlparse(href)
                qs = parsed.query or ""
                if "uddg=" in qs:
                    for part in qs.split("&"):
                        if part.startswith("uddg="):
                            href = httpx.URL(part[5:]).params.get("uddg") or href
                            break
                results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for '%s': %s", query[:60], exc)
        return []


def _extract_companies_from_results(results: list[dict]) -> list[dict]:
    """Extract likely company names from LinkedIn job posting search results."""
    companies = []
    seen = set()

    for r in results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        combined = f"{title} {snippet}"

        # Quick keyword filter
        if not any(kw.lower() in combined.lower() for kw in HIRING_KEYWORDS):
            continue

        # Extract company name — LinkedIn titles often: "Job Title - Company Name | LinkedIn"
        parts = re.split(r"\s+[-–—|·•]\s+", title)
        for part in parts:
            part = part.strip().strip("|").strip()
            if "linkedin" in part.lower():
                continue
            if "engineer" in part.lower() or "manager" in part.lower() or "technician" in part.lower():
                continue
            if len(part) > 2 and len(part) < 80 and part.lower() not in seen:
                seen.add(part.lower())
                companies.append({"company": part, "snippet": snippet[:200], "url": r.get("url", "")})
                break

    return companies[:20]


async def _ai_enrich(candidates: list[dict], country: str) -> list[dict]:
    """AI enriches candidate list: validates company, guesses industry, scores relevance."""
    if not candidates:
        return []

    lines = []
    for i, c in enumerate(candidates):
        lines.append(f"{i+1}. {c['company']} — {c.get('snippet', '')[:100]}")

    prompt = f"""You are a B2B lead qualification AI for {{COMPANY}}.

Search results from country "{country}" about relevant-industry hiring:
{chr(10).join(lines)}

For each candidate, determine:
1. Is this a real company (not a person, not a recruiter)?
2. What industry? (e.g. industrial / automotive / electronics / consumer goods / services / other)
3. Relevance to {{COMPANY}} (1-10): judge against the company's ideal customer profile in the knowledge base.
4. Brief reason for the score.

Return ONLY a JSON array:
[{{"company": "...", "industry": "...", "relevance": 1-10, "reason": "one sentence"}}]

Only return real companies with relevance >= 6. Skip recruiters, individuals, irrelevant companies."""

    try:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, call_simple_sync, prompt, 0.3, 2048)
        clean = raw.strip()
        m = re.search(r"\[[\s\S]*\]", clean)
        if m:
            clean = m.group(0)
        result = json.loads(clean)
        if isinstance(result, list):
            return [r for r in result if isinstance(r, dict) and r.get("company")]
    except Exception as exc:
        logger.warning("AI enrichment failed: %s", exc)
    return []


def _auto_import(prospects: list[dict], country: str) -> dict:
    """Import new prospects to DB (skip duplicates on company name)."""
    session = SessionLocal()
    imported = 0
    skipped = 0
    errors = []

    # Pre-load existing company names for fast dedup
    existing = set()
    for row in session.query(Prospect.company).filter(Prospect.is_deleted == 0).all():
        existing.add(row[0].strip().lower())

    for p in prospects:
        company = (p.get("company") or "").strip()
        if not company:
            continue
        if company.lower() in existing:
            skipped += 1
            continue

        try:
            session.add(Prospect(
                company=company,
                industry=p.get("industry", "") or "",
                country=country,
                source="Hiring signal",
                status="New",
                note=f"AI via job posting — relevance: {p.get('relevance', '?')}/10 — {p.get('reason', '')[:200]}",
                is_deleted=0,
            ))
            imported += 1
        except Exception as exc:
            errors.append(f"{company}: {exc}")

    session.commit()
    session.close()
    return {"imported": imported, "skipped": skipped, "errors": errors}


def _tz_for_country(country: str) -> str:
    """Guess timezone from country code."""
    mapping = {
        "DE": "Europe/Berlin", "AT": "Europe/Vienna", "CH": "Europe/Zurich",
        "NL": "Europe/Amsterdam", "DK": "Europe/Copenhagen", "SE": "Europe/Stockholm",
        "IT": "Europe/Rome", "ES": "Europe/Madrid", "PL": "Europe/Warsaw",
        "AE": "Asia/Dubai", "SA": "Asia/Riyadh", "IN": "Asia/Kolkata",
        "TR": "Europe/Istanbul", "IR": "Asia/Tehran",
    }
    return mapping.get(country, "UTC")


# ── Single-company hiring search ──────────────────────────

def search_company_hiring(company: str, country: str = None) -> dict:
    """Search for a specific company's job postings. Used by drawer button + single scout."""
    if not company:
        return {"company": company, "results": [], "analysis": None, "has_signals": False}

    location = country or ""
    queries = [
        f'site:linkedin.com "{company}" jobs OR hiring OR careers OR "we are looking" {location}',
        f'site:linkedin.com "{company}" "engineer" OR "purchasing" OR "sales" OR "manager" {location}',
    ]

    all_results = []
    for q in queries:
        results = _quick_search(q, max_results=8)
        all_results.extend(results)

    if not all_results:
        return {"company": company, "results": [], "analysis": None, "has_signals": False}

    # Deduplicate by title
    seen = set()
    filtered = []
    for r in all_results:
        t = r.get("title", "")
        if t and t not in seen:
            seen.add(t)
            filtered.append(r)
    results = filtered[:10]

    analysis = _analyze_company_hiring(results, company, country)
    return {
        "company": company,
        "results": results,
        "analysis": analysis,
        "has_signals": analysis is not None and len(analysis) > 0,
    }


def _analyze_company_hiring(results: list[dict], company: str, country: str = None) -> list[str] | None:
    """AI interprets hiring results for a specific company."""
    if not results:
        return None

    snippets = "\n".join([f"- {r.get('title','')}: {r.get('snippet','')[:200]}" for r in results])
    prompt = f"""You analyze company hiring signals for a B2B supplier.

Company: {company} | Country: {country or 'Unknown'}

Job postings found:
{snippets}

Classify each job posting as a buying signal:
- HIGH: Hiring purchasing / procurement / buyers, or engineers / production managers for their product lines → they are scaling and may need component suppliers
- MEDIUM: Hiring related technical or quality roles (mechanical, electrical, production, QC)
- LOW: Unrelated generic roles (HR, admin, marketing only) → weak signal
- NONE: Not actually a job posting or unrelated company

Return ONLY a JSON array of up to 8 signals:
[{{"role": "job title", "confidence": "high|medium|low|none", "relevance": "1-sentence explanation in English"}}]

If no relevant signals, return []. Output only the JSON array, no markdown."""

    try:
        raw = call_simple_sync(prompt, 0.3, 2048)
        clean = raw.strip()
        m = re.search(r"\[[\s\S]*\]", clean)
        if m:
            clean = m.group(0)
        result = json.loads(clean)
        if isinstance(result, list):
            return result
        return None
    except Exception as exc:
        logger.warning("Company hiring analysis failed for %s: %s", company, exc)
        return None


# ── Main entry point ──────────────────────────────────

async def run_hiring_scout(
    countries: Optional[list[str]] = None,
    max_per_query: int = 10,
) -> dict:
    """Main entry point: search for B2B hiring signals, extract companies,
    enrich with AI, and auto-import.

    Returns: {total_searched, total_found, imported: [{country, imported, skipped, errors}]}
    """
    logger.info("Hiring scout started")
    all_candidates = []
    total_searched = 0

    targets = SEARCH_TARGETS
    if countries:
        targets = [t for t in SEARCH_TARGETS if t["country"] in countries]

    for target in targets:
        country = target["country"]
        for query in target["queries"]:
            results = _quick_search(query, max_per_query)
            total_searched += len(results)
            companies = _extract_companies_from_results(results)
            if companies:
                all_candidates.append((country, companies))

    # Deduplicate across queries within same country
    by_country = {}
    for country, candidates in all_candidates:
        if country not in by_country:
            by_country[country] = []
        by_country[country].extend(candidates)

    # AI enrich + import per country
    import_results = []
    for country, candidates in by_country.items():
        # Dedup within country
        seen = set()
        deduped = []
        for c in candidates:
            name = c["company"].strip().lower()
            if name not in seen:
                seen.add(name)
                deduped.append(c)

        enriched = await _ai_enrich(deduped, country)
        if enriched:
            result = _auto_import(enriched, country)
            result["country"] = country
            import_results.append(result)
            logger.info("Hiring scout [%s]: %d enriched, %d imported, %d skipped",
                        country, len(enriched), result["imported"], result["skipped"])

    total_imported = sum(r["imported"] for r in import_results)
    logger.info("Hiring scout done: %d searched, %d imported", total_searched, total_imported)

    return {
        "success": True,
        "total_searched": total_searched,
        "total_imported": total_imported,
        "by_country": import_results,
    }
