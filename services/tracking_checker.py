"""
Auto logistics tracker — polls DHL/FedEx/UPS tracking pages and updates
sample events when status changes. Designed to run as a scheduled task.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.error
import ssl
from datetime import datetime

# -- Path setup --
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tracking_checker")

# Ignore SSL warnings for scraping
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

STATUS_DELIVERED_KEYWORDS = [
    "delivered", "signed", "received", "handed to receiver",
    "shipment delivered", "配達完了", "已签收", "妥投", "已投递",
    "delivered - signed for by", "package delivered",
]

STATUS_IN_TRANSIT_KEYWORDS = [
    "in transit", "departed", "arrived at", "processed at",
    "out for delivery", "with delivery courier", "on the way",
    "customs", "clearance", "shipment picked up",
    "transportation", "运输中", "转运中", "清关中", "派送中",
    "arrival scan", "departure scan", "destination scan",
]

def _fetch(url, data=None, method="GET"):
    """Fetch URL with retries."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
            r = urllib.request.urlopen(req, timeout=20, context=ssl_ctx)
            return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == 2:
                logger.warning("Fetch failed for %s: %s", url[:80], e)
                return None
            time.sleep(2)


def check_dhl(tracking_number):
    """Scrape DHL Express tracking page."""
    url = f"https://www.dhl.com/global-en/home/tracking/tracking-express.html?submit=1&tracking-id={tracking_number}"
    html = _fetch(url)
    if not html:
        return None

    # DHL page loads data via API — try the direct API endpoint
    api_url = f"https://www.dhl.com/utapi?trackingNumber={tracking_number}&language=en&requesterCountryCode=DE"
    api_html = _fetch(api_url)
    if api_html:
        try:
            data = json.loads(api_html)
            results = data.get("results", [])
            if results:
                checkpoints = results[0].get("checkpoints", [])
                if checkpoints:
                    latest = checkpoints[0]
                    status = latest.get("description", "")
                    location = latest.get("location", "")
                    timestamp = latest.get("time", "")
                    is_delivered = "delivered" in status.lower() or "signed" in status.lower()
                    return {
                        "status": "delivered" if is_delivered else "in_transit",
                        "description": status,
                        "location": location,
                        "timestamp": timestamp,
                        "raw": str(checkpoints[:3]),
                    }
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

    # Fallback: search page HTML for status text
    return _extract_from_html(html, "dhl")


def check_fedex(tracking_number):
    """Scrape FedEx tracking page."""
    url = f"https://www.fedex.com/fedextrack/?trknbr={tracking_number}"
    html = _fetch(url)
    if not html:
        return None

    # FedEx embeds tracking data in a <script> tag
    pattern = r'<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            # Navigate into tracking data
            track_data = data.get("trackingData", data)
            if isinstance(track_data, dict):
                status = track_data.get("displayStatus", "") or track_data.get("status", "")
                scans = track_data.get("scanEventList", []) or track_data.get("events", [])
                latest_scan = scans[0] if scans else {}
                desc = latest_scan.get("status", "") or status
                city = latest_scan.get("city", "") or latest_scan.get("scanLocation", {}).get("city", "")
                date = latest_scan.get("date", "") or latest_scan.get("scanDate", "")
                is_delivered = "delivered" in desc.lower()
                return {
                    "status": "delivered" if is_delivered else "in_transit",
                    "description": desc,
                    "location": city,
                    "timestamp": date,
                    "raw": json.dumps(scans[:3]) if scans else "",
                }
        except (json.JSONDecodeError, KeyError):
            pass

    return _extract_from_html(html, "fedex")


