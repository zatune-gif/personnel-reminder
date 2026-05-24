import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "personnel.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                manager_slack_user_id TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slack_user_id TEXT UNIQUE NOT NULL,
                role TEXT DEFAULT '',
                group_id INTEGER REFERENCES groups(id),
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS personality_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                q1_consult INTEGER,
                q2_pressure INTEGER,
                q3_recognition INTEGER,
                q4_adaptability INTEGER,
                q5_stress_relief TEXT,
                profile_labels TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS status_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                survey_date TEXT NOT NULL,
                q1_workload INTEGER,
                q2_motivation INTEGER,
                q3_issues TEXT,
                q4_communication INTEGER,
                analysis TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS survey_dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                survey_type TEXT NOT NULL,
                dispatched_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                triggered_at TEXT DEFAULT (datetime('now')),
                reason TEXT,
                message TEXT,
                acknowledged INTEGER DEFAULT 0
            );
        """)


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def add_group(name: str, manager_slack_user_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO groups (name, manager_slack_user_id) VALUES (?, ?)",
            (name, manager_slack_user_id),
        )
        return cur.lastrowid


def get_all_groups() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM groups").fetchall()]


def get_group_by_manager(manager_slack_user_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM groups WHERE manager_slack_user_id = ?",
            (manager_slack_user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_group_for_member(member_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT g.* FROM groups g JOIN members m ON m.group_id = g.id WHERE m.id = ?",
            (member_id,),
        ).fetchone()
        return dict(row) if row else None


def transfer_member_group(slack_user_id: str, new_group_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE members SET group_id = ? WHERE slack_user_id = ?",
            (new_group_id, slack_user_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def add_member(name: str, slack_user_id: str, group_id: int, role: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO members (name, slack_user_id, role, group_id) VALUES (?, ?, ?, ?)",
            (name, slack_user_id, role, group_id),
        )
        return cur.lastrowid


def get_all_members() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM members").fetchall()]


def get_members_by_group(group_id: int) -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM members WHERE group_id = ?", (group_id,)
        ).fetchall()]


def get_member_by_slack_id(slack_user_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM members WHERE slack_user_id = ?", (slack_user_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Personality profiles
# ---------------------------------------------------------------------------

def save_personality_profile(member_id: int, responses: dict, profile_labels: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO personality_profiles
            (member_id, q1_consult, q2_pressure, q3_recognition, q4_adaptability, q5_stress_relief, profile_labels)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                member_id,
                responses.get("q1"),
                responses.get("q2"),
                responses.get("q3"),
                responses.get("q4"),
                responses.get("q5"),
                json.dumps(profile_labels, ensure_ascii=False),
            ),
        )


def get_personality_profile(member_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM personality_profiles WHERE member_id = ? ORDER BY created_at DESC LIMIT 1",
            (member_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("profile_labels"):
            d["profile_labels"] = json.loads(d["profile_labels"])
        return d


# ---------------------------------------------------------------------------
# Status checks
# ---------------------------------------------------------------------------

def save_status_check(member_id: int, survey_date: str, responses: dict, analysis: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO status_checks
            (member_id, survey_date, q1_workload, q2_motivation, q3_issues, q4_communication, analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                member_id,
                survey_date,
                responses.get("q1"),
                responses.get("q2"),
                responses.get("q3"),
                responses.get("q4"),
                json.dumps(analysis, ensure_ascii=False),
            ),
        )


def get_recent_status_checks(member_id: int, limit: int = 4) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM status_checks WHERE member_id = ? ORDER BY survey_date DESC LIMIT ?",
            (member_id, limit),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("analysis"):
                d["analysis"] = json.loads(d["analysis"])
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Survey dispatches
# ---------------------------------------------------------------------------

def record_survey_dispatch(member_id: int, survey_type: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO survey_dispatches (member_id, survey_type) VALUES (?, ?)",
            (member_id, survey_type),
        )


def get_consecutive_no_responses(member_id: int, survey_type: str = "status") -> int:
    """直近2回の送信に対して回答がなかった回数を返す（最大2）。
    送信から3日以上経過したものだけを対象にする。"""
    with get_conn() as conn:
        dispatches = conn.execute(
            """
            SELECT id, dispatched_at FROM survey_dispatches
            WHERE member_id = ? AND survey_type = ?
              AND dispatched_at < datetime('now', '-3 days')
            ORDER BY dispatched_at DESC
            LIMIT 2
            """,
            (member_id, survey_type),
        ).fetchall()

        consecutive = 0
        for dispatch in dispatches:
            responded = conn.execute(
                """
                SELECT id FROM status_checks
                WHERE member_id = ? AND created_at >= ?
                LIMIT 1
                """,
                (member_id, dispatch["dispatched_at"]),
            ).fetchone()
            if responded is None:
                consecutive += 1
            else:
                break
        return consecutive


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def save_reminder(member_id: int, reason: str, message: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (member_id, reason, message) VALUES (?, ?, ?)",
            (member_id, reason, message),
        )
