"""USA location detection and parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Data tables ──────────────────────────────────────────────────────────────

US_STATE_ABBREVIATIONS: frozenset[str] = frozenset({
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
})

US_STATE_NAMES: dict[str, str] = {
    "alabama":"AL","alaska":"AK","arizona":"AZ","arkansas":"AR","california":"CA",
    "colorado":"CO","connecticut":"CT","delaware":"DE","florida":"FL","georgia":"GA",
    "hawaii":"HI","idaho":"ID","illinois":"IL","indiana":"IN","iowa":"IA",
    "kansas":"KS","kentucky":"KY","louisiana":"LA","maine":"ME","maryland":"MD",
    "massachusetts":"MA","michigan":"MI","minnesota":"MN","mississippi":"MS",
    "missouri":"MO","montana":"MT","nebraska":"NE","nevada":"NV",
    "new hampshire":"NH","new jersey":"NJ","new mexico":"NM","new york":"NY",
    "north carolina":"NC","north dakota":"ND","ohio":"OH","oklahoma":"OK",
    "oregon":"OR","pennsylvania":"PA","rhode island":"RI","south carolina":"SC",
    "south dakota":"SD","tennessee":"TN","texas":"TX","utah":"UT","vermont":"VT",
    "virginia":"VA","washington":"WA","west virginia":"WV","wisconsin":"WI",
    "wyoming":"WY","district of columbia":"DC",
}

US_CITIES: list[tuple[str, str]] = [
    # (city_lower, state_abbr)
    ("santa clara","CA"),("san jose","CA"),("cupertino","CA"),("sunnyvale","CA"),
    ("mountain view","CA"),("menlo park","CA"),("palo alto","CA"),("san francisco","CA"),
    ("san diego","CA"),("irvine","CA"),("san mateo","CA"),("beaverton","CA"),  # Broadcom
    ("folsom","CA"),("rancho cordova","CA"),("campbell","CA"),("milpitas","CA"),
    ("beaverton","OR"),("hillsboro","OR"),("portland","OR"),
    ("austin","TX"),("dallas","TX"),("houston","TX"),("san antonio","TX"),
    ("fort worth","TX"),("plano","TX"),("chandler","AZ"),("phoenix","AZ"),
    ("tempe","AZ"),("scottsdale","AZ"),
    ("seattle","WA"),("redmond","WA"),("bellevue","WA"),("kirkland","WA"),
    ("raleigh","NC"),("research triangle","NC"),("durham","NC"),
    ("boston","MA"),("cambridge","MA"),("waltham","MA"),("lexington","MA"),
    ("wilmington","MA"),("chelmsford","MA"),
    ("new york","NY"),("new york city","NY"),("nyc","NY"),
    ("atlanta","GA"),("boca raton","FL"),("fort collins","CO"),("boulder","CO"),
    ("denver","CO"),("minneapolis","MN"),("detroit","MI"),("ann arbor","MI"),
    ("pittsburgh","PA"),("boise","ID"),("bloomington","MN"),
    ("poughkeepsie","NY"),("san ramon","CA"),("pleasanton","CA"),
    ("san bruno","CA"),("south san francisco","CA"),("fremont","CA"),
    ("santa barbara","CA"),("goleta","CA"),("thousand oaks","CA"),
    ("westlake village","CA"),
    # Bare US city names seen live with no state attached.
    # Bare US city names seen live with no state attached. Deliberately excludes
    # over-generic words ("Allen", "Spring", "Hudson") that would false-positive
    # on the bare-city match, which has no other signal to corroborate it.
    ("cary","NC"),("richardson","TX"),("bay area","CA"),("morrisville","NC"),
    ("longmont","CO"),("colorado springs","CO"),("broomfield","CO"),
    ("mendota heights","MN"),("andover","MA"),("marlborough","MA"),
    ("nashua","NH"),("cedar rapids","IA"),
    # Real US semiconductor/hardware sites that were resolving to "location
    # unknown" and so depended on the unknown-location escape hatch to be seen
    # at all. With USA-only now strict, an unrecognised US city is an INVISIBLE
    # US job, so this list is the thing keeping real roles on the board.
    ("orlando","FL"),("tampa","FL"),("palm bay","FL"),("huntsville","AL"),
    ("tucson","AZ"),("mesa","AZ"),("gilbert","AZ"),("albuquerque","NM"),
    ("round rock","TX"),("sherman","TX"),("el paso","TX"),("lubbock","TX"),
    ("charlotte","NC"),("greensboro","NC"),("columbus","OH"),("cleveland","OH"),
    ("rochester","MN"),("eden prairie","MN"),("shakopee","MN"),
    ("chippewa falls","WI"),("madison","WI"),("corvallis","OR"),
    ("meridian","ID"),("lehi","UT"),("salt lake city","UT"),
    ("allentown","PA"),("malvern","PA"),("bethlehem","PA"),("philadelphia","PA"),
    ("fishkill","NY"),("hopewell junction","NY"),("syracuse","NY"),("albany","NY"),
    ("essex junction","VT"),("burlington","VT"),("manassas","VA"),
    ("herndon","VA"),("reston","VA"),("arlington","VA"),("baltimore","MD"),
    ("columbia","MD"),("nashville","TN"),("kansas city","MO"),("st louis","MO"),
    ("indianapolis","IN"),("des moines","IA"),("omaha","NE"),("loveland","CO"),
]

NON_USA_SIGNALS: frozenset[str] = frozenset({
    "india","bangalore","bengaluru","hyderabad","pune","noida","gurgaon","gurugram",
    "chennai","mumbai","delhi","kolkata","ahmedabad",
    "canada","toronto","vancouver","montreal","ottawa","calgary","waterloo","ontario",
    "uk","united kingdom","london","cambridge uk","bristol","edinburgh",
    "germany","munich","berlin","hamburg","frankfurt","stuttgart","munich",
    "israel","tel aviv","herzliya","haifa","beer sheva","petah tikva","netanya",
    "taiwan","hsinchu","taipei","taichung",
    "singapore","malaysia","kuala lumpur","penang",
    "china","beijing","shanghai","shenzhen","hong kong",
    "japan","tokyo","osaka","yokohama",
    "south korea","korea","seoul","suwon",
    "netherlands","amsterdam","eindhoven",
    "france","paris","grenoble","sophia antipolis",
    "sweden","stockholm","gothenburg","lund",
    "finland","helsinki","espoo",
    "switzerland","zurich","bern",
    "argentina","buenos aires","cordoba argentina",
    "brazil","sao paulo","campinas",
    "australia","sydney","melbourne",
    # Bare foreign city names seen live in the corpus with no country attached,
    # which left them "location unknown" and therefore visible in the USA view.
    "kanata","catania","ho chi minh","belo horizonte","caen","rehovot","isr",
    "alajuela","sofia","belgrade","cork","limerick","galway","krakow","wroclaw",
    "gdansk","brno","timisoara","cluj","bucharest","budapest","prague","sofia",
})

# Explicit foreign COUNTRY/region names. These are strong signals: when one
# appears in the location field and there is NO unambiguous US signal (explicit
# "United States" or a US state), the job is non-USA — even if it also contains a
# city name that collides with a US city (Cambridge UK vs Cambridge MA, London,
# Richmond, Victoria, etc.). This is the guardrail against foreign jobs leaking
# into the USA list.
FOREIGN_COUNTRIES: tuple[str, ...] = (
    "united kingdom", "england", "scotland", "wales", "northern ireland",
    "ireland", "canada", "india", "germany", "israel", "taiwan", "singapore",
    "malaysia", "china", "hong kong", "japan", "south korea", "korea",
    "netherlands", "france", "sweden", "finland", "switzerland", "norway",
    "denmark", "poland", "romania", "spain", "italy", "austria", "belgium",
    "czech", "hungary", "portugal", "greece", "argentina", "brazil", "mexico",
    "australia", "new zealand", "vietnam", "philippines", "thailand",
    "indonesia", "turkey", "ukraine", "uae", "united arab emirates",
    "saudi arabia", "egypt", "morocco", "south africa", "uk",
    # Seen live in the corpus while still classified "location unknown", which
    # let them surface in the USA-or-unknown view: Renesas/Sofia, Tenstorrent/
    # Belgrade, Teradyne/Alajuela, plus their regional neighbours.
    "bulgaria", "serbia", "costa rica", "croatia", "slovenia", "slovakia",
    "lithuania", "latvia", "estonia", "colombia", "chile", "peru", "armenia",
    "georgia (country)", "bosnia", "macedonia", "montenegro", "albania",
    # Clearly non-US regions (e.g. "Remote - Europe", "Remote, EMEA"). Deliberately
    # excludes "Americas"/"North America" which can include the US.
    "europe", "emea", "apac", "latam", "asia pacific",
)

USA_EXPLICIT: tuple[str, ...] = (
    "united states", "united states of america", "usa", "u.s.", "u.s.a.", "us ",
)

REMOTE_SIGNALS: tuple[str, ...] = (
    "remote", "work from home", "wfh", "fully remote", "remote-first",
    "remote usa", "remote us", "remote (usa)", "remote (us)",
)


@dataclass
class LocationResult:
    is_usa: bool = False
    is_remote_usa: bool = False
    country: str = ""
    state: str = ""
    city: str = ""
    confidence: float = 0.0
    reason: str = ""


# Foreign regions whose names CONTAIN a full US state name. Left intact, the
# state name inside them reads as an unambiguous US signal, which suppresses the
# explicit foreign-country check entirely — "Tijuana, Baja California, Mexico"
# was being served as a California job.
#
# Each is rewritten to its COUNTRY before any matching runs, so the region still
# excludes correctly even when the posting never names the country
# ("Mexicali, Baja California" -> "mexicali, mexico" -> foreign), instead of
# degrading to "location unknown".
#
# NOTE: only phrases where a US state name is a strict substring belong here.
# Real US states that merely contain a country name ("New Mexico") must NOT be
# listed — those already resolve correctly via the US-state-name match.
_FALSE_FRIENDS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bbaja california(?:\s+sur)?\b", re.IGNORECASE), " mexico "),
]


def _mask_false_friends(loc: str) -> str:
    for pat, repl in _FALSE_FRIENDS:
        loc = pat.sub(repl, loc)
    return loc


# Workday tenants commonly prefix the location with an ISO-3166 alpha-3 country
# code: "CAN - Burlington, ON", "IND - Hyderabad", "MEX - Aguascalientes",
# "CHE - Neuchatel". Without this the country is invisible to the parser and the
# city can collide with a US one — "CAN - Burlington, ON" was being served as
# Burlington, VERMONT. Prefix-anchored so a stray three-letter word in a city
# name can never trigger it.
_ALPHA3_FOREIGN = {
    "can", "mex", "ind", "chn", "twn", "jpn", "kor", "deu", "fra", "gbr", "che",
    "sgp", "mys", "phl", "vnm", "tha", "isr", "irl", "nld", "swe", "nor", "dnk",
    "fin", "pol", "rou", "esp", "ita", "aut", "bel", "cze", "hun", "prt", "grc",
    "bra", "arg", "chl", "col", "aus", "nzl", "zaf", "tur", "ukr", "are", "sau",
    "egy", "mar", "cri", "bgr", "srb", "hrv", "ltu", "lva", "est", "svk", "svn",
    "idn", "hkg", "lka", "pak", "bgd", "rus", "bel",
}
_ALPHA3_RE = re.compile(r"^\s*([a-z]{3})\s*[-–—]\s*", re.IGNORECASE)

# Canadian province codes. Safe to treat as foreign: none collide with a US
# state abbreviation, and they appear in the same "City, XX" shape that would
# otherwise fall through to a US city match.
_CA_PROVINCE_RE = re.compile(r",\s*(on|qc|bc|ab|mb|sk|ns|nb|nl|pei|pe|yt|nt|nu)\s*$", re.IGNORECASE)


def _foreign_country_code(loc: str) -> str:
    """Country implied by an alpha-3 prefix or Canadian province suffix, else ""."""
    m = _ALPHA3_RE.match(loc)
    if m and m.group(1).lower() in _ALPHA3_FOREIGN:
        return m.group(1).upper()
    if _CA_PROVINCE_RE.search(loc):
        return "CAN"
    return ""


# Workday (and a few others) return a useless roll-up like "2 Locations" in the
# list API when a req spans sites, but the apply URL still carries the real
# primary site as a path slug:
#   .../job/Folsom-CA/MTS--AI-Optimized-Memory_R123   -> "Folsom, CA"
#   .../job/India---Hyderabad/Design-Engineer_R456    -> "India, Hyderabad"
# Recovering it costs nothing (no extra request) and is the difference between
# showing "2 Locations" and showing a real place — and between an India req
# quietly sitting in the USA view and being correctly excluded.
_URL_JOB_SLUG_RE = re.compile(r"/job/([^/?#]+)/[^/?#]*$", re.IGNORECASE)
# Trailing street-address noise: "4420-Arrow-Ave", "3850-N-First-St", "Main-Site".
_ADDR_NOISE_RE = re.compile(
    r"[\s,]+\d[\w\s]*(?:st|street|ave|avenue|rd|road|blvd|dr|drive|way|pkwy|"
    r"parkway|lane|ln|ct|court)?\s*$",
    re.IGNORECASE,
)


def location_from_apply_url(apply_url: str) -> str:
    """Best-effort human location parsed out of a job URL's path slug.

    Returns "" when the URL carries no usable slug. The result is a plain
    location string meant to be fed straight back into parse_location().
    """
    if not apply_url:
        return ""
    m = _URL_JOB_SLUG_RE.search(apply_url)
    if not m:
        return ""
    slug = m.group(1)
    # "---" separates location components; single "-" separates words.
    text = slug.replace("---", ", ").replace("--", ", ").replace("-", " ")
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip(" ,")
    text = _ADDR_NOISE_RE.sub("", text).strip(" ,")
    # A slug that is just a requisition id ("R2512345", "JR0123") is not a place.
    if not text or re.fullmatch(r"[A-Za-z]{0,3}\d[\w\s]*", text):
        return ""
    return text


def parse_location(location_raw: str, description: str = "") -> LocationResult:
    """Detect whether a job is in the USA and extract state/city."""
    if not location_raw and not description:
        return LocationResult(confidence=0.0, reason="no location data")

    loc = _mask_false_friends((location_raw or "").lower().strip())
    desc_snippet = (description or "")[:500].lower()
    combined = loc + " " + desc_snippet

    # An *unambiguous* US signal = explicit "United States", a full US state name,
    # or a "City, ST" state abbreviation. A bare city name does NOT count — cities
    # like Cambridge / London / Richmond / Victoria collide with foreign cities.
    # Only a strong US signal lets a genuine multi-region posting
    # ("Austin, TX; London, United Kingdom") stay in the USA view.
    strong_usa = _has_usa_signal(loc)

    # 0. An explicit country CODE beats everything except an explicit US marker.
    #    Checked before the city/state matching below, because the city half of
    #    "CAN - Burlington, ON" collides with a real US city.
    if not strong_usa:
        code = _foreign_country_code(loc)
        if code:
            return LocationResult(
                is_usa=False, country=code, confidence=0.95,
                reason=f"foreign country code: '{code}'",
            )

    # 1. Explicit foreign COUNTRY in the location field wins unless a strong US
    #    signal is also present — this stops "Cambridge, United Kingdom" being
    #    mis-read as Cambridge, MA.
    if not strong_usa:
        for country in FOREIGN_COUNTRIES:
            if re.search(r"\b" + re.escape(country) + r"\b", loc):
                return LocationResult(
                    is_usa=False, country=country.title(), confidence=0.97,
                    reason=f"foreign country: '{country}'"
                )
        # Foreign CITY signals (Bangalore, Hsinchu, …) — also strong enough to
        # exclude on their own. Checked across loc+description as before.
        for signal in NON_USA_SIGNALS:
            if re.search(r"\b" + re.escape(signal) + r"\b", combined):
                return LocationResult(
                    is_usa=False, country=signal.title(), confidence=0.92,
                    reason=f"non-USA signal: '{signal}'"
                )

    # 2. Explicit USA strings
    for sig in USA_EXPLICIT:
        if sig in loc:
            result = LocationResult(is_usa=True, country="USA", confidence=0.95, reason=f"explicit USA: '{sig}'")
            _extract_state_city(loc, result)
            _check_remote(loc, result)
            return result

    # 3. US state abbreviations (word-boundary matched)
    for abbr in US_STATE_ABBREVIATIONS:
        # Match ", CA" or " CA " or "(CA)" or "CA " at start
        if re.search(r"(?:^|[\s,/(])(" + abbr + r")(?:[\s,/)$]|$)", loc, re.IGNORECASE):
            result = LocationResult(is_usa=True, country="USA", state=abbr, confidence=0.90, reason=f"US state abbr: {abbr}")
            _extract_city(loc, result)
            _check_remote(loc, result)
            return result

    # 4. US state full names
    for state_name, abbr in US_STATE_NAMES.items():
        if state_name in loc:
            result = LocationResult(is_usa=True, country="USA", state=abbr, confidence=0.88, reason=f"US state name: {state_name}")
            _extract_city(loc, result)
            _check_remote(loc, result)
            return result

    # 5. Known US city names
    for city_lower, state_abbr in US_CITIES:
        if city_lower in loc:
            result = LocationResult(
                is_usa=True, country="USA", state=state_abbr, city=city_lower.title(),
                confidence=0.85, reason=f"US city: {city_lower}"
            )
            _check_remote(loc, result)
            return result

    # 6. Remote signal without country — assume USA if company is US-based
    for sig in REMOTE_SIGNALS:
        if sig in loc or sig in desc_snippet:
            return LocationResult(
                is_usa=True, is_remote_usa=True, country="USA",
                confidence=0.65, reason="remote signal, assumed USA"
            )

    # 7. Unknown
    return LocationResult(confidence=0.0, reason="location unknown")


_ABBR_RE = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted(US_STATE_ABBREVIATIONS)) + r")(?![A-Za-z])",
    re.IGNORECASE,
)


def _has_usa_signal(loc: str) -> bool:
    """True only for an UNAMBIGUOUS US signal: explicit "United States", a full
    US state name, or a KNOWN US city paired with a state abbreviation
    ("Sunnyvale, CA"). A bare 2-letter abbreviation alone is NOT trusted —
    CA=Canada, IN=India, DE=Germany all collide — and a bare city name alone is
    NOT trusted either (Cambridge/London/Richmond collide with foreign cities).
    Only this strict signal lets a posting override an explicit foreign country,
    which is what keeps genuine multi-region US offices in while excluding UK/IN
    jobs that merely share a US city name."""
    if not loc:
        return False
    for sig in USA_EXPLICIT:
        if sig in loc:
            return True
    for state_name in US_STATE_NAMES:
        if re.search(r"\b" + re.escape(state_name) + r"\b", loc):
            return True
    # Known US city + a state abbreviation present somewhere = a real US office.
    if _ABBR_RE.search(loc):
        for city_lower, _ in US_CITIES:
            if city_lower in loc:
                return True
    return False


def _check_remote(loc: str, result: LocationResult) -> None:
    for sig in REMOTE_SIGNALS:
        if sig in loc:
            result.is_remote_usa = result.is_usa
            break


def _extract_state_city(loc: str, result: LocationResult) -> None:
    _extract_state(loc, result)
    _extract_city(loc, result)


def _extract_state(loc: str, result: LocationResult) -> None:
    if result.state:
        return
    for abbr in US_STATE_ABBREVIATIONS:
        if re.search(r"(?:^|[\s,/(])(" + abbr + r")(?:[\s,/)$]|$)", loc, re.IGNORECASE):
            result.state = abbr
            return
    for state_name, abbr in US_STATE_NAMES.items():
        if state_name in loc:
            result.state = abbr
            return


def _extract_city(loc: str, result: LocationResult) -> None:
    if result.city:
        return
    for city_lower, state_abbr in US_CITIES:
        if city_lower in loc:
            result.city = city_lower.title()
            if not result.state:
                result.state = state_abbr
            return
