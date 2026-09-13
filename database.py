"""Database engine, session, and seed data setup."""

import logging

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_fts5():
    """Create the FTS5 virtual table and sync triggers. Includes email/dm_email for search."""
    import sqlite3
    db_path = DATABASE_URL.replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        # Drop old FTS table if it exists (schema changed: added email, dm_email)
        conn.execute("DROP TABLE IF EXISTS prospects_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE prospects_fts USING fts5(
                company, contact, industry, country, website, note, email, dm_email,
                content='prospects', content_rowid='id'
            )
        """)
        conn.executescript("""
            CREATE TRIGGER IF NOT EXISTS prospects_fts_ai AFTER INSERT ON prospects BEGIN
                INSERT INTO prospects_fts(rowid, company, contact, industry, country, website, note, email, dm_email)
                VALUES (new.id, new.company, new.contact, new.industry, new.country, new.website, new.note, new.email, new.dm_email);
            END;
            CREATE TRIGGER IF NOT EXISTS prospects_fts_ad AFTER DELETE ON prospects BEGIN
                INSERT INTO prospects_fts(prospects_fts, rowid, company, contact, industry, country, website, note, email, dm_email)
                VALUES ('delete', old.id, old.company, old.contact, old.industry, old.country, old.website, old.note, old.email, old.dm_email);
            END;
            CREATE TRIGGER IF NOT EXISTS prospects_fts_au AFTER UPDATE ON prospects BEGIN
                INSERT INTO prospects_fts(prospects_fts, rowid, company, contact, industry, country, website, note, email, dm_email)
                VALUES ('delete', old.id, old.company, old.contact, old.industry, old.country, old.website, old.note, old.email, old.dm_email);
                INSERT INTO prospects_fts(rowid, company, contact, industry, country, website, note, email, dm_email)
                VALUES (new.id, new.company, new.contact, new.industry, new.country, new.website, new.note, new.email, new.dm_email);
            END;
        """)
        conn.execute("INSERT INTO prospects_fts(prospects_fts) VALUES('rebuild')")
        conn.commit()
        logger.info("FTS5 index initialized")
    except Exception as exc:
        logger.warning("FTS5 init: %s", exc)
    finally:
        conn.close()


# Skill system prompts are now served virtually by routers/knowledge.py
# — no DB seeding needed. They're always available regardless of database state.

_INITIAL_KNOWLEDGE = [
    {
        "category": "product",
        "title": "Product specifications (template - replace with your real details)",
        "content": (
            "Fill in your company's real product specifications here. The AI cites these facts when writing outreach emails and scoring:\n"
            "- Core product lines and names\n"
            "- Key parameter ranges (sizes, tolerances, finishes, etc.)\n"
            "- Quality standards and certifications\n"
            "- MOQ and lead times\n"
            "- Production capacity and common spec list\n"
            "Example: We manufacture precision components across a full size range and multiple finishes, ISO 9001 certified, flexible MOQ, samples in 10 days, production in 25 days."
        ),
        "tags": '["scoring", "email", "linkedin", "strategy"]',
        "is_active": 1,
    },
    {
        "category": "profile",
        "title": "Company positioning (template - replace with your real details)",
        "content": (
            "Fill in your company positioning here. The AI uses this to represent your company in every email:\n"
            "- Company name, year founded, size\n"
            "- Main business and core products\n"
            "- One-line selling point (concrete facts, no fluff)\n"
            "- Target customers and markets (countries, company types)\n"
            "- Contact details and website\n"
            "Example: We are a mid-size manufacturer of industrial components, exporting to European distributors and OEMs, focused on certified quality and reliable lead times."
        ),
        "tags": '["scoring", "email", "linkedin"]',
        "is_active": 1,
    },
    {
        "category": "forbidden",
        "title": "Forbidden actions (template - replace with your real rules)",
        "content": (
            "Fill in what the AI must never say or do, to prevent mistakes in customer communication:\n"
            "- What we cannot promise (lead times, prices, certifications)\n"
            "- What we cannot mention (competitor names, certificates we do not hold)\n"
            "- Customer types we do not approach (e.g. certain large groups, pure traders)\n"
            "- No vague praise or generic template flattery\n"
            "Example: Never promise 7-day delivery unless capacity is confirmed; never mention competitors; never approach pure trading intermediaries."
        ),
        "tags": '["email", "linkedin"]',
        "is_active": 1,
    },
    {
        "category": "guidelines",
        "title": "Customer profile & strategy (template - replace with your real profile)",
        "content": (
            "Fill in the customer types you most want to develop and their priority. The AI uses this for scoring and outreach ordering:\n"
            "- Who the ideal customer is (industry, size, region)\n"
            "- What their pain points are\n"
            "- Who the best person to reach is (purchasing / engineer / owner)\n"
            "- Priority order and exclusion criteria\n"
            "Example: Top priority is mid-size distributors in Germany and Switzerland with their own warehouse; their pain point is unstable supplier lead times. Exclude pure trading companies with no physical presence."
        ),
        "tags": '["scoring", "strategy"]',
        "is_active": 1,
    },
]


def init_knowledge_base():
    from models import KnowledgeBase
    db = SessionLocal()
    try:
        if db.query(KnowledgeBase).count() > 0:
            return
        for entry in _INITIAL_KNOWLEDGE:
            db.add(KnowledgeBase(**entry))
        db.commit()
        logger.info("Seeded knowledge_base with %d entries.", len(_INITIAL_KNOWLEDGE))
    except Exception as exc:
        db.rollback()
        logger.warning("Could not seed knowledge_base: %s", exc)
    finally:
        db.close()
