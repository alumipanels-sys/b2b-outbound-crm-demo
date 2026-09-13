"""Knowledge base self-evolution engine.

The skill layer (prompts in skills/) is industry-generic methodology.
The knowledge base is the customer-specific content that plugs into it.
This engine helps each customer fill, improve, and learn from their own
knowledge base:

1. coverage_report()  — what essential knowledge exists / is missing
2. ensure_gap()       — idempotent recording of "please fill this in"
3. suggest_questions()— AI generates the exact questions to answer
4. generate_draft()   — AI polishes raw customer input into a KB entry
5. save_history()/restore_version() — safe editing with rollback
6. extract_candidates() — learn reusable knowledge from real outcomes
"""

import json
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from models import KnowledgeBase, KnowledgeGap, KnowledgeHistory

logger = logging.getLogger(__name__)


# Essential knowledge every customer should have, with coverage weights.
ESSENTIAL_CATEGORIES = {
    "profile": {
        "name": "Company positioning",
        "weight": 25,
        "question": "What does our company do? Positioning, founding year, size, and core differentiating selling points?",
        "reason": "The AI needs your company positioning to speak for you when writing outreach emails and scoring prospects.",
    },
    "product": {
        "name": "Product specs",
        "weight": 25,
        "question": "What do we sell? Core product lines, spec ranges, quality standards, MOQ, lead time, and certifications?",
        "reason": "The AI needs concrete product facts to write technically convincing content instead of empty words.",
    },
    "guidelines": {
        "name": "Customer profile & strategy",
        "weight": 20,
        "question": "Which customers do we most want to develop? How are their pain points, decision chains, and priority tiers defined?",
        "reason": "So the AI knows who the ideal customer is — scoring and outreach order depend on it.",
    },
    "forbidden": {
        "name": "Do's and don'ts",
        "weight": 15,
        "question": "What must we never promise or do? Which customer types do we avoid?",
        "reason": "Prevents the AI from overpromising, exaggerating, or chasing the wrong customers.",
    },
    "pricing": {
        "name": "Pricing & quote strategy",
        "weight": 10,
        "question": "What are our price ranges, MOQs, payment terms, and negotiation floors?",
        "reason": "So the AI can respond compliantly and strategically when a client asks about price.",
    },
    "voice": {
        "name": "Language & tone",
        "weight": 5,
        "question": "What tone do we prefer — formal, friendly, or engineer-like? Any fixed signature or banned phrases?",
        "reason": "So the AI writes like someone from your own company.",
    },
}