def check_ups(tracking_number):
    """Scrape UPS tracking page."""
    url = f"https://www.ups.com/track?loc=en_US&tracknum={tracking_number}"
    html = _fetch(url)
    if not html:
        return None

    # UPS uses __INITIAL_STATE__
    pattern = r'<script[^>]*>\s*window\.__INITIAL_STATE__\s*=\s*({.*?});\s*</script>'
    match = re.search(pattern, html, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            # Walk into tracking response
            track = data
            for key in ("tracking", "trackedData", "trackDetails"):
                if isinstance(track, dict) and key in track:
                    track = track[key]
                elif isinstance(track, list) and track:
                    track = track[0]
            if isinstance(track, dict):
                status = track.get("progressBarStatus", "") or track.get("packageStatus", "")
                events = track.get("shipmentActivities", []) or track.get("activities", [])
                latest = events[0] if events else {}
                desc = latest.get("activity", "") or latest.get("statusDescription", "") or status
                loc = latest.get("location", "") or latest.get("city", "")
                date = latest.get("date", "") or latest.get("timestamp", "")
                is_delivered = "delivered" in desc.lower()
                return {
                    "status": "delivered" if is_delivered else "in_transit",
                    "description": desc if isinstance(desc, str) else str(desc),
                    "location": loc if isinstance(loc, str) else "",
                    "timestamp": date if isinstance(date, str) else "",
                    "raw": str(events[:3]),
                }
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return _extract_from_html(html, "ups")


def _extract_from_html(html, carrier):
    """Fallback: extract tracking status from HTML keywords."""
    if not html:
        return None
    text = html.lower()
    for kw in STATUS_DELIVERED_KEYWORDS:
        if kw.lower() in text:
            return {"status": "delivered", "description": kw, "location": "", "timestamp": "", "raw": "html-scan"}
    for kw in STATUS_IN_TRANSIT_KEYWORDS:
        if kw.lower() in text:
            return {"status": "in_transit", "description": kw, "location": "", "timestamp": "", "raw": "html-scan"}
    return None


def check_tracking(carrier, tracking_number):
    """Route to correct checker."""
    c = (carrier or "").lower()
    if "dhl" in c:
        return check_dhl(tracking_number)
    if "fedex" in c or "fdx" in c:
        return check_fedex(tracking_number)
    if "ups" in c:
        return check_ups(tracking_number)
    # Try all for unknown carriers
    for fn in [check_dhl, check_fedex, check_ups]:
        r = fn(tracking_number)
        if r:
            return r
    return None


def run_check():
    """Main entry point — checks all active tracking numbers in the DB."""
    from database import SessionLocal
    from models import SampleEvent, Prospect

    db = SessionLocal()
    try:
        # Find all tracking numbers that need checking (stage = 'sent' and has tracking)
        events = (
            db.query(SampleEvent)
            .filter(
                SampleEvent.stage == "sent",
                SampleEvent.tracking_number.isnot(None),
                SampleEvent.tracking_number != "",
            )
            .all()
        )

        if not events:
            logger.info("No active tracking numbers to check")
            return {"checked": 0, "updated": 0}

        checked = 0
        updated = 0

        for ev in events:
            carrier = ev.carrier or ""
            tn = ev.tracking_number.strip()
            if not tn:
                continue

            checked += 1
            logger.info("Checking %s %s (event #%d)", carrier, tn, ev.id)

            result = check_tracking(carrier, tn)
            if not result:
                logger.info("  No status found for %s", tn)
                continue

            new_status = result["status"]
            desc = result["description"]
            loc = result.get("location", "")
            ts = result.get("timestamp", "")
            raw = result.get("raw", "")

            # Build a fingerprint of the current state to detect changes
            fingerprint = f"{new_status}|{desc}|{loc}|{ts}"
            old_fingerprint = (ev.logistics_status or "") + "||"

            # Parse old fingerprint
            old_parts = old_fingerprint.split("|")
            old_status_text = old_parts[0] if len(old_parts) > 0 else ""

            if fingerprint != old_fingerprint or not ev.logistics_status:
                logger.info("  STATUS CHANGE: %s -> %s", old_status_text, desc)

                # Update the sample event
                ev.logistics_status = fingerprint
                ev.note = (ev.note or "") + f"\n[Auto-track {datetime.now().strftime('%m-%d %H:%M')}] {desc} ({loc})"

                # If delivered, auto-advance stage
                if new_status == "delivered":
                    ev.stage = "received"
                    ev.event_date = datetime.now().strftime("%Y-%m-%d")

                    # Also sync prospect
                    prospect = db.query(Prospect).filter(Prospect.id == ev.prospect_id).first()
                    if prospect:
                        prospect.sample_status = "received"
                        prospect.next_follow_date = datetime.now().strftime("%Y-%m-%d")
                        prospect.reminder_note = f"[Auto-track] 样品已送达 — {desc}"
                        prospect.reminder_updated_at = datetime.utcnow()
                        prospect.updated_at = datetime.utcnow()
                        prospect.last_edited_at = datetime.utcnow()

                updated += 1
            else:
                logger.info("  No change for %s", tn)

        db.commit()
        logger.info("Done: checked=%d updated=%d", checked, updated)
        return {"checked": checked, "updated": updated}

    except Exception as e:
        db.rollback()
        logger.exception("run_check failed: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


if __name__ == "__main__":
    result = run_check()
    print(json.dumps(result, ensure_ascii=False))
