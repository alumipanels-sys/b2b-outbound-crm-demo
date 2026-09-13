"""SQLAlchemy ORM models — all 7 tables."""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    ForeignKey,
    DateTime,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ── Table 1: prospects ─────────────────────────────────
class Prospect(Base):
    __tablename__ = "prospects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    # ── Basic info (from lobster import) ──
    contact = Column(Text)
    company = Column(Text, nullable=False)
    website = Column(Text)
    title = Column(Text)
    country = Column(Text)
    size = Column(Text)
    industry = Column(Text)
    phone = Column(Text)
    email = Column(Text)
    linkedin = Column(Text)
    note = Column(Text)
    source = Column(Text)
    source_channel = Column(Text)
    development_batch = Column(Text)
    linkedin_batch = Column(Text)       # 每日LinkedIn加人配额锁
    first_touch_channel = Column(Text)
    duplicate_checked = Column(Integer, default=0)
    timezone = Column(Text)
    parent_company = Column(Text)

    # ── AI scoring ──
    profile_type = Column(Text)       # A/B/C/D/E/EXCLUDE
    profile_source = Column(Text, default="ai")   # "manual" = 手动分类, "ai" = AI猜测, null = 未分类
    ai_score = Column(Float)          # 1-10
    score_breakdown = Column(Text)    # JSON string: 4-dimension scores
    score_reason = Column(Text)
    value_level = Column(Text)        # HIGH/MID/LOW/EXCLUDE
    red_flags = Column(Text)          # JSON array
    intent_signals = Column(Text)     # JSON array: 招聘扩产/展会接触/进口异动/老客户介绍
    sender_key = Column(Text, nullable=True)   # 该客户最近使用的发件邮箱（下次发信默认用它，防发错）
    risk_score = Column(Float)        # 0-100 risk rating: lower = riskier (new domain, no history, etc)

    # ── Decision maker ──
    decision_maker = Column(Text)
    dm_title = Column(Text)
    dm_linkedin = Column(Text)
    dm_email = Column(Text)
    decision_role = Column(Text)   # 老板/采购/生产/工程/技术/未知

    # ── Status ──
    status = Column(Text, default="New")          # New/Following up/Replied/Paused/成交/Lost
    sales_stage = Column(Text, default="new")       # new/touched/connected/replied/interested/sample_pending/sample_sent/testing/feedback/trial_order/won/lost
    email_status = Column(Text)                     # pending/active/paused/completed/bounced/bounced_risk
    linkedin_status = Column(Text, default="not_connected")  # not_connected/pending/connected

    # ── Email verification ──
    email_verified = Column(Integer, default=0)     # 0=pending, 1=valid, -1=invalid
    email_verdict = Column(Text)                    # valid/risky/invalid
    email_verified_at = Column(DateTime)
    email_verification_detail = Column(Text)        # JSON: {syntax, mx, role, smtp, score}
    hunter_data = Column(Text)                      # JSON: Hunter candidates + best match

    # ── Sample tracking ──
    sample_status = Column(Text)      # none/requested/sent/received/feedback
    sample_sent_date = Column(Text)
    sample_feedback = Column(Text)

    # ── Timestamps ──
    next_follow_date = Column(Text)
    next_follow_reason = Column(Text)
    reminder_note = Column(Text)
    reminder_updated_at = Column(DateTime)
    new_outreach_date = Column(Text)      # YYYY-MM-DD — locked as today's outreach target on this date
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    last_edited_at = Column(DateTime, default=None)  # only set on manual PUT, NOT by system tasks
    is_deleted = Column(Integer, default=0)


