"""FDA 510(k) registration lookup service (US medical-device database).

Only relevant when a prospect looks like a regulated medical-device company:
FDA 510(k) clearance proves the company is real, has passed regulatory review
and sells commercial products in the US market.

Uses openFDA API — free, no key required, rate-limited to 240 req/min.
"""

import asyncio
import json
import logging
from datetime import datetime
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov/device/510k.json"


async def lookup_fda_510k(company: str, max_results: int = 10) -> dict:
    """Search FDA 510(k) database for a company (applicant name).

    Returns dict with:
        total_count: int — total matching records
        devices: list of {k_number, device_name, decision_date, clearance_status}
    has_regulatory_signal: bool — whether the company has US device registrations
        searched_at: ISO datetime string
    """
    if not company or not company.strip():
        return {
            "total_count": 0,
            "devices": [],
            "has_regulatory_signal": False,
            "searched_at": datetime.utcnow().isoformat(),
        }

    # Clean company name for search — remove legal suffixes
    search_name = company.strip()
    for suffix in [" Inc.", " Inc", " LLC", " Ltd.", " Ltd", " GmbH", " AG", " S.L.", " S.A."]:
        if search_name.endswith(suffix):
            search_name = search_name[: -len(suffix)].strip()

    query = f'applicant:"{search_name}"'
    encoded_query = quote_plus(query)

    result = {
        "total_count": 0,
        "devices": [],
        "has_regulatory_signal": False,
        "searched_at": datetime.utcnow().isoformat(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Tuodan-Prospect-Engine/1.0",
                "Accept": "application/json",
            },
        ) as client:
            url = f"{OPENFDA_BASE}?search={encoded_query}&limit={max_results}"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                logger.info("FDA 510(k): no results for %s", company)
                return result

            meta = data.get("meta", {}).get("results", {})
            result["total_count"] = meta.get("total", 0)

            records = data.get("results", [])
            device_keywords = [
                "endoscope", "endoscopic", "endoscopy",
                "laparoscope", "laparoscopic",
                "microscope", "microscopic",
                "lens", "optical", "optic",
                "camera", "imaging", "visualization",
                "surgical microscope", "colposcope",
                "arthroscope", "cystoscope", "bronchoscope",
                "laryngoscope", "otoscope", "ophthalmoscope",
                "fundus", "retinal", "illumination",
                "light source", "light guide",
                "fiber optic", "fibre optic",
            ]

            for rec in records:
                device_name = rec.get("device_name", "")
                k_number = rec.get("k_number", "")
                decision_date = rec.get("decision_date", "")
                # openFDA returns dates as YYYYMMDD
                if decision_date and len(decision_date) == 8:
                    decision_date = f"{decision_date[:4]}-{decision_date[4:6]}-{decision_date[6:8]}"

                device_info = {
                    "k_number": k_number,
                    "device_name": device_name[:200] if device_name else "",
                    "decision_date": decision_date,
                }
                result["devices"].append(device_info)

                # Check for device relevance
                if not result["has_regulatory_signal"]:
                    dl = device_name.lower()
                    if any(kw in dl for kw in device_keywords):
                        result["has_regulatory_signal"] = True

            logger.info("FDA 510(k): %s -> %d records (regulatory signal: %s)",
                        company, result["total_count"], result["has_regulatory_signal"])

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.info("FDA 510(k): no records found for %s", company)
        else:
            logger.warning("FDA 510(k) API error %d for %s: %s", exc.response.status_code, company, exc)
    except httpx.TimeoutException:
        logger.warning("FDA 510(k) search timed out for %s", company)
    except Exception as exc:
        logger.warning("FDA 510(k) search failed for %s: %s", company, exc)

    return result
