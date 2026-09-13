# -*- coding: utf-8 -*-
"""演示版一键重置：清空演示数据，生成覆盖全部功能的演示数据。
仅演示版可用（DEMO_MODE=true），避免误清个人/交付版。
"""
import json
import re
from datetime import date, datetime, timedelta

from models import (
    AuditLog, BackupRecord, Deal, EmailQueue, Intelligence, Interaction,
    KnowledgeBase, Prospect, SampleEvent, Sequence, User,
)

# Demo account group: auto-created on reset so the demo works out of the box (owner + 4 sales reps)
DEMO_USERS = [
    ("demo@demo.com", "Demo Owner", "owner", "demo123456"),
    ("alex@demo.com", "Alex Carter", "member", "demo123456"),
    ("ben@demo.com", "Ben Miller", "member", "demo123456"),
    ("chris@demo.com", "Chris Wilson", "member", "demo123456"),
    ("dana@demo.com", "Dana Brooks", "member", "demo123456"),
]

# Old Chinese/pinyin demo handles replaced by pure-Western demo accounts
_LEGACY_DEMO_EMAILS = ["zhang@demo.com", "li@demo.com", "wang@demo.com", "perm@demo.com"]


def _d(offset_days=0):
    return (date.today() + timedelta(days=offset_days)).isoformat()


_COUNTRY_LABEL = {
    "DE": "German", "AT": "Austrian", "CH": "Swiss", "SE": "Swedish", "NO": "Norwegian",
    "FI": "Finnish", "DK": "Danish", "NL": "Dutch", "BE": "Belgian", "FR": "French",
    "ES": "Spanish", "IT": "Italian", "PT": "Portuguese", "GB": "British", "IE": "Irish",
    "PL": "Polish", "CZ": "Czech", "SK": "Slovak", "HU": "Hungarian", "RO": "Romanian",
    "BG": "Bulgarian", "HR": "Croatian", "SI": "Slovenian", "EE": "Estonian", "LV": "Latvian",
    "LT": "Lithuanian", "GR": "Greek", "TR": "Turkish",
}

_BUYER_KIND = {
    "A": "OEM/engineering buyer", "B": "brand/importer", "C": "distributor/retailer",
    "D": "workshop chain", "E": "e-commerce player",
}


def _en_note(stage: str, country: str, profile: str) -> str:
    """English demo note generated from stage/country/profile so the UI looks native."""
    adj = _COUNTRY_LABEL.get(country or "", "European")
    kind = _BUYER_KIND.get((profile or "").upper(), "auto-parts buyer")
    notes = {
        "new": f"New {adj} {kind}; not contacted yet.",
        "touched": f"{adj} {kind}; first email sent — awaiting reply.",
        "connected": f"{adj} {kind}; connected on LinkedIn — send an icebreaker.",
        "replied": f"{adj} {kind}; replied asking for specs/certification — respond today.",
        "interested": f"{adj} {kind}; interested — comparing catalog and quotes.",
        "sample_pending": f"{adj} {kind}; samples requested — confirm model and shipping address.",
        "sample_sent": f"{adj} {kind}; samples sent — tracking test progress.",
        "testing": f"{adj} {kind}; bench-testing samples now.",
        "feedback": f"{adj} {kind}; positive feedback — discussing volume cooperation.",
        "trial_order": f"{adj} {kind}; trial order in progress.",
        "won": f"{adj} {kind}; WON — order or framework agreement confirmed.",
        "lost": f"{adj} {kind}; LOST — price or fit did not match.",
        "cooling": f"{adj} {kind}; cooling period — proactive mail paused.",
    }
    return notes.get(stage, f"{adj} {kind}.")


def _now(offset_days=0, hour=9):
    return datetime.now().replace(hour=hour, minute=15, second=0, microsecond=0) + timedelta(days=offset_days)


def _demo_send_at(idx, last_week=False):
    """把演示数据的“已发送”邮件分配到最近三个发信日（周二/三/四），
    让老板目标看板一打开就有真实进度可看。idx 循环取最近发信日、次近、再次近。"""
    t = date.today() - (timedelta(days=7) if last_week else timedelta(days=0))
    days = []
    d = t
    while len(days) < 3:
        if d.weekday() in (1, 2, 3):
            days.append(d)
        d -= timedelta(days=1)
    target = days[idx % len(days)]
    return datetime(target.year, target.month, target.day, 9, 15)


def _clear_demo_tables(db):
    for m in (SampleEvent, Deal, EmailQueue, Sequence, Interaction, Intelligence, Prospect,
              KnowledgeBase, AuditLog, BackupRecord):
        db.query(m).delete()
    from models import EmailAccount
    db.query(EmailAccount).delete()
    from models import QuoteHistory
    db.query(QuoteHistory).delete()
    db.commit()


# Realistic inbound reply templates by stage
REPLY_BY_STAGE = {
    "replied": [
        "Thanks for the email. Could you send pricing for brake discs, 280mm diameter?",
        "We are interested in brake pads for commercial vehicles. What's your MOQ and lead time?",
        "Could you share your ECE R90 certificates and the batch test reports?",
        "Please send your product catalogue and export terms to Germany.",
    ],
    "interested": [
        "We'd like to test a few samples. What do you recommend for VW/Audi models?",
        "Send us your full range and MOQ list — we are comparing suppliers now.",
        "Can you support our own brand packaging? We are building a local brand.",
    ],
    "sample_pending": ["Please send 2 sets of samples, we will cover the shipping cost."],
    "sample_sent": ["Samples received. We will run the bench test this week."],
    "testing": ["The test results are promising. Could you hold the price for us?"],
    "feedback": ["Feedback is positive. Can we discuss the annual order volume?"],
    "trial_order": ["We'd like to place a trial order of 500 pcs. Please send the PI."],
    "won": ["Order confirmed. Please arrange production and keep us updated."],
}