# ── Customer profile coach: guides the user to define their ideal customer step by step ──
PROFILE_COACH = {
    "intro": (
        "Your customer profile is the soul of this system: it decides who the AI develops first, how it opens, and what it says. "
        "Answer the questions below with everything you know (it doesn't need to be perfect — the AI will organize it). "
        "If you cannot answer a question, that is exactly the information you still need — skip it for now and fill it in later."
    ),
    "framework_note": (
        "Buyer roles differ by industry: brands, distributors, retailers, OEMs, integrators, traders, end users... "
        "First list the roles that actually exist in your industry, then rank them by priority into A-E (A = highest priority, E = lowest). "
        "Skip roles that don't exist in your industry — the AI understands by industry."
    ),
    "roles": [
        "Brand / private label", "OEM manufacturer", "Contract manufacturer", "System integrator", "Distributor / wholesaler",
        "Retailer / chain", "E-commerce platform", "Trading company", "Project / contractor", "Repair / service provider", "End user",
    ],
    "framework": [
        {"tier": "A", "who": "Top-priority buyers: clearest demand, highest order value, strongest repeat purchase",
         "example": "Industry examples: auto parts = large distributor/import wholesaler; consumer electronics = brand; medical = hospital group"},
        {"tier": "B", "who": "Second priority: slightly weaker in size or repeat purchase, but worth proactive outreach",
         "example": "Industry examples: auto parts = OEM/private-label plant; industrial automation = system integrator; electronics = e-commerce distributor"},
        {"tier": "C", "who": "Middle tier: opportunity exists but needs nurturing",
         "example": "Industry examples: emerging-market brands, small/medium distributors"},
        {"tier": "D", "who": "Lower priority: small orders or one-off opportunities",
         "example": "Industry examples: one-off project buyers, small retailers; leave empty if not applicable"},
        {"tier": "E", "who": "Lowest priority: still worth contacting, but no proactive investment",
         "example": "Industry examples: repair/service shops, retail stores; many industries don't have this tier — leave empty"},
    ],
    "questions": [
        {"key": "roles", "q": "Which buyer roles exist in your industry? List every one you can think of",
         "hint": "Brands, distributors, retailers, OEMs, integrators, traders, end users… (see the role list above)"},
        {"key": "who", "q": "Who is your ideal customer? (industry, size, region, type of company)",
         "hint": "e.g. European mid-size auto-parts importer, 20-100 employees, aftermarket"},
        {"key": "need", "q": "What products do they buy from you, and in what use case?",
         "hint": "e.g. brake pads and suspension parts sold to garages/wholesalers"},
        {"key": "pain", "q": "What is their biggest pain point?",
         "hint": "e.g. unstable supply chains, delayed delivery, no reliable China supplier"},
        {"key": "who_buys", "q": "Who makes the decision? (purchasing/engineer/owner? how does the decision chain work)",
         "hint": "e.g. the purchasing manager screens first, the owner finally approves"},
        {"key": "signal", "q": "What signals indicate they have intent? (hiring, equipment, materials, website content…)",
         "hint": "e.g. hiring engineers, product-line expansion on their site"},
        {"key": "priority", "q": "Divide customers into 5 tiers — A (top priority), B, C, D, E. What kind of customer is each?",
         "hint": "Rank by priority, not by role: fill the tiers you have; leave empty or write \"none\" for the rest"},
        {"key": "exclude", "q": "Who is NOT your customer? Which types will you never touch?",
         "hint": "e.g. pure traders without physical operations, retail stores that only buy one SKU"},
    ],
}


def build_profile_raw(answers: dict) -> str:
    """Combine the coach answers into a structured block of raw material."""
    lines = ["Customer profile raw material (customer-provided):"]
    for q in PROFILE_COACH["questions"]:
        val = str(answers.get(q["key"], "") or "").strip()
        if val:
            lines.append(f"{q['q']}\nAnswer: {val}")
        else:
            lines.append(f"{q['q']}\nAnswer: (not provided by the customer — left blank)")
    return "\n\n".join(lines)


def generate_profile_draft(db: Session, answers: dict) -> dict:
    """Turn the customer's profile answers into a knowledge entry (customer profile & strategy) with AI."""
    raw = build_profile_raw(answers)
    return generate_draft(db, "guidelines", raw, title_hint="Customer profile & strategy")


def _entry_ok(entry) -> bool:
    return bool(entry and (entry.content or "").strip())


def _category_entries(db: Session, category: str):
    return (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.category == category, KnowledgeBase.is_active == 1)
        .all()
    )