# ── Table 2: intelligence ──────────────────────────────
class Intelligence(Base):
    __tablename__ = "intelligence"
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)

    # ── Website intelligence (auto-scraped) ──
    website_content = Column(Text)
    website_scraped_at = Column(DateTime)
    website_key_points = Column(Text)     # Gemini key points (JSON array)

    # ── OSINT fields (SRS 叮小蜂) ──
    domain_registered_at = Column(DateTime)    # Whois creation date
    domain_expires_at = Column(DateTime)       # Whois expiry
    domain_registrar = Column(Text)            # Whois registrar name
    osint_report = Column(Text)                # JSON: full OSINT backcheck report
    osint_checked_at = Column(DateTime)

    # ── 对话全景（连续邮件综合理解）──
    dialogue_panorama = Column(Text)           # JSON: AI 全景分析
    dialogue_panorama_at = Column(DateTime)    # 生成时间

    # ── LinkedIn intelligence (manual paste) ──
    linkedin_content = Column(Text)
    linkedin_pasted_at = Column(DateTime)

    # ── Hiring signals ──
    hiring_content = Column(Text)
    hiring_signals = Column(Text)         # Gemini-identified signals (JSON array)

    # ── Gemini analysis results ──
    icebreak_angles = Column(Text)        # 3-5 icebreaker angles (JSON array)
    screenshot_analysis = Column(Text)    # accumulated Gemini Vision screenshot analyses
    analyzed_at = Column(DateTime)

    # ── Change tracking ──
    website_key_points_prev = Column(Text)   # previous key points for diff
    change_flags = Column(Text)              # AI-generated change summary
    last_auto_scraped_at = Column(DateTime)  # last time auto-scraper ran

    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    prospect = relationship("Prospect", backref="intelligence_records")


# ── Table 3: sequences ─────────────────────────────────
class Sequence(Base):
    __tablename__ = "sequences"
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)

    step_number = Column(Integer, nullable=False)
    channel = Column(Text, nullable=False)      # email/linkedin/phone/whatsapp

    # ── Plan ──
    scheduled_date = Column(Text)               # YYYY-MM-DD
    scheduled_time = Column(Text)               # HH:MM

    # ── Content ──
    content = Column(Text)
    subject = Column(Text)                      # email subject
    tone = Column(Text)                         # formal/warm/technical
    to_email = Column(Text)                     # 目标联系人邮箱（同公司多人计划用，留空=发给本客户）
    is_company_plan = Column(Integer, default=0)  # 1=公司级多人计划（全局编号，替换式生成）

    # ── Execution status ──
    status = Column(Text, default="pending")    # pending/done/skipped/cancelled
    executed_at = Column(DateTime)

    # ── Outcome ──
    outcome = Column(Text)
    outcome_note = Column(Text)

    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    prospect = relationship("Prospect", backref="sequences")


# ── Table 4: interactions ─────────────────────────────
class Interaction(Base):
    __tablename__ = "interactions"
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)
    sequence_id = Column(Integer, ForeignKey("sequences.id"))

    # ── Direction & channel ──
    direction = Column(Text, nullable=False)    # outbound / inbound
    channel = Column(Text, nullable=False)      # email/linkedin/phone/whatsapp

    # ── Content ──
    content = Column(Text)
    subject = Column(Text)

    # ── IMAP auto-read fields ──
    email_message_id = Column(Text)             # unique, for dedup
    email_from = Column(Text)
    email_received_at = Column(DateTime)
    attachment_files = Column(Text)              # JSON: [{"filename":"...","path":"attachments/...","size":123}]

    # ── AI analysis (inbound only) ──
    reply_intent = Column(Text)                 # HOT_LEAD / SOFT_REJECTION / etc.
    sentiment_score = Column(Integer)           # 1-10
    key_signals = Column(Text)                  # JSON array
    ai_suggested_action = Column(Text)
    ai_suggested_channel = Column(Text)
    ai_suggested_timing = Column(Text)
    ai_draft_suggestion = Column(Text)

    # ── Generation feedback loop ──
    generation_meta = Column(Text)              # JSON: active methodology KB entries at generation time

    # ── Human review ──
    human_reviewed = Column(Integer, default=0)
    human_decision = Column(Text)

    # ── Read status (inbox) ──
    is_read = Column(Integer, default=0)          # 0=unread, 1=read

    interacted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.current_timestamp())
    created_at = Column(DateTime, server_default=func.current_timestamp())

    prospect = relationship("Prospect", backref="interactions")
    sequence = relationship("Sequence", backref="interactions")


# ── Table 5: email_queue ───────────────────────────────
class EmailQueue(Base):
    __tablename__ = "email_queue"
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)
    sequence_id = Column(Integer, ForeignKey("sequences.id"))

    to_email = Column(Text, nullable=False)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)

    # ── Sending control ──
    status = Column(Text, default="pending")    # pending/sending/sent/failed/cancelled
    scheduled_at = Column(DateTime)
    sent_at = Column(DateTime)

    # ── Rate-limit tracking ──
    daily_send_date = Column(Text)              # YYYY-MM-DD
    retry_count = Column(Integer, default=0)
    last_error = Column(Text)

    # ── Tracking ──
    message_id = Column(Text)

    # ── Which sender account ──
    sender_key = Column(Text, default="primary")  # primary / secondary

    # ── Attachments ──
    attachment_files = Column(Text)  # JSON: [{"filename":"...","path":"...","size":123}]

    created_at = Column(DateTime, server_default=func.current_timestamp())

    prospect = relationship("Prospect", backref="email_queue_items")
    sequence = relationship("Sequence", backref="email_queue_items")


