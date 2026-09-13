"""Trade document generator — per ft-doc-gen spec.

5 standard documents + 1 冷开发 extension:
  [1] Quotation Sheet     — HTML (self-contained, printable)
  [2] Proforma Invoice    — HTML
  [3] Commercial Invoice  — HTML (含船名航次/提单号/装船日期)
  [4] Sales Contract      — HTML (11 Articles)
  [5] Packing List        — HTML (箱号/净重/毛重/CBM)
  [E] AI Proposal         — HTML (冷开发扩展: AI生成的8段方案型报价)
  [冷开发] Customs Decl.     — HTML (报关单, 海关标准格式)

All output files are self-contained HTML with inline CSS — no external dependencies.
Open in any browser, Ctrl+P to print/save as PDF.
Input follows references/input-schema.md (built-in as INPUT_SCHEMA_GUIDE).
"""

import io
import json
import logging
import re
import xml.sax.saxutils as saxutils
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
#  HTML escaping
# ═══════════════════════════════════════

def _esc(s) -> str:
    """HTML-escape a string for safe output."""
    if s is None:
        return ""
    if isinstance(s, (int, float)):
        return str(s)
    return saxutils.escape(str(s))


COMPANY_DEFAULTS = {
    "name": "{{COMPANY}} (Suzhou) Co., Ltd.",
    "short": "{{COMPANY}}",
    "address": "Suzhou, Jiangsu, China",
    "contact": "{{USER_NAME}}",
    "email": "{{USER_EMAIL}}",
    "phone": "+86-512-XXXX-XXXX",
    "website": "{{WEBSITE}}",
}

PRODUCT_DEFAULTS = {
    "category": "Product category (fill in your real one)",
    "tolerance": "Per your spec (fill in)",
    "edge_chipping": "Material / finish per spec",
    "surface_quality": "Per customer spec (fill in)",
    "centration": "Per your spec (fill in)",
    "diameter_range": "Size range (fill in your real range)",
    "standard_sizes": "Per your catalog (fill in)",
    "monthly_capacity": "Per your capacity (fill in)",
    "sampling_lead": "XX days (fill in)",
    "production_lead": "XX days (fill in)",
    "moq": "XX pcs (fill in)",
    "certification": "Your certifications (fill in)",
}

INCOTERMS_2020 = {
    "EXW": ("Ex Works", "Goods ready at seller's premises"),
    "FCA": ("Free Carrier", "Handed over to carrier"),
    "FOB": ("Free On Board", "Loaded on board"),
    "CFR": ("Cost and Freight", "On board (same as FOB)"),
    "CIF": ("Cost, Insurance, Freight", "On board plus insurance"),
    "DAP": ("Delivered At Place", "At destination, ready for unloading"),
    "DDP": ("Delivered Duty Paid", "Delivered to destination, duty paid"),
}

PAYMENT_METHODS = {
    "T/T 30/70": "30% deposit, 70% before shipment",
    "T/T in advance": "100% before shipment",
    "L/C at sight": "Sight letter of credit",
    "L/C 30 days": "Letter of credit, 30 days",
    "L/C 60 days": "Letter of credit, 60 days",
    "D/P at sight": "Documents against payment at sight",
    "D/A 30": "Documents against acceptance, 30 days",
    "D/A 60": "Documents against acceptance, 60 days",
    "O/A": "Open account (pay after receipt)",
}

# ═══════════════════════════════════════
#  Field validation
# ═══════════════════════════════════════

REQUIRED_FIELDS = ["seller.name", "seller.address", "buyer.name", "buyer.address", "currency", "items"]
REQUIRED_ITEM_FIELDS = ["description", "quantity", "unit_price"]

def _validate_input(data: dict, doc_type: str) -> list[str]:
    """Return list of missing required fields. Empty = valid."""
    errors = []
    for f in REQUIRED_FIELDS:
        parts = f.split(".")
        v = data
        for p in parts:
            v = v.get(p) if isinstance(v, dict) else None
        if not v:
            errors.append(f"Missing: {f}")
    items = data.get("items", [])
    if not items:
        errors.append("items is empty")
        return errors
    if doc_type != "packing_list":
        for i, item in enumerate(items):
            for rf in REQUIRED_ITEM_FIELDS:
                if not item.get(rf):
                    errors.append(f"Item[{i}] missing: {rf}")
    if doc_type == "commercial_invoice":
        shipping = data.get("shipping", {})
        for sf in ["port_of_loading", "port_of_discharge"]:
            if not shipping.get(sf):
                errors.append(f"shipping.{sf} required for CI")
    return errors


def _calc_total(items: list) -> float:
    return sum(int(i.get("quantity", 0)) * float(i.get("unit_price", 0)) for i in items)


# ═══════════════════════════════════════
#  HTML common helpers
# ═══════════════════════════════════════

_CSS_COMMON = """*{box-sizing:border-box;margin:0;padding:0}
body{width:210mm;margin:0 auto;padding:12mm 15mm;font-family:"宋体",SimSun,serif;font-size:10pt;color:#1e293b;line-height:1.5}
.company-header{text-align:center;margin-bottom:12px}
.company-header .name{font-size:15pt;font-weight:bold;color:#1e3a5f}
.company-header .meta{font-size:8pt;color:#64748b;margin-top:2px}
.doc-title{text-align:center;font-size:16pt;font-weight:bold;color:#2563eb;margin:16px 0;letter-spacing:3px}
table{border-collapse:collapse}
.meta-table{width:100%;margin:8px 0}
.meta-table td{border:1px solid #94a3b8;padding:3px 6px;font-size:9pt}
.meta-table .lbl{background:#f1f5f9;color:#475569;font-weight:bold;width:14%}
.two-col{width:100%;margin:10px 0}
.two-col td{border:1px solid #333;padding:6px 8px;vertical-align:top}
.two-col .hdr{background:#1e3a5f;color:#fff;font-weight:bold;font-size:9pt;padding:4px 8px}
.items-table{width:100%;margin:10px 0;border:1px solid #333}
.items-table th{background:#2563eb;color:#fff;font-size:9pt;padding:5px 6px;border:1px solid #1d4ed8;text-align:center}
.items-table td{border:1px solid #94a3b8;padding:4px 6px;font-size:9pt}
.items-table td.num{text-align:right}
.items-table td.center{text-align:center}
.total-row td{background:#d1fae5;font-weight:bold;color:#065f46;border:1px solid #6ee7b7}
.notes{font-size:8.5pt;color:#475569;margin:8px 0;line-height:1.5}
.notes p{margin:2px 0}
.sig-block{text-align:right;margin-top:20px;font-size:10pt}
.sig-block .sig-name{font-weight:bold;font-size:11pt}
.sig-block .sig-meta{font-size:8.5pt;color:#64748b}
.bank-detail{font-size:9pt;color:#334155;margin:8px 0;line-height:1.6}
.bank-detail .bank-title{font-weight:bold;font-size:10pt}
.warn{color:#dc2626;font-weight:bold;font-size:8.5pt}
.declaration{font-size:8.5pt;color:#475569;margin:8px 0}
.section-hdr{font-size:12pt;font-weight:bold;color:#059669;margin:14px 0 6px 0;border-bottom:1px solid #6ee7b7;padding-bottom:4px}
.article-title{font-size:11pt;font-weight:bold;color:#1e3a5f;margin:10px 0 2px 0}
.article-body{font-size:10pt;margin:0 0 8px 20px;white-space:pre-line}
.est-value{font-size:11pt;font-weight:bold;color:#2563eb;margin:10px 0}
@media print{body{margin:0;padding:10mm 12mm}}
"""