# Follow-up reasons: concrete and human-sounding, by stage
FOLLOWUP_REASONS = {
    "touched": "First outreach email sent; no reply yet. Send a follow-up email with batch inspection data on Thursday; if still silent, switch to LinkedIn to reach the purchasing contact.",
    "connected": "Connected on LinkedIn / other channel, but no real conversation yet. Send a DM referencing their core business with one concrete angle.",
    "replied": "Client replied asking about specs/certification/pricing — a clear buying signal. Reply today with ECE R90 certificates and inspection reports, and propose sending samples to move into the sample stage.",
    "interested": "Client is interested and comparing prices / requesting a catalog. Send the full catalog and price ranges, highlight certification and the 4-week lead time, and ask about sample-testing intent.",
    "sample_pending": "Client requested samples. Confirm the exact model and shipping address first, then arrange dispatch within 3 days with inspection reports.",
    "sample_sent": "Samples shipped. Follow up on test progress after 3 days; proactively provide testing guidance and benchmark data.",
    "testing": "Client is testing samples. Follow up after 2 days and prepare the quotation and volume lead-time proposal in advance.",
    "feedback": "Positive feedback; discussing annual cooperation. Send the annual price framework and capacity plan as soon as possible.",
    "trial_order": "Trial order is being confirmed. Chase the PI and lead time, then arrange production once payment terms are confirmed.",
    "cooling": "Multiple emails unanswered — pause proactive emails to avoid disturbing the client. The system value-share day will touch base again in 1 month.",
    "new": "New client, not yet contacted. Start with AI scoring and research of their website and LinkedIn, then send a personalized first outreach email.",
}

# Short one-line reasons shown on the Today board cards (demo of the
# follow-up-reason feature). Keep them close to what the engine would write.
SHORT_FOLLOWUP_REASONS = {
    "touched": "Follow-up #1 (no reply yet) — send batch inspection data",
    "connected": "Connected on LinkedIn — open with one concrete angle",
    "replied": "Client replied — draft a response with certificates",
    "interested": "Client is comparing suppliers — send catalog & pricing",
    "sample_pending": "Sample requested — confirm model and dispatch",
    "sample_sent": "Samples shipped — follow up on test progress",
    "testing": "Client is testing samples — follow up with quotation",
    "feedback": "Positive feedback — send annual pricing framework",
    "trial_order": "Trial order — send PI and confirm lead time",
    "cooling": "Cooling period — scheduled re-review",
    "new": "New customer — research and first outreach",
}

# 客户情报多样化（避免所有客户情报千篇一律）
WEB_HINTS = [
    ["auto-parts wholesale", "covers 12 European countries", "operates its own warehouse"],
    ["brake-system OEM supply", "IATF 16949 certified", "website shows a new testing center"],
    ["multi-brand auto-parts distribution", "focus on commercial-vehicle brake parts", "expanding into Eastern Europe"],
    ["automotive aftermarket chain", "serves 300+ repair shops", "recently launched an e-commerce platform"],
    ["braking-system solutions", "specializes in heavy commercial vehicles", "works with two OEM groups"],
]
ICE_BREAKS = [
    ["you opened a new warehouse in Germany", "your site mentions expanding the brake-systems line"],
    ["you recently launched a new product", "the website shows a production line under construction"],
    ["you are hiring a purchasing manager", "client reviews mention your supply stability"],
    ["your site targets the EU market", "you are listed as an Automechanika exhibitor"],
    ["your business covers 8 countries", "your site mentions quality-system certifications"],
]
HIRING_HINTS = [
    ["hiring a purchasing manager"],
    ["hiring a technical quality inspector"],
    ["hiring a sales manager"],
    [],
    ["hiring a warehouse supervisor"],
]
OSINT_HINTS = [
    {"domain_age": "8 years", "company_size": "50-200 employees"},
    {"domain_age": "12 years", "company_size": "200-500 employees"},
    {"domain_age": "5 years", "company_size": "20-50 employees"},
    {"domain_age": "15 years", "company_size": "500+ employees"},
    {"domain_age": "3 years", "company_size": "10-20 employees"},
]

# 首封开发信（按客户轮换，具体有细节）
OUTBOUND_INTRO = [
    "Dear %s,\n\nWe are a Chinese brake disc & pad manufacturer serving the European aftermarket for 8 years. Our range (256-410mm) covers 95%% of EU passenger and commercial vehicle applications, ECE R90 certified, and every batch ships with dimension/hardness/balance reports.\n\nMOQ 500 pcs, 4-week lead time. We can send samples and latest test data for your evaluation.\n\nBest regards,\n%s",
    "Dear %s,\n\nWe specialize in brake discs and pads for trucks and trailers — a niche most suppliers ignore. Our ECE R90 range covers Scania, Volvo, MAN and DAF applications with stable batch quality.\n\nSmall batches welcome, 4 weeks lead time. Happy to share test reports and samples.\n\nBest regards,\n%s",
    "Dear %s,\n\nWe supply brake components to European distributors who value consistent quality over rock-bottom price. Every batch comes with inspection reports, and we keep safety stock on 30+ high-frequency SKUs for fast replenishment.\n\nMay we send our catalogue and a sample set?\n\nBest regards,\n%s",
]


