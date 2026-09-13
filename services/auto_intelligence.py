"""Auto-intelligence service — scheduled OSINT pipeline with 5 steps.

Flow per prospect:
1. Scrape website → extract clean text
2. Whois domain registration lookup (domain age, registrar)
3. Patent search via Google Patents (company patent portfolio)
4. FDA 510(k) medical device registration check
5. AI extracts 5-8 key business facts → compare with previous snapshot
6. Auto-discover career/jobs page → scrape → AI analyze hiring signals
7. Re-generate icebreaker angles if new content found
8. Cross-validate all data sources for contradictions
9. Save change_flags if anything substantial changed

LinkedIn is NOT scraped — user pastes manually.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Prospect, Intelligence
from services.ai_router import call_simple, call_simple_sync
from services.scraper_service import scrape_website, _extract_text, ScrapeError
from services.whois_service import lookup_whois_python_whois
from services.patent_service import lookup_patents
from services.fda_service import lookup_fda_510k

logger = logging.getLogger(__name__)

_HTTP_PROXY = os.getenv("HTTPS_PROXY", "") or os.getenv("HTTP_PROXY", "")

# Profile → refresh cadence in days
CADENCE = {
    "A": 3,
    "B": 5,
    "C": 7,
    "D": 10,
    "E": 14,
}

# URL patterns that indicate a careers/jobs page
CAREER_PATTERNS = re.compile(
    r"(career|jobs?|stellen|recruit|arbeit|vacanc|employ|join|team|about)",
    re.IGNORECASE,
)

CAREER_PATH_PATTERNS = re.compile(
    r"/(career|jobs?|stellen|recruit|arbeit|vacanc|employ|join-us|about-us|company)",
    re.IGNORECASE,
)


def _find_career_url(website_url: str, html: str) -> str | None:
    """Parse homepage HTML and find a careers/jobs page link."""
    soup = BeautifulSoup(html, "html.parser")
    base = website_url.rstrip("/")

    # Score candidates by URL + link text
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        # Resolve relative URLs
        full = urljoin(base, href)
        # Only follow same-domain links
        if urlparse(full).netloc != urlparse(base).netloc:
            continue

        text = a.get_text(" ", strip=True).lower()
        score = 0
        if CAREER_PATH_PATTERNS.search(href):
            score += 3
        if CAREER_PATTERNS.search(text):
            score += 2
        if score >= 3:
            candidates.append((score, full))

    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1] if candidates else None


def _scrape_career_page(career_url: str) -> str:
    """Scrape a career page and return clean text (max 3000 chars for AI analysis)."""
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_event_loop()
    except RuntimeError:
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)

    async def _scrape():
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
                },
                proxy=_HTTP_PROXY or None,
            ) as client:
                response = await client.get(career_url)
                response.raise_for_status()
                return response.text
        except Exception as exc:
            logger.warning("Career page scrape failed for %s: %s", career_url, exc)
            return ""

    html = loop.run_until_complete(_scrape())
    if not html:
        return ""

    text = _extract_text(html, career_url)
    return text[:3000] if text else ""


async def _ai_extract_key_points(website_content: str) -> list[str] | None:
    """AI extracts 5-8 key business facts from website content."""
    prompt = f"""Extract 5-8 key business facts from this website content. Focus on: what they do, products/services, target customers, capabilities, size, regions served. Return ONLY a JSON array of strings.

Website content:
{website_content[:4000]}"""
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, call_simple_sync, prompt, 0.3, 2048)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        result = json.loads(raw)
        return result if isinstance(result, list) else None
    except Exception as exc:
        logger.warning("AI key-point extraction failed: %s", exc)
        return None


async def _ai_extract_hiring_signals(hiring_content: str) -> list[str] | None:
    """AI extracts hiring signals from career page content."""
    prompt = f"""Analyze this career/jobs page content. Identify if they are hiring for: purchasing / sales, engineering, manufacturing, R&D, or quality roles. Return ONLY a JSON array of strings describing each relevant signal found. If no relevant signals, return [].

Content:
{hiring_content[:3000]}"""
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, call_simple_sync, prompt, 0.3, 2048)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        result = json.loads(raw)
        return result if isinstance(result, list) else None
    except Exception as exc:
        logger.warning("AI hiring signal extraction failed: %s", exc)
        return None


async def _ai_detect_changes(old_points: str, new_points: list[str], company: str) -> str | None:
    """Compare old and new website key points. Return change_flags string or None."""
    if not old_points:
        return None
    prompt = f"""Compare the OLD and NEW key business facts for {company}. Identify what CHANGED — new products/services, new markets, new capabilities, or notable shifts. Return a concise 1-2 sentence summary of changes. Return "NO_CHANGE" if nothing material changed.