def _html_error(title: str, errors: list[str]) -> bytes:
    items = "\n".join(f"<li>{_esc(e)}</li>" for e in errors)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{_esc(title)}</title>
<style>{_CSS_COMMON}</style>
</head>
<body>
<div class="doc-title" style="color:#dc2626">{_esc(title)}</div>
<ul style="color:#dc2626">{items}</ul>
</body>
</html>"""
    return html.encode("utf-8")


def _company_header_html() -> str:
    return f"""<div class="company-header">
<div class="name">{_esc(COMPANY_DEFAULTS["name"])}</div>
<div class="meta">{_esc(COMPANY_DEFAULTS["address"])} | {_esc(COMPANY_DEFAULTS["email"])} | {_esc(COMPANY_DEFAULTS["website"])}</div>
</div>"""


def _doc_title_html(title: str) -> str:
    return f'<div class="doc-title">{_esc(title)}</div>'


def _meta_bar_html(fields: list) -> str:
    """Render a horizontal meta bar as a table. fields = [(label, value), ...]"""
    tds = []
    for label, value in fields:
        tds.append(f'<td class="lbl">{_esc(label)}</td><td>{_esc(value)}</td>')
    return '<table class="meta-table"><tr>' + "".join(tds) + '</tr></table>'


def _seller_buyer_block_html(seller: dict, buyer: dict) -> str:
    seller_info = f'{_esc(seller.get("name",""))}<br>{_esc(seller.get("address",""))}<br>Tel: {_esc(seller.get("phone",COMPANY_DEFAULTS["phone"]))}<br>Email: {_esc(seller.get("email",COMPANY_DEFAULTS["email"]))}'
    buyer_info = f'{_esc(buyer.get("name",""))}<br>{_esc(buyer.get("address",""))}<br>Attn: {_esc(buyer.get("contact",""))}<br>Email: {_esc(buyer.get("email",""))}'
    return f"""<table class="two-col">
<tr><td class="hdr">SELLER</td><td class="hdr">BUYER</td></tr>
<tr><td style="width:50%">{seller_info}</td><td style="width:50%">{buyer_info}</td></tr>
</table>"""


def _items_table_html(items: list, cols: list, currency: str = "EUR", total_label: str = "TOTAL") -> str:
    """Render items into an HTML table.

    cols = [{"key": "sku", "label": "SKU", "align": "left"}, ...]
    Special key "amount" computes qty * unit_price.
    Special key "#" is auto row number.
    """
    header_cells = "".join(f"<th>{_esc(c['label'])}</th>" for c in cols)
    rows_html = ""
    total_amount = 0.0

    for idx, item in enumerate(items):
        cells = ""
        for c in cols:
            key = c["key"]
            align = c.get("align", "left")
            cls = ""
            if align == "right":
                cls = ' class="num"'
            elif align == "center":
                cls = ' class="center"'

            if key == "#":
                val = str(idx + 1)
            elif key == "amount":
                qty = int(item.get("quantity", 0))
                price = float(item.get("unit_price", 0))
                amt = qty * price
                total_amount += amt
                val = f'{amt:,.2f}'
                cls = ' class="num"'
            elif key == "unit_price":
                val = f'{float(item.get(key, 0)):,.2f}'
                cls = ' class="num"'
            else:
                val = str(item.get(key, ""))
            cells += f"<td{cls}>{_esc(val)}</td>"
        rows_html += f"<tr>{cells}</tr>"

    # Total row — label in second-to-last column, value in last column
    total_cols = len(cols)
    total_cells = ""
    label_col = total_cols - 2
    for ci in range(total_cols):
        if ci == label_col:
            total_cells += f'<td class="num">{_esc(total_label)}</td>'
        elif ci == label_col + 1:
            total_cells += f'<td class="num">{total_amount:,.2f}</td>'
        else:
            total_cells += '<td></td>'
    rows_html += f'<tr class="total-row">{total_cells}</tr>'

    return f"""<table class="items-table">
<thead><tr>{header_cells}</tr></thead>
<tbody>{rows_html}</tbody>
</table>"""


def _sig_block_html(name: str = "{{USER_NAME}}", title: str = "Export Sales Engineer") -> str:
    return f"""<div class="sig-block">
<div class="sig-name">{_esc(name)}</div>
<div class="sig-meta">{_esc(title)}<br>{_esc(COMPANY_DEFAULTS["name"])}<br>{_esc(COMPANY_DEFAULTS["email"])}</div>
</div>"""


def _wrap_document(body_html: str, title: str = "Document") -> bytes:
    """Wrap body content in a full standalone HTML document."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{_esc(title)}</title>
