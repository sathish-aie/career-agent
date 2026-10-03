"""Did the employer's site reach its confirmation state? Read from the browser
itself over CDP -- never from the agent, whose RESULT:APPLIED a job page can
prompt-inject. Downgrade-only: ats._record_outcome records `submitted` only on
`verified` evidence; anything less is held_unknown (submit_unconfirmed).

Proves: a frame on a host the form was on at the latest CONFIRM shows a fixed
thank-you marker AND has left the CONFIRM-time urls or lost its form controls.
Cannot prove the employer's server accepted it -- only their email/portal can.
Raw page text is never stored, logged or returned (it echoes name and email).

Sync Playwright, as secret_fill: watch()'s wrapper runs on AgentRun's reader
thread, check() through asyncio.to_thread (ats._live_run_agent). Always reach
secret_fill._live_connect through the module: tests/conftest.py patches it."""
import datetime as dt
import logging
import re
import time
from urllib.parse import urlsplit

from career_agent.apply import secret_fill

log = logging.getLogger(__name__)

# Never "thank you for your interest": job pages and rejections say that too.
# ponytail: fixed English markers; an ATS worded otherwise holds (fail closed)
# -- add its wording here when a live run shows it.
MARKERS = {
    "thanks_for_applying": re.compile(
        r"\b(?:thanks|thank you) for (?:applying|your application|submitting)", re.I),
    "application_received": re.compile(
        r"\bapplication (?:has been|was) (?:successfully )?(?:submitted|received|sent)", re.I),
    "we_received": re.compile(r"\bwe(?:['’]ve| have) received your application", re.I),
    "successfully_applied": re.compile(r"\bsuccessfully (?:applied|submitted)", re.I),
}
_CONTROLS = "input:not([type=hidden]), textarea, select"
FORM_GONE_MAX = 2      # visible controls a confirmation page may keep (search, newsletter)
TEXT_TIMEOUT_MS = 2000
TEXT_LIMIT = 20000
TRIES, GAP_S = 3, 2.0  # a confirmation can render a beat after the agent saw it
TIMEOUT_S = 45         # ats._live_run_agent's bound on the whole check


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _frames(browser) -> list:
    return [f for page in secret_fill._pages(browser) for f in page.frames]


def frame_urls(*, connect=None) -> list[str]:
    """Every frame's display url (an embedded ATS form is an iframe). Cached
    properties only -- no per-frame JS, so it cannot stall the reader thread."""
    secret_fill._require_no_running_loop()
    with (connect or secret_fill._live_connect)(secret_fill.CDP_URL) as browser:
        return sorted({secret_fill.display_url(f.url) for f in _frames(browser)})


def _read(frame) -> dict:
    """One frame; text stays in memory. Any failure reads as no text: unverifiable."""
    url, host = secret_fill.display_url(frame.url), _host(frame.url)
    try:
        return {"url": url, "host": host,
                "text": frame.inner_text("body", timeout=TEXT_TIMEOUT_MS)[:TEXT_LIMIT],
                "controls": frame.locator(_CONTROLS).filter(visible=True).count(),
                "title": frame.title()[:80]}
    except Exception:
        return {"url": url, "host": host, "text": "", "controls": 0, "title": ""}


def snapshot(*, hosts=None, connect=None) -> list[dict]:
    """A fresh connection per call, so frames are never Playwright's stale cache."""
    secret_fill._require_no_running_loop()
    with (connect or secret_fill._live_connect)(secret_fill.CDP_URL) as browser:
        return [_read(f) for f in _frames(browser) if hosts is None or _host(f.url) in hosts]


def judge(before_urls, after: list[dict]) -> dict:
    """Pure. The evidence stored in application.confirmation -- never page text."""
    before = set(before_urls)
    hosts = {_host(u) for u in before} - {""}
    for f in after:
        if f["host"] not in hosts:
            continue
        marker = next((k for k, rx in MARKERS.items() if rx.search(f["text"])), None)
        url_changed, form_gone = f["url"] not in before, f["controls"] <= FORM_GONE_MAX
        if marker and (url_changed or form_gone):
            return {"verified": True, "url": f["url"], "marker": marker,
                    "url_changed": url_changed, "form_gone": form_gone,
                    "same_host": True, "title": f["title"], "checked_at": _now()}
    ev = {"verified": False, "urls": sorted({f["url"] for f in after})[:5], "checked_at": _now()}
    if not hosts:
        ev["error"] = "no_anchor"
    return ev


def watch(events, *, connect=None) -> list[str]:
    """Wrap events.on_confirm IN PLACE (the same RunEvents: AgentRun holds it,
    ats._kill_live compares it) so each CONFIRM first records the frame urls --
    before its card exists, so no approve can beat the anchor. The latest
    CONFIRM wins; a failed read clears it, and check() then holds."""
    before: list[str] = []
    inner = events.on_confirm

    def on_confirm(payload: dict) -> None:
        try:
            urls = frame_urls(connect=connect)
        except Exception as exc:
            log.warning("could not anchor the CONFIRM's page: %s", type(exc).__name__)
            urls = []
        before[:] = urls
        inner(payload)

    events.on_confirm = on_confirm
    return before


def check(before_urls, *, connect=None, tries: int = TRIES, gap_s: float = GAP_S) -> dict:
    """After RESULT:APPLIED, before Chrome is cleaned up. Never raises."""
    hosts = {_host(u) for u in before_urls} - {""}
    if not hosts:
        return judge([], [])
    ev = {"verified": False, "error": "not_checked", "checked_at": _now()}
    try:
        for attempt in range(tries):
            ev = judge(before_urls, snapshot(hosts=hosts, connect=connect))
            if ev["verified"] or attempt == tries - 1:
                return ev
            time.sleep(gap_s)
    except Exception as exc:
        log.warning("confirmation check failed: %s", type(exc).__name__)
        return {"verified": False, "error": type(exc).__name__, "checked_at": _now()}
    return ev
