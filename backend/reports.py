"""
reports.py — Automatic reports (dashboard + scheduled email)
=============================================================
build_report() computes all numbers locally from SQLite (no AI cost).
insights() adds a short AI-written summary, cached once per day per period so
dashboard refreshes never spend extra quota. If the AI is unavailable the
summary falls back to rule-based bullet points.
"""

import json
import html
import logging
from datetime import datetime, timezone, timedelta

from logger import get_db_connection
import leads as leads_store

log = logging.getLogger(__name__)

INSIGHTS_PROMPT = """\
You are an operations analyst for {company_desc}'s customer-support inbox.
Write 4-6 short bullet points (plain text, each starting with "- ") summarising
the period below for a manager: what went well, what needs attention, and one
concrete suggestion. Use the numbers; do not invent any. Money values are in EUR (write €).
No headings.

DATA (last {days} days):
{data}\
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_reports():
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS report_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()


def build_report(days: int = 7) -> dict:
    now = _now()
    since = (now - timedelta(days=days)).isoformat()
    prev_since = (now - timedelta(days=2 * days)).isoformat()

    with get_db_connection() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, timestamp, sender, category, status, alert, used_rag, processing_ms, escalated, mood "
            "FROM email_logs WHERE timestamp >= ?", (prev_since,)
        ).fetchall()]
        gaps = [dict(r) for r in conn.execute(
            "SELECT question, category, count FROM kb_gaps WHERE status = 'open' ORDER BY count DESC LIMIT 5"
        ).fetchall()]
        unhappy = [dict(r) for r in conn.execute(
            "SELECT email, name, mood, last_summary, last_seen FROM customers "
            "WHERE mood IN ('frustrated', 'angry') AND last_seen >= ? ORDER BY last_seen DESC LIMIT 5",
            (since,),
        ).fetchall()]

    cur = [r for r in rows if r["timestamp"] >= since]
    prev = [r for r in rows if r["timestamp"] < since]
    real = [r for r in cur if r["status"] != "skipped"]

    def ai_answered(group):
        return sum(1 for r in group if (r["status"] == "sent" and not r["alert"]) or r["status"] == "auto_approved")

    topics: dict[str, int] = {}
    for r in real:
        topics[r["category"]] = topics.get(r["category"], 0) + 1

    daily = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date().isoformat()
        day_rows = [r for r in cur if r["timestamp"][:10] == day and r["status"] != "skipped"]
        daily.append({"date": day, "emails": len(day_rows), "ai": ai_answered(day_rows)})

    times = [r["processing_ms"] for r in real if r["processing_ms"] and r["status"] in ("sent", "auto_approved")]
    lead_m = leads_store.metrics(days=days)

    return {
        "days": days,
        "generated_at": now.isoformat(),
        "emails": len(real),
        "emails_prev": len([r for r in prev if r["status"] != "skipped"]),
        "ai_answered": ai_answered(real),
        "ai_rate": round(100 * ai_answered(real) / len(real)) if real else 0,
        "human_reviewed": sum(1 for r in real if r["status"] in ("approved", "rejected")),
        "waiting_review": sum(1 for r in real if r["status"] == "pending"),
        "escalations": sum(1 for r in real if r["escalated"] or r["alert"]),
        "followups_sent": sum(1 for r in cur if r["status"] == "followup"),
        "skipped_automated": sum(1 for r in cur if r["status"] == "skipped"),
        "kb_hit_rate": round(100 * sum(1 for r in real if r["used_rag"]) / len(real)) if real else 0,
        "avg_ai_seconds": round(sum(times) / len(times) / 1000, 1) if times else None,
        "topics": dict(sorted(topics.items(), key=lambda kv: -kv[1])),
        "daily": daily,
        "top_gaps": gaps,
        "unhappy_customers": unhappy,
        "leads": {
            "new": lead_m["new_in_period"],
            "open": lead_m["open"],
            "won": lead_m["won"],
            "win_rate": lead_m["win_rate"],
            "pipeline_value": lead_m["pipeline_value"],
            "ai": lead_m["by_handler"]["ai"]["total"],
            "human": lead_m["by_handler"]["human"]["total"],
        },
    }


def _rule_based_insights(r: dict) -> list[str]:
    tips = [f"{r['emails']} customer emails in the last {r['days']} days; the AI answered {r['ai_rate']}% on its own."]
    if r["emails_prev"]:
        change = round(100 * (r["emails"] - r["emails_prev"]) / r["emails_prev"])
        tips.append(f"Volume is {'up' if change >= 0 else 'down'} {abs(change)}% compared with the previous period.")
    if r["waiting_review"]:
        tips.append(f"{r['waiting_review']} emails are still waiting in the review queue.")
    if r["escalations"]:
        tips.append(f"{r['escalations']} emails were escalated (critical or unhappy customers).")
    if r["leads"]["new"]:
        tips.append(f"{r['leads']['new']} new sales leads; {r['leads']['open']} leads are open.")
    if r["top_gaps"]:
        tips.append(f"Most asked question without an article: \"{r['top_gaps'][0]['question']}\" — consider adding one.")
    return tips


def insights(report: dict, refresh: bool = False) -> dict:
    """AI summary bullets for a report, cached per day and period."""
    import os
    key = f"insights:{_now().date().isoformat()}:{report['days']}"
    if not refresh:
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM report_cache WHERE key = ?", (key,)).fetchone()
        if row:
            return json.loads(row[0])

    compact = {k: v for k, v in report.items() if k not in ("daily", "generated_at")}
    try:
        from provider import generate
        text = generate(INSIGHTS_PROMPT.format(
            company_desc=os.getenv("COMPANY_DESCRIPTION", "ArtCloud, a web hosting company"),
            days=report["days"],
            data=json.dumps(compact, ensure_ascii=False, default=str)[:4000],
        ))
        bullets = [l.lstrip("-•* ").strip() for l in text.splitlines() if l.strip().startswith(("-", "•", "*"))]
        result = {"bullets": bullets[:6] or _rule_based_insights(report), "source": "ai"}
    except Exception as e:
        log.warning("AI insights unavailable (%s) — using rule-based summary.", e)
        result = {"bullets": _rule_based_insights(report), "source": "rules"}

    result["generated_at"] = _now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO report_cache (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(result)),
        )
        conn.commit()
    return result


def email_html(report: dict, summary: dict, company: str) -> str:
    """Self-contained HTML email (inline styles only — email clients ignore <style>)."""
    e = html.escape
    tiles = [
        ("Emails", report["emails"]),
        ("Answered by AI", f"{report['ai_rate']}%"),
        ("New leads", report["leads"]["new"]),
        ("Escalations", report["escalations"]),
    ]
    tile_html = "".join(
        f'<td style="padding:14px;background:#f4f6fa;border-radius:10px;text-align:center;width:25%">'
        f'<div style="font-size:24px;font-weight:700;color:#1f2a37">{e(str(v))}</div>'
        f'<div style="font-size:12px;color:#556275">{e(k)}</div></td>'
        for k, v in tiles
    )
    bullets = "".join(f'<li style="margin:6px 0">{e(b)}</li>' for b in summary["bullets"])
    gaps = "".join(
        f'<li style="margin:4px 0">{e(g["question"])} <span style="color:#8b96a8">({g["count"]}×)</span></li>'
        for g in report["top_gaps"]
    ) or '<li style="color:#8b96a8">None — great coverage.</li>'
    unhappy = "".join(
        f'<li style="margin:4px 0">{e(c["name"] or c["email"])} — {e(c["mood"])}: {e(c["last_summary"] or "")}</li>'
        for c in report["unhappy_customers"]
    ) or '<li style="color:#8b96a8">No unhappy customers.</li>'

    return f"""<html><body style="margin:0;background:#f4f6fa;font-family:Segoe UI,Arial,sans-serif;color:#1f2a37">