def _seed_knowledge(db):
    entries = [
        ("profile", "Company positioning",
         "Demo Auto Parts GmbH was founded in 2016 and exports brake-system components and chassis parts. "
         "Core advantages: IATF 16949 / ISO 9001 certified, batch-to-batch dimensional stability, and a 4-week lead time "
         "for small custom batches. Main customers: European auto-parts importers, distributors, and automotive component OEMs."),
        ("product", "Brake-system component range",
         "Products: brake discs, brake pads, and brake master-cylinder components. "
         "Materials: grey cast iron / low-metal / ceramic compound. Disc diameter 256-410mm covering most mainstream models, "
         "optional surface coating, dynamic balance and hardness tested per batch, ECE R90 certified. MOQ 500 pcs; "
         "4-week lead time for small batches, 6-8 weeks for volume."),
        ("product", "Delivery & quality commitment",
         "Lead time: 4 weeks for small batches (<2000 pcs), 6-8 weeks for volume. Every batch ships with an inspection report "
         "(dimensions / hardness / dynamic balance). Any quality issue is replaced or refunded without condition."),
        ("guidelines", "Customer profile & strategy",
         "Top priority: German/European automotive component OEMs and auto-parts importers/distributors with annual purchases "
         "above EUR 50,000 who value certification and supply stability. "
         "Tier A = OEM / first-fit engineering clients; B = auto-parts brands/importers; C = distributors/retailers; "
         "D = workshop chains; E = e-commerce platforms. Their pain points: unstable supply, incomplete certification, "
         "delayed delivery, and difficulty finding suppliers for small batches."),
        ("forbidden", "Do's and don'ts",
         "Never promise specs beyond the certified range; never badmouth competitors; never claim stock we do not hold; "
         "never quote non-target industries (e.g. consumer goods or FMCG)."),
        ("pricing", "Quote strategy",
         "Brake discs EUR 8-25 per piece depending on volume and model; MOQ 500 pcs. Samples free (client pays shipping). "
         "Payment: 30% deposit by T/T, 70% before shipment."),
        ("voice", "Language & tone",
         "Emails in English: concise, engineer-like, evidence-driven. No exaggerated adjectives and no generic 'Dear Sir' "
         "blast templates. Signature includes title and company."),
        ("case_study", "German OEM win",
         "Situation: a Bavarian brake-system OEM buys about 8,000 brake discs a year for two European vehicle groups. "
         "Their Eastern European supplier had 6 batch complaints in 2025 — outer-diameter variation up to ±0.15mm caused "
         "frequent assembly-line rework and customer-loss risk.\n"
         "Pain: they needed batch consistency (outer diameter within ±0.05mm), dimension/hardness/balance reports on every "
         "batch, and small mixed-model batches on a 4-week lead time.\n"
         "Our move: sent 3 flagship disc samples with complete inspection reports, offered a 2-week bench test, and shared "
         "data daily during the test.\n"
         "Result: all tests passed; first order of 2,000 pcs, then an annual framework of 5,000 pcs/year at EUR 12.5 each — "
         "we became their second supplier.\n"
         "Lesson: prove stability with inspection data + ship samples fast + stay close during testing = how to win OEMs."),
        ("case_study", "Benelux distributor win",
         "Situation: a Dutch auto-parts distributor serving 1,200 Benelux repair shops needed small mixed-SKU replenishment. "
         "Their previous supplier quoted 8-10 weeks and often ran out of stock.\n"
         "Pain: shops expect 'order today, restock this week'; one stockout loses a shop's trust.\n"
         "Our move: kept safety stock on their 30 high-frequency SKUs, promised 4-week small-batch lead time with fast-moving "
         "models in stock, and provided a monthly replenishment plan.\n"
         "Result: after a 3-month trial they signed an annual framework — ~1,500 pcs/month, stockout rate down from 12% to 0.\n"
         "Lesson: for small-batch clients, responsiveness and stock security beat price."),
        ("case_study", "Sample-to-production win",
         "Situation: an Italian brake brand compared suppliers for 3 months without deciding.\n"
         "Pain: they feared sample quality would not match mass production.\n"
         "Our move: after sending samples, we shared inspection data from 3 production batches to prove sample-to-production "
         "consistency, and offered tiered pricing.\n"
         "Result: the client moved from 'we'll think about it' to a 500-pc trial, then 800 pcs/month within two months.\n"
         "Lesson: the sample is not the finish line — evidence of sample-to-production consistency is what closes the deal."),
    ]
    for cat, title, content in entries:
        db.add(KnowledgeBase(category=cat, title=title, content=content,
                             source="manual", confidence="high", is_active=1))
    db.commit()


