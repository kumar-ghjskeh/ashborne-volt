"""Safe apply URL logic — strips tracking, detects broken patterns, provides fallbacks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Company careers URL fallbacks (for Workday deep-link failures)
COMPANY_SEARCH_URLS: dict[str, str] = {
    # S-Tier / Hyperscalers
    "nvidia":           "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
    "amd":              "https://careers.amd.com/careers-home/jobs",
    "apple":            "https://jobs.apple.com/en-us/search",
    "qualcomm":         "https://careers.qualcomm.com/careers",
    "intel":            "https://jobs.intel.com/en",
    "broadcom":         "https://broadcom.wd1.myworkdayjobs.com/External_Career",
    "globalfoundries":  "https://globalfoundries.wd1.myworkdayjobs.com/External",
    "marvell":          "https://marvell.wd1.myworkdayjobs.com/MarvellCareers",
    "google":           "https://careers.google.com/jobs/results/",
    "amazon":           "https://www.amazon.jobs/en/search",
    "microsoft":        "https://careers.microsoft.com/us/en/search-results",
    "meta":             "https://www.metacareers.com/jobs",
    # EDA
    "synopsys":         "https://synopsys.wd1.myworkdayjobs.com/Synopsys",
    "cadence":          "https://www.cadence.com/en_US/home/company/careers/job-openings.html",
    "siemens":          "https://jobs.siemens.com/careers",
    # Networking / Storage
    "cisco":            "https://jobs.cisco.com/jobs/SearchJobs",
    "juniper":          "https://careers.juniper.net/careers/jobs",
    "arista":           "https://www.arista.com/en/careers/job-openings",
    "western":          "https://careers.westerndigital.com/jobs",
    "seagate":          "https://seagatecareers.com/jobs",
    # Tier1 Semi
    "micron":           "https://micron.wd1.myworkdayjobs.com/External",
    "arm":              "https://careers.arm.com/en/jobs",
    "samsung":          "https://semiconductor.samsung.com/us/careers/jobs/",
    "mediatek":         "https://careers.mediatek.com/eREC/JobSearch/Index/USA",
    "nxp":              "https://nxp.wd3.myworkdayjobs.com/careers",
    "microchip":        "https://careers.microchip.com",
    "texas":            "https://careers.ti.com/jobs",
    "analog":           "https://careers.analog.com/jobs",
    "lattice":          "https://careers.latticesemi.com/jobs",
    "keysight":         "https://careers.keysight.com/jobs",
    "rambus":           "https://boards.greenhouse.io/rambus",
    # AI Accelerators / RISC-V
    "groq":             "https://boards.greenhouse.io/groq",
    "cerebras":         "https://boards.greenhouse.io/cerebrashysystems",
    "tenstorrent":      "https://boards.greenhouse.io/tenstorrent",
    "sambanova":        "https://boards.greenhouse.io/sambanova",
    "d-matrix":         "https://jobs.ashbyhq.com/d-matrix",
    "etched":           "https://jobs.ashbyhq.com/Etched",
    "lightmatter":      "https://boards.greenhouse.io/lightmatter",
    "sifive":           "https://boards.greenhouse.io/sifive",
    "astera":           "https://boards.greenhouse.io/asteralabs",
    "alphawave":        "https://www.awaveip.com/en/careers/",
    "credo":            "https://boards.greenhouse.io/credosemiconductor",
    # Defense / Gov
    "bae":              "https://jobs.baesystems.com/global/en",
    "rtx":              "https://careers.rtx.com/global/en/search-results",
    "raytheon":         "https://careers.rtx.com/global/en/search-results",
    "general":          "https://gdmissionsystems.com/careers",
    "lockheed":         "https://www.lockheedmartinjobs.com/jobs",
    "northrop":         "https://www.northropgrumman.com/careers/jobs",
    # Consulting
    "wipro":            "https://careers.wipro.com/careers-home/jobs",
    "hcltech":          "https://careers.hcltech.com/jobs",
    "hcl":              "https://careers.hcltech.com/jobs",
    # Others
    "ibm":              "https://www.ibm.com/employment/us/en/",
    "synaptics":        "https://boards.greenhouse.io/synaptics",
    "achronix":         "https://boards.greenhouse.io/achronix",
}

TRACKING_PARAMS = frozenset({
    "utm_source","utm_medium","utm_campaign","utm_term","utm_content",
    "fbclid","gclid","msclkid","ref","source","referral","gh_src",
    "lever-source","lever-origin",
})

# Workday broken patterns — these URLs go to generic search, not a specific job
WORKDAY_BROKEN_PATTERNS = [
    r"myworkdayjobs\.com/en-US/[^/]+/jobs$",
    r"myworkdayjobs\.com/wday/cxs/",
]


@dataclass
class ApplyURLResult:
    safe_apply_url: str
    original_apply_url: str
    apply_url_status: str   # ok | stripped | fallback | unknown | dead
    apply_url_reason: str


def process_apply_url(raw_url: str, ats_platform: str, company_name: str = "", careers_url: str = "") -> ApplyURLResult:
    original = raw_url or ""
    # Prefer the company's verified careers URL (from companies.yaml) as the
    # fallback; fall back to the static map only if none was supplied.
    fallback = careers_url or _get_company_fallback(company_name)

    if not original:
        return ApplyURLResult(
            safe_apply_url=fallback,
            original_apply_url="",
            apply_url_status="fallback" if fallback else "dead",
            apply_url_reason="no URL provided, using company careers page" if fallback else "no URL available",
        )

    # Strip tracking params
    cleaned, stripped_count = _strip_tracking(original)

    # Workday: a per-job deep link (…/job/Location/Title_JR123) lands directly on
    # the posting — exactly like LinkedIn — and is stable, so keep it. Only fall
    # back to the careers page for generic/non-job Workday URLs.
    if ats_platform == 'workday' or 'myworkdayjobs.com' in cleaned:
        if '/job/' in cleaned and not _is_broken_workday_url(cleaned):
            return ApplyURLResult(
                safe_apply_url=cleaned,
                original_apply_url=original,
                apply_url_status="ok",
                apply_url_reason="Workday job deep link",
            )
        return ApplyURLResult(
            safe_apply_url=fallback or cleaned,
            original_apply_url=original,
            apply_url_status="fallback" if fallback else "ok",
            apply_url_reason="generic Workday URL; using company careers page" if fallback else "Workday URL (no fallback configured)",
        )

    # Greenhouse, Lever, Ashby URLs are reliable
    if ats_platform in ("greenhouse", "lever", "ashby"):
        return ApplyURLResult(
            safe_apply_url=cleaned,
            original_apply_url=original,
            apply_url_status="ok",
            apply_url_reason=f"direct {ats_platform} URL",
        )

    # Amazon jobs are reliable
    if "amazon.jobs" in cleaned:
        return ApplyURLResult(
            safe_apply_url=cleaned,
            original_apply_url=original,
            apply_url_status="ok",
            apply_url_reason="Amazon Jobs direct URL",
        )

    # Stripped tracking params
    if stripped_count > 0:
        return ApplyURLResult(
            safe_apply_url=cleaned,
            original_apply_url=original,
            apply_url_status="stripped",
            apply_url_reason=f"removed {stripped_count} tracking parameter(s)",
        )

    return ApplyURLResult(
        safe_apply_url=cleaned,
        original_apply_url=original,
        apply_url_status="ok",
        apply_url_reason="direct URL",
    )


def _strip_tracking(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    removed = 0
    clean_params = {}
    for k, v in params.items():
        if k.lower() in TRACKING_PARAMS:
            removed += 1
        else:
            clean_params[k] = v
    new_query = urlencode(clean_params, doseq=True)
    cleaned = urlunparse(parsed._replace(query=new_query))
    return cleaned, removed


def _is_broken_workday_url(url: str) -> bool:
    for pattern in WORKDAY_BROKEN_PATTERNS:
        if re.search(pattern, url):
            return True
    return False


def _get_company_fallback(company_name: str) -> str:
    if not company_name:
        return ""
    name_lower = company_name.lower()
    # Try exact match first, then first-word, then substring scan
    if name_lower in COMPANY_SEARCH_URLS:
        return COMPANY_SEARCH_URLS[name_lower]
    first_word = name_lower.split()[0]
    if first_word in COMPANY_SEARCH_URLS:
        return COMPANY_SEARCH_URLS[first_word]
    # Substring match — for e.g. "Samsung Semiconductor" → "samsung"
    for key, url in COMPANY_SEARCH_URLS.items():
        if key in name_lower:
            return url
    return ""
