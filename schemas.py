"""Pydantic schemas for API request / response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, Field


# ── Prospect ──────────────────────────────────────────
class ProspectBase(BaseModel):
    contact: Optional[str] = None
    company: str
    website: Optional[str] = None
    title: Optional[str] = None
    country: Optional[str] = None
    size: Optional[str] = None
    industry: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    linkedin: Optional[str] = None
    note: Optional[str] = None
    source: Optional[str] = None
    source_channel: Optional[str] = None
    development_batch: Optional[str] = None
    linkedin_batch: Optional[str] = None
    first_touch_channel: Optional[str] = None
    duplicate_checked: Optional[int] = None
    timezone: Optional[str] = None
    parent_company: Optional[str] = None
    sender_key: Optional[str] = None


class ProspectUpdate(ProspectBase):
    company: Optional[str] = None
    contact: Optional[str] = None
    profile_type: Optional[str] = None
    profile_source: Optional[str] = None  # "manual" when user edits profile
    ai_score: Optional[float] = None
    score_breakdown: Optional[str] = None
    score_reason: Optional[str] = None
    value_level: Optional[str] = None
    red_flags: Optional[str] = None
    risk_score: Optional[float] = None
    decision_maker: Optional[str] = None
    decision_role: Optional[str] = None
    dm_title: Optional[str] = None
    dm_linkedin: Optional[str] = None
    dm_email: Optional[str] = None
    status: Optional[str] = None
    sales_stage: Optional[str] = None
    email_status: Optional[str] = None
    email_verified: Optional[int] = None
    email_verdict: Optional[str] = None
    email_verified_at: Optional[datetime] = None
    email_verification_detail: Optional[str] = None
    hunter_data: Optional[str] = None
    linkedin_status: Optional[str] = None
    sample_status: Optional[str] = None
    sample_sent_date: Optional[str] = None
    sample_feedback: Optional[str] = None
    next_follow_date: Optional[str] = None
    next_follow_reason: Optional[str] = None
    reminder_note: Optional[str] = None
    new_outreach_date: Optional[str] = None
    last_edited_at: Optional[datetime] = None


class ProspectOut(ProspectBase):
    id: int
    owner_user_id: Optional[int] = None
    profile_type: Optional[str] = None
    profile_source: Optional[str] = None
    ai_score: Optional[float] = None
    score_breakdown: Optional[str] = None
    score_reason: Optional[str] = None
    value_level: Optional[str] = None
    red_flags: Optional[str] = None
    risk_score: Optional[float] = None
    decision_maker: Optional[str] = None
    decision_role: Optional[str] = None
    dm_title: Optional[str] = None
    dm_linkedin: Optional[str] = None
    dm_email: Optional[str] = None
    status: Optional[str] = None
    sales_stage: Optional[str] = None
    email_status: Optional[str] = None
    email_verified: Optional[int] = None
    email_verdict: Optional[str] = None
    email_verified_at: Optional[datetime] = None
    email_verification_detail: Optional[str] = None
    hunter_data: Optional[str] = None
    linkedin_status: Optional[str] = None
    sample_status: Optional[str] = None
    sample_sent_date: Optional[str] = None
    sample_feedback: Optional[str] = None
    next_follow_date: Optional[str] = None
    next_follow_reason: Optional[str] = None
    reminder_note: Optional[str] = None
    reminder_updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_edited_at: Optional[datetime] = None
    is_deleted: Optional[int] = None
    interaction_count: Optional[int] = 0  # 0 = never contacted, >0 = had interactions

    model_config = {"from_attributes": True}


class ProspectListOut(BaseModel):
    items: List[ProspectOut]
    total: int
    page: int
    limit: int


# ── Import ────────────────────────────────────────────
class ImportResult(BaseModel):
    imported: int
    skipped: int
    errors: List[str] = []
    scored: int = 0  # How many newly-imported prospects triggered auto-scoring
    warnings: List[str] = []  # Duplicate/protective notices shown to the user


# ── Intelligence ──────────────────────────────────────
class IntelligenceOut(BaseModel):
    id: int
    prospect_id: int
    website_content: Optional[str] = None
    website_scraped_at: Optional[datetime] = None
    website_key_points: Optional[str] = None
    # ── OSINT ──
    domain_registered_at: Optional[datetime] = None
    domain_expires_at: Optional[datetime] = None
    domain_registrar: Optional[str] = None
    osint_report: Optional[str] = None
    osint_checked_at: Optional[datetime] = None
    # ── LinkedIn ──
    linkedin_content: Optional[str] = None
    linkedin_pasted_at: Optional[datetime] = None
    hiring_content: Optional[str] = None
    hiring_signals: Optional[str] = None
    icebreak_angles: Optional[str] = None
    screenshot_analysis: Optional[str] = None
    website_key_points_prev: Optional[str] = None
    change_flags: Optional[str] = None
    last_auto_scraped_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class IntelligenceUpdate(BaseModel):
    website_content: Optional[str] = None
    linkedin_content: Optional[str] = None
    hiring_content: Optional[str] = None
    screenshot_analysis: Optional[str] = None


# ── Sequence ──────────────────────────────────────────
class SequenceCreate(BaseModel):
    step_number: int
    channel: str = "email"
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    tone: Optional[str] = None
    to_email: Optional[str] = None
    is_company_plan: Optional[int] = 0


class SequenceUpdate(BaseModel):
    step_number: Optional[int] = None
    channel: Optional[str] = None
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    tone: Optional[str] = None
    to_email: Optional[str] = None
    is_company_plan: Optional[int] = None
    status: Optional[str] = None
    outcome: Optional[str] = None
    outcome_note: Optional[str] = None


class SequenceOut(BaseModel):
    id: int
    prospect_id: int
    step_number: int
    channel: str
    scheduled_date: Optional[str] = None
    scheduled_time: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    tone: Optional[str] = None
    to_email: Optional[str] = None
    is_company_plan: Optional[int] = None
    status: Optional[str] = None
    executed_at: Optional[datetime] = None
    outcome: Optional[str] = None
    outcome_note: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Interaction ───────────────────────────────────────
class InteractionOut(BaseModel):
    id: int
    prospect_id: int
    sequence_id: Optional[int] = None
    direction: str
    channel: str
    content: Optional[str] = None
    subject: Optional[str] = None
    email_message_id: Optional[str] = None
    email_from: Optional[str] = None
    email_received_at: Optional[datetime] = None
    attachment_files: Optional[str] = None   # JSON array of attachment metadata
    reply_intent: Optional[str] = None
    sentiment_score: Optional[int] = None
    key_signals: Optional[str] = None
    ai_suggested_action: Optional[str] = None
    ai_suggested_channel: Optional[str] = None
    ai_suggested_timing: Optional[str] = None
    ai_draft_suggestion: Optional[str] = None
    human_reviewed: Optional[int] = None
    human_decision: Optional[str] = None
    is_read: Optional[int] = 0
    interacted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    company: Optional[str] = None  # prospect company name, set by inbox API

    model_config = {"from_attributes": True}


# ── Email Queue ───────────────────────────────────────
class EmailQueueCreate(BaseModel):
    prospect_id: int
    sequence_id: Optional[int] = None
    to_email: str = ""
    subject: str
    body: str
    status: Optional[str] = "draft"
    scheduled_at: Optional[datetime] = None
    sender_key: Optional[str] = "primary"
    attachment_files: Optional[str] = None  # JSON: [{"filename":"x.pdf","path":"attachments/x.pdf","size":12345}]


class EmailQueueOut(BaseModel):
    id: int
    prospect_id: int
    sequence_id: Optional[int] = None
    to_email: str
    subject: str
    body: str
    status: str
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    daily_send_date: Optional[str] = None
    retry_count: Optional[int] = None
    last_error: Optional[str] = None
    message_id: Optional[str] = None
    sender_key: Optional[str] = "primary"
    attachment_files: Optional[str] = None  # JSON array
    created_at: Optional[datetime] = None
    company: Optional[str] = None
    timezone: Optional[str] = None

    model_config = {"from_attributes": True}


class EmailStatsOut(BaseModel):
    date: str
    sent_count: int
    limit_count: int
    remaining: int


# ── Knowledge Base ────────────────────────────────────
class KnowledgeCreate(BaseModel):
    category: str
    title: str
    content: str
    source_url: Optional[str] = None
    tags: Optional[str] = None
    is_active: int = 1
    source: Optional[str] = "manual"      # manual / ai_suggestion / from_case / imported / template
    confidence: Optional[str] = "medium"  # high / medium / low


class KnowledgeUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    source_url: Optional[str] = None
    tags: Optional[str] = None
    is_active: Optional[int] = None
    source: Optional[str] = None
    confidence: Optional[str] = None


class KnowledgeOut(BaseModel):
    id: int
    category: str
    title: str
    content: str
    tags: Optional[str] = None
    is_active: int
    source_url: Optional[str] = None
    source: Optional[str] = "manual"
    confidence: Optional[str] = "medium"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Knowledge self-evolution ─────────────────────────
class KnowledgeGapCreate(BaseModel):
    category: str
    question: str
    reason: Optional[str] = None
    source: Optional[str] = "manual"      # ai_detected / manual / from_case


class KnowledgeGapResolve(BaseModel):
    note: Optional[str] = None


class KnowledgeDraftRequest(BaseModel):
    category: str
    raw: str                              # customer's raw input to polish
    title_hint: Optional[str] = None


class KnowledgeSuggestRequest(BaseModel):
    limit: int = 5


class KnowledgeClassifyRequest(BaseModel):
    content: str
    title: Optional[str] = None
    category: Optional[str] = None


class ProfileCoachRequest(BaseModel):
    answers: dict


# ── AI ────────────────────────────────────────────────
class BatchScoreRequest(BaseModel):
    prospect_ids: List[int]


class GenerateMessageRequest(BaseModel):
    message_type: str = "cold_email"   # cold_email / linkedin_connection / linkedin_followup / followup_noreply / followup_softreject / followup_signal
    tone: str = "formal"               # formal / warm / technical
    sequence_step: int = 1
    additional_context: Optional[str] = None
    model_override: Optional[str] = None  # auto / deepseek / openai / gemini


class TimelineItem(BaseModel):
    type: str                          # sequence / interaction
    id: int
    date: Optional[str] = None
    channel: Optional[str] = None
    direction: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[str] = None
    status: Optional[str] = None
    outcome: Optional[str] = None
    reply_intent: Optional[str] = None
    step_number: Optional[int] = None


# ── Deal ───────────────────────────────────────────────
class DealCreate(BaseModel):
    prospect_id: int
    name: str
    amount: float = 0
    stage: str = "Initial contact"
    expected_date: Optional[str] = None
    note: Optional[str] = None


class DealUpdate(BaseModel):
    prospect_id: Optional[int] = None
    name: Optional[str] = None
    amount: Optional[float] = None
    stage: Optional[str] = None
    expected_date: Optional[str] = None
    note: Optional[str] = None


class DealOut(BaseModel):
    id: int
    prospect_id: int
    name: str
    amount: Optional[float] = None
    stage: Optional[str] = None
    expected_date: Optional[str] = None
    note: Optional[str] = None
    is_deleted: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DealFunnelOut(BaseModel):
    stage: str
    count: int
    total_amount: float


# ── Sample Events ─────────────────────────────────────
class SampleEventCreate(BaseModel):
    prospect_id: Optional[int] = None  # derived from URL path, not required in body
    stage: str = "requested"
    note: Optional[str] = None
    event_date: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    logistics_status: Optional[str] = None
    expected_arrival: Optional[str] = None
    signed_date: Optional[str] = None
    test_purpose: Optional[str] = None
    client_deadline: Optional[str] = None
    notified_at: Optional[str] = None
    notified_channel: Optional[str] = None


class SampleEventUpdate(BaseModel):
    stage: Optional[str] = None
    note: Optional[str] = None
    event_date: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    logistics_status: Optional[str] = None
    expected_arrival: Optional[str] = None
    signed_date: Optional[str] = None
    test_purpose: Optional[str] = None
    client_deadline: Optional[str] = None
    ai_followup_prompt: Optional[str] = None
    notified_at: Optional[str] = None
    notified_channel: Optional[str] = None


class SampleEventOut(BaseModel):
    id: int
    prospect_id: int
    stage: str
    note: Optional[str] = None
    event_date: Optional[str] = None
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    tracking_url: Optional[str] = None
    logistics_status: Optional[str] = None
    expected_arrival: Optional[str] = None
    signed_date: Optional[str] = None
    test_purpose: Optional[str] = None
    client_deadline: Optional[str] = None
    ai_followup_prompt: Optional[str] = None
    followup_draft_id: Optional[int] = None
    notified_at: Optional[str] = None
    notified_channel: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class QuoteHistoryOut(BaseModel):
    id: int
    prospect_id: int
    direction: Optional[str] = "quote"
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_subject: Optional[str] = None
    source_content: Optional[str] = None
    quote_date: Optional[str] = None
    product: Optional[str] = None
    spec: Optional[str] = None
    qty: Optional[str] = None
    unit_price: Optional[str] = None
    total: Optional[str] = None
    currency: Optional[str] = None
    terms: Optional[str] = None
    summary: Optional[str] = None
    ai_extracted: Optional[int] = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class QuoteHistoryUpdate(BaseModel):
    prospect_id: int
    direction: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    source_subject: Optional[str] = None
    quote_date: Optional[str] = None
    product: Optional[str] = None
    spec: Optional[str] = None
    qty: Optional[str] = None
    unit_price: Optional[str] = None
    total: Optional[str] = None
    currency: Optional[str] = None
    terms: Optional[str] = None
    summary: Optional[str] = None