PROSPECTS = [
    # (company, country, contact, title, stage, profile, value, score, nfd_offset, owner_idx, note)
    ("AutoParts Berlin GmbH", "DE", "Fischer", "Purchasing Manager", "new", "C", "MID", 62, 3, 1, "德国汽配零售商，关注刹车系统配件"),
    ("Kraftfahrzeug-Teile AG", "CH", "Schulz", "Owner", "new", "B", "HIGH", 78, 2, 1, "瑞士汽配进口商，年采购量大"),
    ("AutoTeile Wien", "AT", "Rossi", "Buyer", "new", "C", "MID", 55, 3, 2, "奥地利汽配分销商"),
    ("Parts Depot München", "DE", "Weber", "Procurement", "new", "B", "HIGH", 80, 2, 2, "慕尼黑汽配仓储分销"),
    ("Nord Auto Service", "SE", "Lindqvist", "Owner", "new", "C", "MID", 58, 4, 3, "瑞典汽修连锁"),
    ("Turbo Parts Italia", "IT", "Bianchi", "Purchasing", "touched", "B", "HIGH", 82, -1, 1, "意大利汽配品牌商，已发首封开发信"),
    ("Precision Auto GmbH", "DE", "Meyer", "Engineering Manager", "touched", "A", "HIGH", 88, -2, 1, "德国汽车零部件 OEM，精度要求高"),
    ("Auto Components Lyon", "FR", "Martin", "Buyer", "touched", "B", "MID", 70, 0, 2, "法国汽配进口，已触达"),
    ("Zürich Auto Parts", "CH", "Keller", "Owner", "touched", "C", "MID", 65, 1, 2, "瑞士汽配批发"),
    ("Madrid Motor Supply", "ES", "Garcia", "Purchasing", "touched", "C", "MID", 68, 2, 3, "西班牙汽配供应商"),
    ("Praga Auto Parts", "CZ", "Novak", "Buyer", "touched", "B", "HIGH", 75, 3, 3, "捷克汽配 OEM 配套"),
    ("Warszawa Auto Sp. z o.o.", "PL", "Kowalski", "Owner", "touched", "C", "LOW", 52, 4, 1, "波兰汽配分销，价格敏感"),
    ("Euro Drive Components", "IT", "Ricci", "Technical Director", "touched", "A", "HIGH", 84, 5, 2, "意大利汽车电子部件，已触达"),
    ("Rotterdam Auto Import", "NL", "de Vries", "Buyer", "connected", "C", "MID", 66, 1, 3, "荷兰汽配进口，领英已连接"),
    ("Auto Systems GmbH", "DE", "Schmidt", "Procurement Manager", "replied", "A", "HIGH", 86, 0, 1, "德国汽配系统商，Replied询价"),
    ("TurboTech France", "FR", "Bernard", "Buyer", "replied", "B", "HIGH", 79, -1, 1, "法国涡轮增压配件，回复询问 MOQ"),
    ("Auto Parts UK Ltd", "GB", "Taylor", "Purchasing", "replied", "B", "MID", 72, 2, 2, "英国汽配进口，Replied感兴趣"),
    ("Scandinavian Auto AB", "SE", "Andersson", "Owner", "interested", "C", "MID", 69, 1, 2, "北欧汽配分销，有兴趣试用"),
    ("Auto Fasteners BV", "NL", "Jansen", "Buyer", "interested", "B", "HIGH", 81, 3, 3, "荷兰汽配紧固件商，要样品"),
    ("Berlin Brake Systems", "DE", "Hoffmann", "Engineering", "interested", "A", "HIGH", 87, 4, 3, "德国刹车系统 OEM，深度意向"),
    ("Auto Parts Milano", "IT", "Romano", "Buyer", "sample_pending", "B", "MID", 74, 2, 1, "意大利汽配商，样品待寄"),
    ("Vienna Auto Tech", "AT", "Gruber", "Purchasing", "sample_pending", "B", "HIGH", 77, 3, 1, "奥地利汽配商，已确认寄样地址"),
    ("Auto Components Madrid", "ES", "Lopez", "Buyer", "sample_sent", "C", "MID", 71, 5, 2, "西班牙汽配商，样品已寄"),
    ("Bavaria Motor Parts", "DE", "Fuchs", "Technical", "sample_sent", "A", "HIGH", 85, 6, 2, "巴伐利亚汽配 OEM，样品测试中"),
    ("Auto Supply Paris", "FR", "Durand", "Buyer", "testing", "B", "HIGH", 76, 7, 3, "法国汽配供应商，样品测试"),
    ("Nordic Auto Components", "FI", "Virtanen", "Owner", "feedback", "B", "MID", 73, 8, 3, "芬兰汽配商，样品反馈阶段"),
    ("Auto Parts Amsterdam", "NL", "Bakker", "Buyer", "trial_order", "B", "HIGH", 80, 3, 1, "荷兰汽配商，试单确认中"),
    ("Lyon Automotive", "FR", "Moreau", "Purchasing", "trial_order", "A", "HIGH", 83, 4, 2, "法国汽车部件商，小批量试单"),
    ("Auto Import Dublin", "IE", "Murphy", "Owner", "trial_order", "C", "MID", 67, 5, 3, "爱尔兰汽配进口，试单"),
    ("German Auto Parts GmbH", "DE", "Baumann", "CEO", "won", "B", "HIGH", 90, 14, 1, "成交：年度框架订单 5000 件"),
    ("Auto Tech Stuttgart", "DE", "Wagner", "Director", "won", "A", "HIGH", 92, 14, 2, "成交：OEM 配套，月供 800 件"),
    ("Euro Car Parts Italia", "IT", "Conti", "Owner", "won", "B", "HIGH", 88, 14, 3, "成交：品牌商长期合作"),
    ("Auto Parts Oslo", "NO", "Hansen", "Buyer", "lost", "C", "LOW", 45, 0, 1, "Lost：价格谈不拢"),
    ("Riga Auto Supply", "LV", "Berzins", "Owner", "lost", "C", "LOW", 40, 0, 2, "Lost：已有固定供应商"),
    ("Athens Auto Parts", "GR", "Papadopoulos", "Buyer", "lost", "C", "LOW", 42, 0, 3, "Lost：需求量太小"),
    ("Cooling Auto Berlin", "DE", "Krause", "Buyer", "cooling", "C", "MID", 50, -5, 1, "冷却：5 封无回复"),
    ("Cooling Auto Milan", "IT", "Esposito", "Purchasing", "cooling", "B", "MID", 55, -3, 2, "冷却：3 封无回复"),
    ("Cooling Auto Prague", "CZ", "Svoboda", "Owner", "cooling", "C", "LOW", 48, -7, 3, "冷却：无回复"),
    ("Cooling Auto Warsaw", "PL", "Nowak", "Buyer", "cooling", "C", "MID", 53, -2, 1, "冷却：无回复"),
    ("Future Auto Hamburg", "DE", "Lange", "Owner", "new", "B", "HIGH", 79, 3, 2, "新客户：未触达，德国汽配品牌"),

    # ── 第二批：补足各阶段、更多国家、真实经营感 ──
    ("AutoBremsen Nord GmbH", "DE", "Hartmann", "Technical Director", "new", "A", "HIGH", 84, 3, 1, "德国制动系统 OEM，官网显示新产线"),
    ("BrakeTech Iberia SL", "ES", "Navarro", "Owner", "new", "C", "MID", 61, 3, 2, "西班牙刹车配件分销商"),
    ("PneuParts Italia", "IT", "Gallo", "Purchasing", "new", "B", "HIGH", 77, 4, 3, "意大利轮胎/制动进口商"),
    ("AutoParts Warszawa", "PL", "Zielinski", "Buyer", "new", "C", "LOW", 50, 2, 1, "波兰汽配电商，价格敏感"),
    ("Nordic Brake AB", "SE", "Johansson", "Engineering", "new", "A", "HIGH", 86, 5, 2, "北欧制动 OEM，正在测试新供应商"),
    ("AutoTeile Budapest", "HU", "Nagy", "Owner", "new", "C", "MID", 57, 3, 3, "匈牙利汽配批发"),
    ("Brake Parts Romania SRL", "RO", "Popescu", "Purchasing", "new", "B", "MID", 68, 4, 1, "罗马尼亚制动配件进口"),
    ("Oberland Bremsen", "DE", "Keller", "Quality Manager", "touched", "A", "HIGH", 87, -1, 1, "德国刹车片 OEM，质量要求极高"),
    ("Brake Import Lyon", "FR", "Roux", "Owner", "touched", "B", "HIGH", 76, -2, 2, "法国制动进口商，已询盘"),
    ("AutoParts Croatia", "HR", "Horvat", "Buyer", "touched", "C", "MID", 63, 0, 3, "克罗地亚汽配进口"),
    ("Baltic Brake OÜ", "EE", "Tamm", "Purchasing", "touched", "B", "MID", 70, 1, 1, "爱沙尼亚制动配件商"),
    ("Brake Systems Austria", "AT", "Steiner", "Technical", "touched", "A", "HIGH", 82, -1, 2, "奥地利制动系统集成商"),
    ("TurboBrake Portugal", "PT", "Silva", "Buyer", "connected", "B", "MID", 72, 1, 1, "葡萄牙制动品牌进口，领英已加"),
    ("Brake Solutions NL", "NL", "van Dijk", "Director", "connected", "A", "HIGH", 85, 2, 2, "荷兰制动方案商，多渠道接触中"),
    ("AutoParts Greece", "GR", "Nikolaou", "Owner", "connected", "C", "MID", 60, 3, 3, "希腊汽配分销，WhatsApp 已联系"),
    ("BrakeTech Finland", "FI", "Lahtinen", "Purchasing", "replied", "B", "HIGH", 78, 0, 1, "芬兰制动进口，回复询问 MOQ"),
    ("AutoBrake Czech", "CZ", "Dvorak", "Engineering", "replied", "A", "HIGH", 83, -1, 2, "捷克制动 OEM，回复要求检测报告"),
    ("Brake Parts Slovakia", "SK", "Kral", "Buyer", "replied", "B", "MID", 71, 1, 3, "斯洛伐克汽配，回复想要样品"),
    ("Nordic Auto Parts", "NO", "Solberg", "Owner", "replied", "C", "MID", 64, 0, 1, "挪威汽配，回复询问认证资质"),
    ("BrakeMaster Italia", "IT", "Ferrari", "Purchasing", "interested", "A", "HIGH", 88, 2, 2, "意大利制动 OEM，深度意向"),
    ("AutoParts Denmark", "DK", "Nielsen", "Owner", "interested", "B", "MID", 73, 3, 3, "丹麦汽配进口，想要产品目录"),
    ("Brake Supply Hungary", "HU", "Kovacs", "Buyer", "interested", "C", "MID", 62, 4, 1, "匈牙利汽配，正在比价"),
    ("AutoBremsen France", "FR", "Petit", "Technical", "sample_pending", "A", "HIGH", 81, 1, 2, "法国制动技术商，申请样品"),
    ("Brake Parts Belgium", "BE", "Peeters", "Purchasing", "sample_pending", "B", "MID", 74, 2, 3, "比利时汽配，确认寄样地址"),
    ("AutoParts Slovenia", "SI", "Novak", "Owner", "sample_sent", "C", "MID", 65, 5, 1, "斯洛文尼亚汽配，样品已寄出"),
    ("BrakeTech Netherlands", "NL", "Bakker", "Engineering", "sample_sent", "A", "HIGH", 84, 6, 2, "荷兰制动 OEM，样品台架测试"),
    ("AutoBrake Poland", "PL", "Nowicki", "Technical", "testing", "B", "HIGH", 79, 7, 3, "波兰制动厂，样品测试中"),
    ("Brake Parts Turkey", "TR", "Demir", "Owner", "testing", "B", "MID", 75, 8, 1, "土耳其汽配，样品测试中"),
    ("AutoParts Baltic", "LT", "Kazlauskas", "Buyer", "feedback", "B", "MID", 70, 9, 2, "立陶宛汽配，反馈样品数据"),
    ("BrakeTech Spain", "ES", "Alonso", "Engineering", "feedback", "A", "HIGH", 82, 10, 3, "西班牙制动 OEM，反馈积极"),
    ("AutoBrake Belgium", "BE", "Janssens", "Owner", "trial_order", "B", "HIGH", 80, 2, 1, "比利时制动商，试单确认中"),
    ("Brake Systems France", "FR", "Laurent", "Purchasing", "trial_order", "A", "HIGH", 86, 3, 2, "法国制动系统商，小批量试单"),
    ("AutoParts Vienna", "AT", "Wagner", "Buyer", "trial_order", "B", "MID", 76, 4, 3, "奥地利汽配，试单中"),
    ("BrakeMaster Germany", "DE", "Schneider", "Director", "won", "A", "HIGH", 91, 14, 1, "成交：德国制动 OEM 年度框架 8000 件"),
    ("AutoBrake Sweden", "SE", "Ek", "Owner", "won", "B", "HIGH", 89, 14, 2, "成交：瑞典制动进口商长期合作"),
    ("Brake Supply UK", "GB", "Clarke", "Purchasing", "won", "B", "HIGH", 87, 14, 3, "成交：英国汽配分销商"),
    ("AutoParts Romania", "RO", "Dumitrescu", "Buyer", "lost", "C", "LOW", 44, 0, 1, "Lost：价格无法匹配"),
    ("AutoBrake Latvia", "LV", "Ozols", "Buyer", "lost", "C", "LOW", 43, 0, 3, "Lost：需求量过小"),
    ("Brake Parts Estonia", "EE", "Saar", "Purchasing", "cooling", "C", "MID", 51, -4, 1, "冷却：4 封无回复"),
    ("AutoParts Finland", "FI", "Korhonen", "Owner", "cooling", "C", "LOW", 47, -6, 2, "冷却：无回复"),
    ("BrakeTech Lithuania", "LT", "Petrauskas", "Buyer", "cooling", "B", "MID", 54, -3, 3, "冷却：3 封无回复"),
]