<style>{_CSS_COMMON}</style>
</head>
<body>
{body_html}
</body>
</html>"""
    return html.encode("utf-8")


# ═══════════════════════════════════════
#  [1] Quotation Sheet — HTML
# ═══════════════════════════════════════

def generate_quotation(data: dict) -> bytes:
    """Generate Quotation Sheet as self-contained HTML with 3-tier volume pricing note."""
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    trade = data.get("trade", {})
    items = data.get("items", [])
    currency = data.get("currency", "EUR")
    doc_no = data.get("document_no", f'TD-QT-{date.today().strftime("%Y%m%d")}')
    doc_date = data.get("date", date.today().isoformat())
    incoterm = trade.get("incoterm", "EXW")

    meta = [
        ("QTN No.", doc_no),
        ("Date", doc_date),
        ("Valid Until", data.get("valid_until", "30 days")),
        ("Incoterm", f"{incoterm} {_esc(trade.get('place', COMPANY_DEFAULTS['address']))}"),
        ("Payment", trade.get("payment", "T/T 30/70")),
        ("Currency", currency),
        ("Delivery", trade.get("lead_time", PRODUCT_DEFAULTS["production_lead"])),
    ]

    item_cols = [
        {"key": "#", "label": "#", "align": "center"},
        {"key": "sku", "label": "SKU", "align": "left"},
        {"key": "description", "label": "Description", "align": "left"},
        {"key": "specification", "label": "Specification", "align": "left"},
        {"key": "unit", "label": "Unit", "align": "center"},
        {"key": "quantity", "label": "Qty", "align": "right"},
        {"key": "unit_price", "label": "Unit Price", "align": "right"},
        {"key": "amount", "label": "Amount", "align": "right"},
    ]

    body = _company_header_html()
    body += _doc_title_html("QUOTATION")
    body += _seller_buyer_block_html(seller, buyer)
    body += _meta_bar_html(meta)
    body += _items_table_html(items, item_cols, currency)

    # 3-tier volume pricing note
    body += f"""<div class="notes">
<p><strong>Volume Pricing (contact us for exact tier quotes):</strong></p>
<p>50-100 pcs &mdash; Standard price as listed</p>
<p>100-500 pcs &mdash; Volume discount available</p>
<p>500-1000 pcs &mdash; Significant volume discount</p>
<p>1000+ pcs &mdash; Contact for tailored pricing</p>
</div>"""

    # Terms
    body += f"""<div class="notes">
<p>1. All prices in {_esc(currency)}, {_esc(incoterm)} {_esc(trade.get("place", COMPANY_DEFAULTS["address"]))} (Incoterms 2020).</p>
<p>2. Lead time: {_esc(PRODUCT_DEFAULTS["sampling_lead"])} for samples, {_esc(PRODUCT_DEFAULTS["production_lead"])} for production.</p>
<p>3. Payment: {_esc(trade.get("payment", "T/T 30/70"))}.</p>
<p>4. This quotation is valid for {_esc(data.get("valid_until", "30 days from issue"))}.</p>
<p>5. Tolerance: {_esc(PRODUCT_DEFAULTS["tolerance"])}. Surface quality: {_esc(PRODUCT_DEFAULTS["surface_quality"])}.</p>
<p>6. MOQ: {_esc(PRODUCT_DEFAULTS["moq"])}. Prices subject to final confirmation.</p>
</div>"""

    body += _sig_block_html()
    return _wrap_document(body, f"Quotation {_esc(doc_no)}")


# ═══════════════════════════════════════
#  [2] Proforma Invoice — HTML
# ═══════════════════════════════════════

def generate_pi(data: dict) -> bytes:
    """Generate Proforma Invoice as self-contained HTML."""
    errors = _validate_input(data, "pi")
    if errors:
        return _html_error("Validation Errors", errors)

    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    trade = data.get("trade", {})
    items = data.get("items", [])
    currency = data.get("currency", "EUR")
    doc_no = data.get("document_no", f'TD-PI-{date.today().strftime("%Y%m%d")}')
    doc_date = data.get("date", date.today().isoformat())
    incoterm = trade.get("incoterm", "EXW")

    meta = [
        ("PI No.", doc_no),
        ("Date", doc_date),
        ("Incoterm", f"{incoterm} {_esc(trade.get('place', 'Suzhou'))}"),
        ("Payment", trade.get("payment", "T/T 30/70")),
        ("Currency", currency),
        ("Country of Origin", data.get("country_of_origin", "China")),
    ]

    item_cols = [
        {"key": "#", "label": "#", "align": "center"},
        {"key": "sku", "label": "SKU", "align": "left"},
        {"key": "description", "label": "Description", "align": "left"},
        {"key": "specification", "label": "Specification", "align": "left"},
        {"key": "unit", "label": "Unit", "align": "center"},
        {"key": "quantity", "label": "Qty", "align": "right"},
        {"key": "unit_price", "label": "Unit Price", "align": "right"},
        {"key": "amount", "label": "Amount", "align": "right"},
    ]

    body = _company_header_html()
    body += _doc_title_html("PROFORMA INVOICE")
    body += _seller_buyer_block_html(seller, buyer)
    body += _meta_bar_html(meta)
    body += _items_table_html(items, item_cols, currency)

    total = _calc_total(items)

    # Total in words
    if total > 0:
        body += f'<div class="notes"><strong>SAY TOTAL:</strong> {_esc(_amount_to_words(total, currency))}</div>'

    # Bank details
    bank_info = seller.get("bank", {})
    if bank_info and bank_info.get("account_no"):
        iban_html = f'IBAN: {_esc(bank_info["iban"])}<br>' if bank_info.get("iban") else ""
        intermediary_html = f'Intermediary Bank: {_esc(bank_info["intermediary"])}<br>' if bank_info.get("intermediary") else ""
        body += f"""<div class="bank-detail">
<div class="bank-title">Bank Details:</div>
Beneficiary: {_esc(bank_info.get("beneficiary", seller.get("name", "")))}<br>
Bank: {_esc(bank_info.get("bank_name", ""))}<br>
Account No.: {_esc(bank_info.get("account_no", ""))}<br>
SWIFT: {_esc(bank_info.get("swift", ""))}<br>
{iban_html}{intermediary_html}</div>"""
    else:
        body += '<div class="warn">Bank Details: [TO BE CONFIRMED — user must verify bank info before sending]</div>'

    # Notes
    body += f"""<div class="notes">
