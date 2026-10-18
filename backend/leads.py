"""
leads.py — Sales leads captured from emails
============================================
Sales emails create or update a lead for the sender. The details (services,
websites, mailboxes, storage, budget, timeline) are extracted by the existing
classification call — no extra AI calls.

handled_by decides who answers the customer's next emails:
  "ai"    — the AI replies on its own in sales mode (quotes from the knowledge base)
  "human" — every email goes to the Review queue for the sales team

Stages move automatically:
  new → needs_info → qualified    from the details the customer gives
  → quoted                        when a sent reply contains a price
  → won / lost                    when the customer accepts / declines the offer
Won leads count as revenue (their value).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from logger import get_db_connection

STAGES = ["new", "needs_info", "qualified", "quoted", "won", "lost"]
OPEN_STAGES = ["new", "needs_info", "qualified", "quoted"]
DETAIL_FIELDS = ["services", "websites", "mailboxes", "storage", "budget", "timeline"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_leads():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_email TEXT NOT NULL,
                name TEXT,
                company TEXT,
                subject TEXT,
                summary TEXT,
                stage TEXT NOT NULL DEFAULT 'new',
                handled_by TEXT NOT NULL DEFAULT 'ai',
                owner TEXT,
                services TEXT,
                websites TEXT,
                mailboxes TEXT,
                storage TEXT,
                budget TEXT,
                timeline TEXT,
                value REAL,
                first_log_id INTEGER,
                last_log_id INTEGER,
                email_count INTEGER NOT NULL DEFAULT 1,
                first_response_sec INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
        """)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)")}
        for col, ddl in (("value_source", "TEXT"), ("quoted_at", "TEXT"), ("closed_by", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {ddl};")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_customer ON leads(customer_email);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);")
        conn.commit()


def _row(row) -> Optional[dict]:
    return dict(row) if row else None


def get_lead(lead_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        return _row(conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone())


def open_lead_for(email: str) -> Optional[dict]:
    with get_db_connection() as conn:
        return _row(conn.execute(
            f"SELECT * FROM leads WHERE customer_email = ? AND stage IN ({','.join('?' * len(OPEN_STAGES))}) "
            "ORDER BY id DESC LIMIT 1",
            (email.lower(), *OPEN_STAGES),
        ).fetchone())


def _auto_stage(lead: dict) -> str:
    """Stage from how complete the details are. Never moves a lead backwards past 'qualified'."""
    if lead.get("stage") in ("quoted", "won", "lost"):
        return lead["stage"]
    has_need = bool(lead.get("services") or lead.get("websites") or lead.get("mailboxes"))
    has_when = bool(lead.get("timeline") or lead.get("budget"))
    if has_need and has_when:
        return "qualified"
    if has_need or has_when:
        return "needs_info"
    return "new"


def upsert_from_email(
    *, email: str, name: str, company: str, subject: str, summary: str,
    details: dict, log_id: int, handled_by: str,
) -> dict:
    """Create a lead for the sender, or merge new details into their open lead."""
    email = email.lower()
    clean = {k: str(details.get(k) or "").strip()[:200] for k in DETAIL_FIELDS}
    clean = {k: v for k, v in clean.items() if v and v.lower() not in ("null", "none", "unknown", "n/a")}
    now_iso = _now().isoformat()
    lead = open_lead_for(email)

    if lead:
        merged = {**lead, **clean}
        stage = _auto_stage(merged)
        # a person working the lead keeps it "human" until they hand it back
        handler = "human" if lead["handled_by"] == "human" else handled_by
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE leads SET {', '.join(f'{k} = ?' for k in clean)}{', ' if clean else ''}"
                "name = COALESCE(NULLIF(?, ''), name), company = COALESCE(NULLIF(?, ''), company), "
                "summary = ?, stage = ?, handled_by = ?, last_log_id = ?, email_count = email_count + 1, "
                "updated_at = ? WHERE id = ?",
                (*clean.values(), name, company, summary, stage, handler, log_id, now_iso, lead["id"]),
            )
            conn.commit()
        return get_lead(lead["id"])

    stage = _auto_stage(clean)
    with get_db_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO leads (customer_email, name, company, subject, summary, stage, handled_by, "
            f"{', '.join(DETAIL_FIELDS)}, first_log_id, last_log_id, created_at, updated_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, {', '.join('?' * len(DETAIL_FIELDS))}, ?, ?, ?, ?)",
            (email, name, company, subject, summary, stage, handled_by,
             *(clean.get(k) for k in DETAIL_FIELDS), log_id, log_id, now_iso, now_iso),
        )
        conn.commit()
        return get_lead(cur.lastrowid)


def set_first_response(lead_id: int, seconds: int):
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE leads SET first_response_sec = ? WHERE id = ? AND first_response_sec IS NULL",
            (max(0, int(seconds)), lead_id),
        )
        conn.commit()