def _seed(db, users):
    members = [u for u in users if u.role != "owner"]
    if not members:
        members = users
    owner_ids = [u.id for u in members]
    today = _d(0)

    # 生成客户
    for i, row in enumerate(PROSPECTS):
        (company, country, contact, title, stage, profile, value, score, nfd_off, owner_idx, note) = row
        # 用客户序号混合分配，保证 4 个业务员都有客户和发送记录（目标看板才真实）
        owner_id = owner_ids[(i + owner_idx) % len(owner_ids)]
        if stage == "new" and i % 7 == 0:
            owner_id = None  # 部分新客户未分配
        slug = re.sub(r"[^a-z0-9]+", "", company.lower())[:24]
        email = f"contact@{slug}.com"
        p = Prospect(
            tenant_id=1, owner_user_id=owner_id,
            contact=contact, company=company, country=country, title=title,
            website=f"www.{slug}.com",
            size="20-100 employees", industry="Auto parts", phone="+49 30 0000 %04d" % i,
            email=email, source="Trade Show", source_channel="Trade Show",
            development_batch="Automechanika Frankfurt 2026",
            first_touch_channel="email", timezone="Europe/Berlin",
            profile_type=profile, profile_source="manual", ai_score=score,
            value_level=value, email_verified=1, email_verdict="valid",
            sales_stage=stage, status="Following up",
            next_follow_date=(_d(nfd_off) if stage not in ("won", "lost", "cooling") else (_d(nfd_off) if stage == "cooling" else "")),
            reminder_note=(FOLLOWUP_REASONS.get(stage, "") if stage not in ("won", "lost") else ""),
            next_follow_reason=(SHORT_FOLLOWUP_REASONS.get(stage, "") if stage not in ("won", "lost") else ""),
            note=_en_note(stage, country, profile), email_status=("bounced" if i in (36, 37, 81) else "active"),
            is_deleted=0, created_at=_now(-20 - i % 10),
        )
        if stage == "won":
            p.status = "成交"
            p.next_follow_date = ""
        if stage == "lost":
            p.status = "Lost"
            p.next_follow_date = ""
        if stage == "cooling":
            p.status = "Following up"
            p.reminder_note = ""
        if stage in ("sample_pending", "sample_sent", "testing", "feedback"):
            p.sample_status = {"sample_pending": "requested", "sample_sent": "sent",
                               "testing": "testing", "feedback": "feedback"}[stage]
            p.sample_sent_date = _d(-5)
        db.add(p)
        db.flush()

        # 互动记录
        if stage in ("touched", "connected", "replied", "interested", "sample_pending",
                     "sample_sent", "testing", "feedback", "trial_order", "won", "cooling"):
            for k in range(1, 3):
                intro = OUTBOUND_INTRO[i % len(OUTBOUND_INTRO)] % (contact, "Sales")
                db.add(Interaction(prospect_id=p.id, owner_user_id=owner_id,
                                   direction="outbound", channel="email",
                                   subject="Brake parts spec — %s" % company,
                                   content=intro,
                                   interacted_at=_now(-10 + k * 3)))
        if stage in ("replied", "interested", "sample_pending", "sample_sent",
                     "testing", "feedback", "trial_order", "won"):
            intent = {"replied": "INFORMATION_REQUEST", "interested": "POSITIVE_ENGAGEMENT",
                      "sample_pending": "SAMPLE", "sample_sent": "SAMPLE_ADDRESS",
                      "testing": "SAMPLE", "feedback": "POSITIVE_ENGAGEMENT",
                      "trial_order": "QUOTE_REQUEST", "won": "PURCHASE_ORDER"}[stage]
            pool = REPLY_BY_STAGE.get(stage, [])
            reply_text = pool[i % len(pool)] if pool else "Thanks for your email, could you send more details?"
            db.add(Interaction(prospect_id=p.id, owner_user_id=owner_id,
                               direction="inbound", channel="email",
                               subject="Re: %s" % company, content=reply_text,
                               reply_intent=intent, interacted_at=_now(-5)))
            if stage == "replied":
                db.add(Interaction(prospect_id=p.id, owner_user_id=owner_id,
                                   direction="inbound", channel="email",
                                   subject="Re: catalogue — %s" % company,
                                   content="Also, could you include your brake pad range for commercial vehicles?",
                                   reply_intent="INFORMATION_REQUEST", interacted_at=_now(-4)))

        # 邮件队列
        slot = (i + owner_idx) % len(owner_ids)
        if stage in ("touched", "connected", "replied", "interested", "cooling"):
            # Simulate realistic differences: Alex full attendance, Ben ~80%, Chris ~60%, Dana full + more follow-ups
            skip = (slot == 1 and i % 5 == 0) or (slot == 2 and i % 3 == 0)
            if not skip:
                # Some emails land last week (Ben ~half, Chris ~2/3) so this week shows a comparison
                last_week = (slot == 1 and i % 2 == 0) or (slot == 2 and i % 3 != 0)
                db.add(EmailQueue(prospect_id=p.id, owner_user_id=owner_id, to_email=email,
                                  subject="Brake component data — %s" % company,
                                  body="Dear %s,\n\nFollowing up on our earlier email — here are our brake disc & pad specifications with batch inspection data (dimension/hardness/balance). Our ECE R90 certified range covers 256-410mm and most EU car & truck applications, MOQ 500 pcs.\n\nWould a sample set help your team evaluate?\n\nBest regards" % contact,
                                  status="sent", sender_key="primary", sent_at=_demo_send_at(i, last_week=last_week)))
        if stage in ("replied", "interested", "sample_sent", "won", "trial_order"):
            db.add(EmailQueue(prospect_id=p.id, owner_user_id=owner_id, to_email=email,
                              subject="Follow-up with data — %s" % company,
                              body="Dear %s,\n\nFollowing up with the batch inspection report and lead time details...\n\nBest regards" % contact,
                              status="sent", sender_key="primary", sent_at=_demo_send_at(i + 1)))
        if i % 6 == 0:
            db.add(EmailQueue(prospect_id=p.id, owner_user_id=owner_id, to_email=email,
                              subject="Draft: custom spec enquiry — %s" % company,
                              body="Dear %s,\n\nWe noticed your company focuses on brake systems and aftermarket parts...\nAI-drafted outreach email — pending human review.\n\nBest regards" % contact,
                              status="draft", sender_key="primary"))
        if i % 9 == 0:
            db.add(EmailQueue(prospect_id=p.id, owner_user_id=owner_id, to_email=email,
                              subject="Follow up — %s" % company,
                              body="Following up on our earlier email...",
                              status="pending", sender_key="acc_2",
                              scheduled_at=_now(0, 23)))

        # 开发计划
        if stage in ("touched", "replied", "interested", "sample_sent"):
            db.add(Sequence(prospect_id=p.id, owner_user_id=owner_id, step_number=1,
                            channel="email", status="pending",
                            subject="Intro email", content="First touch email content..."))
            db.add(Sequence(prospect_id=p.id, owner_user_id=owner_id, step_number=2,
                            channel="email", status="pending",
                            subject="Follow up", content="Follow-up email content..."))

        # 情报
        if i % 5 != 1:
            db.add(Intelligence(prospect_id=p.id, tenant_id=1, owner_user_id=owner_id,
                                website_key_points=json.dumps(WEB_HINTS[i % len(WEB_HINTS)], ensure_ascii=False),
                                icebreak_angles=json.dumps(ICE_BREAKS[i % len(ICE_BREAKS)], ensure_ascii=False),
                                hiring_signals=json.dumps(HIRING_HINTS[i % len(HIRING_HINTS)], ensure_ascii=False),
                                osint_report=json.dumps(OSINT_HINTS[i % len(OSINT_HINTS)], ensure_ascii=False),))

        # 商机
        if stage in ("trial_order", "won", "interested", "sample_sent"):
            deal_stage = {"trial_order": "方案报价", "won": "Won",
                          "interested": "需求确认", "sample_sent": "谈判中"}[stage]
            db.add(Deal(prospect_id=p.id, tenant_id=1, owner_user_id=owner_id,
                        name="%s — Order" % company,
                        amount=(i % 5 + 2) * (18000 if stage == "won" else 12000),
                        stage=deal_stage, expected_date=_d(20)))

        # 样品事件
        if stage in ("sample_pending", "sample_sent", "testing", "feedback"):
            db.add(SampleEvent(prospect_id=p.id, tenant_id=1,
                               stage=p.sample_status or "requested", event_date=_d(-5)))

    # 操作记录
    db.add(AuditLog(tenant_id=1, user_id=owner_ids[0], action="import_prospects", detail="Imported 40 customers (demo data)"))
    db.add(AuditLog(tenant_id=1, user_id=owner_ids[0], action="ai_score", target="prospect#1", detail="AI scoring"))
    db.add(AuditLog(tenant_id=1, user_id=owner_ids[1], action="send_email", target="prospect#2", detail="Sent outreach email"))
    db.add(BackupRecord(tenant_id=1, user_id=owner_ids[0], kind="db_full", file_path="Demo data backup"))
    db.commit()


