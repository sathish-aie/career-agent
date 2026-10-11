import httpx
import pytest

from career_agent.sources import linkedin

# The markup of a real guest posting page (2026-10-11), cut down to the parts
# linkedin.fetch reads. `{extra}` is where the apply state sits in the top card.
PAGE = """
<section class="top-card-layout container-lined overflow-hidden babybear:rounded-[0px]">
  <a class="topcard__link" href="https://in.linkedin.com/jobs/view/x-at-citi-4451904611">
    <h2 class="top-card-layout__title font-sans text-lg papabear:text-xl font-bold leading-open text-color-text mb-0 topcard__title">AI Engineer, Agentic Systems &amp; Python</h2>
  </a>
  <h4 class="top-card-layout__second-subline">
    <span class="topcard__flavor">
      <a class="topcard__org-name-link topcard__flavor--black-link" data-tracking-control-name="public_jobs_topcard-org-name" href="https://www.linkedin.com/company/citi" rel="noopener" target="_blank">
        Citi
      </a>
    </span>
    <span class="topcard__flavor topcard__flavor--bullet">
      Chennai, Tamil Nadu, India
    </span>
    {extra}
  </h4>
</section>
<div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5 relative overflow-hidden">
  <strong>About the role</strong><br><br>Build agents.<ul><li>Python</li><li>LLMs &amp; evals</li></ul>
</div>
"""
OFFSITE = ('<div class="contextual-sign-in-modal" data-impression-id='
           '"public_jobs_apply-link-offsite_contextual-sign-in-modal"></div>')
CLOSED = ('<figure class="closed-job closed-job__flavor topcard__flavor-row"><figcaption'
          ' class="closed-job__flavor--closed">No longer accepting applications</figcaption></figure>')


def _get(status=200, extra=OFFSITE, seen=None):
    def get(url, **kw):
        if seen is not None:
            seen.append(url)
        return httpx.Response(status, text=PAGE.format(extra=extra) if status == 200 else "")
    return get


@pytest.mark.parametrize("text, expected", [
    ("https://www.linkedin.com/jobs/view/4451904611", "4451904611"),
    ("https://www.linkedin.com/jobs/view/4451904611/?refId=abc&trk=x", "4451904611"),
    ("apply to https://in.linkedin.com/jobs/view/ai-engineer-2-at-citi-4451904611 please", "4451904611"),
    ("https://www.linkedin.com/comm/jobs/view/4451904611", "4451904611"),
    ("linkedin.com/jobs/view/4451904611", "4451904611"),
    ("https://www.linkedin.com/jobs/search/?keywords=ai&currentJobId=4451904611", "4451904611"),
    ("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4451904611&x=1", "4451904611"),
    ("https://www.linkedin.com/in/someone-4451904611", None),
    ("https://www.linkedin.com/company/citi/jobs/", None),
    ("https://boards.greenhouse.io/acme/jobs/4451904611", None),
    ("https://notlinkedin.com/jobs/view/4451904611", None),
    ("apply to #1639", None),
])
def test_job_id_reads_only_linkedin_job_links(text, expected):
    assert linkedin.job_id(text) == expected


def test_without_links_drops_the_link_and_keeps_the_words():
    text = "this one https://in.linkedin.com/jobs/view/sales-pan-india-at-acme-4451904611 thanks"
    assert linkedin.without_links(text) == "this one  thanks"


def test_fetch_reads_a_company_site_posting():
    seen = []

    p = linkedin.fetch("4451904611", get=_get(seen=seen))

    assert seen == ["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4451904611"]
    assert p.apply == "company_site"
    job = p.job
    assert (job.source, job.external_id) == ("linkedin", "4451904611")
    assert job.title == "AI Engineer, Agentic Systems & Python"
    assert job.company == "Citi"
    assert job.location == "Chennai, Tamil Nadu, India"
    assert job.url == "https://www.linkedin.com/jobs/view/4451904611"
    assert job.description == "About the role\n\nBuild agents.\nPython\nLLMs & evals"


def test_fetch_tells_a_closed_posting_from_one_with_no_company_site_link():
    assert linkedin.fetch("1", get=_get(extra=CLOSED)).apply == "closed"
    # Signed out, an Easy Apply posting shows no apply control at all.
    assert linkedin.fetch("1", get=_get(extra="")).apply == "unknown"


def test_fetch_returns_none_for_a_page_it_cannot_read():
    assert linkedin.fetch("1", get=_get(status=404)) is None

    def boom(url, **kw):
        raise httpx.ConnectError("offline")
    assert linkedin.fetch("1", get=boom) is None

    assert linkedin.fetch("1", get=lambda url, **kw: httpx.Response(200, text="<html>sign in</html>")) is None