def set_handler_for_log(log_id: int, handled_by: str, response_sec: Optional[int] = None):
    """Called when a held reply is approved/rejected (human) or auto-sent after timeout (ai)."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM leads WHERE last_log_id = ? OR first_log_id = ?", (log_id, log_id)).fetchone()
    if not row:
        return
    with get_db_connection() as conn:
        conn.execute("UPDATE leads SET handled_by = ?, updated_at = ? WHERE id = ?",
                     (handled_by, _now().isoformat(), row[0]))
        conn.commit()
    if response_sec is not None:
        set_first_response(row[0], response_sec)


def update_lead(lead_id: int, changes: dict) -> Optional[dict]:
    lead = get_lead(lead_id)
    if not lead:
        return None
    allowed = {"stage", "handled_by", "owner", "value", "name", "company", *DETAIL_FIELDS}
    clean = {k: v for k, v in changes.items() if k in allowed and v is not None}
    if "stage" in clean and clean["stage"] not in STAGES:
        raise ValueError(f"Stage must be one of: {', '.join(STAGES)}.")
    if "handled_by" in clean and clean["handled_by"] not in ("ai", "human"):
        raise ValueError("handled_by must be 'ai' or 'human'.")
    if "value" in clean:
        try:
            clean["value"] = max(0.0, float(clean["value"]))
        except (TypeError, ValueError):
            raise ValueError("Value must be a number.")
        if clean["value"] != (lead["value"] or 0):
            clean["value_source"] = "manual"
    if clean.get("owner"):
        clean["owner"] = str(clean["owner"]).strip()[:80]
        clean.setdefault("handled_by", "human")  # someone took ownership

    now_iso = _now().isoformat()
    if clean.get("stage") in ("won", "lost") and lead["stage"] not in ("won", "lost"):
        clean["closed_at"] = now_iso
        clean["closed_by"] = "team"
    elif clean.get("stage") in OPEN_STAGES:
        clean["closed_at"] = None
    clean["updated_at"] = now_iso

    with get_db_connection() as conn:
        conn.execute(f"UPDATE leads SET {', '.join(f'{k} = ?' for k in clean)} WHERE id = ?",
                     (*clean.values(), lead_id))
        conn.commit()
    return get_lead(lead_id)


def lead_block(lead: Optional[dict]) -> str:
    """What the AI should know about an open lead (short — keeps prompts small)."""
    if not lead:
        return ""
    details = ", ".join(f"{k}: {lead[k]}" for k in DETAIL_FIELDS if lead.get(k))
    lines = [f"Lead stage: {lead['stage']}", f"What they need: {details or 'not stated yet'}"]
    if lead.get("value") and lead["stage"] == "quoted":
        lines.append(f"We already offered them: {lead['value']:g} EUR — refer to that offer, don't change the price.")
    return "\n".join(lines)


def record_quote(lead_id: int, price: Optional[float]):
    """A reply containing a price was sent → stage 'quoted' and the deal value (unless typed by a person)."""
    lead = get_lead(lead_id)
    if not lead or lead["stage"] in ("won", "lost") or not price or price <= 0:
        return
    now_iso = _now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE leads SET stage = CASE WHEN stage IN ('new','needs_info','qualified') THEN 'quoted' ELSE stage END, "
            "value = CASE WHEN COALESCE(value_source, '') = 'manual' THEN value ELSE ? END, "
            "value_source = CASE WHEN COALESCE(value_source, '') = 'manual' THEN value_source ELSE 'quote' END, "
            "quoted_at = ?, updated_at = ? WHERE id = ?",
            (price, now_iso, now_iso, lead_id),
        )
        conn.commit()


def apply_deal_signal(lead_id: int, signal: str) -> Optional[str]:
    """
    Customer accepted → won (counts as revenue); declined → lost.
    Only an offer that was actually made can be accepted (stage qualified/quoted).
    Returns the new stage, or None if nothing changed.
    """
    lead = get_lead(lead_id)
    if not lead or lead["stage"] in ("won", "lost"):
        return None
    if signal == "accept" and lead["stage"] in ("qualified", "quoted"):
        new_stage = "won"
    elif signal == "reject":
        new_stage = "lost"
    else:
        return None
    now_iso = _now().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE leads SET stage = ?, closed_at = ?, closed_by = 'customer', updated_at = ? WHERE id = ?",
            (new_stage, now_iso, now_iso, lead_id),
        )
        conn.commit()
    return new_stage


def list_leads(stage: Optional[str] = None, handled_by: Optional[str] = None, limit: int = 500) -> list[dict]:
    sql, args = "SELECT * FROM leads WHERE 1=1", []
    if stage:
        sql += " AND stage = ?"
        args.append(stage)
    if handled_by:
        sql += " AND handled_by = ?"
        args.append(handled_by)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    with get_db_connection() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def metrics(days: int = 30) -> dict:
    """Everything the sales dashboard needs in one call."""
    now = _now()
    since = (now - timedelta(days=days)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    stale = (now - timedelta(days=3)).isoformat()

    with get_db_connection() as conn:
        all_leads = [dict(r) for r in conn.execute("SELECT * FROM leads").fetchall()]

    open_leads = [l for l in all_leads if l["stage"] in OPEN_STAGES]
    won = [l for l in all_leads if l["stage"] == "won"]
    lost = [l for l in all_leads if l["stage"] == "lost"]

    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values)) if values else None

    by_handler = {}
    for h in ("ai", "human"):
        group = [l for l in all_leads if l["handled_by"] == h]
        closed = [l for l in group if l["stage"] in ("won", "lost")]
        by_handler[h] = {
            "total": len(group),
            "open": sum(1 for l in group if l["stage"] in OPEN_STAGES),
            "won": sum(1 for l in group if l["stage"] == "won"),
            "win_rate": round(100 * sum(1 for l in closed if l["stage"] == "won") / len(closed)) if closed else None,
            "avg_response_sec": avg(l["first_response_sec"] for l in group),
            "revenue": round(sum(l["value"] or 0 for l in group if l["stage"] == "won"), 2),
        }

    by_stage = {s: {"ai": 0, "human": 0} for s in STAGES}
    for l in all_leads:
        by_stage[l["stage"]][l["handled_by"]] += 1

    # new leads per day, split by handler (oldest day first)
    daily = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date().isoformat()
        day_leads = [l for l in all_leads if l["created_at"][:10] == day]
        day_won = [l for l in won if (l["closed_at"] or "")[:10] == day]
        daily.append({
            "date": day,
            "ai": sum(1 for l in day_leads if l["handled_by"] == "ai"),
            "human": sum(1 for l in day_leads if l["handled_by"] == "human"),
            "revenue_ai": round(sum(l["value"] or 0 for l in day_won if l["handled_by"] == "ai"), 2),
            "revenue_human": round(sum(l["value"] or 0 for l in day_won if l["handled_by"] == "human"), 2),
        })

    attention = []
    for l in open_leads:
        if l["stage"] == "needs_info" and l["updated_at"] < stale:
            attention.append({**l, "reason": "Waiting for details for 3+ days"})
        elif l["stage"] == "qualified" and not l["owner"]:
            attention.append({**l, "reason": "Ready for a quote — no owner yet"})
        elif l["stage"] == "quoted" and l["updated_at"] < stale:
            attention.append({**l, "reason": "Quote sent 3+ days ago — follow up"})
    for l in won:
        if not l["value"]:
            attention.append({**l, "reason": "Won — set the deal value so it counts as revenue"})

    closed_total = len(won) + len(lost)
    return {
        "open": len(open_leads),
        "new_this_week": sum(1 for l in all_leads if l["created_at"] >= week_ago),
        "new_in_period": sum(1 for l in all_leads if l["created_at"] >= since),
        "won": len(won),
        "lost": len(lost),
        "win_rate": round(100 * len(won) / closed_total) if closed_total else None,
        "pipeline_value": round(sum(l["value"] or 0 for l in open_leads), 2),
        "won_value": round(sum(l["value"] or 0 for l in won), 2),
        "revenue_period": round(sum(l["value"] or 0 for l in won if (l["closed_at"] or "") >= since), 2),
        "revenue_week": round(sum(l["value"] or 0 for l in won if (l["closed_at"] or "") >= week_ago), 2),
        "avg_response_sec": avg(l["first_response_sec"] for l in all_leads),
        "by_handler": by_handler,
        "by_stage": by_stage,
        "daily": daily,
        "attention": attention[:10],
        "stages": STAGES,
    }