<div style="max-width:640px;margin:0 auto;padding:24px">
  <div style="background:linear-gradient(135deg,#4f6bdc,#7158c4);border-radius:14px;padding:22px 24px;color:#fff">
    <div style="font-size:13px;opacity:.85">{e(company)} · last {report['days']} days</div>
    <div style="font-size:22px;font-weight:700;margin-top:4px">Support & sales report</div>
  </div>
  <table style="width:100%;border-spacing:8px;margin:12px -8px"><tr>{tile_html}</tr></table>
  <div style="background:#fff;border:1px solid #e4e8ef;border-radius:12px;padding:18px 22px;margin-top:8px">
    <div style="font-weight:700;margin-bottom:6px">Summary</div><ul style="padding-left:18px;margin:0">{bullets}</ul>
  </div>
  <div style="background:#fff;border:1px solid #e4e8ef;border-radius:12px;padding:18px 22px;margin-top:12px">
    <div style="font-weight:700;margin-bottom:6px">Sales</div>
    <div style="font-size:14px;color:#556275">{report['leads']['open']} open leads · {report['leads']['won']} won ·
    pipeline {report['leads']['pipeline_value']:,.0f} · AI handled {report['leads']['ai']} / people handled {report['leads']['human']}</div>
  </div>
  <div style="background:#fff;border:1px solid #e4e8ef;border-radius:12px;padding:18px 22px;margin-top:12px">
    <div style="font-weight:700;margin-bottom:6px">Questions the AI could not answer</div><ul style="padding-left:18px;margin:0">{gaps}</ul>
  </div>
  <div style="background:#fff;border:1px solid #e4e8ef;border-radius:12px;padding:18px 22px;margin-top:12px">
    <div style="font-weight:700;margin-bottom:6px">Customers who need care</div><ul style="padding-left:18px;margin:0">{unhappy}</ul>
  </div>
  <div style="font-size:12px;color:#8b96a8;text-align:center;margin-top:16px">Sent automatically by Email Automation</div>
</div></body></html>"""


def get_cache(key: str):
    with get_db_connection() as conn:
        row = conn.execute("SELECT value FROM report_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def set_cache(key: str, value):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO report_cache (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        conn.commit()