# ── Table 6: knowledge_base ────────────────────────────
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)

    category = Column(Text, nullable=False)     # product/profile/guidelines/case_study/forbidden
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)

    tags = Column(Text)                         # JSON array: ["scoring","email","linkedin","strategy"]
    source_url = Column(Text)                   # Optional URL where this knowledge came from
    source = Column(Text, default="manual")     # manual / ai_suggestion / from_case / imported / template
    confidence = Column(Text, default="medium") # high / medium / low
    is_active = Column(Integer, default=1)

    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


# ── Table 7b: knowledge_gaps (self-evolution queue) ─────────
class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(Text, nullable=False)     # which essential category is missing/weak
    question = Column(Text, nullable=False)     # what the customer should fill in
    reason = Column(Text)                       # why this gap matters
    source = Column(Text, default="ai_detected")  # ai_detected / manual / from_case
    status = Column(Text, default="open")       # open / resolved / ignored
    note = Column(Text)                         # resolution note / ignore reason
    created_at = Column(DateTime, server_default=func.current_timestamp())
    resolved_at = Column(DateTime)


# ── Table 7c: knowledge_history (version rollback) ─────────
class KnowledgeHistory(Base):
    __tablename__ = "knowledge_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, nullable=False)
    category = Column(Text)
    title = Column(Text)
    content = Column(Text)
    tags = Column(Text)
    changed_at = Column(DateTime, server_default=func.current_timestamp())


# ── 多用户：租户 / 用户 / 会话 / 审计 ─────────────────────
class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)                 # 公司名
    plan = Column(Text, default="single")               # single / team / enterprise
    max_users = Column(Integer, default=1)              # seat limit set by the license key
    status = Column(Text, default="active")             # active / expired / disabled
    license_key = Column(Text)                          # 激活码（按账号数发放）
    activated_at = Column(DateTime)                     # 激活时间（体验码从这天起算试用期）
    expires_at = Column(DateTime)                       # 到期时间（永久买断为 NULL）
    created_at = Column(DateTime, server_default=func.current_timestamp())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    role = Column(Text, nullable=False, default="member")  # owner / admin / member
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    status = Column(Text, default="active")             # active / disabled
    email_signature = Column(Text, nullable=True)        # 个人邮件签名（每个员工可不同）
    default_sender = Column(Text, nullable=True)         # 默认发件邮箱 key（第一次选择后固定，防发错）
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.current_timestamp())


# ── 每日目标：老板给成员定“新客户触达”目标（周二/三/四考核），纯展示督促、不限制发送 ──
class DailyTarget(Base):
    __tablename__ = "daily_targets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, unique=True)   # 每个成员一条
    target_per_day = Column(Integer, default=3)              # 老板设置：每天几个新触达
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(Text, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    action = Column(Text, nullable=False)               # login / create_user / update_user / backup / export / restore ...
    target = Column(Text)                               # 目标对象描述（如 user#3 / prospect#12）
    detail = Column(Text)
    created_at = Column(DateTime, server_default=func.current_timestamp())


# ── 备份记录（谁在什么时候备份了什么）──
class BackupRecord(Base):
    __tablename__ = "backup_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)  # 谁触发的（调度任务为 NULL）
    kind = Column(Text, nullable=False)                   # db_full / user_export
    file_path = Column(Text)
    size_mb = Column(Float, default=0)
    integrity = Column(Text, default="ok")
    created_at = Column(DateTime, server_default=func.current_timestamp())


# ── Table 7: system_settings (key-value config) ─────────
class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(Text, nullable=False, unique=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())


# ── Table 8: daily_email_stats ─────────────────────────
class DailyEmailStats(Base):
    __tablename__ = "daily_email_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    date = Column(Text, nullable=False, unique=True)    # YYYY-MM-DD
    sent_count = Column(Integer, default=0)
    limit_count = Column(Integer, default=10)
    created_at = Column(DateTime, server_default=func.current_timestamp())


# ── Table 8b: email_accounts（客户可自定义添加，不限数量）─────────
class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(Text, nullable=True, unique=True)          # primary/secondary/third（旧兼容）或 acc_<id>
    name = Column(Text, nullable=False, default="")          # 显示名，如 工作邮箱 1
    smtp_host = Column(Text, default="")
    smtp_port = Column(Integer, default=465)
    smtp_user = Column(Text, default="")
    smtp_pass = Column(Text, default="")
    smtp_name = Column(Text, default="")                     # 发件人显示名
    imap_host = Column(Text, default="")
    imap_port = Column(Integer, default=993)
    imap_user = Column(Text, default="")
    imap_pass = Column(Text, default="")
    bound_user_id = Column(Integer, nullable=True)           # 绑定的成员/主账号
    is_active = Column(Integer, default=1)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp())