<p>1. All prices in {_esc(currency)}, {_esc(incoterm)} {_esc(trade.get("place", "Suzhou, China"))} (Incoterms 2020).</p>
<p>2. Lead time: {_esc(trade.get("lead_time", PRODUCT_DEFAULTS["production_lead"]))} after deposit.</p>
<p>3. Payment: {_esc(trade.get("payment", "T/T 30/70"))}.</p>
<p>4. MOQ: {_esc(PRODUCT_DEFAULTS["moq"])}. Tolerance: {_esc(PRODUCT_DEFAULTS["tolerance"])}.</p>
<p>5. This PI is valid for {_esc(data.get("valid_until", "15 days"))}.</p>
</div>"""

    body += _sig_block_html()
    return _wrap_document(body, f"PI {_esc(doc_no)}")


# ═══════════════════════════════════════
#  [3] Commercial Invoice — HTML
# ═══════════════════════════════════════

def generate_invoice(data: dict) -> bytes:
    """Generate Commercial Invoice as self-contained HTML.

    REQUIRES shipping block: port_of_loading, port_of_discharge, vessel_voyage, bl_no, shipped_on.
    This is the customs clearance document — fields must match B/L and packing list.
    """
    errors = _validate_input(data, "commercial_invoice")
    if errors:
        return _html_error("Validation Errors", errors)

    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    trade = data.get("trade", {})
    items = data.get("items", [])
    shipping = data.get("shipping", {})
    currency = data.get("currency", "EUR")
    doc_no = data.get("document_no", f'TD-CI-{date.today().strftime("%Y%m%d")}')
    doc_date = data.get("date", date.today().isoformat())
    incoterm = trade.get("incoterm", "FOB")

    body = _company_header_html()
    body += _doc_title_html("COMMERCIAL INVOICE")

    # Seller / Buyer / Notify Party block
    seller_info = f'{_esc(seller.get("name", COMPANY_DEFAULTS["name"]))}<br>{_esc(seller.get("address", COMPANY_DEFAULTS["address"]))}<br>Tel: {_esc(seller.get("phone", COMPANY_DEFAULTS["phone"]))}<br>Email: {_esc(seller.get("email", COMPANY_DEFAULTS["email"]))}<br>Tax ID: {_esc(seller.get("tax_id", "N/A"))}'
    buyer_info = f'{_esc(buyer.get("name", ""))}<br>{_esc(buyer.get("address", ""))}<br>Attn: {_esc(buyer.get("contact", ""))}<br>Email: {_esc(buyer.get("email", ""))}'
    notify_party = data.get("notify_party", {})
    notify_name = notify_party.get("name", buyer.get("name", "")) if notify_party else buyer.get("name", "")

    body += f"""<table class="two-col">
<tr><td class="hdr">SELLER / EXPORTER</td><td class="hdr">BUYER / CONSIGNEE</td></tr>
<tr><td style="width:50%">{seller_info}</td><td style="width:50%">{buyer_info}</td></tr>
<tr><td class="hdr" style="background:#64748b">NOTIFY PARTY</td><td>{_esc(notify_name)}</td></tr>
</table>"""

    # Meta bar
    meta = [
        ("Invoice No.", doc_no),
        ("Date", doc_date),
        ("Incoterm", f"{incoterm} {_esc(trade.get('place', 'Shanghai'))} (Incoterms 2020)"),
        ("Payment", trade.get("payment", "T/T 30/70")),
    ]
    body += _meta_bar_html(meta)

    # Shipping details
    ship_items = []
    ship_fields = [
        ("Port of Loading", shipping.get("port_of_loading", "")),
        ("Port of Discharge", shipping.get("port_of_discharge", "")),
        ("Vessel &amp; Voyage No.", shipping.get("vessel_voyage", "")),
        ("B/L No.", shipping.get("bl_no", "")),
        ("Shipped on", shipping.get("shipped_on", "")),
        ("Marks &amp; Numbers", shipping.get("marks", "")),
        ("Container No.", shipping.get("container_no", "")),
    ]
    for label, val in ship_fields:
        if val:
            ship_items.append(f"<strong>{_esc(label)}:</strong> {_esc(val)}")

    if ship_items:
        body += '<div class="notes" style="border:1px solid #cbd5e1;padding:8px;background:#f8fafc">'
        body += '<strong style="color:#2563eb;font-size:10pt">Shipping Information</strong><br>'
        body += "<br>".join(ship_items)
        body += '</div>'

    # Items table with weight/CBM columns
    item_cols = [
        {"key": "#", "label": "#", "align": "center"},
        {"key": "sku", "label": "SKU", "align": "left"},
        {"key": "description", "label": "Description", "align": "left"},
        {"key": "specification", "label": "Specification", "align": "left"},
        {"key": "unit", "label": "Unit", "align": "center"},
        {"key": "quantity", "label": "Qty", "align": "right"},
        {"key": "net_weight_kg", "label": "Net Wt (kg)", "align": "right"},
        {"key": "gross_weight_kg", "label": "Gross Wt (kg)", "align": "right"},
        {"key": "unit_price", "label": "Unit Price", "align": "right"},
        {"key": "amount", "label": "Amount", "align": "right"},
    ]
    body += _items_table_html(items, item_cols, currency)

    # Summary totals
    total_packages = sum(int(it.get("packages", 1)) for it in items)
    total_net = sum(float(it.get("net_weight_kg", 0)) for it in items)
    total_gross = sum(float(it.get("gross_weight_kg", 0)) for it in items)
    total_cbm = sum(float(it.get("cbm", 0)) for it in items)
    total_amount = _calc_total(items)

    body += f"""<div class="notes" style="font-weight:bold;color:#1e3a5f;font-size:10pt">
<div>Total Packages: {total_packages}</div>
<div>Total Net Weight: {total_net:,.2f} kg</div>
<div>Total Gross Weight: {total_gross:,.2f} kg</div>
<div>Total CBM: {total_cbm:,.3f} m&sup3;</div>
<div>Total Amount: {_esc(currency)} {total_amount:,.2f}</div>
"""
    if total_amount > 0:
        body += f"<div>SAY TOTAL: {_esc(_amount_to_words(total_amount, currency))}</div>"
    body += "</div>"

    body += '<div class="declaration"><strong>We certify that the goods are of Chinese origin. The information above is true and correct.</strong></div>'

    # Signature with stamp placeholder
    body += f"""<div class="sig-block">
<div class="sig-name">{{USER_NAME}}</div>
<div class="sig-meta">Export Sales Engineer<br>{_esc(COMPANY_DEFAULTS["name"])}<br><br>Date: _______________<br>Stamp: _______________</div>
</div>"""

    return _wrap_document(body, f"CI {_esc(doc_no)}")


# ═══════════════════════════════════════
#  [4] Sales Contract — HTML
# ═══════════════════════════════════════

def generate_contract(data: dict) -> bytes:
    """Generate Sales Contract as self-contained HTML with 11 Articles."""
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    trade = data.get("trade", {})
    items = data.get("items", [])
    currency = data.get("currency", "EUR")
    contract_no = data.get("document_no", f'TD-SC-{date.today().strftime("%Y%m%d")}')
    contract_date = data.get("date", date.today().isoformat())
    contract_place = data.get("contract_place", "Suzhou, China")

    total_amount = _calc_total(items)

    body = _company_header_html()
    body += _doc_title_html("SALES CONTRACT")

    # Meta
    body += f"""<div style="margin:8px 0;font-size:11pt;font-weight:bold">
<div>Contract No.: {_esc(contract_no)}</div>
<div>Date: {_esc(contract_date)}</div>
<div>Place of Signing: {_esc(contract_place)}</div>
</div>"""

    # Parties
    body += f"""<div style="margin:10px 0">