def coverage_report(db: Session) -> dict:
    """Per-category coverage + overall knowledge health score (0-100)."""
    categories = []
    total_weight = 0
    weighted = 0
    missing = []

    for cat, meta in ESSENTIAL_CATEGORIES.items():
        entries = _category_entries(db, cat)
        count = len(entries)
        has_substance = sum(1 for e in entries if len((e.content or "").strip()) > 80)
        if has_substance >= 2:
            score = 100
            status = "good"
        elif has_substance == 1:
            score = 65
            status = "partial"
        elif count >= 1:
            score = 35
            status = "weak"
        else:
            score = 0
            status = "missing"
            missing.append({"category": cat, "name": meta["name"], "question": meta["question"]})

        total_weight += meta["weight"]
        weighted += meta["weight"] * score
        categories.append({
            "category": cat,
            "name": meta["name"],
            "weight": meta["weight"],
            "score": score,
            "status": status,
            "count": count,
        })

    overall = round(weighted / max(total_weight, 1))
    open_gaps = (
        db.query(KnowledgeGap)
        .filter(KnowledgeGap.status == "open")
        .order_by(KnowledgeGap.created_at.asc())
        .all()
    )
    return {
        "score": overall,
        "level": "excellent" if overall >= 85 else "good" if overall >= 65 else "developing" if overall >= 40 else "empty",
        "categories": categories,
        "missing": missing,
        "open_gaps": [
            {
                "id": g.id,
                "category": g.category,
                "question": g.question,
                "reason": g.reason,
                "source": g.source,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in open_gaps
        ],
    }


def ensure_gap(db: Session, category: str, question: str, reason: str = None, source: str = "ai_detected") -> bool:
    """Record a gap idempotently (same category+question, still open => skip)."""
    try:
        existing = (
            db.query(KnowledgeGap)
            .filter(
                KnowledgeGap.category == category,
                KnowledgeGap.question == question,
                KnowledgeGap.status == "open",
            )
            .first()
        )
        if existing:
            return False
        db.add(KnowledgeGap(category=category, question=question, reason=reason, source=source))
        db.commit()
        return True
    except Exception as e:
        logger.warning("ensure_gap failed: %s", e)
        db.rollback()
        return False


def ensure_missing_essential_gaps(db: Session) -> int:
    """Create open gaps for every essential category that has no substance."""
    added = 0
    report = coverage_report(db)
    for m in report["missing"]:
        meta = ESSENTIAL_CATEGORIES[m["category"]]
        if ensure_gap(db, m["category"], meta["question"], meta["reason"], source="ai_detected"):
            added += 1
    return added


def suggest_questions(db: Session, limit: int = 5) -> list[dict]:
    """AI generates the specific questions this customer should answer next.
    Falls back to the built-in essential questions when AI is unavailable."""
    report = coverage_report(db)
    weak = [c for c in report["categories"] if c["score"] < 65]
    if not weak:
        return []

    weak_block = "\n".join(
        f"- {c['name']} (current coverage {c['score']} points, {c['count']} entries)"
        for c in weak
    )
    prompt = (
        "You are the knowledge-base coach of an export customer-acquisition system. The customer's "
        "knowledge base is still weak. Generate the most-needed specific questions for this company "
        "to answer, targeting the weak categories below.\n"
        f"Weak categories:\n{weak_block}\n"
        f"Requirements: {limit} questions in total, covering the categories above; each question must be specific and answerable, "
        "not generic. Return a strict JSON array: "
        '[{"category":"profile","question":"...","reason":"why it matters"}]'
    )
    try:
        from services.ai_router import call_simple_sync as call_simple
        raw = call_simple(prompt, temperature=0.4, max_tokens=1024)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        data = json.loads(raw)
        if isinstance(data, list):
            return [
                {"category": str(d.get("category", "guidelines"))[:40],
                 "question": str(d.get("question", ""))[:300],
                 "reason": str(d.get("reason", ""))[:200]}
                for d in data[:limit]
                if d.get("question")
            ]
    except Exception as e:
        logger.warning("suggest_questions AI failed, using fallback: %s", e)

    # Fallback: essential questions for weak categories
    fallback = []
    for c in weak:
        meta = ESSENTIAL_CATEGORIES.get(c["category"])
        if meta:
            fallback.append({"category": c["category"], "question": meta["question"], "reason": meta["reason"]})
    return fallback[:limit]


def generate_draft(db: Session, category: str, raw: str, title_hint: str = None) -> dict:
    """AI polishes raw customer input into a ready-to-save knowledge entry.
    Never raises: returns a usable fallback on any failure."""
    meta = ESSENTIAL_CATEGORIES.get(category, {"name": category})
    prompt = (
        f"You are an export sales knowledge-base editor. The customer's raw input is material about "
        f"\"{meta['name']}\". Organize it into one clearly structured knowledge entry that the AI can "
        "use directly for writing outreach emails and scoring.\n"
        "Rules: keep every fact, do not invent; structure it; output in English; no pleasantries.\n"
        f"Raw material:\n{raw[:3000]}\n\n"
        'Return strict JSON: {"title":"short title","content":"organized content","tags":["tag1","tag2"]}'
    )
    try:
        from services.ai_router import call_simple_sync as call_simple
        out = call_simple(prompt, temperature=0.3, max_tokens=1200)
        if "```" in out:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", out, re.DOTALL)
            out = m.group(1).strip() if m else out
        data = json.loads(out)
        return {
            "category": category,
            "title": str(data.get("title") or title_hint or meta["name"])[:120],
            "content": str(data.get("content") or raw).strip(),
            "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
            "source": "ai_suggestion",
            "confidence": "low",
        }
    except Exception as e:
        logger.warning("generate_draft AI failed, using raw input: %s", e)
        return {
            "category": category,
            "title": (title_hint or meta["name"])[:120],
            "content": raw.strip(),
            "tags": [],
            "source": "ai_suggestion",
            "confidence": "low",
        }


def save_history(db: Session, kb: KnowledgeBase) -> None:
    """Snapshot the current state before an edit (no-op if unchanged)."""
    try:
        latest = (
            db.query(KnowledgeHistory)
            .filter(KnowledgeHistory.knowledge_id == kb.id)
            .order_by(KnowledgeHistory.id.desc())
            .first()
        )
        if latest and latest.content == kb.content and latest.title == kb.title:
            return
        db.add(KnowledgeHistory(
            knowledge_id=kb.id,
            category=kb.category,
            title=kb.title,
            content=kb.content,
            tags=kb.tags,
        ))
        db.commit()
    except Exception as e:
        logger.warning("save_history failed: %s", e)
        db.rollback()


def history_for(db: Session, kb_id: int) -> list[dict]:
    rows = (
        db.query(KnowledgeHistory)
        .filter(KnowledgeHistory.knowledge_id == kb_id)
        .order_by(KnowledgeHistory.id.desc())
        .all()
    )
    return [
        {
            "id": h.id,
            "title": h.title,
            "content": h.content,
            "tags": h.tags,
            "changed_at": h.changed_at.isoformat() if h.changed_at else None,
        }
        for h in rows
    ]


def restore_version(db: Session, kb_id: int, history_id: int) -> bool:
    """Restore a previous version; current state is snapshotted first."""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    h = db.query(KnowledgeHistory).filter(KnowledgeHistory.id == history_id, KnowledgeHistory.knowledge_id == kb_id).first()
    if not kb or not h:
        return False
    save_history(db, kb)  # keep current version recoverable
    kb.category = h.category or kb.category
    kb.title = h.title or kb.title
    kb.content = h.content or kb.content
    kb.tags = h.tags
    kb.updated_at = datetime.utcnow()
    db.commit()
    return True


def extract_candidates(db: Session, limit: int = 3) -> list[dict]:
    """Learn reusable knowledge from recent real outcomes (won / sample / positive).
    Returns AI-proposed entries; the customer decides whether to save them."""
    try:
        from models import Interaction, Prospect
        prospects = (
            db.query(Prospect)
            .filter(
                Prospect.is_deleted == 0,
                Prospect.sales_stage.in_(["won", "trial_order", "sample_sent", "sample_received", "replied"]),
            )
            .order_by(Prospect.id.desc())
            .limit(5)
            .all()
        )
        samples = []
        for p in prospects[:3]:
            interactions = (
                db.query(Interaction)
                .filter(Interaction.prospect_id == p.id)
                .order_by(Interaction.interacted_at.desc())
                .limit(6)
                .all()
            )
            text = "\n".join(
                f"[{'In' if i.direction == 'inbound' else 'Out'}] {i.channel}: {(i.content or i.subject or '')[:300]}"
                for i in interactions
            )
            if text.strip():
                samples.append(f"Client: {p.company} ({p.country or ''}, Profile {p.profile_type or '?'})\n{text}")

        if not samples:
            return []

        prompt = (
            "Below are real customer interactions of an export company (including wins/samples/positive signals). "
            "Extract 2-4 reusable sales lessons for the AI to use in future outreach and follow-up emails.\n"
            "Requirements: generalize from concrete cases; do not copy whole emails; "
            "give each lesson a category (guidelines strategy / voice tone / case_study example) and a title.\n"
            "Interactions:\n" + "\n---\n".join(samples) + "\n\n"
            'Return a strict JSON array: [{"category":"guidelines","title":"...","content":"...","tags":["..."]}]'
        )
        from services.ai_router import call_simple_sync as call_simple
        raw = call_simple(prompt, temperature=0.4, max_tokens=1500)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        data = json.loads(raw)
        if isinstance(data, list):
            return [
                {
                    "category": str(d.get("category", "guidelines"))[:40],
                    "title": str(d.get("title", ""))[:120],
                    "content": str(d.get("content", ""))[:4000],
                    "tags": d.get("tags") if isinstance(d.get("tags"), list) else [],
                    "source": "from_case",
                    "confidence": "medium",
                }
                for d in data[:limit]
                if d.get("content")
            ]
    except Exception as e:
        logger.warning("extract_candidates failed: %s", e)
    return []


def run_kb_health_check() -> dict:
    """Weekly job: coverage report + auto-gaps + 画像表现体检（数据驱动进化）+ ServerChan digest."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        added = ensure_missing_essential_gaps(db)
        report = coverage_report(db)
        profile_suggestions = profile_performance_review(db)
        summary = {
            "score": report["score"],
            "level": report["level"],
            "open_gaps": len(report["open_gaps"]),
            "gaps_added": added,
            "profile_suggestions": len(profile_suggestions),
        }
        logger.info("KB_HEALTH: %s", summary)
        try:
            from config import SERVERCHAN_SENDKEY
            key = (SERVERCHAN_SENDKEY or "").strip()
            if key:
                import requests
                weak = [c["name"] for c in report["categories"] if c["score"] < 65]
                profile_lines = "\n".join(
                    f"- {s.get('title','')}: {s.get('suggestion','')}" for s in profile_suggestions[:3]
                )
                desp = (
                    f"Knowledge-base health: {report['score']}/100 ({report['level']})\n"
                    f"Open gaps to fill: {len(report['open_gaps'])}\n"
                    f"Weak categories: {', '.join(weak) if weak else 'None'}\n"
                )
                if profile_lines:
                    desp += f"Profile evolution suggestions:\n{profile_lines}\n"
                desp += "Open the system → Knowledge Base → Setup Wizard / Gaps list to fill them in."
                requests.post(
                    f"https://sctapi.ftqq.com/{key}.send",
                    data={"title": f"Knowledge-base weekly report {report['score']}/100", "desp": desp},
                    timeout=10,
                    proxies={"http": None, "https": None},
                )
        except Exception as e:
            logger.warning("KB_HEALTH notify failed: %s", e)
        return summary
    finally:
        db.close()


def profile_performance_review(db: Session, min_contacted: int = 3, max_suggestions: int = 3) -> list[dict]:
    """数据驱动的画像进化：按画像分类统计真实表现，AI 复杂分析归纳出修订建议，记入缺口。
    退信不算回复（口径与回复率统计一致）。"""
    from models import Deal, Interaction, Prospect
    from services.reply_metrics import is_bounce_interaction

    prospects = db.query(Prospect).filter(Prospect.is_deleted == 0).all()
    if not prospects:
        return []
    interactions = db.query(Interaction).all()
    deals = db.query(Deal).filter(Deal.is_deleted == 0).all()

    outbound_pids = set()
    inbound_pids = set()
    for ix in interactions:
        if ix.direction == "outbound":
            outbound_pids.add(ix.prospect_id)
        elif ix.direction == "inbound" and not is_bounce_interaction(ix):
            inbound_pids.add(ix.prospect_id)

    won_pids = {d.prospect_id for d in deals if (d.stage or "").strip() in {"Won", "won", "WON", "成交"}}
    sample_statuses = {"requested", "sent", "received", "testing", "feedback"}
    by_profile = {}
    for p in prospects:
        pt = p.profile_type or ""
        if not pt or pt == "EXCLUDE":
            continue
        s = by_profile.setdefault(pt, {"contacted": 0, "replied": 0, "sample": 0, "won": 0})
        if p.id in outbound_pids:
            s["contacted"] += 1
        if p.id in inbound_pids:
            s["replied"] += 1
        if p.sample_status in sample_statuses:
            s["sample"] += 1
        if p.id in won_pids or (p.sales_stage or "") == "won":
            s["won"] += 1

    rows = []
    for pt, s in by_profile.items():
        if s["contacted"] < min_contacted:
            continue
        rows.append({
            "profile": pt,
            "contacted": s["contacted"],
            "replied": s["replied"],
            "reply_rate": round(s["replied"] / s["contacted"] * 100, 1) if s["contacted"] else 0.0,
            "sample": s["sample"],
            "won": s["won"],
        })
    rows.sort(key=lambda r: -r["contacted"])
    if not rows:
        return []

    label_map = {}
    try:
        from services.profile_categories import load_profile_categories
        label_map = {c["key"]: c["label"] for c in load_profile_categories(db)}
    except Exception:
        pass
    for r in rows:
        r["label"] = label_map.get(r["profile"], r["profile"])

    table = "\n".join(
        "- %s (%s): contacted %d, replied %d (%s%%), samples %d, won %d" % (
            r["label"], r["profile"], r["contacted"], r["replied"], r["reply_rate"], r["sample"], r["won"]
        )
        for r in rows
    )
    prompt = (
        "You are the customer-profile coach of the B2B Outbound OS export system. Below is this company's real outreach "
        "performance grouped by customer profile:\n\n"
        + table + "\n\n"
        "Analyze deeply and summarize the most valuable changes to the customer profile — at most 3. Rules:\n"
        "1. If a tier has many touches but a clearly low reply rate (e.g. below half the average) → the profile definition may be too broad; suggest tightening the filtering criteria.\n"
        "2. If a tier has a clearly high reply or win rate → suggest writing this tier's characteristics into the profile so the AI prioritizes replicating it.\n"
        "3. Do not suggest anything for tiers with too few touches to judge.\n"
        "Return a strict JSON array (no markdown, no other text): "
        '[{"profile":"A","title":"one-line title (<=25 words)","suggestion":"specific action (<=80 words)"}]'
    )
    try:
        from services.ai_router import call_simple_sync as call_simple
        raw = call_simple(prompt, temperature=0.3, max_tokens=800)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            raw = m.group(1).strip() if m else raw
        data = json.loads(raw)
        if not isinstance(data, list):
            data = []
    except Exception:
        data = _rule_based_suggestions(rows)

    suggestions = []
    for d in (data or [])[:max_suggestions]:
        pid = str(d.get("profile", ""))[:40]
        title = str(d.get("title", ""))[:200]
        suggestion = str(d.get("suggestion", ""))[:300]
        if not pid or not title:
            continue
        label = label_map.get(pid, pid)
        question = "Profile evolution suggestion: %s" % label
        existing = (
            db.query(KnowledgeGap)
            .filter(
                KnowledgeGap.category == "guidelines",
                KnowledgeGap.question == question,
                KnowledgeGap.status == "open",
            )
            .first()
        )
        if existing:
            existing.reason = suggestion
            existing.note = "Generated by this week's data-driven profile health review"
        else:
            db.add(KnowledgeGap(
                category="guidelines", question=question, reason=suggestion,
                source="ai_profile_review",
            ))
        suggestions.append({
            "profile": pid, "label": label, "title": title,
            "suggestion": suggestion, "question": question,
        })
    db.commit()
    return suggestions


def _rule_based_suggestions(rows: list[dict]) -> list[dict]:
    """AI 不可用时的规则兜底：最差表现建议收紧，最好表现建议写入画像。"""
    if not rows:
        return []
    out = []
    avg = sum(r["reply_rate"] for r in rows) / len(rows)
    for r in rows:
        if r["contacted"] >= 5 and r["reply_rate"] < max(5.0, avg / 2):
            out.append({
                "profile": r["profile"],
                "title": r["label"] + " — reply rate low",
                "suggestion": "Contacted %d but only %d replied (%s%%). The profile definition may be too broad — tighten the criteria in the profile coach." % (
                    r["contacted"], r["replied"], r["reply_rate"]),
            })
    best = sorted(rows, key=lambda x: -x["reply_rate"])[0] if rows else None
    if best and best["contacted"] >= 5 and best["reply_rate"] >= avg:
        out.append({
            "profile": best["profile"],
            "title": best["label"] + " — best performer",
            "suggestion": "Reply rate %s%%. Write this tier's characteristics into the customer profile so the AI can prioritize replicating it." % best["reply_rate"],
        })
    return out[:3]