# ── Table 9: deals ──────────────────────────────────────
class Deal(Base):
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)
    name = Column(Text, nullable=False)                 # 商机名称
    amount = Column(Float, default=0)                   # 金额 (EUR)
    stage = Column(Text, default="Initial contact")             # Initial contact/Requirements confirmed/Quotation sent/Negotiating/Won/Lost
    expected_date = Column(Text)                        # 预计成交日期 YYYY-MM-DD
    note = Column(Text)                                 # 备注
    is_deleted = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    prospect = relationship("Prospect", backref="deals")


# ── Table 10: sample_events ──────────────────────────────
class SampleEvent(Base):
    __tablename__ = "sample_events"
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)

    id = Column(Integer, primary_key=True, autoincrement=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False)

    # Stage: requested / sent / received / testing / feedback / trial_order / completed / dead
    stage = Column(Text, nullable=False, default="requested")
    note = Column(Text)
    event_date = Column(Text)              # YYYY-MM-DD

    # AI-generated follow-up prompt for this stage
    ai_followup_prompt = Column(Text)

    # Tracking details
    carrier = Column(Text)
    tracking_number = Column(Text)
    tracking_url = Column(Text)
    logistics_status = Column(Text)
    expected_arrival = Column(Text)        # YYYY-MM-DD
    signed_date = Column(Text)             # YYYY-MM-DD
    test_purpose = Column(Text)            # What the client is testing
    client_deadline = Column(Text)         # When client said they'd respond
    followup_draft_id = Column(Integer, ForeignKey("email_queue.id"))

    # Notification tracking — set when client is notified about this stage change
    notified_at = Column(Text)          # YYYY-MM-DD HH:MM
    notified_channel = Column(Text)     # email / linkedin / whatsapp / wechat

    created_at = Column(DateTime, server_default=func.current_timestamp())

    prospect = relationship("Prospect", backref="sample_events")
    followup_draft = relationship("EmailQueue")


# ── Table 11: quote_history ─────────────────────────────
# AI 从邮件/互动中提取的报价记录，按客户归档成时间线。
# ai_extracted=1 表示来自 AI 自动提取（业务员可一键修正，修正后变人工确认）。
class QuoteHistory(Base):
    __tablename__ = "quote_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    prospect_id = Column(Integer, ForeignKey("prospects.id"), nullable=False, index=True)

    # 类型：inquiry=客户询盘 / quote=我方报价
    direction = Column(Text, default="quote")
    # 来源（哪封邮件/互动）
    source_type = Column(Text, default="email")       # email / linkedin / manual
    source_id = Column(Integer, nullable=True)        # interactions.id
    source_subject = Column(Text)                     # 邮件主题

    quote_date = Column(Text)                         # 报价日期 YYYY-MM-DD
    product = Column(Text)                            # 产品/品名
    spec = Column(Text)                               # 规格
    qty = Column(Text)                                # 数量（保留原文，如 "500pcs"）
    unit_price = Column(Text)                         # 单价（保留原文，如 "$8.00"）
    total = Column(Text)                              # 总价（保留原文）
    currency = Column(Text)                           # 币种 USD/EUR/CNY...
    terms = Column(Text)                              # 付款条件/交期等备注
    summary = Column(Text)                            # AI 一句话摘要

    ai_extracted = Column(Integer, default=0)         # 1=AI 提取草稿，0=人工确认
    ai_raw = Column(Text)                             # AI 原始 JSON（保留备查）
    is_deleted = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.current_timestamp())
    updated_at = Column(DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    prospect = relationship("Prospect", backref="quote_history")