OLD facts: {old_points}

NEW facts: {json.dumps(new_points, ensure_ascii=False)}

Change summary:"""
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, call_simple_sync, prompt, 0.3, 512)
        raw = raw.strip().strip('"').strip("'")
        if "NO_CHANGE" in raw.upper():
            return None
        return raw[:300]
    except Exception:
        return None


async def _ai_cross_validate(prospect, intel) -> str | None:
    """Cross-validate data sources: website vs WHOIS vs LinkedIn vs OSINT.
    Returns contradiction summary string or None if all consistent.
    """
    sources = []
    if intel.website_key_points:
        sources.append(f"[WEBSITE key points]\n{intel.website_key_points}")
    if intel.domain_registered_at:
        age_days = (datetime.utcnow() - intel.domain_registered_at).days
        sources.append(f"[WHOIS] domain registered {intel.domain_registered_at.strftime('%Y-%m-%d')} ({age_days} days ago), registrar: {intel.domain_registrar or 'N/A'}")
    if intel.linkedin_content:
        sources.append(f"[LINKEDIN]\n{intel.linkedin_content[:1500]}")
    if intel.hiring_signals:
        sources.append(f"[HIRING SIGNALS]\n{intel.hiring_signals}")
    if intel.osint_report:
        try:
            osint = json.loads(intel.osint_report)
            osint_summary = {}
            for k, v in osint.items():
                if isinstance(v, dict):
                    osint_summary[k] = {sk: sv for sk, sv in v.items() if not isinstance(sv, (list, dict)) or len(str(sv)) < 200}
                else:
                    osint_summary[k] = str(v)[:200]
            sources.append(f"[OSINT REPORT]\n{json.dumps(osint_summary, ensure_ascii=False)}")
        except Exception:
            pass

    if len(sources) < 3:
        return None  # need at least 3 sources to cross-validate meaningfully

    prompt = f"""Cross-validate these data sources for {prospect.company or 'this company'} ({prospect.country or 'Unknown'}).

Your job: find any INCONSISTENCIES or contradictions between sources. Examples:
- Website says 50 employees, LinkedIn says 200
- WHOIS shows domain registered 2024 but website claims "since 1998"
- LinkedIn says manufacturer but website looks like a trading company
- Hiring for engineering roles but the website shows no related products
- Company size on website conflicts with OSINT data

Return a concise summary of contradictions found, in English, 2-4 sentences. Be specific — cite which source says what vs which other source says what. If all data sources are consistent and reinforce each other, return "CONSISTENT".

Data sources:
{chr(10).join(f'--- {s}' for s in sources)}"""

    try:
        raw = await call_simple(prompt, temperature=0.3, max_tokens=1024, model_override="deepseek")
        raw = str(raw).strip().strip('"').strip("'")
        if raw.upper() == "CONSISTENT":
            return None
        return raw[:400]
    except Exception as exc:
        logger.warning("Cross-validation failed for #%d: %s", prospect.id, exc)
        return None


async def _ai_generate_icebreakers(
    company: str, country: str,
    website_points: str, hiring_signals: str, linkedin_content: str
) -> list[dict] | None:
    """Generate 3-5 icebreaker angles based on all available intelligence."""
    parts = []
    if website_points:
        parts.append(f"Website key points: {website_points}")
    if hiring_signals:
        parts.append(f"Hiring signals: {hiring_signals}")
    if linkedin_content:
        parts.append(f"LinkedIn: {linkedin_content[:1000]}")

    if not parts:
        return None

    prompt = f"""Generate 3-5 personalized outreach/icebreaker angles for {{COMPANY}} (the company described in the knowledge base). Each angle should be specific and reference real details. Return ONLY a JSON array of objects with "angle" and "why" fields.

{chr(10).join(parts)}

