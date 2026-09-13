"""Trade show timeline engine for 冷开发 cold outreach.

The goal is not only to store event dates. The useful sales behavior is:
- match global medical/optics shows to each prospect by country, region, industry and profile
- turn the event timeline into a natural outreach reason
- keep a local fallback catalog, while allowing periodic source verification/cache refresh
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import httpx
except Exception:  # pragma: no cover - optional at runtime
    httpx = None

logger = logging.getLogger(__name__)

from config import APP_DIR
PROJECT_ROOT = APP_DIR
CACHE_PATH = PROJECT_ROOT / ".auto_state" / "trade_show_sources.json"
SOURCE_CACHE_DAYS = 30

COUNTRY_ALIASES = {
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "DE": "DE",
    "AUSTRIA": "AT", "AT": "AT",
    "SWITZERLAND": "CH", "CH": "CH",
    "NETHERLANDS": "NL", "HOLLAND": "NL", "NL": "NL",
    "FRANCE": "FR", "FR": "FR",
    "ITALY": "IT", "IT": "IT",
    "SPAIN": "ES", "ES": "ES",
    "UNITED KINGDOM": "GB", "UK": "GB", "GB": "GB",
    "UNITED STATES": "US", "USA": "US", "US": "US",
    "CANADA": "CA", "CA": "CA",
    "MEXICO": "MX", "MX": "MX",
    "BRAZIL": "BR", "BR": "BR",
    "ARGENTINA": "AR", "AR": "AR",
    "CHILE": "CL", "CL": "CL",
    "COLOMBIA": "CO", "CO": "CO",
    "UAE": "AE", "UNITED ARAB EMIRATES": "AE", "AE": "AE",
    "SAUDI ARABIA": "SA", "KSA": "SA", "SA": "SA",
    "QATAR": "QA", "QA": "QA",
    "KUWAIT": "KW", "KW": "KW",
    "OMAN": "OM", "OM": "OM",
    "TURKEY": "TR", "TR": "TR",
    "EGYPT": "EG", "EG": "EG",
    "CHINA": "CN", "CN": "CN",
    "JAPAN": "JP", "JP": "JP",
    "SINGAPORE": "SG", "SG": "SG",
    "THAILAND": "TH", "TH": "TH",
    "MALAYSIA": "MY", "MY": "MY",
    "INDONESIA": "ID", "ID": "ID",
    "VIETNAM": "VN", "VN": "VN",
    "INDIA": "IN", "IN": "IN",
    "SOUTH KOREA": "KR", "KOREA": "KR", "KR": "KR",
    "AUSTRALIA": "AU", "AU": "AU",
    "SOUTH AFRICA": "ZA", "ZA": "ZA",
    "NIGERIA": "NG", "NG": "NG",
    "KENYA": "KE", "KE": "KE",
}

REGION_COUNTRIES = {
    "Europe": {"DE", "AT", "CH", "NL", "FR", "IT", "ES", "GB", "PL", "CZ", "BE", "SE", "DK", "FI"},
    "North America": {"US", "CA"},
    "Americas": {"US", "CA", "MX", "BR", "AR", "CL", "CO", "PE"},
    "Middle East": {"AE", "SA", "QA", "KW", "OM", "BH", "TR", "EG"},
    "APAC": {"CN", "JP", "SG", "TH", "MY", "ID", "VN", "KR", "IN", "AU"},
    "Africa": {"ZA", "NG", "KE", "EG", "MA"},
}

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


def _show(
    slug: str,
    name: str,
    location: str,
    country_codes: List[str],
    region: str,
    start: date,
    end: date,
    industry: str,
    priority: str,
    relevance: str,
    source_url: str,
    source_name: str,
    aliases: Optional[List[str]] = None,
    profile_types: Optional[List[str]] = None,
    industry_tags: Optional[List[str]] = None,
    outreach_days: int = 28,
    exhibitor_prep_days: int = 84,
    post_show_days: int = 10,
) -> Dict:
    return {
        "slug": slug,
        "name": name,
        "aliases": aliases or [],
        "location": location,
        "country_codes": [c.upper() for c in country_codes],
        "region": region,
        "dates": (start, end),
        "industry": industry,
        "industry_tags": [t.lower() for t in (industry_tags or [])],
        "profile_types": [p.upper() for p in (profile_types or [])],
        "priority": priority,
        "relevance": relevance,
        "outreach_days": outreach_days,
        "exhibitor_prep_days": exhibitor_prep_days,
        "post_show_days": post_show_days,
        "outreach_window_start": start - timedelta(days=outreach_days),
        "exhibitor_prep_start": start - timedelta(days=exhibitor_prep_days),
        "post_show_until": end + timedelta(days=post_show_days),
        "source_url": source_url,
        "source_name": source_name,
        "source_status": "seed",
        "source_verified_at": None,
    }


# Seed catalog. Dates are intentionally stored locally so AI generation never depends on live web access.
# Source refresh can verify/update these entries into .auto_state/trade_show_sources.json.
SHOWS: List[Dict] = [
    _show(
        "whx-miami-2026",
        "WHX Miami",
        "Miami, USA",
        ["US"],
        "Americas",
        _d(2026, 6, 17),
        _d(2026, 6, 19),
        "Medical devices and healthcare trade for the Americas",
        "MEDIUM",
        "Formerly FIME. Near-term Americas medical show, useful for US, Canada and Latin America distributors and repair centers.",
        "https://www.worldhealthexpo.com/events/healthcare/miami/",
        "World Health Expo Miami official site",
        aliases=["FIME", "Florida International Medical Expo"],
        profile_types=["C", "E"],
        industry_tags=["medical", "distributor", "repair", "americas", "endoscopy"],
        post_show_days=21,
    ),
    _show(
        "medevice-boston-2026",
        "MEDevice Boston",
        "Boston, USA",
        ["US"],
        "North America",
        _d(2026, 8, 26),
        _d(2026, 8, 27),
        "Medtech innovation, medical device development and manufacturing",
        "MEDIUM",
        "Good US East Coast medtech manufacturing opener. Useful for OEM and engineering contacts arranging samples or supplier meetings.",
        "https://www.medeviceboston.com/",
        "MEDevice Boston official site",
        aliases=["BIOMEDevice Boston"],
        profile_types=["A", "B", "C"],
        industry_tags=["medical", "oem", "manufacturing", "medtech"],
    ),
    _show(
        "medical-fair-asia-2026",
        "Medical Fair Asia",
        "Singapore",
        ["SG"],
        "APAC",
        _d(2026, 9, 9),
        _d(2026, 9, 11),
        "Hospital, diagnostic, pharmaceutical and medical equipment for Southeast Asia",
        "MEDIUM",
        "Useful regional opener for Southeast Asia distributors, repair centers and emerging OEMs.",
        "https://www.medicalfair-asia.com/event-overview/",
        "Medical Fair Asia official overview",
        profile_types=["C", "D", "E"],
        industry_tags=["medical", "endoscopy", "distributor", "repair", "apac"],
    ),
    _show(
        "cioe-2026",
        "CIOE",
        "Shenzhen, China",
        ["CN"],
        "APAC",
        _d(2026, 9, 9),
        _d(2026, 9, 11),
        "Optoelectronics, precision optics, laser, infrared, sensing",
        "MEDIUM",
        "Good optics supply-chain signal for precision optics, coating and photonics companies.",
        "https://www.cioe.cn/en/",
        "CIOE official site",
        aliases=["China International Optoelectronic Expo"],
        profile_types=["A", "B"],
        industry_tags=["optics", "photonics", "coating", "laser", "optoelectronics"],
    ),
    _show(
        "cmef-autumn-2026",
        "CMEF Autumn",
        "Beijing, China",
        ["CN"],
        "APAC",
        _d(2026, 10, 21),
        _d(2026, 10, 24),
        "Medical equipment and healthcare technology",
        "MEDIUM",
        "Strong APAC medical device context. Good for OEMs and emerging-market medical equipment buyers.",
        "https://www.cmef.com.cn/en",
        "CMEF official site",
        profile_types=["B", "C", "E"],
        industry_tags=["medical", "oem", "distributor", "endoscopy"],
    ),
    _show(
        "optatec-2028",
        "OPTATEC",
        "Frankfurt, Germany",
        ["DE"],
        "Europe",
        _d(2028, 5, 9),
        _d(2028, 5, 11),
        "Optical components, precision optics, optomechanics, coatings and metrology",
        "HIGH",
        "Direct fit for the optical component supply chain. Strong opener for precision optics manufacturers and metrology teams.",
        "https://www.optatec-messe.de/en/",
        "OPTATEC official site",
        profile_types=["A", "B"],
        industry_tags=["optics", "photonics", "coating", "metrology", "components"],
        outreach_days=42,
        exhibitor_prep_days=120,
    ),
    _show(
        "medica-2026",
        "MEDICA",
        "Dusseldorf, Germany",
        ["DE"],
        "Europe",
        _d(2026, 11, 16),
        _d(2026, 11, 19),
        "Medical devices, endoscopy, hospital equipment",
        "HIGH",
        "World-leading medical trade fair. Best timing hook for EU medical-device OEMs, repair centers and distributors.",
        "https://www.medica-tradefair.com/",
        "MEDICA official site",
        profile_types=["B", "C", "E"],
        industry_tags=["medical", "endoscopy", "oem", "repair", "distributor"],
    ),
    _show(
        "compamed-2026",
        "COMPAMED",
        "Dusseldorf, Germany",
        ["DE"],
        "Europe",
        _d(2026, 11, 16),
        _d(2026, 11, 19),
        "Medical technology supplier sector, components, manufacturing and product development",
        "HIGH",
        "Supplier-side companion to MEDICA. Very relevant for component buyers, contract manufacturers and OEM engineering teams.",
        "https://www.compamed-tradefair.com/en/Exhibit/Information/At_a_glance",
        "COMPAMED official at-a-glance",
        profile_types=["A", "B", "C"],
        industry_tags=["medical", "components", "oem", "manufacturing", "optics"],
    ),
    _show(
        "whx-dubai-2027",
        "WHX Dubai",
        "Dubai, UAE",
        ["AE"],
        "Middle East",
        _d(2027, 1, 25),
        _d(2027, 1, 28),
        "Healthcare, medical devices, Middle East distribution",
        "HIGH",
        "Formerly Arab Health. Best timing hook for Middle East distributors, repair centers, veterinary and industrial scope buyers.",
        "https://www.worldhealthexpo.com/events/healthcare/dubai/",
        "World Health Expo Dubai official site",
        aliases=["Arab Health"],
        profile_types=["C", "D", "E"],
        industry_tags=["medical", "distributor", "repair", "veterinary", "middle east"],
    ),
    _show(
        "vmx-2027",
        "VMX",
        "Orlando, USA",
        ["US"],
        "North America",
        _d(2027, 1, 17),
        _d(2027, 1, 20),
        "Veterinary equipment and animal healthcare",
        "LOW",
        "Specialized timing hook for niche medical-device assemblers and repair companies.",
        "https://vmxconference.com/",
        "VMX official site",
        aliases=["Veterinary Meeting & Expo"],
        profile_types=["D", "E"],
        industry_tags=["veterinary", "endoscopy", "repair", "medical"],
    ),
    _show(
        "spie-bios-2027",
        "SPIE BiOS Expo",
        "San Francisco, USA",
        ["US"],
        "North America",
        _d(2027, 1, 30),
        _d(2027, 1, 31),
        "Biomedical optics, biophotonics, medical imaging and diagnostics",
        "HIGH",
        "Very strong fit for biomedical and medical-device R&D contacts. Natural bridge between suppliers and device teams.",
        "https://lux.spie.org/conferences-and-exhibitions/photonics-west/exhibitions/bios-expo",
        "SPIE BiOS official page",
        profile_types=["A", "B"],
        industry_tags=["biomedical optics", "medical", "optics", "endoscopy", "imaging"],
    ),
    _show(
        "spie-photonics-west-2027",
        "SPIE Photonics West",
        "San Francisco, USA",
        ["US"],
        "North America",
        _d(2027, 1, 30),
        _d(2027, 2, 4),
        "Photonics, lasers, biomedical optics, precision optics",
        "HIGH",
        "Largest North American photonics timing hook. Strong for precision optics, coating houses and biomedical optics R&D teams.",
        "https://spie.org/conferences-and-exhibitions/photonics-west",
        "SPIE Photonics West official page",
        profile_types=["A", "B"],
        industry_tags=["optics", "photonics", "laser", "biomedical optics", "coating"],
    ),
    _show(
        "mdm-west-2027",
        "MD&M West",
        "Anaheim, USA",
        ["US"],
        "North America",
        _d(2027, 2, 9),
        _d(2027, 2, 11),
        "Medical design and manufacturing, medtech supply chain",
        "MEDIUM",
        "Good US manufacturing and OEM supply-chain opener for contract manufacturers and medical device engineers.",
        "https://www.mdmwest.com/",
        "MD&M West official site",
        profile_types=["B", "C"],
        industry_tags=["medical", "manufacturing", "oem", "medtech", "components"],
    ),
    _show(
        "laser-photonics-china-2027",
        "Laser World of Photonics China",
        "Shanghai, China",
        ["CN"],
        "APAC",
        _d(2027, 3, 8),
        _d(2027, 3, 10),
        "Laser, photonics, optics components and systems",
        "MEDIUM",
        "China/APAC optics timing hook for photonics suppliers, precision optics and coating prospects.",
        "https://world-of-photonics-china.com.cn/en",
        "Laser World of Photonics China official site",
        profile_types=["A", "B"],
        industry_tags=["optics", "photonics", "laser", "coating"],
    ),
    _show(
        "whx-lagos-2027",
        "WHX Lagos",
        "Lagos, Nigeria",
        ["NG"],
        "Africa",
        _d(2027, 6, 1),
        _d(2027, 6, 3),
        "Healthcare and medical devices for West Africa",
        "LOW",
        "Useful regional opener for Africa distributors and hospital equipment buyers.",
        "https://www.worldhealthexpo.com/events/events/",
        "World Health Expo global calendar",
        profile_types=["C", "E"],
        industry_tags=["medical", "distributor", "africa"],
    ),
    _show(
        "whx-miami-2027",
        "WHX Miami",
        "Miami, USA",
        ["US"],
        "Americas",
        _d(2027, 6, 16),
        _d(2027, 6, 18),
        "Medical devices and healthcare trade for the Americas",
        "MEDIUM",
        "Formerly FIME. Useful timing hook for US, Canada and Latin America distributors and repair centers.",
        "https://www.worldhealthexpo.com/events/healthcare/miami/",
        "World Health Expo Miami official site",
        aliases=["FIME"],
        profile_types=["C", "E"],
        industry_tags=["medical", "distributor", "repair", "americas"],
    ),
    _show(
        "laser-world-of-photonics-2027",
        "LASER World of Photonics",
        "Munich, Germany",
        ["DE"],
        "Europe",
        _d(2027, 6, 22),
        _d(2027, 6, 25),
        "Photonics components, systems and applications",
        "HIGH",
        "World-leading photonics event. Excellent opener for European precision optics, coating and photonics prospects.",
        "https://world-of-photonics.com/en/trade-fair/",
        "LASER World of Photonics official site",
        profile_types=["A", "B"],
        industry_tags=["optics", "photonics", "laser", "coating", "components"],
    ),
    _show(
        "medical-fair-thailand-2027",
        "Medical Fair Thailand",
        "Bangkok, Thailand",
        ["TH"],
        "APAC",
        _d(2027, 9, 8),
        _d(2027, 9, 10),
        "Medical and rehabilitation equipment for Southeast Asia",
        "LOW",
        "Regional opener for Thailand and ASEAN medical distributors.",
        "https://www.medicalfair-thailand.com/event-overview/",
        "Medical Fair Thailand official overview",
        profile_types=["C", "D", "E"],
        industry_tags=["medical", "distributor", "repair", "apac"],
    ),
    _show(
        "medical-japan-osaka-2027",
        "Medical Japan Osaka",
        "Osaka, Japan",
        ["JP"],
        "APAC",
        _d(2027, 9, 29),
        _d(2027, 10, 1),
        "Medical, elderly care and pharmacy week",
        "LOW",
        "Japan/APAC healthcare opener. Useful for Japanese medical equipment buyers and regional partners.",
        "https://www.medical-jpn.jp/osaka/en-gb/about.html",
        "Medical Japan Osaka official outline",
        profile_types=["B", "C", "E"],
        industry_tags=["medical", "oem", "distributor", "apac"],
    ),
]


def _normalize_country(country: str | None) -> str:
    if not country:
        return ""
    raw = str(country).strip().upper()
    return COUNTRY_ALIASES.get(raw, raw[:2] if len(raw) == 2 else raw)


def _country_region(country_code: str) -> str:
    for region, countries in REGION_COUNTRIES.items():
        if country_code in countries:
            return region
    return ""


def _date_range(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%b %d, %Y")
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%b %d')}-{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}"


def _phase_for_show(show: Dict, d: date) -> Tuple[str, str]:
    start, end = show["dates"]
    exhibitor_start = show["exhibitor_prep_start"]
    outreach_start = show["outreach_window_start"]
    post_until = show["post_show_until"]

    if d < exhibitor_start:
        return "future", "future watchlist"
    if exhibitor_start <= d < outreach_start:
        return "exhibitor_planning", "exhibitor planning window"
    if outreach_start <= d < start:
        return "pre_show", "pre-show outreach window open"
    if start <= d <= end:
        return "live", "show is live"
    if end < d <= post_until:
        return "post_show", "post-show follow-up window"
    return "closed", "closed"


def _industry_tokens(industry: str | None) -> set:
    if not industry:
        return set()
    text = re.sub(r"[^a-zA-Z0-9]+", " ", str(industry).lower())
    tokens = {t for t in text.split() if len(t) >= 3}
    synonyms = set(tokens)
    if {"scope", "scopes", "endoscope", "endoscopy", "borescope"} & tokens:
        synonyms.update({"endoscopy", "medical", "optics"})
    if {"lens", "optical", "optics", "photonics", "coating"} & tokens:
        synonyms.update({"optics", "photonics", "coating"})
    if {"repair", "service", "maintenance"} & tokens:
        synonyms.update({"repair", "aftermarket"})
    return synonyms


def _score_show(show: Dict, country_code: str, industry: str | None, profile_type: str | None, d: date) -> Tuple[int, List[str]]:
    score = {"HIGH": 45, "MEDIUM": 32, "LOW": 18}.get(show.get("priority"), 18)
    reasons = [f"{show.get('priority', 'LOW')} priority event"]

    prospect_region = _country_region(country_code)
    show_region = show.get("region", "")
    if country_code and country_code in show.get("country_codes", []):
        score += 30
        reasons.append("local country match")
    elif country_code and prospect_region and prospect_region == show_region:
        score += 18
        reasons.append("regional match")

    profile = (profile_type or "").strip().upper()
    if profile and profile in show.get("profile_types", []):
        score += 15
        reasons.append(f"Profile {profile} match")

    tokens = _industry_tokens(industry)
    tags = set(show.get("industry_tags", []))
    overlap = tokens & tags
    if overlap:
        score += min(12, 4 * len(overlap))
        reasons.append("industry match: " + ", ".join(sorted(overlap)[:3]))

    phase, _ = _phase_for_show(show, d)
    if phase == "pre_show":
        score += 20
        reasons.append("best outreach timing")
    elif phase == "live":
        score += 16
        reasons.append("live event timing")
    elif phase == "post_show":
        score += 14
        reasons.append("post-show follow-up timing")
    elif phase == "exhibitor_planning":
        score += 10
        reasons.append("early planning timing")

    return min(100, score), reasons


def _angle_for_show(show: Dict, country_code: str, phase: str, local_or_regional: bool) -> str:
    name = show["name"]
    location = show["location"]
    if phase == "post_show":
        return (
            f"Use {name} as a post-show follow-up angle: ask if they saw any new supply-chain "
            f"requirements or related projects after the event."
        )
    if phase == "live":
        return (
            f"Use {name} as a timely opener: ask whether they are following the show this week "
            f"and connect it to component supply or repair parts."
        )
    if phase == "pre_show":
        if local_or_regional:
            return (
                f"Ask lightly if they are attending or following {name} in {location}. "
                f"Even if they are not going, it is a natural timing hook for their market."
            )
        return (
            f"Mention {name} as a market-timing hook, not as an assumption. "
            f"Ask if this event is relevant to their sourcing plans this season."
        )
    if phase == "exhibitor_planning":
        return (
            f"Use {name} as an early planning signal: exhibitors and OEM teams are arranging "
            f"samples, booth demos and supplier meetings now."
        )
    return (
        f"Keep {name} on the radar as a future timing hook for a later follow-up."
    )


def _serialize_show(show: Dict) -> Dict:
    data = dict(show)
    data["dates"] = [show["dates"][0].isoformat(), show["dates"][1].isoformat()]
    for key in ("outreach_window_start", "exhibitor_prep_start", "post_show_until"):
        if isinstance(data.get(key), date):
            data[key] = data[key].isoformat()
    return data


def _load_source_cache() -> Dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_cached_date(value: str | None) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except Exception:
        return None


def get_trade_show_catalog(use_cache: bool = True) -> List[Dict]:
    """Return local seed shows, optionally merged with verified cached source dates."""
    shows = deepcopy(SHOWS)
    if not use_cache:
        return shows

    cache = _load_source_cache()
    by_slug = cache.get("shows", {}) if isinstance(cache, dict) else {}
    for show in shows:
        item = by_slug.get(show.get("slug"), {})
        if not item:
            continue
        start = _parse_cached_date(item.get("start"))
        end = _parse_cached_date(item.get("end"))
        if start and end and start <= end:
            show["dates"] = (start, end)
            show["outreach_window_start"] = start - timedelta(days=show.get("outreach_days", 28))
            show["exhibitor_prep_start"] = start - timedelta(days=show.get("exhibitor_prep_days", 84))
            show["post_show_until"] = end + timedelta(days=show.get("post_show_days", 10))
        show["source_status"] = item.get("status", show.get("source_status", "seed"))
        show["source_verified_at"] = item.get("verified_at")
        if item.get("source_excerpt"):
            show["source_excerpt"] = item.get("source_excerpt")
    return shows


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _make_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_future_date_range(text: str, today: date) -> Tuple[Optional[date], Optional[date], str]:
    """Best-effort parser for common official-event date formats."""
    candidates = []
    patterns = [
        # 16 - 19 November 2026
        re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b", re.I),
        # November 16-19, 2026
        re.compile(r"\b([A-Za-z]+)\s+(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2}),?\s+(\d{4})\b", re.I),
        # January 30 - February 4, 2027
        re.compile(r"\b([A-Za-z]+)\s+(\d{1,2})\s*(?:-|–|to)\s*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
        # Sep. 29 (Wed) - Oct. 1 (Fri), 2027
        re.compile(r"\b([A-Za-z]+)\.?\s+(\d{1,2})(?:\s*\([^)]+\))?\s*(?:-|–|to)\s*([A-Za-z]+)\.?\s+(\d{1,2})(?:\s*\([^)]+\))?,?\s+(\d{4})\b", re.I),
    ]

    for m in patterns[0].finditer(text):
        day1, day2, month_name, year = m.groups()
        month = MONTHS.get(month_name.lower().strip("."))
        if month:
            start = _make_date(int(year), month, int(day1))
            end = _make_date(int(year), month, int(day2))
            if start and end:
                candidates.append((start, end, m.group(0)))

    for m in patterns[1].finditer(text):
        month_name, day1, day2, year = m.groups()
        month = MONTHS.get(month_name.lower().strip("."))
        if month:
            start = _make_date(int(year), month, int(day1))
            end = _make_date(int(year), month, int(day2))
            if start and end:
                candidates.append((start, end, m.group(0)))

    for m in patterns[2].finditer(text):
        month1, day1, month2, day2, year = m.groups()
        m1 = MONTHS.get(month1.lower().strip("."))
        m2 = MONTHS.get(month2.lower().strip("."))
        if m1 and m2:
            start = _make_date(int(year), m1, int(day1))
            end = _make_date(int(year), m2, int(day2))
            if start and end:
                candidates.append((start, end, m.group(0)))

    for m in patterns[3].finditer(text):
        month1, day1, month2, day2, year = m.groups()
        m1 = MONTHS.get(month1.lower().strip("."))
        m2 = MONTHS.get(month2.lower().strip("."))
        if m1 and m2:
            start = _make_date(int(year), m1, int(day1))
            end = _make_date(int(year), m2, int(day2))
            if start and end:
                candidates.append((start, end, m.group(0)))

    future = [c for c in candidates if c[1] >= today - timedelta(days=14)]
    if not future:
        return None, None, ""
    future.sort(key=lambda x: x[0])
    return future[0]


def refresh_trade_show_sources(force: bool = False, timeout: int = 8) -> Dict:
    """Verify/update event dates from source URLs and cache the result.

    This is designed for a scheduled task or a manual admin call. AI prompt building reads the
    cache only; it does not make live network calls during cold outreach.
    """
    now = datetime.utcnow()
    today = date.today()
    cache = _load_source_cache()
    if not force:
        last = cache.get("updated_at") if isinstance(cache, dict) else None
        try:
            if last and (now - datetime.fromisoformat(last)).days < SOURCE_CACHE_DAYS:
                return cache
        except Exception:
            pass

    result = {"updated_at": now.isoformat(), "shows": {}}
    if httpx is None:
        result["error"] = "httpx not available"
        return result

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": "冷开发 trade show verifier"}) as client:
        for show in SHOWS:
            slug = show["slug"]
            item = {
                "name": show["name"],
                "source_url": show.get("source_url"),
                "verified_at": now.isoformat(),
                "status": "seed",
                "start": show["dates"][0].isoformat(),
                "end": show["dates"][1].isoformat(),
            }
            try:
                resp = client.get(show["source_url"])
                resp.raise_for_status()
                text = _html_to_text(resp.text)
                start, end, excerpt = _extract_future_date_range(text, today)
                if start and end:
                    item.update({
                        "status": "verified",
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "source_excerpt": excerpt[:180],
                    })
                else:
                    item.update({"status": "checked_no_date"})
            except Exception as exc:
                item.update({"status": "source_error", "error": str(exc)[:180]})
            result["shows"][slug] = item

    CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def get_upcoming_shows(d: date = None, days_ahead: int = 90) -> List[Dict]:
    """Return shows with an active or soon-opening sales window."""
    if d is None:
        d = date.today()

    upcoming = []
    for show in get_trade_show_catalog():
        _, end = show["dates"]
        if d > show["post_show_until"]:
            continue
        ws = show["outreach_window_start"]
        prep = show["exhibitor_prep_start"]
        if prep <= d <= show["post_show_until"]:
            upcoming.append(show)
        elif d < ws <= d + timedelta(days=days_ahead):
            upcoming.append(show)
        elif d < prep <= d + timedelta(days=days_ahead):
            upcoming.append(show)
        elif d < show["dates"][0] <= d + timedelta(days=days_ahead):
            upcoming.append(show)
        elif d <= end <= d + timedelta(days=days_ahead):
            upcoming.append(show)

    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    upcoming.sort(key=lambda s: (priority_rank.get(s["priority"], 3), s["outreach_window_start"]))
    return upcoming


def get_prospect_trade_show_signals(
    country: str = None,
    industry: str = None,
    profile_type: str = None,
    d: date = None,
    days_ahead: int = 180,
    limit: int = 5,
) -> List[Dict]:
    """Return ranked event signals for one prospect."""
    if d is None:
        d = date.today()
    country_code = _normalize_country(country)
    prospect_region = _country_region(country_code)

    signals = []
    horizon = d + timedelta(days=days_ahead)
    for show in get_trade_show_catalog():
        start, end = show["dates"]
        if d > show["post_show_until"] or show["exhibitor_prep_start"] > horizon:
            continue
        phase, phase_label = _phase_for_show(show, d)
        if phase == "closed":
            continue
        score, reasons = _score_show(show, country_code, industry, profile_type, d)
        local_or_regional = bool(
            country_code and (
                country_code in show.get("country_codes", []) or
                (prospect_region and prospect_region == show.get("region"))
            )
        )
        signal = _serialize_show(show)
        signal.update({
            "fit_score": score,
            "fit_reasons": reasons,
            "phase": phase,
            "phase_label": phase_label,
            "days_to_start": (start - d).days,
            "days_since_end": (d - end).days if d > end else None,
            "is_local_or_regional": local_or_regional,
            "timing_angle": _angle_for_show(show, country_code, phase, local_or_regional),
            "date_range": _date_range(start, end),
        })
        signals.append(signal)

    signals.sort(key=lambda s: (-s["fit_score"], s["days_to_start"]))
    return signals[:limit]


def get_show_context_for_prospect(
    country: str = None,
    industry: str = None,
    profile_type: str = None,
    d: date = None,
) -> str:
    """Return AI prompt context about relevant global trade shows for one prospect."""
    signals = get_prospect_trade_show_signals(
        country=country,
        industry=industry,
        profile_type=profile_type,
        d=d,
        days_ahead=180,
        limit=5,
    )

    if not signals:
        return "No major trade shows with useful outreach timing in the next 180 days."

    lines = [
        "Use trade shows as a light market-timing opener. Do not assume the prospect or the company will attend unless explicitly known.",
        "Even if the prospect does not attend, the show is still a natural reason to discuss sourcing, samples, repair demand, or new projects.",
    ]
    for s in signals:
        local = "LOCAL/REGIONAL" if s["is_local_or_regional"] else "GLOBAL"
        lines.append(
            f"- {s['name']} ({s['date_range']}, {s['location']}) "
            f"[{s['priority']}, fit {s['fit_score']}/100, {local}, {s['phase_label']}]: "
            f"{s['timing_angle']} 冷开发 relevance: {s['relevance']}"
        )
    return "\n".join(lines)


def is_show_outreach_window_active(show: Dict, d: date = None) -> bool:
    """Check if we are in the standard pre-show outreach window."""
    if d is None:
        d = date.today()
    return show["outreach_window_start"] <= d <= show["dates"][1]


def get_show_icebreaker(
    country: str = None,
    industry: str = None,
    profile_type: str = None,
    d: date = None,
) -> Optional[str]:
    """Return one trade-show opener for email/LinkedIn drafting."""
    signals = get_prospect_trade_show_signals(
        country=country,
        industry=industry,
        profile_type=profile_type,
        d=d,
        days_ahead=180,
        limit=1,
    )
    if not signals:
        return None

    s = signals[0]
    return (
        f"Use {s['name']} ({s['date_range']}, {s['location']}) as a soft opener. "
        f"{s['timing_angle']} Keep it natural: ask if they are following or planning around the event; "
        f"do not assume attendance."
    )
