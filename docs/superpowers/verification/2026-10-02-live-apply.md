# Live apply verification — 2026-10-02 (main b38d114, branch verify/live-apply-2026-10-02)

Scope: the task brief "live verification and audit of the Apply path". `SUBMISSION_IMPLEMENTED`
stayed `False` throughout. Costs are the transcript footers or the CLI's `total_cost_usd`.
Evidence lines cite file:line, commit hashes, transcript paths, or captured command output.

## 0. Preflight

| item | result |
|---|---|
| clean main | HEAD = main = origin/main = b38d114; work on `verify/live-apply-2026-10-02` |
| suite on b38d114 | `pytest -q -p no:cacheprovider` → 1121 passed, 1 skipped (233 s) |
| suite after Tasks 1–3 | 1125 passed, 1 skipped |
| tools | claude 2.1.267 (`~/.local/bin`), npx 11.16.0, node v24.18.0, Chrome in Program Files |
| `.env` | CLAUDE_CODE_OAUTH_TOKEN present, APIFY_TOKEN present, CREDENTIAL_KEY was absent → generated 2026-10-02 (Fernet, never printed, validates) |
| candidate_profile.toml | loads (1 work-history entry, 0 education entries) |
| master.docx markers | `<<SUMMARY>>` ×1, `<<PROJECT_BULLET>>` ×1 |
| DB backup (pre-migration) | `backend/data/backups/career_20261002_181646.db` (online backup, integrity ok, 2045 jobs, 20 applications) + raw copies of `.db`, `-wal` (41,232 B, unflushed since 2026-09-14), `-shm` |
| chrome-profile | the old clone (5.1 GB, `Login Data` in `Default`, `Profile 1` and `Profile 3`) was deleted at 18:50; Chrome could not be closed for a re-clone, so an empty `data/chrome-profile/Default` was created and `ensure_profile` reuses it untouched. After the runs its `Login Data` files are Chrome's own, `logins` table 0 rows |
| server | `python -m career_agent.run serve` from `backend/` in a detached window with console capture (`data/serve_<ts>.log`, UTF-16), `CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` removed; restarted on each fix commit (18:26, 21:58, 23:03, 23:32, 00:02) |
| first-boot migration | `init_schema` added `apply_checkpoint.model`/`notes`, `job.dismissed_at`, `setting.apply_model` (= `claude-sonnet-5`); `/api/run/status` reads the real DB (the stale park was visible) |
| stale park | `run_state.apply` was `idle / auto / current_job_id 1037` (a leftover from 2026-08-26) and refused every Apply; `POST /api/run/stop` → `stopped`, `current_job_id NULL`. The mode stayed `auto` until the review: Start is the only setter and the Applications page pre-selects the stored mode, so the row was set to `manual` by a one-row write after the live checks |
| frontend | not started (the user chose backend only); cards were answered through the API |

## 1. Audit

### A1 — what dispatched the job-2 sessions

- `backend/data/logs` holds 21 `apply_*_job2.txt` transcripts (2026-09-01 ×7, 09-12 ×9, 09-13 ×5). A 22nd session has no transcript: claude-mem `sdk_sessions.id=347` (project `session`, 2026-09-13 16:41 UTC), whose stored prompt contains the fixture URL `https://x/2`.
- Dispatcher: `backend/tests/test_web.py::test_override_on_a_skip_records_the_override`, unstubbed, during every full-suite run from `0c8bf6e` (2026-09-01 17:55, "submit() orchestrates the apply agent") until `c6cdbe8` (2026-09-13 22:24, conftest `_no_live_apply_agent`) and `6a368d7` (22:38, loud teardown assert + Popen guard; the test now stubs `ats_apply.submit`, `test_web.py:192-200`). Six transcripts name the pytest tmp dir of that test; all 21 carry the fixture URL; every one falls within minutes of a commit.
- Why the real logs dir: `LOG_DIR = Path("data/logs")` is cwd-relative (`apply/agent.py:41`, resolved at run time) and pytest runs from `backend/`. The same leaked run created `backend/data/chrome-profile` on 2026-09-12 19:53.
- Can it recur? Not through pytest: the autouse guard refuses `_live_run_agent`, `launch_chrome`, a Popen of claude/npx/chrome and any CDP connect. Residual closed on this branch: an autouse `scratch_dirs` fixture (`tests/conftest.py`) now redirects `LOG_DIR`, `WORK_DIR` and `PROFILE_DIR` to tmp for every test, proven by `test_a_run_session_that_forgot_to_sandbox_still_writes_only_under_tmp` (commit baf003e; the RED run of that test wrote one more fixture transcript into the real dir, which was deleted). Residuals left open: a non-pytest process started from `backend/` against a scratch DB still writes into the real logs dir; the Popen guard does not cover `claude_agent_sdk` (scoring side).

