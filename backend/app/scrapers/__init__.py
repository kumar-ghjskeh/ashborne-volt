"""Scraper registry — maps ATS platform name to scraper class."""

from __future__ import annotations

from .amazon import AmazonScraper
from .ashby import AshbyScraper
from .avature import AvatureScraper
from .base import BaseScraper, JobData
from .eightfold import EightfoldScraper
from .generic import GenericScraper
from .greenhouse import GreenhouseScraper
from .icims import ICIMSScraper
from .jibe import JibeScraper
from .jobs2web import Jobs2WebScraper
from .jobvite import JobviteScraper
from .lever import LeverScraper
from .oracle import OracleHcmScraper
from .phenom import PhenomScraper
from .radancy import RadancyScraper
from .smartrecruiters import SmartRecruitersScraper
from .workday import WorkdayScraper

SCRAPER_MAP: dict[str, type[BaseScraper]] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "ashby": AshbyScraper,
    "workday": WorkdayScraper,
    "icims": ICIMSScraper,
    "jibe": JibeScraper,
    "amazon": AmazonScraper,
    "smartrecruiters": SmartRecruitersScraper,
    "eightfold": EightfoldScraper,
    "phenom": PhenomScraper,
    "jobs2web": Jobs2WebScraper,
    "oracle": OracleHcmScraper,
    "jobvite": JobviteScraper,
    "avature": AvatureScraper,
    "radancy": RadancyScraper,
    # All others fall through to GenericScraper
    "generic": GenericScraper,
    "apple": GenericScraper,
    "google": GenericScraper,
    "microsoft": GenericScraper,
    "meta": GenericScraper,
}


def get_scraper(company_config: dict) -> BaseScraper:
    ats = company_config.get("ats_platform", "generic").lower()
    cls = SCRAPER_MAP.get(ats, GenericScraper)
    return cls(company_config)
