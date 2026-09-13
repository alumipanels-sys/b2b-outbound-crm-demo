"""
POST /api/prospects/sell-export — export a sellable prospect list (xlsx)

Exports a clean, sellable prospect list as Excel — no internal system fields.

Exported columns:
  Company | Website | Country | Industry | Size | Contact | Job Title
  LinkedIn | Email | Phone
  Profile | AI Score | Value Tier | First Touch
  Source | Created At

Query params:
  min_score (float): minimum AI score, default 5
  profile_types (str): comma-separated filter, e.g. "A,B,D"
  value_level (str): HIGH/MID
  countries (str): comma-separated filter, e.g. "DE,US"
  limit (int): max rows, default 200
"""

from datetime import datetime
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Prospect

logger = logging.getLogger(__name__)

_SHEET_COLUMNS = [
    ("Company", "company"),
    ("Website", "website"),
    ("Country", "country"),
    ("Industry", "industry"),
    ("Company Size", "size"),
    ("Contact", "contact"),
    ("Job Title", "title"),
    ("LinkedIn", "linkedin"),
    ("Email", "email"),
    ("Phone", "phone"),
    ("Profile Tier", "profile_type"),
    ("AI Score", "ai_score"),
    ("Value Tier", "value_level"),
    ("First Touch", "first_touch_channel"),
    ("Source", "source"),
    ("Created At", "created_at"),
]


def _build_query(db: Session, min_score: float, profile_types: str | None,
                 value_level: str | None, countries: str | None, limit: int):
    """Build filtered query for sellable prospects."""
    q = db.query(Prospect).filter(
        Prospect.is_deleted == 0,
        Prospect.ai_score >= min_score,
        Prospect.profile_type.notin_(["EXCLUDE"]) if True else True,  # always exclude
    )
    q = q.filter(
        (Prospect.profile_type != "EXCLUDE") | (Prospect.profile_type.is_(None))
    )
    if profile_types:
        pts = [x.strip() for x in profile_types.split(",") if x.strip()]
        if pts:
            q = q.filter(Prospect.profile_type.in_(pts))
    if value_level:
        q = q.filter(Prospect.value_level == value_level.upper())
    if countries:
        cs = [x.strip().upper() for x in countries.split(",") if x.strip()]
        if cs:
            q = q.filter(Prospect.country.in_(cs))

    q = q.order_by(Prospect.ai_score.desc(), Prospect.id.desc())
    q = q.limit(min(limit, 500))
    return q.all()


def _build_xlsx(rows) -> io.BytesIO:
    """Build xlsx in memory using raw XML (no dependency)."""
    # We'll use openpyxl since it's commonly installed.
    # If not available, fall back to CSV.
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return _build_csv(rows)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prospect List"

    # -- Header style --
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # A-grade fill
    a_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")  # amber
    b_fill = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")  # green
    c_fill = PatternFill(start_color="F0F4FF", end_color="F0F4FF", fill_type="solid")  # blue

    thin_border = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        top=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )

    # -- Write headers --
    for col_idx, (label, _) in enumerate(_SHEET_COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = thin_border

    # -- Write data --
    body_font = Font(name="Calibri", size=10)
    body_align = Alignment(vertical="center")

    for row_idx, p in enumerate(rows, 2):
        pt = (p.profile_type or "").strip().upper()
        row_fill = None
        if pt == "A":
            row_fill = a_fill
        elif pt == "B":
            row_fill = b_fill
        elif pt == "C":
            row_fill = c_fill

        for col_idx, (_, attr) in enumerate(_SHEET_COLUMNS, 1):
            val = getattr(p, attr, "")
            if attr == "created_at" and val:
                val = val.strftime("%Y-%m-%d") if hasattr(val, "strftime") else str(val)[:10]
            elif attr == "ai_score" and val is not None:
                val = round(float(val), 1)
            cell = ws.cell(row=row_idx, column=col_idx, value=val if val not in (None, "None") else "")
            cell.font = body_font
            cell.alignment = body_align
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill

    # -- Column widths --
    col_widths = {
        1: 28,   # Company
        2: 24,   # Website
        3: 8,    # Country
        4: 18,   # Industry
        5: 10,   # Size
        6: 16,   # Contact
        7: 18,   # Title
        8: 28,   # LinkedIn
        9: 26,   # Email
        10: 16,  # Phone
        11: 10,  # Profile
        12: 8,   # AI score
        13: 8,   # Value tier
        14: 10,  # First touch
        15: 12,  # Source
        16: 12,  # Created at
    }
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # -- Freeze header --
    ws.freeze_panes = "A2"

    # -- Auto filter --
    ws.auto_filter.ref = f"A1:{get_column_letter(len(_SHEET_COLUMNS))}{len(rows)+1}"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def _build_csv(rows) -> io.BytesIO:
    """Fallback CSV when openpyxl not available."""
    import csv as csv_mod
    output = io.StringIO()
    writer = csv_mod.writer(output)
    # Header
    writer.writerow([label for label, _ in _SHEET_COLUMNS])
    # Data
    for p in rows:
        row = []
        for _, attr in _SHEET_COLUMNS:
            val = getattr(p, attr, "")
            if attr == "created_at" and val:
                val = val.strftime("%Y-%m-%d") if hasattr(val, "strftime") else str(val)[:10]
            elif attr == "ai_score" and val is not None:
                val = round(float(val), 1)
            row.append(str(val) if val not in (None, "None") else "")
        writer.writerow(row)
    buf = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    buf.seek(0)
    return buf


def _detect_format(rows) -> str:
    """Check if openpyxl available for xlsx, otherwise csv."""
    try:
        import openpyxl  # noqa
        return ".xlsx"
    except ImportError:
        return ".csv"


def register_sell_export_router(app):
    """Register the sell-export route on the prospects router or directly on app."""

    @app.post("/api/prospects/sell-export")
    async def sell_export(
        min_score: float = Query(5, ge=0, le=10),
        profile_types: str | None = Query(None),
        value_level: str | None = Query(None),
        countries: str | None = Query(None),
        limit: int = Query(200, ge=1, le=500),
        db: Session = Depends(get_db),
    ):
        rows = _build_query(db, min_score, profile_types, value_level, countries, limit)

        xlsx_buf = _build_xlsx(rows)
        ext = _detect_format(rows)

        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"customers_min{int(min_score)}_n{len(rows)}_{ts}{ext}"

        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if ext == ".xlsx"
            else "text/csv"
        )

        return StreamingResponse(
            xlsx_buf,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Exported-Count": str(len(rows)),
            },
        )