def reset_demo_data(db) -> dict:
    """清空并重建演示数据（仅演示版调用）。"""
    _clear_demo_tables(db)
    _ensure_demo_users(db)
    _seed_email_accounts(db)
    _seed_profile_categories(db)
    users = db.query(User).order_by(User.id.asc()).all()
    _seed_knowledge(db)
    _seed(db, users)
    # 为 3 个重点客户生成报价历史 + 对话全景（让演示版开箱就能展示新功能）
    _seed_quote_panorama(db)
    return {"ok": True, "prospects": db.query(Prospect).count()}


def _seed_quote_panorama(db):
    """从演示客户里挑 3 个有代表性的（询价中/测试中/Won），
    用 AI 生成报价历史 + 对话全景，让客户一打开演示版就能看到新功能效果。
    失败不阻塞：AI key 没配或调用失败时静默跳过。"""
    from services.quote_extractor import extract_quotes_for_prospect, generate_dialogue_panorama
    stages = ["replied", "testing", "won"]
    picked = []
    for st in stages:
        p = (
            db.query(Prospect)
            .filter(Prospect.is_deleted == 0, Prospect.sales_stage == st)
            .order_by(Prospect.id.asc())
            .first()
        )
        if p:
            picked.append(p)
    if not picked:
        return
    for p in picked:
        try:
            nq = extract_quotes_for_prospect(p.id, limit=40)
            rp = generate_dialogue_panorama(p.id)
            print(f"[demo seed] {p.company} (stage={p.sales_stage}): quotes={nq} panorama={rp.get('success')}")
        except Exception as exc:
            print(f"[demo seed] {p.company} FAILED: {exc}")


