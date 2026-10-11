import sqlite3

import pytest

from career_agent import db, reset

KEPT = ("job", "assessment", "fact", "qa_bank", "resume", "setting", "site_credential")

SEED = """
INSERT INTO job (id, fingerprint, source, external_id, company, company_normalized,
                 title, title_normalized, priority, dismissed_at)
     VALUES (1, 'f1', 'ats', '1', 'Acme', 'acme', 'AI Engineer', 'aiengineer', -1,
             datetime('now'));
INSERT INTO assessment (job_id, stage, verdict, rationale, model, prompt_version)
     VALUES (1, 'scored', 'submit', 'ok', 'm', 'gate-v1');
INSERT INTO application (id, job_id, resume_version, status) VALUES (1, 1, 'base-v1', 'draft');
INSERT INTO outcome (application_id, type) VALUES (1, 'no_response');
INSERT INTO apply_checkpoint (job_id, session_id, nonce, status) VALUES (1, 's', 'n', 'resumable');
INSERT INTO event (job_id, type) VALUES (1, 'human_applied'), (NULL, 'run_started'),
                                        (NULL, 'pipeline_started');
INSERT INTO conversation (id, kind, job_id, title) VALUES (1, 'home', NULL, 'Home'),
                                                          (2, 'job', 1, 'Acme');
INSERT INTO message (conversation_id, role, content) VALUES (1, 'user', 'hi'), (2, 'agent', 'yo');
INSERT INTO agent_prompt (job_id, conversation_id, kind, payload)
     VALUES (NULL, 1, 'approve', '{}'), (1, 2, 'text', '{}');
INSERT INTO fact (claim, evidence) VALUES ('built it', 'repo');
INSERT INTO qa_bank (question_normalized, answer) VALUES ('notice period', '30 days');
INSERT INTO resume (version, path, job_id) VALUES ('tailored-1-r1', 'r.docx', 1);
INSERT INTO site_credential (domain, email, password_enc, created_by)
     VALUES ('acme.com', 'a@b.c', 'x', 'user');
UPDATE run_state SET status = 'paused', current_job_id = 1, last_error = 'boom'
 WHERE kind = 'apply';
"""


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "data" / "career.db"
    c = db.connect(p)
    db.init_schema(c)
    c.executescript(SEED)
    c.close()
    return p


def _n(conn, table, where=""):
    return conn.execute(f"SELECT COUNT(*) FROM {table}{where}").fetchone()[0]


def test_reset_wipes_application_history_and_keeps_everything_else(path):
    conn = db.connect(path)

    deleted = reset.reset(conn)

    assert deleted == {"outcome": 1, "application": 1, "apply_checkpoint": 1,
                       "agent_prompt": 2, "message": 2, "conversation": 1, "event": 2}
    assert all(n == 0 for n in reset.counts(conn).values())
    assert [r["kind"] for r in conn.execute("SELECT kind FROM conversation")] == ["home"]
    assert [r["type"] for r in conn.execute("SELECT type FROM event")] == ["pipeline_started"]
    assert {t: _n(conn, t) for t in KEPT} == dict.fromkeys(KEPT, 1)
    job = conn.execute("SELECT priority, dismissed_at FROM job").fetchone()
    assert tuple(job) == (None, None)
    run = conn.execute("SELECT status, current_job_id, last_error FROM run_state"
                       " WHERE kind = 'apply'").fetchone()
    assert tuple(run) == ("stopped", None, None)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_main_is_a_dry_run_without_yes(path, monkeypatch, capsys):
    monkeypatch.setattr(reset, "_server_up", lambda: False)

    reset.main(["--db", str(path)])

    assert "Dry run" in capsys.readouterr().out
    assert _n(db.connect(path), "application") == 1
    assert not (path.parent / "backups").exists()


def test_main_backs_up_before_it_resets(path, monkeypatch):
    monkeypatch.setattr(reset, "_server_up", lambda: False)

    reset.main(["--db", str(path), "--yes"])

    assert _n(db.connect(path), "application") == 0
    (backup,) = (path.parent / "backups").glob("career_*_pre-reset.db")
    assert _n(sqlite3.connect(backup), "application") == 1


def test_main_refuses_while_the_server_is_running(path, monkeypatch):
    monkeypatch.setattr(reset, "_server_up", lambda: True)

    with pytest.raises(SystemExit, match="stop the server"):
        reset.main(["--db", str(path), "--yes"])
    assert _n(db.connect(path), "application") == 1


def test_main_refuses_to_drop_a_possible_real_send_without_force(path, monkeypatch):
    monkeypatch.setattr(reset, "_server_up", lambda: False)
    conn = db.connect(path)
    conn.execute("UPDATE application SET status = 'held_unknown'")
    conn.commit()

    with pytest.raises(SystemExit, match="--force"):
        reset.main(["--db", str(path), "--yes"])
    assert _n(conn, "application") == 1

    reset.main(["--db", str(path), "--yes", "--force"])
    assert _n(conn, "application") == 0


def test_main_refuses_a_missing_database(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        reset.main(["--db", str(tmp_path / "nope.db")])
    assert not (tmp_path / "nope.db").exists()