<p><strong>THE SELLER:</strong> {_esc(seller.get("name", COMPANY_DEFAULTS["name"]))}</p>
<p><strong>Address:</strong> {_esc(seller.get("address", COMPANY_DEFAULTS["address"]))}</p>
<p><strong>THE BUYER:</strong> {_esc(buyer.get("name", ""))}</p>
<p><strong>Address:</strong> {_esc(buyer.get("address", ""))}</p>
</div>
<p style="font-size:10pt;margin:10px 0">This Contract is made by and between the Buyer and the Seller, whereby the Buyer agrees to buy and the Seller agrees to sell the undermentioned commodity according to the terms and conditions stipulated below:</p>"""

    # Articles
    article_descriptions = _build_item_descriptions(items)
    country_of_origin = data.get("country_of_origin", "China")
    shipping_marks = data.get("shipping", {}).get("marks", "Per Seller's standard")

    articles = [
        ("Article 1: Commodity, Country of Origin &amp; Shipping Marks",
         f"{article_descriptions}\n\nCountry of Origin: {country_of_origin}\nShipping Marks: {_esc(shipping_marks)}"),
        ("Article 2: Quantity, Unit Price &amp; Total Amount",
         _build_article2(items, currency, total_amount)),
        ("Article 3: Incoterms",
         f'{trade.get("incoterm", "FOB")} {_esc(trade.get("place", "Shanghai"))} (Incoterms 2020)\n\nThe risk of loss or damage to the goods passes from Seller to Buyer when the goods are delivered in accordance with the chosen Incoterm.'),
        ("Article 4: Payment",
         trade.get("payment", "T/T 30% deposit, 70% before shipment")),
        ("Article 5: Shipment",
         _build_article5(data, trade)),
        ("Article 6: Documents Required",
         "The Seller shall provide:\n  a) Signed Commercial Invoice\n  b) Packing List\n  c) Bill of Lading / Air Waybill\n  d) Certificate of Origin (if required)\n  e) Other documents as agreed"),
        ("Article 7: Inspection",
         "The Buyer shall inspect the goods within 14 days of receipt. Any quality claim must be submitted in writing with photographic evidence within this period. The Seller shall not be liable for claims made after 14 days."),
        ("Article 8: Force Majeure",
         "Neither party shall be liable for any failure or delay in performance due to events beyond their reasonable control, including but not limited to: natural disasters, war, riots, epidemics, government actions, or labor disputes."),
        ("Article 9: Dispute Resolution",
         data.get("dispute_resolution", "Any dispute arising from this contract shall be settled through friendly negotiation. If negotiation fails, the dispute shall be submitted to arbitration in Shanghai in accordance with the rules of CIETAC.")),
        ("Article 10: Governing Law",
         "This contract shall be governed by and construed in accordance with the laws of the People's Republic of China."),
        ("Article 11: Miscellaneous",
         "This contract constitutes the entire agreement between the parties. Amendments must be in writing and signed by both parties. This contract is made in two originals, each party holding one."),
    ]

    for title, content in articles:
        body += f'<div class="article-title">{_esc(title)}</div>'
        body += f'<div class="article-body">{_esc(content)}</div>'

    # Signature block
    seller_name = seller.get("name", COMPANY_DEFAULTS["name"])
    buyer_name = buyer.get("name", "")
    body += f"""<table class="two-col" style="margin-top:20px">
<tr><td class="hdr">THE BUYER</td><td class="hdr">THE SELLER</td></tr>
<tr>
<td style="width:50%">{_esc(buyer_name)}<br><br>Signature: _______________<br>Date: _______________</td>
<td style="width:50%">{_esc(seller_name)}<br>{{USER_NAME}}, Export Sales Engineer<br><br>Signature: _______________<br>Date: _______________</td>
</tr>
</table>"""

    return _wrap_document(body, f"SC {_esc(contract_no)}")


# ═══════════════════════════════════════
#  [5] Packing List — HTML
# ═══════════════════════════════════════

def generate_packing_list(data: dict) -> bytes:
    """Generate Packing List as HTML — 1:1 match of 真实装箱单模板 (HVI-20260601 style)."""
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    items = data.get("items", [])
    doc_no = data.get("document_no") or f'HVI-{date.today().strftime("%Y%m%d")}'
    doc_date_str = data.get("date", "")
    if doc_date_str:
        from datetime import datetime as _dt
        try:
            dt = _dt.fromisoformat(doc_date_str)
            doc_date_str = dt.strftime("%B %d, %Y")
        except Exception:
            doc_date_str = date.today().strftime("%B %d, %Y")
    else:
        doc_date_str = date.today().strftime("%B %d, %Y")

    seller_name = seller.get("name", "{{COMPANY}}")
    seller_addr = seller.get("address", "{{COMPANY_ADDRESS}}")
    seller_email = seller.get("email", "{{USER_EMAIL_2}}")
    buyer_name = buyer.get("name", "")
    buyer_addr = buyer.get("address", "")
    buyer_contact = buyer.get("contact", "")
    po_no = data.get("po_no", "")

    rows = ""
    total_qty = 0
    for item in items:
        qty = int(item.get("quantity", 0))
        total_qty += qty
        item_no = item.get("sku", item.get("hs_code", ""))
        desc = item.get("description", "Product item (fill in)")
        spec = item.get("specification", "")
        full_desc = f"{desc} {spec}".strip()
        unit = item.get("unit", "PCS")
        nw = item.get("net_weight_kg", "") or "---"
        gw = item.get("gross_weight_kg", "") or "---"
        rows += f"""        <tr>
            <td>{_esc(item_no)}</td>
            <td>{_esc(full_desc)}</td>
            <td>{qty}</td>
            <td>{_esc(unit)}</td>
            <td>{nw}</td>
            <td>{gw}</td>
        </tr>
