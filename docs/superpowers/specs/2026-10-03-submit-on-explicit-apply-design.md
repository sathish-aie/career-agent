# Submit on an explicit Apply — design (2026-10-03)

## Why

Until now `SUBMISSION_IMPLEMENTED = False` made every apply run stop at a draft. The
user asked (2026-10-03) to turn real submission on, but only for jobs they explicitly
start with the job's **Apply** button, keeping every existing check, verifying the
employer's confirmation state before recording `submitted`, and recording
`submitted_at` and the event accurately.

A plain flip was unsafe:

- `can_submit = SUBMISSION_IMPLEMENTED or run_agent is not None` was global, so the
  queue worker in Auto mode would have submitted with nobody watching, and the Home
  "apply to #id" card, "Track anyway", Continue and "Redo draft" would all have sent.
- `submitted` was recorded purely from the agent's own `RESULT:APPLIED`; nothing read
  the employer's page, and `application.confirmation` was never written.
- After an approve, a `FAILED:*`, `DRAFT_READY`, `CAPTCHA` or `NEEDS_ANSWER` result was
  recorded as retryable, draft or deleted, so a possibly-sent job could be re-queued and
  sent twice.
- The prompt had no rule for a missing Submit control, validation errors after Submit,
  or an unconfirmed submit.
- The review card's "Submission off" badge read the global flag.

The 2026-10-02 verification log recommended keeping the flag off until the L4–L6 live
checks pass. The user decided to enable submission anyway; L4–L6 remain unrun.

## Decisions (the user's)

- **The review card stays.** Apply → the agent fills the form → the review card lists
  every field → the human's **Approve** makes the agent click Submit. Apply runs stay in
  manual mode.
- **Who may submit:** the job's Apply button (`POST /api/apply/{id}` and the legacy
  Jinja `POST /apply/{id}`), and Continue of a run that Apply started. Continue inherits
  that run's permission and never upgrades a draft-only run.
- **Draft-only:** "Track anyway" (`/api/override`, `/override`), the Home "apply to #id"
  card, the queue worker (Start/Resume, Auto and Manual) and auto-resume.

## Design

1. **Per-run permission, fail-closed.** `ats.submit()` takes a keyword-only
   `submit_allowed` that defaults to False. Only the Apply routes and Continue pass True,
   and on a resume `submit()` ANDs it with the session's stored
   `apply_checkpoint.can_submit` bit, so nothing escalates. The global flag becomes a
   master switch: off, every run drafts. An injected `run_agent` remains the test seam;
   no production caller passes one.
2. **The agent's submit protocol (submitting runs only).** After the approve, click the
   form's one final submit control exactly once; if there is not exactly one, click
   nothing and report `FAILED:submit_not_found`. After the click: a confirmation page →
   `APPLIED` and stay on the page; validation errors or the form still showing →
   `FAILED:validation_error`; neither within about 30 seconds →
   `FAILED:submit_unconfirmed`. For every run, CONFIRM only on the last page of the form,
   with every required field filled, the résumé attached and no validation error showing.
3. **Backend confirmation check.** At each CONFIRM the backend records the browser's
   frame URLs (the anchor). After `APPLIED`, and before the agent's Chrome is closed, it
   reads the frames on the anchor's hosts over CDP and judges: a fixed thank-you marker
   AND (the URL left the anchor OR the form controls are gone). It stores the evidence
   (URL, marker id, flags, title, time) in `application.confirmation`, never page text.
   The check is downgrade-only and never raises; any failure means "not verified".
4. **Outcome recording.** `submitted` (with `submitted_at`, the `submitted` event and
   the evidence) only on a verified check. An unverified `APPLIED` becomes
   `held_unknown` / `submit_unconfirmed`, with the approved answers and the evidence
   kept. In a run that could submit, any other result after an approve becomes
   `held_unknown` with its reason, never a draft, a delete or a requeue.
5. **Daily cap.** Re-checked inside the apply lock for submitting runs, because two
   Apply clicks can both pass the early check before either sends.
6. **UI.** The job detail exposes the run's own `can_submit`; the review card says
   "Approving submits the application" and its button reads "Approve and submit" only
   for such a run, otherwise "Draft only — approving saves a draft". "Redo draft" becomes
   "Apply again" where it goes through the Apply route.

## Known limits

- The confirmation markers are fixed English phrases. An ATS worded otherwise holds a
  real submission as `submit_unconfirmed` until the user adjudicates it with
  **Mark applied**; add the wording to the markers when it is seen.
- A `held_unknown` / `submit_unconfirmed` row does not count toward the daily cap.
- A job-description tab on the form's host whose text matches a marker and that shows two
  or fewer visible controls could verify falsely.
- Not yet proven live: reading text inside a cross-origin embedded form over CDP, the
  confirmation tab surviving the agent's MCP shutdown, and a second CDP client at CONFIRM
  time not disturbing the agent.
- The first live Apply is a real application. "Track anyway" and the Home card remain
  draft-only paths for rehearsal.
