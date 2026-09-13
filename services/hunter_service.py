"""Hunter.io — full API: domain-search, email-finder, email-verifier, combined.

Endpoints:
  /v2/domain-search     — find all emails for a domain
  /v2/email-finder      — find email given first_name + last_name + domain
  /v2/email-verifier    — verify/score a single email
  /v2/combined/find     — enrich all data for a single email in one call
  /v2/people/find       — enrich person info from email
  /v2/companies/find    — enrich company info from domain
"""

import json
import logging
import urllib.request
import urllib.parse

from config import HUNTER_API_KEY

logger = logging.getLogger(__name__)

BASE = "https://api.hunter.io/v2"


def _get(path: str, params: dict = None) -> dict:
    """Internal GET to Hunter API."""
    if not HUNTER_API_KEY:
        return {"errors": [{"details": "HUNTER_API_KEY not configured"}]}
    p = params or {}
    p["api_key"] = HUNTER_API_KEY
    url = f"{BASE}/{path}?{urllib.parse.urlencode(p)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Tuodan-Prospect-Engine/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.error("Hunter HTTP %s: %s", e.code, body[:200])
        return {"errors": [{"details": f"HTTP {e.code}: {body[:300]}"}]}
    except Exception as e:
        logger.error("Hunter exception: %s", e)
        return {"errors": [{"details": str(e)[:300]}]}


# ═══════════════════════════════════════
#  Core endpoints
# ═══════════════════════════════════════

def domain_search(domain: str, limit: int = 50, **kwargs) -> dict:
    """Search ALL emails found for a domain."""
    return _get("domain-search", {"domain": domain, "limit": limit, **kwargs})


def email_finder(domain: str, first_name: str = None, last_name: str = None,
                 full_name: str = None) -> dict:
    """Find the most likely email for a specific person at a domain."""
    params = {"domain": domain}
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name
    if full_name and not first_name:
        params["full_name"] = full_name
    return _get("email-finder", params)


def email_verifier(email: str) -> dict:
    """Verify a single email — returns deliverability score, SMTP check, catch-all flag."""
    return _get("email-verifier", {"email": email})


def combined_find(email: str) -> dict:
    """One call: verify + enrich person + enrich company."""
    return _get("combined/find", {"email": email})


def people_find(email: str) -> dict:
    """Enrich person info from an email address."""
    return _get("people/find", {"email": email})


def company_find(domain: str) -> dict:
    """Enrich company info from a domain."""
    return _get("companies/find", {"domain": domain})


# ═══════════════════════════════════════
#  High-level helpers for 冷开发 workflow
# ═══════════════════════════════════════

def _extract_domain(url_or_email: str) -> str | None:
    if not url_or_email:
        return None
    s = url_or_email.strip().lower()
    if "://" in s:
        s = s.split("://")[1]
    s = s.split("/")[0]
    if s.startswith("www."):
        s = s[4:]
    if "@" in s:
        s = s.split("@")[1]
    if ":" in s:
        s = s.split(":")[0]
    return s.strip() if "." in s else None


def _parse_email_entry(e: dict) -> dict:
    return {
        "email": e.get("value", ""),
        "first_name": e.get("first_name", "") or "",
        "last_name": e.get("last_name", "") or "",
        "full_name": f"{e.get('first_name','') or ''} {e.get('last_name','') or ''}".strip(),
        "position": e.get("position", "") or "",
        "department": e.get("department", "") or "",
        "type": e.get("type", ""),
        "confidence": e.get("confidence", 0),
        "verification": e.get("verification", {}).get("status", ""),
        "twitter": e.get("twitter", ""),
        "linkedin": e.get("linkedin", ""),
        "phone": e.get("phone_number", ""),
        "sources": [s.get("domain", "") for s in e.get("sources", [])],
    }


_PROFILE_POSITIONS = {
    "A": ["procurement", "purchasing", "buyer", "supply chain", "sourcing", "purchasing manager",
          "head of procurement", "director of purchasing", "global sourcing"],
    "B": ["procurement", "purchasing", "engineer", "production", "quality", "operations", "supply chain"],
    "C": ["ceo", "owner", "founder", "general manager", "purchasing", "procurement", "import"],
    "D": ["veterinarian", "surgeon", "doctor", "practice manager", "purchasing", "procurement"],
    "E": ["technician", "service manager", "maintenance", "repair", "operations", "purchasing"],
}