def _ensure_demo_users(db):
    """Make sure the demo account group exists and is clean: remove legacy Chinese/pinyin demo users, add missing accounts, and normalize names/roles."""
    from models import Tenant
    from services.auth_service import hash_password
    for old_email in _LEGACY_DEMO_EMAILS:
        db.query(User).filter(User.email == old_email).delete(synchronize_session=False)
    db.commit()
    t = db.query(Tenant).filter(Tenant.id == 1).first()
    if t is None:
        t = Tenant(id=1, name="Demo Auto Parts (sample)", plan="team", max_users=10, status="active")
        db.add(t)
        db.flush()
    tid = t.id
    for email, name, role, pwd in DEMO_USERS:
        u = db.query(User).filter(User.email == email).first()
        if u is None:
            db.add(User(tenant_id=tid, role=role, name=name, email=email,
                        password_hash=hash_password(pwd), status="active"))
        else:
            # 修正历史遗留的乱码名字/角色（演示账号以规范值为准）
            u.name = name
            u.role = role
    db.commit()


def _seed_email_accounts(db):
    """演示版：3 个工作邮箱账号绑定成员（SMTP 密码不写入代码，客户自行配置）。"""
    from models import EmailAccount
    members = {u.email: u for u in db.query(User).filter(User.status == "active").all()}
    accounts = [
        ("primary", "Main work mailbox", "Alex Carter", "alex@demo.com"),
        ("acc_2", "Work mailbox 2", "Ben Miller", "ben@demo.com"),
        ("acc_3", "Work mailbox 3", "Chris Wilson", "chris@demo.com"),
    ]
    for key, name, smtp_name, member_email in accounts:
        uid = members.get(member_email)
        db.add(EmailAccount(key=key, name=name, smtp_name=smtp_name,
                            bound_user_id=uid.id if uid else None,
                            sort_order=0, is_active=1))
    db.commit()


def _seed_profile_categories(db):
    """演示版：汽配行业客户画像分类（客户可在系统设置里自定义）。"""
    import json as _json
    from models import SystemSetting
    cats = [
        {"key": "A", "label": "OEM / vehicle manufacturer"},
        {"key": "B", "label": "Brand / importer"},
        {"key": "C", "label": "Distributor / retailer"},
        {"key": "D", "label": "Workshop chain"},
        {"key": "E", "label": "E-commerce / platform"},
    ]
    val = _json.dumps(cats, ensure_ascii=False)
    row = db.query(SystemSetting).filter(SystemSetting.key == "profile_categories").first()
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key="profile_categories", value=val))
    db.commit()