"""

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Packing List - {_esc(doc_no)}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 1000px;
            margin: 30px auto;
            padding: 40px;
            color: #2c3e50;
            line-height: 1.6;
            background-color: white;
        }}
        .header-section {{
            border-bottom: 3px solid #2c3e50;
            padding-bottom: 15px;
            margin-bottom: 30px;
        }}
        .company-name {{
            font-size: 24px;
            font-weight: 700;
            color: #2c3e50;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }}
        .header-section p {{
            font-size: 14px;
            color: #555;
        }}
        .pl-header {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 35px;
            gap: 20px;
        }}
        .pl-header div {{
            flex: 1;
        }}
        .pl-header h2 {{
            font-size: 26px;
            font-weight: 700;
            color: #2c3e50;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .pl-header strong {{
            font-size: 14px;
            color: #2c3e50;
        }}
        .pl-header div:last-child {{
            text-align: right;
        }}
        .pack-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 25px;
            font-size: 14px;
        }}
        .pack-table th {{
            background-color: #2c3e50;
            color: white;
            padding: 14px;
            text-align: left;
            font-weight: 600;
        }}
        .pack-table td {{
            padding: 12px 14px;
            border-bottom: 1px solid #e0e0e0;
        }}
        .total-info {{
            font-size: 15px;
            line-height: 1.8;
            margin-top: 10px;
        }}
        .material-info {{
            margin-top: 25px;
            font-size: 13px;
            color: #555;
            border-top: 1px solid #eee;
            padding-top: 15px;
        }}
    </style>
</head>
<body>
<div class="header-section">
    <p class="company-name">{_esc(seller_name)}</p>
    <p>{_esc(seller_addr)}</p>
    <p>Email: {_esc(seller_email)}</p>
</div>
<div class="pl-header">
    <div>
        <strong>CONSIGNEE:</strong><br>
        {_esc(buyer_contact)}<br>
        {_esc(buyer_name)}<br>
        {_esc(buyer_addr)}
    </div>
    <div>
        <h2>PACKING LIST</h2>
        <strong>Invoice No:</strong> {_esc(doc_no)}<br>
        Date: {_esc(doc_date_str)}<br>
        <strong>Your PO No:</strong> {_esc(po_no)}
    </div>
</div>
<table class="pack-table">
    <thead>
        <tr>
            <th>Item No</th>
            <th>Goods Description</th>
            <th>Qty</th>
            <th>Unit</th>
            <th>Net Weight(KGS)</th>
            <th>Gross Weight(KGS)</th>
        </tr>
    </thead>
    <tbody>
{rows}    </tbody>
</table>
<div class="total-info">
    <strong>Total Quantity:</strong> {total_qty} PCS<br>
    <strong>Total Net Weight:</strong> ---<br>
    <strong>Total Gross Weight:</strong> ---<br>
    <strong>Packing:</strong> Export Carton<br>
    <strong>Measurement:</strong> ---
</div>
<div class="material-info">
    <strong>Main Material Composition:</strong><br>
    Silicon Dioxide 81%, Diboron Trioxide 13%, Sodium Oxide 4%, Aluminum Oxide 2%
</div>
</body>
</html>
"""
    return body.encode("utf-8")

