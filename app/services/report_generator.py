"""
Daily Opportunity Report — generates a PDF summary and optionally emails it.
Uses reportlab for PDF generation.
"""
import logging
import io
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def generate_daily_report(db) -> bytes:
    """
    Generate a PDF daily opportunity report and return the bytes.

    Args:
        db: SQLAlchemy session

    Returns:
        PDF bytes
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        raise RuntimeError("reportlab is not installed. Run: pip install reportlab")

    from app.models import Opportunity, Signal
    from app.config import get_settings

    settings = get_settings()
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today_start - timedelta(days=1)

    # ── Query data ────────────────────────────────────────────────────────────
    all_opps = db.query(Opportunity).order_by(Opportunity.overall_score.desc()).all()
    new_today = [o for o in all_opps if o.created_at and o.created_at >= yesterday]
    high_priority = [o for o in all_opps if o.priority == "high"]
    active_pipeline = [o for o in all_opps if o.status not in ("closed",)]

    signal_counts = {}
    for s in db.query(Signal).all():
        signal_counts[s.signal_type] = signal_counts.get(s.signal_type, 0) + 1

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=20,
        textColor=colors.HexColor("#1a56db"),
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    h2_style = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#1e429f"),
        spaceBefore=14,
        spaceAfter=4,
    )
    body_style = styles["Normal"]
    small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=9)

    HEADER_BG = colors.HexColor("#1a56db")
    ROW_ALT = colors.HexColor("#f0f4ff")

    story = []

    # Header
    story.append(Paragraph(settings.COMPANY_NAME, title_style))
    story.append(Paragraph("Daily Opportunity Report", styles["Heading2"]))
    story.append(Paragraph(f"Generated: {now.strftime('%B %d, %Y at %H:%M UTC')}", small_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a56db")))
    story.append(Spacer(1, 0.4 * cm))

    # 1. Executive Summary
    story.append(Paragraph("Executive Summary", h2_style))
    summary_data = [
        ["Metric", "Count"],
        ["Total Opportunities", str(len(all_opps))],
        ["New (Last 24h)", str(len(new_today))],
        ["High Priority", str(len(high_priority))],
        ["Active Pipeline", str(len(active_pipeline))],
    ]
    summary_table = Table(summary_data, colWidths=[10 * cm, 6 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.3 * cm))

    # 2. New Opportunities (last 24h)
    story.append(Paragraph("New Opportunities (Last 24 Hours)", h2_style))
    if new_today:
        rows = [["Company", "Type", "Score", "Priority", "Status"]]
        for o in new_today[:15]:
            rows.append([
                Paragraph(o.company_name or "—", small_style),
                o.opportunity_type or "—",
                f"{o.overall_score:.2f}" if o.overall_score else "0.00",
                o.priority or "low",
                o.status or "new",
            ])
        t = Table(rows, colWidths=[5.5 * cm, 3.5 * cm, 2 * cm, 2.5 * cm, 3 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN",       (2, 0), (4, -1), "CENTER"),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No new opportunities in the last 24 hours.", body_style))
    story.append(Spacer(1, 0.3 * cm))

    # 3. Active Pipeline by Status
    story.append(Paragraph("Active Pipeline by Status", h2_style))
    status_groups: dict = {}
    for o in active_pipeline:
        status_groups.setdefault(o.status or "new", []).append(o)

    if status_groups:
        status_rows = [["Status", "Count", "High Priority"]]
        for st, items in sorted(status_groups.items()):
            hp = sum(1 for x in items if x.priority == "high")
            status_rows.append([st, str(len(items)), str(hp)])
        st_table = Table(status_rows, colWidths=[6 * cm, 4 * cm, 6 * cm])
        st_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",  (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(st_table)
    else:
        story.append(Paragraph("No active opportunities.", body_style))
    story.append(Spacer(1, 0.3 * cm))

    # 4. Signal Activity
    story.append(Paragraph("Signal Activity", h2_style))
    if signal_counts:
        sig_rows = [["Signal Type", "Total Detected"]]
        for sig_type, cnt in sorted(signal_counts.items(), key=lambda x: -x[1]):
            sig_rows.append([sig_type.replace("_", " ").title(), str(cnt)])
        sig_table = Table(sig_rows, colWidths=[10 * cm, 6 * cm])
        sig_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",    (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",  (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(sig_table)
    else:
        story.append(Paragraph("No signal data available.", body_style))
    story.append(Spacer(1, 0.3 * cm))

    # 5. Top 5 High-Priority Leads
    story.append(Paragraph("Top 5 High-Priority Leads", h2_style))
    top5 = sorted(high_priority, key=lambda x: x.overall_score or 0, reverse=True)[:5]
    if top5:
        for i, o in enumerate(top5, 1):
            action = "Send email outreach" if o.opportunity_type == "email_outreach" else "Prepare proposal"
            story.append(Paragraph(
                f"{i}. <b>{o.company_name or 'Unknown'}</b> — Score: {o.overall_score:.2f} | "
                f"Status: {o.status} | Action: {action}",
                body_style,
            ))
            story.append(Spacer(1, 0.15 * cm))
    else:
        story.append(Paragraph("No high-priority leads at this time.", body_style))

    # Footer
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    story.append(Paragraph(
        f"Confidential — {settings.COMPANY_NAME} | {settings.COMPANY_WEBSITE}",
        ParagraphStyle("Footer", parent=small_style, alignment=TA_CENTER, textColor=colors.grey),
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def send_daily_report_email(db) -> bool:
    """Generate PDF report and email it to MARKETING_EMAIL."""
    from app.config import get_settings
    from app.services.notification_service import get_notification_service

    settings = get_settings()
    if not settings.DAILY_REPORT_ENABLED:
        logger.info("[Report] Daily report email is disabled")
        return False

    if not settings.MARKETING_EMAIL:
        logger.warning("[Report] MARKETING_EMAIL not configured — skipping")
        return False

    try:
        pdf_bytes = generate_daily_report(db)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"daily_opportunity_report_{date_str}.pdf"

        ns = get_notification_service()
        success = ns.send_email_with_attachment(
            to_email=settings.MARKETING_EMAIL,
            subject=f"Daily Opportunity Report — {date_str}",
            body=(
                f"Please find attached the daily opportunity report for {date_str}.\n\n"
                f"Generated by {settings.COMPANY_NAME} AI Sales Platform."
            ),
            attachment_bytes=pdf_bytes,
            attachment_filename=filename,
            attachment_mime="application/pdf",
        )
        if success:
            logger.info(f"[Report] Daily report emailed to {settings.MARKETING_EMAIL}")
        return success
    except Exception as e:
        logger.error(f"[Report] Failed to send daily report: {e}")
        return False
