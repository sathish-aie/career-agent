"""confirmation: after the agent says APPLIED the backend reads the employer's
page itself -- never the agent's word -- before a run is recorded 'submitted'.
Fake CDP pages only; tests/conftest.py fails any real connect_over_cdp."""
import json
from urllib.parse import urlsplit

import pytest

from career_agent.apply import confirmation
from career_agent.apply.runner import RunEvents
from test_secret_fill import connect_to

FORM = "https://boards.greenhouse.io/acme/jobs/1"


class _Loc:
    def __init__(self, n):
        self.n = n

    def filter(self, visible=None):
        assert visible is True, "only visible controls count"
        return self

    def count(self):
        return self.n


class Frame:
    def __init__(self, url, text="", controls=0, title="", detached=False):
        self.url, self.text, self.controls = url, text, controls
        self._title, self.detached = title, detached

    def inner_text(self, selector, timeout=None):
        assert selector == "body" and timeout, "every read carries a short timeout"
        if self.detached:
            raise RuntimeError("Frame was detached")
        return self.text

    def locator(self, selector):
        return _Loc(self.controls)

    def title(self):
        return self._title


class Page:
    def __init__(self, *frames):
        self.frames = list(frames)
        self.url = frames[0].url


def _seen(url, text="", controls=0, title="Acme"):
    """One frame as snapshot() reports it."""
    return {"url": url, "host": urlsplit(url).hostname, "title": title,
            "text": text, "controls": controls}


@pytest.mark.parametrize("text", [
    "Thank you for applying!", "Thanks for your application to Acme",
    "Your application has been submitted.", "Application was successfully received",
    "We've received your application", "You have successfully applied"])
def test_a_thank_you_page_on_the_forms_host_verifies(text):
    ev = confirmation.judge([FORM], [_seen(FORM + "/confirmation",
                                           "Jane Doe jane@example.com\n" + text)])
    assert ev["verified"] and ev["same_host"] and ev["url_changed"] and ev["checked_at"]
    assert ev["url"] == FORM + "/confirmation" and ev["marker"] in confirmation.MARKERS
    assert "jane" not in json.dumps(ev).lower(), "evidence never carries page text"


@pytest.mark.parametrize("before,after", [
    ([FORM], [_seen(FORM + "/done", "Thank you for your interest in Acme")]),       # brush-off
    ([FORM], [_seen("https://evil.example/thanks", "Thank you for applying")]),     # other host
    ([FORM], [_seen(FORM, "We thank you for applying. * required", controls=14)]),  # form still there
    ([], [_seen(FORM + "/confirmation", "Thank you for applying")]),                # no anchor
])
def test_anything_short_of_the_forms_own_confirmation_is_unverified(before, after):
    assert confirmation.judge(before, after)["verified"] is False


def test_an_spa_whose_form_is_gone_verifies_without_a_navigation():
    ev = confirmation.judge([FORM], [_seen(FORM, "Thank you for applying!", controls=0)])
    assert ev["verified"] and not ev["url_changed"] and ev["form_gone"]


def test_an_embedded_form_is_judged_in_its_iframe():
    """Greenhouse/Lever embeds: the company page stays put, the iframe confirms."""
    top, frame = "https://acme.com/careers/ai-engineer", "https://boards.greenhouse.io/embed/job_app"
    ev = confirmation.judge([top, frame], [_seen(top, "AI Engineer at Acme. Apply below."),
                                           _seen(frame + "/confirmation", "Thank you for applying.")])
    assert ev["verified"] and ev["url"] == frame + "/confirmation"


def test_snapshot_reads_frames_on_the_given_hosts_with_display_urls():
    page = Page(Frame("https://acme.com/careers?utm=x#top", "Careers", 1, "Acme " + "x" * 100),
                Frame("https://boards.greenhouse.io/embed/job_app?token=s3cr3t", "Apply", 9),
                Frame("https://boards.greenhouse.io/embed/other", detached=True),
                Frame("https://ads.example/frame", "ad", 3))
    seen = confirmation.snapshot(hosts={"acme.com", "boards.greenhouse.io"}, connect=connect_to(page))
    assert [(f["url"], f["controls"]) for f in seen] == [
        ("https://acme.com/careers", 1), ("https://boards.greenhouse.io/embed/job_app", 9),
        ("https://boards.greenhouse.io/embed/other", 0)]
    assert seen[1]["text"] == "Apply" and seen[2]["text"] == ""        # a failed read is empty
    assert all(len(f["title"]) <= 80 for f in seen) and "s3cr3t" not in json.dumps(seen)


def test_frame_urls_lists_every_frame_once():
    page = Page(Frame("https://acme.com/c?x=1"), Frame("https://boards.greenhouse.io/embed/job_app"),
                Frame("https://acme.com/c"))
    assert confirmation.frame_urls(connect=connect_to(page)) == [
        "https://acme.com/c", "https://boards.greenhouse.io/embed/job_app"]


async def test_reads_refuse_to_run_on_the_event_loop():
    with pytest.raises(RuntimeError, match="event loop"):
        confirmation.frame_urls(connect=connect_to(Page(Frame(FORM))))


def test_watch_anchors_the_form_urls_before_the_confirm_card_exists(monkeypatch):
    monkeypatch.setattr(confirmation, "frame_urls",
                        lambda connect=None: [FORM, "https://acme.com/x"])
    delegated = []
    events = RunEvents(on_confirm=lambda p: delegated.append((p, list(before))))
    before = confirmation.watch(events)
    events.on_confirm({"fields": []})
    assert before == [FORM, "https://acme.com/x"]
    assert delegated == [({"fields": []}, [FORM, "https://acme.com/x"])]


def test_a_failed_anchor_still_delivers_the_confirm_and_anchors_nothing(monkeypatch):
    def boom(connect=None):
        raise RuntimeError("cdp went away")
    monkeypatch.setattr(confirmation, "frame_urls", boom)
    got, events = [], RunEvents()
    events.on_confirm = got.append
    before = confirmation.watch(events)
    before.append("stale")                       # a previous CONFIRM's anchor
    events.on_confirm({"fields": []})
    assert got == [{"fields": []}] and before == []


def test_check_retries_then_verifies_and_never_raises(monkeypatch):
    reads = iter([[_seen(FORM, "Loading…", controls=12)],
                  [_seen(FORM + "/thanks", "Thank you for applying")]])
    monkeypatch.setattr(confirmation, "snapshot", lambda hosts=None, connect=None: next(reads))
    assert confirmation.check([FORM], gap_s=0)["verified"] is True

    def boom(hosts=None, connect=None):
        raise TimeoutError("cdp")
    monkeypatch.setattr(confirmation, "snapshot", boom)
    ev = confirmation.check([FORM], gap_s=0)
    assert ev["verified"] is False and ev["error"] == "TimeoutError"
    ev = confirmation.check([], gap_s=0)            # no CONFIRM anchor: nothing to compare against
    assert ev["verified"] is False and ev["error"] == "no_anchor"