def generate_customs_declaration(data: dict) -> bytes:
    """Generate Customs Declaration (报关单) as HTML matching 海关标准格式 — strict template alignment."""
    seller = data.get("seller", {})
    buyer = data.get("buyer", {})
    items = data.get("items", [])
    customs = data.get("customs", {})
    doc_date = data.get("date", date.today().isoformat())

    seller_name = seller.get("name", COMPANY_DEFAULTS["name"])
    buyer_name = buyer.get("name", "")
    currency = data.get("currency", "EUR")

    items_html = ""
    for ri, item in enumerate(items):
        qty = int(item.get("quantity", 0))
        up = float(item.get("unit_price", 0))
        tp = qty * up
        nw = item.get("net_weight_kg", "") or ""
        items_html += f"""  <tr>
    <td>{ri + 1}</td>
    <td>{_esc(item.get("hs_code", customs.get("hs_code", "13-9001-01")))}</td>
    <td class="left">{_esc(item.get("description", "光学玻璃样品"))} {_esc(item.get("specification", ""))}</td>
    <td>{qty}个{f' / {nw}KG' if nw else ''}</td>
    <td>{up:.2f} / {tp:.2f} / {_esc(currency)}</td>
    <td>{_esc(data.get("country_of_origin", "中国"))}</td>
    <td>{_esc(customs.get("dest_country", buyer.get("address", "")))}</td>
    <td>{_esc(customs.get("source_tax", data.get("country_of_origin", "苏州") + "/照章征税"))}</td>
  </tr>
"""

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>中华人民共和国海关出口货物报关单</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{width:210mm;margin:0 auto;padding:12mm;font-family:"宋体",SimSun;font-size:9pt;line-height:1.4;}}
h1{{font-size:14pt;font-weight:bold;text-align:center;margin-bottom:8px;}}
.top-line{{margin-bottom:6px;}}
.fill{{display:inline-block;border-bottom:1px solid #000;min-width:100px;}}
table{{width:100%;border-collapse:collapse;margin:10px 0;}}
td{{border:1px solid #000;padding:4px;vertical-align:middle;}}
.left{{text-align:left;}}
.center{{text-align:center;}}
.right{{text-align:right;}}
.bold{{font-weight:bold;}}
</style>
</head>
<body>
<h1>中华人民共和国海关出口货物报关单</h1>
<div class="top-line">
预录入编号:<span class="fill">{_esc(customs.get("pre_entry_no", ""))}</span> &nbsp;&nbsp;海关编号: <span class="fill">{_esc(customs.get("customs_no", ""))}</span> &nbsp;&nbsp;({_esc(customs.get("customs_office", "上海快件"))})
</div>
<div class="top-line">仅供核对用 &nbsp;&nbsp;页码/页数:1/1</div>
<table>
  <tr>
    <td>出口日期</td>
    <td class="fill">{_esc(customs.get("export_date", doc_date))}</td>
    <td>申报日期</td>
    <td class="fill">{_esc(customs.get("declare_date", doc_date))}</td>
    <td>备案号</td>
    <td>{_esc(customs.get("record_no", "3201960RF7"))}</td>
    <td>出境关别</td>
    <td>{_esc(customs.get("exit_customs", "上海快件"))}</td>
  </tr>
  <tr>
    <td>境内发货人</td>
    <td colspan="3" class="left">{_esc(seller_name)}</td>
    <td>境外收货人</td>
    <td colspan="3" class="left">{_esc(buyer_name)}</td>
  </tr>
  <tr>
    <td>运输方式</td>
    <td>{_esc(customs.get("transport_mode", "航空运输"))}</td>
    <td>运输工具名称及航次号</td>
    <td class="fill">{_esc(customs.get("vessel", ""))}</td>
    <td>提运单号</td>
    <td colspan="3" class="fill">{_esc(customs.get("bl_no", ""))}</td>
  </tr>
  <tr>
    <td>征免性质</td>
    <td>{_esc(customs.get("tax_nature", "一般征税"))}</td>
    <td>监管方式</td>
    <td>{_esc(customs.get("supervision_mode", "货样广告品A"))}</td>
    <td>生产销售单位</td>
    <td colspan="3" class="left">{_esc(seller_name)}</td>
  </tr>
  <tr>
    <td>许可证号</td>
    <td class="fill">{_esc(customs.get("license_no", ""))}</td>
    <td>合同协议号</td>
    <td>{_esc(customs.get("contract_no", data.get("document_no", "")))}</td>
    <td>离境口岸</td>
    <td>{_esc(customs.get("departure_port", "上海浦东国际机场"))}</td>
    <td>指运港</td>
    <td>{_esc(customs.get("dest_port", ""))}</td>
  </tr>
  <tr>
    <td>运抵国(地区)</td>
    <td>{_esc(customs.get("arrival_country", buyer.get("address", "")))}</td>
    <td>贸易国(地区)</td>
    <td>{_esc(customs.get("trade_country", buyer.get("address", "")))}</td>
    <td>件数</td>
    <td>{customs.get("total_packages", sum(int(i.get("quantity", 0)) for i in items))}</td>
    <td>包装种类</td>
    <td>{_esc(customs.get("package_type", "纸箱"))}</td>
  </tr>
  <tr>
    <td>毛重(千克)</td>
    <td>{customs.get("gross_weight_kg", "")}</td>
    <td>净重(千克)</td>
    <td>{customs.get("net_weight_kg", "")}</td>
    <td>运费</td>
    <td>{_esc(customs.get("freight", "0.00"))}</td>
    <td>保费</td>
    <td>{_esc(customs.get("insurance", "0.00"))}</td>
  </tr>
  <tr>
    <td>杂费</td>
    <td>{_esc(customs.get("misc_fee", "0.00"))}</td>
    <td>成交方式</td>
    <td>{_esc(data.get("trade", {}).get("incoterm", "EXW"))}</td>
    <td colspan="4"></td>
  </tr>
  <tr>
    <td colspan="8" class="left">随附单证及编号：{_esc(customs.get("accompanying_docs", "商业发票、装箱单、出口商品申报要素"))}</td>
  </tr>
  <tr>
    <td colspan="8" class="left">标记唛码及备注：{_esc(customs.get("marks_remarks", "MADE IN CHINA"))}</td>
  </tr>
  <tr class="bold center">
    <td>项号</td>
    <td>商品编号</td>
    <td>商品名称及规格型号</td>
    <td>数量及单位</td>
    <td>单价/总价/币制</td>
    <td>原产国</td>
    <td>最终目的国</td>
    <td>货源地/征免</td>
  </tr>
{items_html}</table>
<div style="margin:15px 0;">
特殊关系确认：<span class="fill">{_esc(customs.get("special_relation", ""))}</span> &nbsp;&nbsp;价格影响确认：<span class="fill">{_esc(customs.get("price_influence", ""))}</span> &nbsp;&nbsp;支付特许权使用费确认：<span class="fill">{_esc(customs.get("royalty_payment", ""))}</span>
<br>公式定价确认：<span class="fill">{_esc(customs.get("formula_pricing", ""))}</span> &nbsp;&nbsp;暂定价格确认：<span class="fill">{_esc(customs.get("provisional_price", ""))}</span> &nbsp;&nbsp;自报自缴：否 &nbsp;&nbsp;水运中转：<span class="fill"></span>
</div>
<table>
  <tr>
    <td>报关人员</td>
    <td class="fill">{_esc(customs.get("declarant", ""))}</td>
    <td>报关人员证号</td>
    <td class="fill">{_esc(customs.get("declarant_id", ""))}</td>
    <td colspan="4" class="left">兹申明对以上内容承担如实申报、依法纳税之法律责任</td>
  </tr>
  <tr>
    <td>申报单位</td>
    <td colspan="3" class="left">{_esc(seller_name)}</td>
    <td colspan="4" class="left">申报单位(签章)：<span class="fill"></span></td>
  </tr>
  <tr>
    <td colspan="8" class="left">海关批注及签章：<span class="fill"></span></td>
  </tr>
</table>
</body>
</html>
"""
    return body.encode("utf-8")


# ═══════════════════════════════════════
#  Proposal helpers (shared with router)
# ═══════════════════════════════════════


def _load_product_kb(db) -> str:
    try:
        from models import KnowledgeBase
        entries = db.query(KnowledgeBase).filter(
            KnowledgeBase.is_active == 1,
            KnowledgeBase.category == "product",
        ).all()
        if entries:
            return "\n\n".join([f"## {e.title}\n{e.content}" for e in entries])
    except Exception:
        pass
    return ""


def _build_conv_context(interactions) -> str:
    if not interactions:
        return "New client — no prior interactions."
    parts = []
    for ix in reversed(interactions):
        dtag = "[Client]" if ix.direction == "inbound" else "[Cold outreach]"
        parts.append(f"{dtag} {ix.channel}: {(ix.content or ix.subject or '')[:200]}")
    return "\n".join(parts)


def _build_proposal_prompt(prospect, product_context: str, conv_context: str, spec_note: str, target_price: str) -> str:
    from services.ai_router import get_voice_rules, get_signature_for_profile
    voice = get_voice_rules()
    sig = get_signature_for_profile(prospect.profile_type)
    return f"""You are an export sales specialist for {{COMPANY}}.

## CLIENT PROFILE
Company: {prospect.company or 'N/A'}
Country: {prospect.country or 'N/A'}
Profile type: {prospect.profile_type or 'Unknown'}
Contact: {prospect.contact or prospect.decision_maker or 'N/A'}

## PRODUCT KNOWLEDGE
{product_context[:3000] or '{{COMPANY}}: Please add product and company details in the Knowledge Base.'}

## CONVERSATION CONTEXT
{conv_context}

## CUSTOM NOTES
Spec requirement: {spec_note or 'Not specified'}
Target price: {target_price or 'Not specified — suggest based on typical pricing'}

{voice}

SIGNATURE:
{sig}

## TASK
Generate a complete structured cooperation proposal with the following 8 sections.
Return ONLY valid JSON — no markdown, no code fences:

{{
  "subject": "Proposal: {{COMPANY}} products for {prospect.company or 'Your Company'}",
  "proposal_title": "Cooperation Proposal",
  "sections": {{
    "1_specs": "Product specifications with concrete numbers",
    "2_packaging": "Packaging — individual wrapping, tray qty, carton, protection",
    "3_lead_time": "Lead time — sample batch, production batch, realistic ranges",
    "4_sample_policy": "Sample policy — free/paid, qty limit, shipping, evaluation period",
    "5_payment_terms": "Payment terms — T/T, L/C, deposit %, balance timing",
    "6_selling_points": "3-5 selling points specific to this client's profile and country",
    "7_channel_fit": "How product fits their market channel (OEM/distributor/repair)",
    "8_next_step": "Clear single next action — call, drawing review, sample dispatch, etc."
  }},
  "total_estimated_value": "Estimated order value range in EUR (e.g. €5,000-15,000)",
  "notes": "Caveats, recommendations, things to confirm before proceeding"
}}

CRITICAL: All section content in English. Output ONLY the JSON object."""


def _build_item_descriptions(items: list) -> str:
    if not items:
        return "Product details per attached specification."
    lines = []
    for it in items:
        lines.append(f'- {it.get("description","Product item")}: {it.get("specification","See spec sheet")}, {it.get("unit","pcs")}, Qty: {it.get("quantity","TBD")}')
    return "\n".join(lines)


def _build_article2(items: list, currency: str, total: float) -> str:
    lines = []
    for it in items:
        price = float(it.get("unit_price", 0))
        qty = int(it.get("quantity", 0))
        lines.append(f'{it.get("description","Item")}: {qty} {it.get("unit","pcs")} @ {currency} {price:,.2f} = {currency} {qty*price:,.2f}')
    lines.append(f'\nTotal Contract Value: {currency} {total:,.2f}')
    if total > 0:
        lines.append(f'({_amount_to_words(total, currency)})')
    return "\n".join(lines)


def _build_article5(data: dict, trade: dict) -> str:
    shipping = data.get("shipping", {})
    pd_default = "Per Buyer's instructions"
    pd_default_loading = trade.get("place", "Shanghai")
    parts = [
        f'Port of Loading: {shipping.get("port_of_loading", pd_default_loading)}',
        f'Port of Discharge: {shipping.get("port_of_discharge", pd_default)}',
        f'Latest Shipment Date: {shipping.get("shipped_on", trade.get("lead_time", PRODUCT_DEFAULTS["production_lead"]) + " after deposit")}',
    ]
    partial = shipping.get("partial_shipment", "")
    if partial:
        parts.append(f'Partial Shipment: {partial}')
    transship = shipping.get("transshipment", "")
    if transship:
        parts.append(f'Transshipment: {transship}')
    return "\n".join(parts)


def _amount_to_words(amount: float, currency: str = "EUR") -> str:
    """Convert a number to words (English). Simple implementation."""
    if amount == 0:
        return f"Zero {currency}"
    if amount >= 1_000_000:
        return f'Say {currency} {amount:,.2f} only'
    thousands = int(amount // 1000)
    hundreds = int(amount % 1000)
    cents = int(round((amount - int(amount)) * 100))
    if thousands > 0 and hundreds > 0:
        return f'Say {currency} {thousands} Thousand {hundreds} and Cents {cents:02d} Only'
    elif thousands > 0:
        return f'Say {currency} {thousands} Thousand and Cents {cents:02d} Only'
    else:
        return f'Say {currency} {hundreds} and Cents {cents:02d} Only'


def _parse_json(raw: str) -> dict:
    try: return json.loads(raw)
    except json.JSONDecodeError: pass
    m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
    if m:
        try: return json.loads(m.group(1))
        except json.JSONDecodeError: pass
    m2 = re.search(r'\{[\s\S]*\}', raw)
    if m2:
        try: return json.loads(m2.group(0))
        except json.JSONDecodeError: pass
    return {"error": "Could not parse JSON", "raw": raw}


# ═══════════════════════════════════════
#  Proposal rendering
# ═══════════════════════════════════════

def _render_proposal_html(prospect, data: dict) -> bytes:
    """冷开发 extension: render AI proposal as self-contained HTML."""
    sections = data.get("sections", {})

    body = _company_header_html()
    body += _doc_title_html("COOPERATION PROPOSAL")

    # Client info block
    info_lines = []
    for label, val in [
        ("Prepared for", prospect.company),
        ("Contact", prospect.contact or prospect.decision_maker),
        ("Country", prospect.country),
        ("Date", date.today().strftime("%Y-%m-%d")),
    ]:
        if val:
            info_lines.append(f"<strong>{_esc(label)}:</strong> {_esc(str(val))}")

    body += '<div style="font-size:10pt;margin:10px 0;padding:8px;background:#f8fafc;border:1px solid #e2e8f0">'
    body += "<br>".join(info_lines)
    body += "</div>"

    # 8 sections
    section_labels = {
        "1_specs": "1. Product Specifications",
        "2_packaging": "2. Packaging Details",
        "3_lead_time": "3. Lead Time",
        "4_sample_policy": "4. Sample Policy",
        "5_payment_terms": "5. Payment Terms",
        "6_selling_points": "6. Key Selling Points",
        "7_channel_fit": "7. Channel Fit Analysis",
        "8_next_step": "8. Recommended Next Step",
    }

    for key, label in section_labels.items():
        content = sections.get(key, "")
        if not content:
            continue
        body += f'<div class="section-hdr">{_esc(label)}</div>'
        body += f'<div style="font-size:10pt;margin:0 0 12px 0;white-space:pre-line">{_esc(content)}</div>'

    # Estimated value
    if data.get("total_estimated_value"):
        body += '<hr style="border:1px solid #cbd5e1;margin:10px 0">'
        body += f'<div class="est-value">Estimated Order Value: {_esc(data["total_estimated_value"])}</div>'

    # Notes
    if data.get("notes"):
        body += '<div style="font-size:9.5pt;color:#92400e;margin:10px 0;padding:8px;background:#fffbeb;border:1px solid #fcd34d">'
        body += f'<strong>Notes &amp; Recommendations:</strong><br>{_esc(data["notes"])}'
        body += '</div>'

    body += _sig_block_html()
    return _wrap_document(body, "Cooperation Proposal")


# ═══════════════════════════════════════
#  [E] AI Proposal — HTML (冷开发 扩展)
# ═══════════════════════════════════════

def generate_proposal(data: dict) -> bytes:
    """Render a cooperation proposal from pre-generated AI data as HTML.

    This is the synchronous render-only counterpart. The AI generation step
    (calling the generate-proposal API) produces the proposal data; this
    function renders it to a self-contained HTML document.

    The data dict should include:
      - sections: dict with 8 sections (1_specs through 8_next_step)
      - total_estimated_value: str
      - notes: str
      - buyer: dict with name, contact, address (for header info)
    """
    buyer = data.get("buyer", {})

    class _ProspectInfo:
        pass

    prospect = _ProspectInfo()
    prospect.company = buyer.get("name", "")
    prospect.contact = buyer.get("contact", "")
    prospect.country = buyer.get("address", "")
    prospect.profile_type = data.get("profile_type", "")

    return _render_proposal_html(prospect, data)
