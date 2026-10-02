"""Browser-rendered ATS discovery. JS-heavy careers pages only reveal their ATS
board after scripts run, so load each in real Chromium and capture the network
calls to Greenhouse / Lever / Ashby / Workday / SmartRecruiters — those URLs
contain the exact board slug. Prints a paste-ready summary per company.
"""
import asyncio
import json
import re
import ssl
import urllib.request
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import sys as _sys
DEEP = "--deep" in _sys.argv

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

TARGETS = {
    "Groq": "https://groq.com/careers/",
    "Arista Networks": "https://www.arista.com/en/careers",
    "Synaptics": "https://www.synaptics.com/careers",
    "Achronix": "https://www.achronix.com/careers",
    "Alphawave Semi": "https://awaveip.com/careers/",
    "Credo Semiconductor": "https://www.credosemi.com/careers/",
    "Cornelis Networks": "https://www.cornelisnetworks.com/careers/",
    "Enfabrica": "https://www.enfabrica.net/",
    "Esperanto Technologies": "https://www.esperanto.ai/careers/",
    "MaxLinear": "https://www.maxlinear.com/company/careers",
    "Untether AI": "https://www.untether.ai/",
    "Ayar Labs": "https://ayarlabs.com/careers/",
    "Rivos": "https://rivosinc.com/careers/",
    "SiMa.ai": "https://sima.ai/careers/",
    "Recogni": "https://recogni.com/careers/",
    "Celestial AI": "https://www.celestial.ai/careers",
    "Mythic": "https://mythic.ai/careers/",
    "Blaize": "https://www.blaize.com/careers/",
    "Quadric": "https://quadric.io/careers/",
    "Expedera": "https://www.expedera.com/careers/",
}

CAPTURE = re.compile(
    r"(boards-api\.greenhouse\.io/v1/boards/([a-z0-9]+)"
    r"|job-?boards\.greenhouse\.io/([a-z0-9]+)"
    r"|api\.lever\.co/v0/postings/([a-z0-9-]+)"
    r"|jobs\.lever\.co/([a-z0-9-]+)"
    r"|api\.ashbyhq\.com/posting-api/job-board/([a-z0-9-]+)"
    r"|jobs\.ashbyhq\.com/([a-z0-9-]+)"
    r"|([a-z0-9]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[a-z0-9]+/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"
    r"|api\.smartrecruiters\.com/v1/companies/([a-z0-9]+)/postings"
    # Appended, not inserted: the handler reads groups positionally, so anything
    # added before this point silently renumbers the ones above it.
    # iCIMS is how Arm and Rambus were actually found, and it was missing entirely.
    r"|([a-z0-9-]+)\.icims\.com"
    r"|([a-z0-9-]+)\.avature\.net"
    r"|([a-z0-9-]+)\.eightfold\.ai"
    r"|([a-z0-9-]+)\.my\.site\.com"
    r"|([a-z0-9-]+)\.phenompeople\.com"
    r"|([a-z0-9-]+)\.jobs2web\.com)",
    re.I,
)


# Path segments that are NOT board slugs. jobs.lever.co also serves its static
# assets, so the slug capture happily read "cdn-cgi", "img" and "js" as company
# boards on one candidate. A tool whose output needs manual filtering is a tool
# that will eventually have a wrong board pasted out of it.
NOT_A_SLUG = {
    "cdn-cgi", "img", "images", "js", "css", "static", "assets", "fonts",
    "favicon", "api", "embed", "v0", "v1", "v2", "jobs", "job", "postings",
    "search", "careers", "about", "privacy", "terms", "login", "signup",
}


def looks_related(company: str, slug: str) -> bool:
    """Does this identifier plausibly belong to this company?

    One candidate's page referenced nxp.my.site.com — another company's portal,
    embedded or linked. Reporting that as the candidate's board is the same class
    of error as the greenhouse "ventana" entry that turned out to be a nursing
    home, so anything unrelated is flagged rather than printed as a find.
    """
    import re as _re
    a = _re.sub(r"[^a-z0-9]", "", company.lower())
    b = _re.sub(r"[^a-z0-9]", "", slug.lower())
    if not a or not b:
        return False
    return a[:5] in b or b[:5] in a


