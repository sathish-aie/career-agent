"""Wipe the application history -- applications, apply sessions, cards, chats
and per-job events -- back to empty. Jobs, scores, facts, remembered answers,
resumes, settings and saved logins are kept. Run from backend/:

    python -m career_agent.reset          # dry run: prints what would go
    python -m career_agent.reset --yes    # backs up, then resets

Stop the server first: every request re-creates rows (the Home conversation,
backfilled job chats) and holds the write lock."""
import argparse
import socket
import sqlite3
from datetime import datetime
from pathlib import Path

from career_agent import db

# Children first: no foreign key here has ON DELETE, and db.connect enforces them.
WIPE = (
    ("outcome", ""),
    ("application", ""),
    ("apply_checkpoint", ""),
    ("agent_prompt", ""),
    ("message", ""),
    ("conversation", " WHERE kind = 'job'"),
    # Per-job history goes with the chats: chat.jobs_needing_backfill rebuilds
    # a job's chat from any event or application row left behind.
    ("event", " WHERE job_id IS NOT NULL OR type LIKE 'run!_%' ESCAPE '!'"),
)
KEPT = ("job", "assessment", "fact", "qa_bank", "resume", "setting", "site_credential")


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rows the reset would delete, per table."""
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}{where}").fetchone()[0]
            for table, where in WIPE}


def may_have_sent(conn: sqlite3.Connection) -> int:
    """Applications that are, or may be, real sends. Wiping one drops the
    one-live-application guard that stops a second send to that employer."""
    return conn.execute("SELECT COUNT(*) FROM application"
                        " WHERE status IN ('submitted','held_unknown')").fetchone()[0]


def reset(conn: sqlite3.Connection) -> dict[str, int]:
    """One transaction. Returns the rows deleted per table."""
    deleted = {}
    with conn:
        for table, where in WIPE:
            deleted[table] = conn.execute(f"DELETE FROM {table}{where}").rowcount
        conn.execute("UPDATE job SET priority = NULL, dismissed_at = NULL")
        conn.execute("UPDATE run_state SET status = 'stopped', current_job_id = NULL,"
                     " last_error = NULL, updated_at = datetime('now') WHERE kind = 'apply'")
    return deleted


def _server_up(port: int = 8000) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m career_agent.reset")
    parser.add_argument("--db", default="data/career.db")
    parser.add_argument("--yes", action="store_true",
                        help="back up, then reset (without it: a dry run)")
    parser.add_argument("--force", action="store_true",
                        help="reset even with submitted or held applications on record")
    args = parser.parse_args(argv)

    path = Path(args.db)
    if not path.exists():   # db.connect would create an empty one, e.g. from the repo root
        raise SystemExit(f"{path} not found -- run this from backend/")
    conn = db.connect(path)

    print("Would delete:")
    for table, n in counts(conn).items():
        print(f"  {table:18}{n}")
    print("Keeps:")
    for table in KEPT:
        print(f"  {table:18}{conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
    if not args.yes:
        print("Dry run: nothing changed. Re-run with --yes to back up and reset.")
        return

    if _server_up():
        raise SystemExit("Port 8000 is in use -- stop the server first.")
    sent = may_have_sent(conn)
    if sent and not args.force:
        raise SystemExit(f"{sent} application(s) are submitted or held: resetting would let"
                         " the agent apply to those employers again. Pass --force to do it anyway.")

    backup = path.parent / "backups" / f"career_{datetime.now():%Y%m%d_%H%M%S}_pre-reset.db"
    backup.parent.mkdir(exist_ok=True)
    dst = sqlite3.connect(backup)
    conn.backup(dst)
    dst.close()
    print(f"Backed up to {backup}")

    reset(conn)
    print("Reset done.")


if __name__ == "__main__":
    main()
