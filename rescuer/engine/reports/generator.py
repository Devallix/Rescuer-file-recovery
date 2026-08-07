import csv
import datetime
import html
import json
import os
from pathlib import Path

from rescuer.core.database import Database


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _scan_summary(db: Database, scan_id: int) -> dict:
    scan = db.query_one(
        "SELECT device_id, mode, started_at, finished_at, found_count FROM scans WHERE id = ?",
        (scan_id,),
    )
    counts = {
        row["status"] or "new": row["n"]
        for row in db.query(
            "SELECT status, COUNT(*) AS n FROM files WHERE scan_id = ? GROUP BY status",
            (scan_id,),
        )
    }
    recovered = db.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(bytes_written),0) AS bytes FROM recoveries "
        "WHERE scan_id = ? AND status = 'success'",
        (scan_id,),
    )
    return {
        "scan": dict(scan) if scan else {},
        "status_counts": counts,
        "recovered_count": int(recovered["n"]) if recovered else 0,
        "recovered_bytes": int(recovered["bytes"]) if recovered else 0,
    }


def _rows_for(db: Database, scan_id: int, status: str | None = None) -> list[dict]:
    where = "f.scan_id = ?"
    params: list = [scan_id]
    if status:
        where += " AND f.status = ?"
        params.append(status)
    return [dict(r) for r in db.query(
        f"SELECT f.name, f.ext, f.size, f.quality_score, f.confidence, f.is_deleted, "
        f"f.found_by, f.category, f.status, f.sha256, r.dest_path "
        f"FROM files f LEFT JOIN recoveries r ON r.file_id = f.id "
        f"WHERE {where} ORDER BY f.quality_score DESC", params,
    )]


def generate_csv(db: Database, scan_id: int, out_dir: str) -> str:
    path = os.path.join(out_dir, f"scan_{scan_id}_report_{datetime.date.today().isoformat()}.csv")
    os.makedirs(out_dir, exist_ok=True)
    rows = _rows_for(db, scan_id)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["name"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def generate_html(db: Database, scan_id: int, out_dir: str) -> str:
    summary = _scan_summary(db, scan_id)
    rows = _rows_for(db, scan_id)
    path = os.path.join(out_dir, f"scan_{scan_id}_report_{datetime.date.today().isoformat()}.html")
    os.makedirs(out_dir, exist_ok=True)

    def _esc(v):
        return html.escape(str(v if v is not None else ""))

    header = (
        "<html><head><meta charset='utf-8'><title>Rescuer Report</title>"
        "<style>body{font-family:Segoe UI,sans-serif;margin:24px;color:#0B0E14}"
        "h1{color:#2E8CFF}table{border-collapse:collapse;width:100%;font-size:13px}"
        "th,td{border:1px solid #cbd2dc;padding:6px 8px;text-align:left}"
        "th{background:#eef3fb}tr:nth-child(even){background:#f7f9fc}</style></head><body>"
    )
    body = [header, "<h1>Rescuer Recovery Report</h1>", f"<p>Generated: {_now()} | Scan ID: {scan_id}</p>"]
    body.append("<h2>Summary</h2>")
    body.append(f"<p>Found: <b>{summary['status_counts'].get('new', 0) + summary['status_counts'].get('queued', 0) + summary['recovered_count']}</b> | "
                f"Recovered: <b>{summary['recovered_count']}</b> | Bytes: <b>{summary['recovered_bytes']}</b></p>")
    body.append("<h2>Files</h2><table><tr><th>Name</th><th>Type</th><th>Size</th><th>Score</th>"
                "<th>Confidence</th><th>Deleted</th><th>Method</th><th>Status</th></tr>")
    for r in rows:
        body.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}%</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _esc(r.get("name")), _esc(r.get("ext")), _esc(r.get("size")),
                _esc(r.get("quality_score")), _esc(r.get("confidence")),
                "yes" if r.get("is_deleted") else "no",
                _esc(r.get("found_by")), _esc(r.get("status")),
            )
        )
    body.append("</table></body></html>")
    Path(path).write_text("\n".join(body), encoding="utf-8")
    return path


def generate_pdf(db: Database, scan_id: int, out_dir: str) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    summary = _scan_summary(db, scan_id)
    rows = _rows_for(db, scan_id)
    path = os.path.join(out_dir, f"scan_{scan_id}_report_{datetime.date.today().isoformat()}.pdf")
    os.makedirs(out_dir, exist_ok=True)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    story = [Paragraph("Rescuer Recovery Report", styles["Title"]),
             Paragraph(f"Scan {scan_id} &middot; generated {_now()}", styles["Normal"]),
             Spacer(1, 12)]
    story.append(Paragraph(
        f"Recovered {summary['recovered_count']} of {summary['status_counts'].get('new', 0)} new files "
        f"({summary['recovered_bytes']} bytes)", styles["Normal"]))
    story.append(Spacer(1, 12))

    data = [["Name", "Type", "Size", "Score", "Confidence", "Deleted", "Method", "Status"]]
    for r in rows[:500]:
        data.append([
            str(r.get("name") or ""), str(r.get("ext") or ""), str(r.get("size") or 0),
            str(r.get("quality_score") or 0), f"{r.get('confidence') or 0}%",
            "yes" if r.get("is_deleted") else "no", str(r.get("found_by") or ""),
            str(r.get("status") or ""),
        ])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E8CFF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd2dc")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f6fc")]),
    ]))
    story.append(table)
    doc.build(story)
    return path


def generate(db: Database, scan_id: int, out_dir: str, report_type: str = "html") -> str:
    if report_type == "csv":
        return generate_csv(db, scan_id, out_dir)
    if report_type == "pdf":
        return generate_pdf(db, scan_id, out_dir)
    return generate_html(db, scan_id, out_dir)