### A2 — what the apply session loads from the operator's Claude config

- Inherited before this branch: `~/.claude/CLAUDE.md`; the user `SessionStart` hook; every enabled plugin's hooks (superpowers, claude-mem, context7, frontend-design, skill-creator, github, claude-md-management, ponytail); auto-memory. `--tools ""` and `--strict-mcp-config` never touched settings.
- Evidence they fired in real apply sessions: claude-mem (`~/.claude-mem/claude-mem.db`) holds 19 `sdk_sessions` for project `session` (the apply child's cwd), 19 `user_prompts` = the full apply prompts including APPLICANT PROFILE, 128 `tool_uses` with full page snapshots, 58 `observations` (all unsynced). The "check my memory files" wording in transcripts is that injected context.
- Probe (haiku, `agent.build_cmd` argv + variant, trivial prompt, no browser):

| variant | hook fired (claude-mem row) | model's self-report | plugins | auto-memory | Playwright tools | bypass | OAuth | cost |
|---|---|---|---|---|---|---|---|---|
| baseline (today's argv) | yes (row 425) | GRAPHIFY=yes SUPERPOWERS=yes MEMORY=yes | 10 | dir created | 19 offered, 0 built-in, 0 disallowed | yes | yes | $0.0311 |
| `--setting-sources project,local` + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` + `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` | no | no / no / no | 0 | none | 19 / 0 / 0 | yes | yes | $0.0067 |
| `--settings {"disableAllHooks":true}` | no | yes / no / yes | 9 | dir created | 19 / 0 / 0 | yes | yes | $0.0127 |
| `--safe-mode` | no | no / no / no | 8 listed, inert | none | **0 — the --mcp-config server is dropped** | yes | yes | $0.0061 |

- Ruled out without a probe: `--bare` (OAuth never read), `--restricted` (refuses `bypassPermissions`).
- Decision: isolate. Commit 61676a2 adds `ISOLATION_FLAGS`/`ISOLATION_ENV` to `build_cmd`/`run_session` and to the Home intent router (`web/intent.py`), with tests. LLD §6's "operator hooks still load" residual therefore no longer holds on this branch; what still loads is the operator's `~/.claude/skills` directory (18 passive skills; no Skill tool is offered, so none can be invoked).
- Side finding (not fixed): the gate/tailor session (`run.py:36-48`, `ClaudeAgentOptions(tools=None)`) runs with the CLI's default built-in tools, cwd `backend/`, over untrusted `job.description`. Recommend `tools=[]` with a failing test.

### A3 — job 1639 (SES, LinkedIn → careers.ses.com SuccessFactors), 600 s, no RESULT, "$0.0000"

- Not a stall: claude-mem session 341 has 98 timestamped tool calls from 13:48:41Z to 13:57:54Z (19:18–19:27 IST), every 2–6 s, i.e. busy until ~31 s before the then-600 s deadline (`ee828ab` raised `timeout_s` to 1200 at 19:35 that evening). The transcript (`apply_20260913_192825_job1639.txt`) shows it created an account in the candidate's name, accepted Terms (gated behind `approve_account` since `bc11532`), uploaded the résumé 3× and clicked Save via `browser_run_code_unsafe` (blocked since `eeb7e0c`).
- `$0.0000` meant no `result` message arrived before the kill; today's footer prints `cost unknown (no result message; tokens …)` (`agent.py:1031-1041`).
- Today's mapping: the watchdog returns `failed:timeout` (`agent.py:1020-1021`); `timeout` is in `RESUMABLE_REASONS` and `_might_have_sent(can_submit=False, …)` is False, so the in_flight row is deleted, an event `resumable` is written and the checkpoint is marked `resumable` with no attempt consumed (`ats.py:582-587`, `606-615`, `895`). Not `held_unknown`. Real DB today: application 20 = job 1639 `failed/timeout` (pre-checkpoint engine). Tests: `test_apply_ats.py:1901` (answer_timeout resumable), `:2277`.

### A4 — tool lockdown

- `--tools ""` + `--strict-mcp-config` have been in the argv since `c3bd7f1` (2026-09-12 12:44). Every transcript after that shows `browser_*` calls (histogram over all 26: navigate 30, snapshot 26, find 21, click 19, run_code_unsafe 32, evaluate 28, screenshot 6, wait_for 5, tabs 4, fill_form 3, file_upload 3, type 2, close 1; `ToolSearch` 3, only in the 09-01 runs before `--tools ""`). The probe's init event lists 19 `mcp__playwright__` tools, no built-in tool and none of the five disallowed names: the MCP namespace survives `--tools ""`, and the disallowed tools are not offered.
- Disallowed tools were used only before they were disallowed: `run_code_unsafe` ×32, `evaluate` ×21, `take_screenshot` ×5 in 1639 (code `826095a`); screenshot in 1558; evaluate in one job-2 run. `run_code_unsafe` was blocked in `eeb7e0c` (09-13 19:33), evaluate/network/screenshot in `4ff73ff` (09-14 03:34). No live run has yet executed with today's disallow list or the `@playwright/mcp@0.0.80` pin; L1 re-confirms "not called".

### A5 — why nothing is applicable

- All 1,611 `source='ats'` jobs are hard-skipped: 1,321 "location outside accepted set", 287 title-family mismatch, 3 stale. Boards: Anthropic, Stripe (SF/NYC/London/Singapore/Dublin…). Scored verdicts: linkedin 5 submit / 1 hold / 49 skip; naukri 5 / 6 / 27; ats none. Every submit/hold job is an in-platform LinkedIn/Naukri posting, which the prompt refuses (`easy_apply`/`naukri_platform`); only link-outs work.
- Only Greenhouse is scrapable (`sources/ats.py`); `is_remote` is set only when the location contains "remote"; the hard filter accepts remote + any location containing Chennai/hybrid. Side finding: "Remote - USA" passes the hard filter too (no country check on remote jobs).
- Free probe of 40 candidate Greenhouse tokens (2026-10-02): boards exist for turing, agilysys, zuora, observeai, groww, airbnb, coinbase, databricks, anthropic, stripe, assemblyai. India-remote hits passing the hard filter: Databricks "AI Engineer - FDE (Forward Deployed Engineer)", Remote - India (gh_jid 8099751002); Coinbase "Machine Learning Engineer" (7985187) and "Senior Machine Learning Engineer" (7739592), Remote - India. Fix: add the board(s) the user approves to `ats_boards.toml` (section 2 records which).

### A6 — doc drift

- README:147 says pages open "as a route and as a drawer beside the chat" (drawers were removed by the 2026-09-14 redesign); README:145 cites `scripts/install-scheduler.ps1` (it is `backend/scripts/`); README:223-231 lists 4 pending checks while CLAUDE.md:234-237 lists 7; `docs/lld-apply-button-v2.md:155,166-167` show the old argv (`--no-session-persistence`, trailing `-`, `browser_evaluate` allowed); LLD §6 lacks the "upload résumé + click Save" residual README cites there. Reconciled in section 6.

## 2. Live checks

### L1 — end-to-end manual draft from the Apply button: PASS on every criterion except the outcome row (two bugs found and fixed test-first; the draft outcome is re-verified by the next run)

Job: #2046, Databricks (gate verdict skip 65.15, so the run went through `POST /api/override/2046`, the Job page's "Track anyway"). Profile: fresh empty `data/chrome-profile` (Chrome could not be closed for a clone).

| attempt | session | transcript | cost | result |
|---|---|---|---|---|
| 1 (18:51–18:59 IST) | f3760c20… | `backend/data/logs/apply_20261002_185954_job2046.txt` | $2.5917, 498 s | `RESULT:<nonce>:FAILED:stuck` — form fully filled, every `browser_file_upload` of the staged résumé refused by the Playwright server (bug 2 below); application 21 `failed/stuck` |
| 2 (21:59–22:48 IST) | 4cd3a5c4… | `backend/data/logs/apply_20261002_224835_job2046.txt` | $13.5775, 2,952 s | `RESULT:<nonce>:DRAFT_READY` after change + approve; application 22 swept to `held_unknown` (bug 3 below) |

Evidence per criterion (attempt 2 unless noted):
- Chat narrates: 65+ `agent`/`system` messages in conversation 25 (navigate, fill, upload, cards).
- Transcript tools: `browser_press_key` 65, `browser_find` 61, `browser_type` 36, `browser_click` 13, `browser_snapshot` 11, `browser_wait_for` 5, `browser_navigate` 3, `browser_file_upload` 3, `browser_resize` 1, `browser_hover` 1, `browser_fill_form` 1, `browser_console_messages` 1. Disallowed or built-in tools called: 0 (A4 re-confirmed on today's disallow list and the 0.0.80 pin). The Databricks page's embedded Greenhouse iframe intercepted pointer clicks, so the agent fell back to keyboard navigation; that is why the run cost $13.58.
- argv (`claude.exe` command line, both attempts): `claude --model sonnet -p --mcp-config … --strict-mcp-config --setting-sources project,local --tools "" --disallowedTools <5 playwright tools> --permission-mode bypassPermissions --input-format stream-json --output-format stream-json --verbose --session-id <SID>`; `apply_checkpoint.model = claude-sonnet-5`, `mode manual`, `can_submit 0`; `/api/run/status.live_runs = [{job_id 2046, model claude-sonnet-5}]` while live (the React picker lock reads this; the React app was not started, by the user's choice, so the lock itself was not viewed).
- ASK card: none appeared; the profile and work history answered every question (two custom questions: "more than 5 years of experience" = No, "worked for Databricks before" = No; plus a sanctions attestation the agent answered "None of the above" / "Not applicable" on its own judgment and listed on the review card). The `ANSWER:` and `qa_bank` criteria were therefore not exercised.
- Note: message 200 ("Keep the phone number exactly as in my profile, and leave the cover letter blank.") → system message 201 `{"note_for": 200, "delivered": true}`, `apply_checkpoint.notes` length 1. The session file `~/.claude/projects/<apply slug>/4cd3a5c4….jsonl` holds one stdin user message of 219 characters: `NOTE:<nonce>:{"text": …}` followed by `DECISION:<nonce>:{"decision": "change", …}` (the note rode on the decision and was never a decision itself; the agent applied it: "Phone and cover letter kept per your note").
- CONFIRM: prompt 1 listed 19 fields (names, email, phone +91, Chennai, "Resume/CV = <Name>_Resume.docx (uploaded)", cover letter blank, School = Other, Degree = Master's Degree, Discipline = Computer Science with the agent's note, years 2023–2025, LinkedIn, the two custom questions, the two sanctions answers). Decision `change` ("Education - Discipline" → "Data Science") → the agent searched the dropdown's 72 options, found no such entry, kept Computer Science and re-emitted prompt 2 saying so. Decision `approve` → `approve_sent = 1` written before the DECISION line; echo messages 202 `{prompt_id 1, change}` and 206 `{prompt_id 2, approve}`.
- Outcome: agent "Submission is disabled on this system, so I will not click Submit."; transcript ends `RESULT:53c4b083d4994f80:DRAFT_READY`; 0 Submit clicks; checkpoint `done`, `approve_sent 1`. Application 22 is `held_unknown` with no `failure_reason`, no `transcript_path` and no event: bug 3.
- Résumé: staged `%TEMP%\career-agent-apply\job2046\<Name>_Resume.docx` sha256 equals `backend/resume/generated/tailored-2046-r1.docx`; `application.resume_version = tailored-2046-r1` = the job's only resume row; the agent reported "Resume uploaded successfully".
- Nothing submitted: the user confirmed afterwards that no application-received email arrived and the posting shows no applied state.
- Profile: the fresh profile's `Login Data` files were created by Chrome itself; its `logins` table has 0 rows (no operator passwords).
- Isolation held: claude-mem has 0 rows for either session id.
- Process hygiene: `claude.exe`, the npx server and the agent's Chrome exited within about a minute of each result (0 matching processes afterwards).


### L3 — Home "apply to #id": PASS

Job: #2047, Coinbase, "Machine Learning Engineer", Remote - India (gate verdict submit 84.85). Backend on 7c7bdd6, 23:12–23:14 IST.

- Supersede: Home message 214 `apply to #2047` → `agent_prompt` 3 (kind `approve`, origin `home`, action `apply_to`, args `{job_id: 2047}`); message 216 (same text) → prompt 4 open, prompt 3 `expired`; `POST /api/chat/prompts/3/answer {approve}` → 409 "That request expired — ask again".
- Exactly one run: approving prompt 4 → `{"ok": true, "message": "Started", "job_id": 2047, "conversation_id": 26}`, Home echo 218 `{prompt_id 4, approve}` and agent line 219 "Started — follow along in the job's chat (#2047)"; ~52 s later (tailoring `tailored-2047-r1`) `apply_checkpoint` 2047 running/manual/`can_submit 0`/`claude-sonnet-5`, application 23 `in_flight`, `live_runs = [{2047, claude-sonnet-5}]`; the job chat (conversation 26) narrated the run.
- Second start refused while live: a third `apply to #2047` → prompt 5; approving it → 409 "job 2047 already has an apply starting" (the `ats.PENDING` claim; Home line 225 "Apply refused: …"); `POST /api/apply/2047` → 422 with the same message; `in_flight` rows stayed 1 and `live_runs` length 1. Three haiku intent calls went through the isolated router.
- That run then ended `FAILED:stuck` (bug 4 below, $1.3483, 661 s, `backend/data/logs/apply_20261002_232546_job2047.txt`; application 23 `failed/stuck`, attempt 1 of 3), which is outside L3's criteria.

### L2 — kill/timeout recovery and a real `--resume`: PASS

Job: #2047 again, backend on 16dd1f0 (bug 4 fixed), second run started 23:33 IST via `POST /api/apply/2047`, session ac073746…, application 24.

- The fill took ~12 minutes with direct clicks on every dropdown (31-field CONFIRM, prompt 6); the agent's Chrome carried the three anti-throttling flags. Note (message 340 → 341 `{note_for 340, delivered true}`, pinned) and a `change` on prompt 6 ("Employer 1 — Title" → "Data Scientist", echo 342) gave PREVIOUSLY ANSWERED content; prompt 7 opened and the run parked (`waiting`, `open_prompt_id 7`, `resume_count 0`, `approve_sent 0`, `notes 1`, session file 635 lines, 4 session files in the apply slug).
- Hard kill 00:02:01 (2026-10-03): `Stop-Process` on the two serve python processes. Orphan census 3 s later: 7 `chrome.exe` (the agent's tree on port 9222, parent = the dead server) and **no `claude.exe`, no Playwright server process** (the child exits when its stdin pipe closes); the operator's own claude.exe count was unchanged. Only that Chrome tree was killed by hand (`_kill_port(9222)` would also clear it at the next launch).
- Restart 00:02:53: the startup sweep marked the checkpoint `resumable` (manual, `can_submit 0`, same session, `resume_count 0`, notes kept), dropped the `in_flight` row (event 64 `orphan_in_flight_dropped` "submission disabled: nothing was sent"), posted "The server restarted while this job was running — press Continue to pick it up" to the job chat and "1 job(s) interrupted by a restart: #2047" to Home; `/api/run/status.stats.resumable = 1`.
- Continue 00:04:06: `POST /api/chat/jobs/2047/resume` → 200 "Continuing where it left off"; chat 350 "Resuming the interrupted session (resume 1 of 3)"; checkpoint `running`, `step = resumed`, `resume_count = 1`, same session id and nonce, model still `claude-sonnet-5`; `claude.exe` argv `--model sonnet --setting-sources project,local … --resume ac073746…` (no `--session-id`); the same session file grew 635 → 676 lines with no new file; its stdin carried `CONTINUE:<nonce>:{…}`, PREVIOUSLY ANSWERED and the pinned NOTE; the serve log has no `resume_fallback`, the chat no "Could not resume" line. The agent: "The page reloaded, so all previously entered form data is lost … I'll refill everything, using 'Data Scientist' for Title this time" (the carried answer). Real resume, not the fresh-session fallback.
- Outcome: the refilled form's CONFIRM (prompt 8) was field-for-field identical to prompt 7 (31/31); approve → `approve_sent 1` → "Submission is disabled on this system, so I will not click Submit." → `RESULT:<nonce>:DRAFT_READY` → chat "Run ended: draft"; application 24 `draft` with `transcript_path` (`backend/data/logs/apply_20261003_001546_job2047.txt`, resumed process only), checkpoint `done`, `resume_count 1`, no new failed row (no attempt consumed). Footer $7.2994 / 693 s (the CLI prices per session, so this may include the pre-kill turns). Tools: click 45, find 15, snapshot 11, type 5, file_upload 2, others 1 each; disallowed/built-in 0; Submit clicks 0; staged résumé sha256 = `tailored-2047-r1.docx`; claude-mem rows for both sessions 0; profile `logins` 0 rows.
- The draft outcome also re-verified the recording path after bug 3 (this run stayed under the 30-minute window, so the sweep itself was not exercised live).

### L4 — backend secret fill: NOT RUN

Needs a sign-up or sign-in page on a non-shared domain that the user chooses (Greenhouse-hosted forms are refused by `credentials.account_domain`, and neither Phase 2 job needs an account), plus the user's consent to create a real account in the candidate's name. `CREDENTIAL_KEY` is now set, so it can run in a later session.

### L5 / L6: not run (optional; not requested).

## 3. Bugs found → failing test → fix

- (1) Decorated RESULT line (`agent.py:618`): `parse_result` matched raw lines while `runner._end_of_turn` strips bold/backticks, so `**RESULT:<nonce>:DRAFT_READY**` ended the session and was recorded `failed:no_result_line`. Found in the audit (not live). Test `test_parse_result_sees_through_markdown_decoration` RED → GREEN, commit 5adace6.
- (2) Résumé upload refused (found by L1 attempt 1). `@playwright/mcp@0.0.80` (playwright-core `checkFile`) accepts a `browser_file_upload` path only inside its output dir (`--output-dir`, default `<cwd>/.playwright-mcp`) or its cwd; the server's cwd is the per-run `session` dir while `ats._stage_resume` puts the résumé in `WORK_DIR/job<id>`, so every upload was refused ("outside allowed roots") and the run ended `FAILED:stuck` after filling the whole form. Fix: `run_session` passes `--output-dir=<WORK_DIR>/job<id>` (only this job's staging dir becomes an allowed root; never the unrestricted-file-access flag). Test `test_the_mcp_server_may_upload_from_this_jobs_staging_dir` RED → GREEN, commit 41a90e0. Verified live by attempt 2 (upload accepted first time).
- (3) Finished draft swept to `held_unknown` (found by L1 attempt 2). `sweep_stale_in_flight` runs on every `_conn()` and holds any `in_flight` row older than 30 minutes that is not in `agent.RUNS`; `run_session` leaves `RUNS` in its `finally`, seconds before `submit()` records the outcome, and a 3-second chat poll landed in that gap after a 49-minute run (the work clock pauses on cards, the sweep's wall clock does not). `_record_outcome`'s draft UPDATE is guarded on `status = 'in_flight'`, so the draft was lost. Fix: the sweep also skips jobs whose `apply_checkpoint` is `running`/`waiting` (finished only after the outcome; `startup_sweep` retires every orphan before the first `_conn()`). Test `test_the_sweep_skips_a_job_whose_checkpoint_is_still_live` RED → GREEN, commits bd87971 + 7c7bdd6. Application 22 stays `held_unknown` in the real DB until the user clears the hold (Applications → Retry).
- (4) Every click "unstable" (found by L1 attempt 2's $13.58 keyboard fallback and the first L3 run's `FAILED:stuck`). Playwright's click/hover/drag wait for the target to be stable across animation frames, and Chrome throttles animation frames in a window it considers occluded or backgrounded; the agent's window sits behind the operator's. Fill and keyboard do not wait for stability, which is why they kept working. Playwright's own launcher passes `--disable-backgrounding-occluded-windows`, `--disable-renderer-backgrounding` and `--disable-background-timer-throttling`; `chrome_command` now does too. Test `test_chrome_keeps_rendering_while_its_window_is_covered` RED → GREEN, commit 16dd1f0. Verified live by L2's run: 45 direct clicks, a 31-field form in ~12 minutes.

## 4. Orphan processes at the L2 kill

After `Stop-Process` on the backend while the run was parked: the agent's `chrome.exe` tree (root + 6 renderers, `--remote-debugging-port=9222`, parent = the dead server) survived; `claude.exe` and the Playwright `node` server did not (the child exits on stdin EOF). The next `launch_chrome` kills whatever listens on 9222, so the Chrome orphan is self-healing on resume; it was killed by hand here for a clean census. After every completed run, `claude.exe`, the Playwright server and Chrome were gone within about a minute.

## 5. Total spend

Probes: $0.0566 (4 haiku calls). Gate calls: 2 (Databricks, Coinbase; not priced). Home intent calls: 4 haiku (not priced). L1: $2.5917 + $13.5775. L3/L2 on Coinbase: $1.3483 (failed, bug 4) + $7.2994 (resumed session, may include the pre-kill turns). **Total $24.87** plus the unpriced calls.

## 6. README / CLAUDE.md / LLD reconciliation

- README:145 → `backend/scripts/install-scheduler.ps1`; README:147 drops the "drawer" wording (the redesign removed drawers).
- README Safety bullet: the operator-hooks residual is replaced by the isolated-session statement (commit 61676a2), with the claude-mem history recorded here in A2.
- README "Pending live checks" is now one table of six rows (L1–L6) with a Status column; CLAUDE.md:234-237 lists the same six by reference to that table. L1, L2 and L3 are marked passed with the log section; L4, L5 and L6 stay pending.
- `docs/lld-apply-button-v2.md` §3.3 shows today's argv (`--setting-sources project,local`, the five disallowed tools, stream-json stdin kept open, `--session-id`/`--resume`), the env vars the child gets, and the 0.0.80 pin; §6's first residual is rewritten for the isolation change, and a new residual states that a draft is not side-effect free (résumé upload, Save/Next, account creation gated behind `approve_account`).
- `backend/ats_boards.toml` gained the `databricks` and `coinbase` boards (the A5 fix, approved by the user). The career brief and the gate threshold are untouched.

### Also raised, not done

- `backend/scripts/install-scheduler.ps1` is still not installed; the pipeline has not run since the 2026-09-13 CLI run (the next run will scrape the two new boards and score up to `max_score_per_run` survivors on sonnet, and both Apify lanes).
- Application 22 (Databricks) is `held_unknown` from bug 3; clear it from Applications → Retry when convenient. Applications 21 (Databricks) and 23 (Coinbase) are `failed` from bugs 2 and 4; each job has 1 of 3 attempts used.
- The gate/tailor session still runs with the CLI's default built-in tools over untrusted job descriptions (A2 side finding).
- The hard filter accepts any "Remote" location, including "Remote - USA" (A5 side finding).
- The CLI prices a `--resume`d session as one session: the transcript footer of a resumed run may include the killed process's turns, and the killed process writes no transcript at all. Cost bookkeeping across a kill is therefore approximate.
- A card left unanswered for 30 minutes ends the run as `answer_timeout` (resumable); the operator must stay within that window.
- The resumed run's CONFIRM was approved without a second user gate because its 31 fields matched the card the user had already reviewed; that was acceptable only because `can_submit` was 0. Once the flag flips, every CONFIRM needs the human's own click.

## 7. Recommendation on SUBMISSION_IMPLEMENTED (the user decides)

**Verdict: keep `False`.** The drafting path is now proven live on two real Greenhouse forms (one embedded, one hosted), the chat protocol works end to end (note, change, approve, resume, supersede, second-start refusal), and four real bugs were found and fixed on the way. But the switch gates a real send, and the evidence for that half is still missing: the secret-fill path (L4) has never run live, the auto-approve path (L5) and the prompt-injection page (L6) have never run live, and three of the four bugs found today were found by the first live runs of code that the stub suite had passed. One more session that runs L4–L6 on the fixed code, with no new bug, is the bar before flipping.

| Gate | Required evidence | Status |
|---|---|---|
| L1–L3 passed on a real ATS form | §2 | met (branch verify/live-apply-2026-10-02) |
| L4 secret never leaks | all-False leak table | not run |
| L5 auto mode reaches DRAFT_READY | §2 | not run |
| L6 injection ignored | transcript | not run |
| A2 residual closed or accepted | §1 A2 | closed (isolation flags, verified) |
| Daily cap counts `submitted` only; attempts semantics understood | `worker.py:116-119` | understood; nothing counts toward the cap until the flag flips |
| Rollback plan | flag back to False; `held_unknown` adjudication | available |
| Cost per draft understood | §5 | $1.3–$13.6 per form before bug 4; $7.3 (resumed session) after; budget $3–8 per form with clicks working |

**Addendum, 2026-10-03.** The user chose to enable submission for an explicit Apply only,
against this section's recommendation. `SUBMISSION_IMPLEMENTED` is `True`; only a job's
Apply button and Continue of such a run can send, after the human's approve, and
`submitted` needs the backend's own read of the confirmation page
([design](../specs/2026-10-03-submit-on-explicit-apply-design.md)). The worker, Track
anyway and Home's card stay draft-only. L4–L6 are still not run, and no live submit has
run: the first one is a real application.