def gh_count(slug):
    try:
        req = urllib.request.Request(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15, context=CTX) as r:
            return len(json.loads(r.read()).get("jobs", []))
    except Exception:
        return "?"


async def discover(ctx, name, url):
    page = await ctx.new_page()
    hits = set()

    def on_request(req):
        m = CAPTURE.search(req.url)
        if not m:
            return
        u = req.url
        host = (urlparse(u).hostname or "").lower()

        def on(domain: str) -> bool:
            return host == domain or host.endswith("." + domain)

        if on("greenhouse.io"):
            slug = m.group(2) or m.group(3)
            if slug and slug not in ("embed",):
                hits.add(("greenhouse", slug))
        elif on("lever.co"):
            slug = m.group(4) or m.group(5)
            if slug:
                hits.add(("lever", slug))
        elif on("ashbyhq.com"):
            slug = m.group(6) or m.group(7)
            if slug and slug not in ("api",):
                hits.add(("ashby", slug))
        elif on("myworkdayjobs.com"):
            hits.add(("workday", f"{m.group(8)}.{m.group(9)}/{m.group(10)}"))
        elif on("smartrecruiters.com"):
            hits.add(("smartrecruiters", m.group(11)))
        elif on("icims.com"):
            hits.add(("icims", f"{m.group(12)}.icims.com"))
        elif on("avature.net"):
            hits.add(("avature", m.group(13)))
        elif on("eightfold.ai"):
            hits.add(("eightfold", m.group(14)))
        elif on("my.site.com"):
            hits.add(("salesforce(no adapter)", f"{m.group(15)}.my.site.com"))
        elif on("phenompeople.com"):
            hits.add(("phenom", m.group(16)))
        elif on("jobs2web.com"):
            hits.add(("jobs2web", m.group(17)))

    page.on("request", on_request)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await page.wait_for_timeout(3500)
        # Many careers landing pages only LINK to their board ("Search jobs")
        # instead of calling it. Run every link and the page HTML through the same
        # matcher, as if each were a request.
        try:
            html = await page.content()
            hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        except Exception:
            html, hrefs = "", []

        class _Fake:
            def __init__(self, u):
                self.url = u
        for h in hrefs:
            on_request(_Fake(h))
        for m in CAPTURE.finditer(html):
            on_request(_Fake("https://" + m.group(0)))

        # --deep: utility and EPC careers pages often link to a separate "Search
        # jobs" page that is the one calling the board. Follow up to three such
        # links one level down, capturing their requests too.
        if DEEP and not hits:
            try:
                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => [e.href, (e.innerText || e.getAttribute('aria-label') || '').trim()])")
            except Exception:
                links = []
            follow = []
            for href, text in links:
                t = f"{text} {href}".lower()
                if href.startswith("http") and re.search(
                        r"search (all )?jobs|view (all )?jobs|job search|find (a )?job|open (positions|roles|jobs)|"
                        r"current openings|career opportunities|explore (jobs|careers)|apply now|/jobs|/search|jobsearch",
                        t) and href not in follow:
                    follow.append(href)
            for href in follow[:3]:
                try:
                    await page.goto(href, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(2500)
                    html2 = await page.content()
                    for m in CAPTURE.finditer(html2):
                        on_request(_Fake("https://" + m.group(0)))
                    on_request(_Fake(page.url))
                except Exception:
                    continue
                if hits:
                    break
    except Exception as e:
        await page.close()
        return f"XX  {name:24} nav-error {str(e)[:40]}"
    await page.close()

    if not hits:
        return f"XX  {name:24} -> no ATS calls captured"
    parts, suspect = [], []
    for ats, slug in sorted(hits):
        bare = slug.split(".")[0]
        if bare in NOT_A_SLUG:
            continue                       # static asset path, not a board
        extra = ""
        if ats == "greenhouse":
            n = gh_count(slug)
            if n == "?":
                # The page referenced this board but its API 404s — the board moved
                # or was deleted. Printing it as OK invites pasting a dead slug into
                # the config, where it reads as "connected, no openings" forever.
                suspect.append(f"{ats}:{slug} (board API 404 — dead or moved)")
                continue
            extra = f"={n}"
        entry = f"{ats}:{slug}{extra}"
        (parts if looks_related(name, bare) else suspect).append(entry)
    if not parts and not suspect:
        return f"XX  {name:24} -> only static-asset paths captured"
    line = f"OK  {name:24} -> " + ", ".join(parts) if parts else f"??  {name:24} ->"
    if suspect:
        line += "   [SUSPECT, name mismatch: " + ", ".join(suspect) + "]"
    return line


def targets_from_config(names: list[str]) -> dict[str, str]:
    """Every company worth probing, read from the catalog rather than hardcoded.

    Default set: entries that are disabled or still on the heuristic `generic`
    adapter — exactly the ones whose real board has not been found yet. The
    hardcoded TARGETS above is kept as a fallback for ad-hoc probing.
    """
    import pathlib

    import yaml
    cfg = pathlib.Path(__file__).resolve().parents[1] / "config" / "companies.yaml"
    companies = yaml.safe_load(cfg.read_text(encoding="utf-8"))["companies"]
    if names:
        wanted = {n.lower() for n in names}
        return {c["name"]: c.get("careers_url", "") for c in companies
                if c["name"].lower() in wanted and c.get("careers_url")}
    return {
        c["name"]: c.get("careers_url", "") for c in companies
        if c.get("careers_url")
        and (not c.get("enabled", True) or c.get("ats_platform") == "generic")
    }


def already_in_catalog() -> set[str]:
    """Names already in companies.yaml, normalised for comparison.

    Only ENABLED entries. A disabled entry is a legitimate rediscovery target —
    Groq is in the catalog but disabled precisely because its board was lost, so
    skipping it would skip the thing worth looking for.

    A sweep that reports an already-working source as a find wastes the reader's
    attention on a duplicate — Eliyan surfaced that way, already enabled with 14
    US jobs.
    """
    import pathlib
    import re as _re

    import yaml
    cfg = pathlib.Path(__file__).resolve().parents[1] / "config" / "companies.yaml"
    out = set()
    for c in yaml.safe_load(cfg.read_text(encoding="utf-8"))["companies"]:
        if c.get("enabled", True):
            out.add(_re.sub(r"[^a-z0-9]", "", c["name"].lower()))
    return out


def targets_from_file(path: str) -> dict[str, str]:
    """Candidates NOT yet in the catalog: one `Name,https://careers-url` per line.

    The config-driven mode only sees companies already listed, so this is how a
    fresh candidate sweep is run. Blank lines and `#` comments are ignored.
    """
    import pathlib
    out: dict[str, str] = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        name, url = line.split(",", 1)
        out[name.strip()] = url.strip()
    return out


async def main():
    import sys
    args = sys.argv[1:]
    cand = next((a.split("=", 1)[1] for a in args if a.startswith("--candidates=")), None)
    names = [a for a in args if not a.startswith("-")]
    targets = (targets_from_file(cand) if cand
               else targets_from_config(names) or TARGETS)
    if cand:
        import re as _re
        have = already_in_catalog()

        def _dup(n: str) -> bool:
            # NOT exact membership: the catalog says "Eliyan" while a candidate list
            # says "Eliyan Corp", and an exact check reports a company we already
            # scrape as a fresh find. Same failure as the H1B lookup that missed
            # "Cadence Design Systems" because the key was "cadence".
            k = _re.sub(r"[^a-z0-9]", "", n.lower())
            return any(k.startswith(h) or h.startswith(k) for h in have if len(h) >= 4)

        dupes = [n for n in targets if _dup(n)]
        for n in dupes:
            print(f"--  {n:24} already in the catalog, skipping", flush=True)
            targets.pop(n, None)
    print(f"probing {len(targets)} companies", flush=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900},
            # Untether AI serves ERR_SSL_VERSION_OR_CIPHER_MISMATCH. Acceptable
            # here: this reads public job listings and sends no credentials.
            ignore_https_errors=True,
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        for name, url in targets.items():
            print(await discover(ctx, name, url), flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