Company: {company}
Country: {country or 'Unknown'}"""
    try:
        raw = await asyncio.get_event_loop().run_in_executor(None, call_simple_sync, prompt, 0.3, 2048)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        result = json.loads(raw)
        return result if isinstance(result, list) else None
    except Exception as exc:
        logger.warning("Icebreaker generation failed: %s", exc)
        return None


def _fallback_key_points(prospect: Prospect, website_content: str) -> list[str]:
    """Deterministic fallback when AI is unavailable or the page is short."""
    lines = []
    for raw in (website_content or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        text = re.sub(r"^(Page Title|Description|\[h1\]|\[h2\]):\s*", "", text).strip()
        if len(text) >= 20 and text not in lines:
            lines.append(text[:220])
        if len(lines) >= 5:
            break
    if not lines:
        lines.append(f"{prospect.company or 'This company'} has a website but the scraper found limited text.")
    return lines[:6]


def _fallback_icebreakers(prospect: Prospect, key_points: list[str]) -> list[dict]:
    company = prospect.company or "this company"
    profile = prospect.profile_type or "Unknown"
    first = key_points[0] if key_points else ""
    return [
        {
            "angle": f"Reference {company}'s visible business focus before introducing the company.",
            "why": first[:180] or "Uses public website context instead of a generic cold opening.",
        },
        {
            "angle": f"Use Profile {profile} positioning to choose the first outreach channel.",
            "why": "Connects the case/playbook logic with this prospect even when AI extraction is limited.",
        },
    ]


def _local_profile_summary(prospect: Prospect) -> list[str]:
    points = []
    if prospect.company:
        points.append(f"Company: {prospect.company}")
    if prospect.country or prospect.industry:
        points.append(f"Market context: {prospect.country or 'Unknown country'} / {prospect.industry or 'Unknown industry'}")
    if prospect.profile_type or prospect.value_level or prospect.ai_score:
        points.append(f"Fit: Profile {prospect.profile_type or 'Unknown'}, value level {prospect.value_level or 'Unknown'}, score {prospect.ai_score or 'N/A'}")
    if prospect.score_reason:
        points.append(f"Existing scoring insight: {prospect.score_reason[:220]}")
    if prospect.note:
        points.append(f"Sales note: {prospect.note[:220]}")
    if prospect.website:
        points.append(f"Website listed but automatic scrape failed or returned limited content: {prospect.website}")
    return points or ["Local prospect data is limited; add website, industry, note, or LinkedIn content before outreach."]


async def refresh_single_prospect(prospect_id: int, db: Session) -> dict:
    """Run the full auto-intelligence pipeline for one prospect. Returns summary dict.

    Split into two phases:
    - Phase 1 (website-dependent): scrape site, Whois, AI key points, career page, icebreakers
    - Phase 2 (company name only): patent search, FDA 510(k) — runs even without website
    """
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        return {"prospect_id": prospect_id, "status": "skip", "reason": "prospect not found"}

    # Get or create intelligence record
    intel = db.query(Intelligence).filter(Intelligence.prospect_id == prospect_id).first()
    if not intel:
        intel = Intelligence(prospect_id=prospect_id)
        db.add(intel)
        db.commit()
        db.refresh(intel)

    result = {"prospect_id": prospect_id, "company": prospect.company, "steps": []}
    has_website = bool(prospect.website and prospect.website.strip())

    # ═══════════════════════════════════════
    #  Phase 1: Website-dependent scraping
    # ═══════════════════════════════════════
    if has_website:
        # Step 1: Scrape website
        try:
            website_content = await scrape_website(prospect.website)
        except ScrapeError as exc:
            result["website_error"] = str(exc)
            website_content = None
        except Exception as exc:
            result["website_error"] = str(exc)[:200]
            website_content = None

        if website_content:
            intel.website_content = website_content
            intel.website_scraped_at = datetime.utcnow()
            result["steps"].append("website_scraped")

            # Step 1b: Whois domain registration lookup
            if not intel.domain_registered_at:
                try:
                    loop = asyncio.get_event_loop()
                    whois_result = await loop.run_in_executor(None, lookup_whois_python_whois, prospect.website)
                    if whois_result.get("registered_at"):
                        intel.domain_registered_at = whois_result["registered_at"]
                    if whois_result.get("expires_at"):
                        intel.domain_expires_at = whois_result["expires_at"]
                    if whois_result.get("registrar"):
                        intel.domain_registrar = whois_result["registrar"]
                    intel.osint_checked_at = datetime.utcnow()
                    result["steps"].append("whois_checked")
                    if whois_result.get("registered_at"):
                        domain_age_days = (datetime.utcnow() - whois_result["registered_at"]).days
                        result["domain_age_days"] = domain_age_days
                except Exception as exc:
                    logger.warning("Whois lookup failed for #%d: %s", prospect_id, exc)

# Step 1c: Patent search (company patent portfolio)
    osint_parts = {}
    try:
        existing_osint = {}
        if intel.osint_report:
            try:
                existing_osint = json.loads(intel.osint_report)
            except json.JSONDecodeError:
                pass
    except Exception:
        existing_osint = {}

    if not existing_osint.get("patents"):
        try:
            patent_result = await lookup_patents(prospect.company or "")
            if patent_result.get("patent_count", 0) > 0:
                existing_osint["patents"] = patent_result
                intel.osint_report = json.dumps(existing_osint, ensure_ascii=False)
                intel.osint_checked_at = datetime.utcnow()
                result["steps"].append("patents_checked")
                result["patent_count"] = patent_result["patent_count"]
                result["related_patent_count"] = patent_result.get("related_patent_count", 0)
        except Exception as exc:
            logger.warning("Patent search failed for #%d: %s", prospect_id, exc)

    # Step 1d: FDA 510(k) medical device registration check
    if not existing_osint.get("fda_510k"):
        try:
            fda_result = await lookup_fda_510k(prospect.company or "")
            if fda_result.get("total_count", 0) > 0:
                existing_osint["fda_510k"] = fda_result
                intel.osint_report = json.dumps(existing_osint, ensure_ascii=False)
                intel.osint_checked_at = datetime.utcnow()
                result["steps"].append("fda_checked")
                result["fda_510k_count"] = fda_result["total_count"]
                result["fda_has_regulatory_signal"] = fda_result.get("has_regulatory_signal", False)
        except Exception as exc:
            logger.warning("FDA 510(k) check failed for #%d: %s", prospect_id, exc)

    # ═══════════════════════════════════════
    #  Phase 2: AI analysis (website required)
    # ═══════════════════════════════════════

    if has_website and website_content:
        # Step 2: AI extract key points
        new_points = await _ai_extract_key_points(website_content)
        if not new_points:
            new_points = _fallback_key_points(prospect, website_content)
            result["steps"].append("key_points_fallback")
        if new_points:
            new_points_json = json.dumps(new_points, ensure_ascii=False)
            if intel.website_key_points:
                change_flags = await _ai_detect_changes(intel.website_key_points, new_points, prospect.company or "")
                if change_flags:
                    intel.change_flags = change_flags
                    result["steps"].append("change_detected")
                    result["change_flags"] = change_flags

            intel.website_key_points_prev = intel.website_key_points
            intel.website_key_points = new_points_json
            if "key_points_fallback" not in result["steps"]:
                result["steps"].append("key_points_extracted")
        else:
            result["steps"].append("key_points_failed")

        # Step 3: Auto-discover and scrape career page
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
                },
                proxy=_HTTP_PROXY or None,
            ) as client:
                response = await client.get(prospect.website)
                html = response.text

            career_url = _find_career_url(prospect.website, html)
            if career_url:
                career_text = _scrape_career_page(career_url)
                if career_text:
                    intel.hiring_content = career_text
                    hiring_signals = await _ai_extract_hiring_signals(career_text)
                    if hiring_signals and (len(hiring_signals) > 0 and hiring_signals != []):
                        intel.hiring_signals = json.dumps(hiring_signals, ensure_ascii=False)
                        result["steps"].append("hiring_signals_found")
                        result["hiring_signals"] = hiring_signals
                    else:
                        result["steps"].append("hiring_no_signals")
                else:
                    result["steps"].append("career_page_empty")
            else:
                result["steps"].append("no_career_page_found")
        except Exception as exc:
            logger.warning("Career page discovery failed for #%d: %s", prospect_id, exc)
            result["steps"].append("career_error")

        # Step 4: Re-generate icebreaker angles
        icebreakers = await _ai_generate_icebreakers(
            prospect.company or "",
            prospect.country or "",
            intel.website_key_points or "",
            intel.hiring_signals or "",
            intel.linkedin_content or "",
        )
        if not icebreakers and intel.website_key_points:
            try:
                pts = json.loads(intel.website_key_points)
            except Exception:
                pts = []
            icebreakers = _fallback_icebreakers(prospect, pts if isinstance(pts, list) else [])
            result["steps"].append("icebreakers_fallback")
        if icebreakers:
            intel.icebreak_angles = json.dumps(icebreakers, ensure_ascii=False)
            if "icebreakers_fallback" not in result["steps"]:
                result["steps"].append("icebreakers_updated")

        # Step 5: Cross-validate all data sources for contradictions
        try:
            contradictions = await _ai_cross_validate(prospect, intel)
            if contradictions:
                existing_flags = intel.change_flags or ""
                cross_val_flag = f"[Cross-validation] {contradictions}"
                if existing_flags and "[Cross-validation]" not in existing_flags:
                    intel.change_flags = f"{existing_flags}\n{cross_val_flag}"
                elif not existing_flags:
                    intel.change_flags = cross_val_flag
                result["steps"].append("cross_validated_contradiction")
                result["cross_validation"] = contradictions
            else:
                result["steps"].append("cross_validated_consistent")
        except Exception as exc:
            logger.warning("Cross-validation failed for #%d: %s", prospect_id, exc)

    if not result["steps"]:
        local_points = _local_profile_summary(prospect)
        intel.website_key_points = json.dumps(local_points, ensure_ascii=False)
        intel.icebreak_angles = json.dumps(_fallback_icebreakers(prospect, local_points), ensure_ascii=False)
        intel.change_flags = result.get("website_error") or "Automatic website scrape produced no content; local prospect data summary generated."
        result["steps"].extend(["local_summary_generated", "icebreakers_fallback"])

    useful_steps = {
        "website_scraped",
        "whois_checked",
        "patents_checked",
        "fda_checked",
        "key_points_extracted",
        "key_points_fallback",
        "hiring_signals_found",
        "icebreakers_updated",
        "icebreakers_fallback",
        "change_detected",
        "cross_validated_consistent",
        "cross_validated_contradiction",
        "local_summary_generated",
    }
    has_useful_result = any(step in useful_steps for step in result["steps"])

    intel.analyzed_at = datetime.utcnow()
    # Only count it as a successful auto-scrape if we actually captured
    # something useful. Otherwise the Ops page should keep it due and show
    # the failure reason instead of silently "checking it off".
    if has_useful_result:
        intel.last_auto_scraped_at = datetime.utcnow()
    intel.updated_at = datetime.utcnow()
    db.commit()

    if has_useful_result:
        result["status"] = "ok"
    else:
        result["status"] = "failed"
        result["reason"] = result.get("website_error") or "no intelligence signals captured"
    return result


def _needs_refresh(prospect: Prospect, intel: Intelligence | None) -> bool:
    """Check if this prospect is due for an auto-refresh based on profile cadence."""
    profile = prospect.profile_type or "C"
    days = CADENCE.get(profile, 10)

    if not intel or not intel.last_auto_scraped_at:
        return True  # never scraped

    next_due = intel.last_auto_scraped_at + timedelta(days=days)
    return datetime.utcnow() >= next_due


def _run_auto_intelligence():
    """Entry point for the scheduler — refreshes all due prospects."""
    logger.info("Auto-intelligence refresh starting...")
    db = SessionLocal()
    try:
        prospects = db.query(Prospect).filter(
            Prospect.is_deleted == 0,
            Prospect.website.isnot(None),
            Prospect.website != "",
        ).all()

        due = []
        for p in prospects:
            intel = db.query(Intelligence).filter(Intelligence.prospect_id == p.id).first()
            if _needs_refresh(p, intel):
                due.append(p)

        if not due:
            logger.info("Auto-intelligence: all %d prospects up to date", len(prospects))
            return

        logger.info("Auto-intelligence: %d/%d prospects due for refresh", len(due), len(prospects))

        # Process with small delay between each to avoid hammering sites
        import time
        changes = 0
        for i, p in enumerate(due):
            try:
                # Re-fetch inside loop to get fresh session state
                result = asyncio.get_event_loop().run_until_complete(
                    refresh_single_prospect(p.id, db)
                )
                if result.get("change_flags"):
                    changes += 1
                    logger.info("CHANGE #%d %s: %s", p.id, p.company, result["change_flags"])
                if i < len(due) - 1:
                    time.sleep(2)  # polite delay between sites
            except Exception as exc:
                logger.error("Auto-intel failed for #%d %s: %s", p.id, p.company, exc)

        logger.info("Auto-intelligence complete: %d processed, %d with changes", len(due), changes)
    except Exception as exc:
        logger.error("Auto-intelligence run failed: %s", exc)
    finally:
        db.close()

def run_auto_intelligence():
    """Sync wrapper for the scheduler."""
    try:
        _run_auto_intelligence()
    except Exception as exc:
        logger.error("Auto-intelligence wrapper failed: %s", exc)