def _score_candidate(c: dict, profile_type: str = None) -> int:
    """Score a candidate for relevance to the company's buyer profile."""
    score = c.get("confidence", 0) or 0
    if c.get("type") == "generic":
        score -= 30
    pos = (c.get("position", "") + " " + c.get("department", "")).lower()
    dept = c.get("department", "").lower()

    # Penalize irrelevant departments
    bad = ["marketing", "sales", "support", "developer", "software", "legal", "accounting"]
    for b in bad:
        if b in pos or b in dept:
            score -= 30
            break

    # Boost for procurement-related keywords
    keywords = _PROFILE_POSITIONS.get(profile_type, []) if profile_type else []
    if not keywords:
        keywords = ["procurement", "purchasing", "buyer", "supply chain", "sourcing", "operations"]
    for kw in keywords:
        if kw.lower() in pos:
            score += 25
            break

    return score


def _check_quota(raw: dict) -> str | None:
    """Return quota error message if applicable."""
    if not raw.get("errors"):
        return None
    msg = raw["errors"][0].get("details", "")
    msg_lower = msg.lower()
    if any(w in msg_lower for w in ["not enough", "subscription", "quota", "limit exceeded", "credit"]):
        return "Hunter 免费额度已用完（每月25次搜索）。下月重置或升级付费计划。"
    return f"Hunter API 错误: {msg}"


def find_decision_maker(prospect: dict) -> dict:
    """Find the best decision-maker email for a single prospect.

    1. priority: if contact name exists → email-finder
    2. fallback: domain-search → score & rank all found
    3. auto-fill dm_email: best candidate

    Args:
        prospect: {id, company, website, email, contact, title, profile_type, ...}

    Returns:
        {"success": bool, "total": int, "candidates": [...], "best": {...}, "message": str}
    """
    domain = (_extract_domain(prospect.get("website")) or
              _extract_domain(prospect.get("email")) or
              _extract_domain(prospect.get("dm_email")))
    if not domain:
        return {"success": False, "error": "Cannot extract a domain. Please fill in the website or email field first."}

    contact = (prospect.get("contact") or "").strip()
    profile_type = prospect.get("profile_type") or ""
    candidates = []
    found_method = ""

    # ── Step 1: email-finder (if we have a name) ──
    if contact:
        parts = contact.split()
        fn = parts[0] if parts else None
        ln = parts[-1] if len(parts) >= 2 else None
        raw = email_finder(domain, first_name=fn, last_name=ln)
        qerr = _check_quota(raw)
        if qerr is not None and "error" not in qerr.lower():
            return {"success": False, "error": qerr, "quota_exceeded": True}
        if raw.get("data") and raw["data"].get("email"):
            e = raw["data"]
            c = _parse_email_entry(e)
            c["score"] = _score_candidate(c, profile_type)
            candidates.append(c)
            found_method = "email-finder (按联系人姓名)"

    # ── Step 2: domain-search (always, to fill gaps) ──
    raw = domain_search(domain, limit=30)
    qerr = _check_quota(raw)
    if qerr is not None and "error" not in qerr.lower():
        if not candidates:
            return {"success": False, "error": qerr, "quota_exceeded": True}
        # else: we already have the email-finder result, skip domain quota error
    elif raw.get("data", {}).get("emails"):
        seen = {c["email"] for c in candidates}
        for e in raw["data"]["emails"]:
            email_val = e.get("value", "")
            if email_val in seen:
                continue
            c = _parse_email_entry(e)
            c["score"] = _score_candidate(c, profile_type)
            candidates.append(c)
            seen.add(email_val)
        if not found_method:
            found_method = "domain-search"

    if not candidates:
        return {
            "success": True,
            "total": 0,
            "candidates": [],
            "best": None,
            "message": f"在 {domain} 未找到任何邮箱。试试 LinkedIn 搜索或换一个域名。",
        }

    # ── Sort by score ──
    candidates.sort(key=lambda c: -(c["score"]))

    # ── Pick best ──
    best = candidates[0] if candidates else None

    return {
        "success": True,
        "total": len(candidates),
        "domain": domain,
        "method": found_method,
        "candidates": candidates[:20],
        "best": best,
        "message": f"在 {domain} 找到 {len(candidates)} 个邮箱，最佳: {best['email'] if best else '无'}",
    }


def verify_and_enrich(email: str, verify: bool = True) -> dict:
    """Verify an email and return enriched person/company info in one call."""
    if verify:
        return combined_find(email)
    return people_find(email)
