"""One LinkedIn posting from a link the user pasted (Home chat). Discovery's
LinkedIn lane is the Apify actor in apify.py; this reads LinkedIn's own public
posting page, which needs no login and no Apify credits."""
import html
import logging
import re
from typing import Callable, Literal, NamedTuple

import httpx

from career_agent.models import Job

log = logging.getLogger(__name__)

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
JOB_URL = "https://www.linkedin.com/jobs/view/{}"

_LINK = re.compile(r"(?<![\w.-])(?:https?://)?(?:[\w-]+\.)?linkedin\.com/\S*", re.I)
_ID = re.compile(r"/jobs/view/(?:[^/?#\s]*-)?(\d+)(?=[/?#]|$)|[?&]currentJobId=(\d+)")

# ponytail: regexes over the class names of LinkedIn's guest page (checked live
# 2026-10-11). A markup change makes fetch() return None, which the chat reports
# as an unreadable posting; an Apify single-posting actor is the upgrade path.
_TITLE = re.compile(r'class="top-card-layout__title[^"]*"[^>]*>(.*?)</h2>', re.S)
_COMPANY = re.compile(r'class="topcard__org-name-link[^"]*"[^>]*>(.*?)</a>', re.S)
_LOCATION = re.compile(r'class="topcard__flavor topcard__flavor--bullet"[^>]*>(.*?)</span>', re.S)
_DESCRIPTION = re.compile(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)</div>', re.S)
_BREAK = re.compile(r"<br\s*/?>|</p>|<li[^>]*>|</[uo]l>", re.I)
_TAG = re.compile(r"<[^>]+>")


class Posting(NamedTuple):
    job: Job
    # Signed out, LinkedIn shows an apply control only for a posting that
    # applies on the employer's site, so "unknown" is most likely Easy Apply.
    apply: Literal["company_site", "closed", "unknown"]


def job_id(text: str) -> str | None:
    """The posting id in the first LinkedIn job link in `text`, else None."""
    for link in _LINK.findall(text or ""):
        m = _ID.search(link)
        if m:
            return m.group(1) or m.group(2)
    return None


def without_links(text: str) -> str:
    return _LINK.sub("", text)


def _text(fragment: str) -> str:
    lines = (html.unescape(_TAG.sub("", line)).strip()
             for line in _BREAK.sub("\n", fragment).split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def fetch(posting_id: str, get: Callable = httpx.get) -> Posting | None:
    """Read one posting. None when the page is gone or unreadable."""
    try:
        r = get(GUEST_URL.format(posting_id), timeout=20)
    except httpx.HTTPError as exc:
        log.warning("linkedin posting %s: %s", posting_id, exc)
        return None
    page = r.text if r.status_code == 200 else ""
    title, company = _TITLE.search(page), _COMPANY.search(page)
    if not (title and company):
        log.warning("linkedin posting %s unreadable (HTTP %s)", posting_id, r.status_code)
        return None
    location, description = _LOCATION.search(page), _DESCRIPTION.search(page)
    job = Job(source="linkedin", external_id=posting_id,
              company=_text(company.group(1)), title=_text(title.group(1)),
              location=_text(location.group(1)) if location else None,
              url=JOB_URL.format(posting_id),
              description=_text(description.group(1)) if description else None)
    if 'class="closed-job' in page:
        return Posting(job, "closed")
    return Posting(job, "company_site" if "apply-link-offsite" in page else "unknown")
