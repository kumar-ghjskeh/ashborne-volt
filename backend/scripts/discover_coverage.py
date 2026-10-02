"""Honest coverage audit: for each still-disabled high-value company, fetch its
careers host(s) via curl_cffi (bypasses Cloudflare/anti-bot) and detect the real
ATS + a reachable job API. Reports a verdict per company so only SAFE connectors
get wired — no blind enabling."""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from curl_cffi import requests  # noqa: E402

# (company, [candidate careers hosts])
TARGETS = [
    ("Cisco", ["jobs.cisco.com", "careers.cisco.com"]),
    ("Infineon", ["www.infineon.com/cms/en/careers", "careers.infineon.com"]),
    ("STMicroelectronics", ["careers.st.com", "www.st.com/careers"]),
    ("onsemi", ["careers.onsemi.com", "www.onsemi.com/careers"]),
    ("Skyworks", ["careers.skyworksinc.com", "www.skyworksinc.com/careers"]),
    ("Qorvo", ["careers.qorvo.com", "www.qorvo.com/careers"]),
    ("Silicon Labs", ["careers.silabs.com", "www.silabs.com/careers"]),
    ("Cirrus Logic", ["careers.cirrus.com", "www.cirrus.com/careers"]),
    ("Ambarella", ["careers.ambarella.com", "www.ambarella.com/careers"]),
    ("Teradyne", ["careers.teradyne.com", "jobs.teradyne.com"]),
    ("Wolfspeed", ["careers.wolfspeed.com", "www.wolfspeed.com/company/careers"]),
    ("MaxLinear", ["careers.maxlinear.com", "www.maxlinear.com/company/careers"]),
    ("Tesla", ["www.tesla.com/careers/search"]),
    ("Texas Instruments", ["careers.ti.com"]),
    ("Seagate", ["careers.seagate.com", "www.seagate.com/careers"]),
    ("Juniper Networks", ["careers.juniper.net", "jobs.juniper.net"]),
    ("MediaTek", ["careers.mediatek.com", "www.mediatek.com/careers"]),
    ("Groq", ["groq.com/careers", "jobs.groq.com"]),
    ("Achronix", ["www.achronix.com/careers"]),
    ("SK Hynix", ["careers.skhynix.com"]),
]

SIGS = {
    "phenom": [r"/api/jobs", r"phenom"],
    "workday": [r"myworkdayjobs", r"/wday/cxs"],
    "greenhouse": [r"boards\.greenhouse\.io", r"greenhouse"],
    "lever": [r"jobs\.lever\.co", r"api\.lever\.co"],
    "icims": [r"icims\.com"],
    "smartrecruiters": [r"smartrecruiters"],
    "jobvite": [r"jobvite", r"/search/jobs"],
    "eightfold": [r"eightfold\.ai"],
    "avature": [r"avature", r"/careers/SearchJobs"],
    "radancy": [r"radancy", r"talentbrew", r"/search-jobs"],
    "successfactors": [r"successfactors", r"jobs\.sap"],
    "workable": [r"workable\.com"],
    "ashby": [r"ashbyhq|jobs\.ashby"],
}


def fetch(url):
    try:
        return requests.get(url if url.startswith("http") else f"https://{url}",
                            impersonate="chrome", timeout=20)
    except Exception as e:
        return e


def main():
    for name, hosts in TARGETS:
        verdict = "no-API"
        detail = ""
        for host in hosts:
            r = fetch(host)
            if isinstance(r, Exception):
                continue
            low = r.text.lower()
            found = [ats for ats, pats in SIGS.items() if any(re.search(p, low) for p in pats)]
            final = urlparse(str(r.url)).netloc
            if found:
                verdict = "+".join(found[:3])
                detail = f"host={host} final={final}"
                break
            detail = f"host={host} [{r.status_code}] final={final} (no ATS sig)"
        print(f"{name:22} -> {verdict:28} {detail}")


if __name__ == "__main__":
    main()
