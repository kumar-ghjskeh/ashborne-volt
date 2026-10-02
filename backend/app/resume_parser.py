"""Résumé parsing for electrical engineers.

Extracts text from PDF / DOCX / TXT / TeX and turns it into a structured
profile (standards, studies, software tools, protocols, equipment & domains,
programming languages, projects, education, experience, role focus) using a
deterministic EE dictionary — no third-party AI; the résumé never leaves this
backend, which keeps nothing.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict

# ── EE skill dictionaries (canonical -> match patterns) ───────────────────────
# Patterns are matched case-insensitively against lowercased text.

STANDARDS = {
    "NEC / NFPA 70": [r"\bnec\b", r"national electrical code", r"nfpa\s?70\b(?!e)"],
    "NFPA 70E": [r"nfpa\s?70e", r"arc[\s-]flash safety"],
    "NFPA 72": [r"nfpa\s?72\b"],
    "IEEE 1547": [r"ieee\s?1547"],
    "IEEE 519": [r"ieee\s?519"],
    "IEEE 1584": [r"ieee\s?1584"],
    "IEEE C37": [r"ieee\s?c37", r"\bc37\.\d+"],
    "IEEE 80": [r"ieee\s?(std\s?)?80\b"],
    "IEEE Color Books": [r"ieee\s?(141|142|242|399|493)\b", r"(red|green|buff|gold|brown) book"],
    "IEC 61850": [r"iec\s?61850"],
    "IEC 61131-3": [r"iec\s?61131"],
    "IEC 61511 / SIS": [r"iec\s?61511", r"\bsil\s?[1-4]\b", r"safety instrumented"],
    "IEC 61000 / CISPR": [r"iec\s?61000", r"\bcispr\b"],
    "FCC Part 15": [r"fcc part 15", r"\bfcc\b"],
    "MIL-STD-461": [r"mil[\s-]?std[\s-]?461"],
    "MIL-STD-704": [r"mil[\s-]?std[\s-]?704"],
    "DO-160": [r"\bdo[\s-]?160\b"],
    "DO-254": [r"\bdo[\s-]?254\b"],
    "NERC CIP": [r"nerc\s?cip", r"\bcip-\d"],
    "NERC Reliability Standards": [r"\bnerc\b", r"\bprc-\d", r"\btpl-\d", r"\bmod-\d"],
    "UL 508A": [r"ul\s?508a?"],
    "UL 1741": [r"ul\s?1741"],
    "UL 9540": [r"ul\s?9540"],
    "NEMA": [r"\bnema\b"],
    "ANSI C84.1": [r"c84\.1"],
    "ISA-5.1 / ISA-88 / ISA-95": [r"\bisa[\s-]?(5\.1|88|95|18\.2)\b"],
    "ISO 26262": [r"iso\s?26262"],
    "TIA-942": [r"tia[\s-]?942"],
    "OSHA": [r"\bosha\b"],
}

STUDIES = {
    "Load Flow": [r"load[\s-]?flow", r"power[\s-]?flow"],
    "Short Circuit Analysis": [r"short[\s-]?circuit"],
    "Arc Flash Analysis": [r"arc[\s-]?flash"],
    "Protective Device Coordination": [r"(protective device )?coordination stud", r"\btcc\b", r"selective coordination"],
    "Relay Settings": [r"relay settings?", r"setting calculations?", r"protective relay"],
    "Transient Stability": [r"transient stability", r"dynamic stability", r"\bstability stud"],
    "Harmonic Analysis": [r"harmonic"],
    "Motor Starting": [r"motor starting"],
    "Grounding Design": [r"grounding", r"earthing", r"ground grid"],
    "Cable Sizing / Ampacity": [r"ampacity", r"cable sizing", r"conductor sizing"],
    "Voltage Drop": [r"voltage drop"],
    "Lightning Protection": [r"lightning protection", r"\bsurge\b"],
    "Interconnection Studies": [r"interconnection stud", r"system impact stud", r"facilities stud"],
    "Hosting Capacity": [r"hosting capacity"],
    "Transmission Planning": [r"transmission planning"],
    "Distribution Planning": [r"distribution planning"],
    "Power Quality": [r"power quality"],
    "Reliability / RCM": [r"reliability[\s-]centered", r"\brcm\b", r"\bfmea\b", r"\bmtbf\b"],
    "Root Cause Analysis": [r"root cause", r"\brca\b"],
    "Commissioning": [r"commissioning", r"\bfat\b", r"\bsat\b", r"start[\s-]?up"],
    "Loop Checks": [r"loop check"],
    "Load Calculations": [r"load calc"],
    "Lighting Calculations": [r"lighting calc", r"photometric"],
    "Single-Line Diagrams": [r"one[\s-]line", r"single[\s-]line"],
    "Schematics & Wiring Diagrams": [r"schematic", r"wiring diagram", r"three[\s-]line", r"\belementary diagram"],
    "Panel Design": [r"panel design", r"control panel", r"panel layout"],
    "PLC Programming": [r"plc programming", r"ladder logic", r"\bplc\b"],
    "HMI Development": [r"\bhmi\b"],
    "Control Loop Tuning": [r"\bpid\b", r"loop tuning", r"control loop"],
    "Signal Integrity": [r"signal integrity", r"\bsi/pi\b"],
    "Link Budget": [r"link budget"],
    "EMC Testing": [r"emc test", r"radiated emissions", r"conducted emissions", r"pre[\s-]?compliance"],
    "Converter Design": [r"converter design", r"(buck|boost|flyback|llc|dab)\b"],
    "Magnetics Design": [r"magnetics design", r"transformer design", r"inductor design"],
    "Motor Design": [r"motor design", r"machine design"],
    "EM / FEA Simulation": [r"\bfea\b", r"finite element", r"electromagnetic simulation"],
    "Battery Management": [r"battery management", r"\bbms\b"],
    "Grid-Forming Controls": [r"grid[\s-]forming", r"grid[\s-]following"],
    "Circuit Design": [r"circuit design", r"analog design"],
    "PCB Layout": [r"pcb layout", r"board layout"],
    "Hardware Testing": [r"oscilloscope", r"bench test", r"hardware test", r"\bdvt\b", r"\bevt\b"],
}

TOOLS = {
    "ETAP": [r"\betap\b"], "SKM PowerTools": [r"\bskm\b"], "EasyPower": [r"easy\s?power"],
    "PSS/E": [r"pss/?e\b", r"\bpsse\b"], "PSCAD": [r"\bpscad\b"], "PowerWorld": [r"power\s?world"],
    "PSLF": [r"\bpslf\b"], "CYME": [r"\bcyme\b"], "Synergi Electric": [r"\bsynergi\b"],
    "PowerFactory": [r"power\s?factory", r"digsilent"], "Aspen OneLiner": [r"aspen", r"oneliner"],
    "CAPE": [r"\bcape\b"], "RTDS / RSCAD": [r"\brtds\b", r"\brscad\b"], "WindMil": [r"windmil"],
    "AutoCAD": [r"\bautocad\b"], "AutoCAD Electrical": [r"autocad electrical", r"acade"],
    "Revit": [r"\brevit\b"], "MicroStation": [r"microstation"], "EPLAN": [r"\beplan\b"],
    "SolidWorks Electrical": [r"solidworks electrical"], "PLS-CADD": [r"pls[\s-]?cadd"],
    "Bentley Substation": [r"bentley substation"],
    "Studio 5000 / RSLogix": [r"studio\s?5000", r"rslogix", r"logix\s?5000", r"allen[\s-]bradley"],
    "TIA Portal / STEP 7": [r"tia portal", r"step\s?7", r"siemens s7", r"\bs7-1[25]00"],
    "Ignition": [r"\bignition\b"], "AVEVA / Wonderware": [r"wonderware", r"\baveva\b", r"intouch"],
    "FactoryTalk": [r"factorytalk"], "DeltaV": [r"deltav"], "Experion": [r"experion"],
    "Ovation": [r"\bovation\b"], "CODESYS": [r"codesys"], "OSIsoft PI": [r"osisoft", r"\bpi system\b", r"pi historian"],
    "Altium Designer": [r"\baltium\b"], "OrCAD": [r"\borcad\b"], "Cadence Allegro": [r"\ballegro\b"],
    "KiCad": [r"\bkicad\b"], "LTspice": [r"lt\s?spice"], "PSpice / SPICE": [r"\bp?spice\b"],
    "PLECS": [r"\bplecs\b"], "PSIM": [r"\bpsim\b"], "Simulink": [r"\bsimulink\b"],
    "ANSYS Maxwell": [r"\bmaxwell\b"], "ANSYS HFSS": [r"\bhfss\b"], "CST Studio": [r"\bcst\b"],
    "Keysight ADS": [r"\bads\b", r"advanced design system"], "AWR Microwave Office": [r"microwave office", r"\bawr\b"],
    "COMSOL": [r"\bcomsol\b"], "SEL AcSELerator": [r"acselerator", r"\bsel[\s-]?\d{3}"],
    "Omicron / Doble Test Sets": [r"\bomicron\b", r"\bdoble\b"], "Megger": [r"\bmegger\b"],
    "Oscilloscopes & Analyzers": [r"oscilloscope", r"spectrum analy[sz]er", r"\bvna\b", r"network analy[sz]er"],
    "PVsyst": [r"\bpvsyst\b"], "HOMER": [r"\bhomer\b"], "Helioscope": [r"helioscope"],
    "AGi32 / DIALux": [r"\bagi32\b", r"\bdialux\b"], "ArcGIS": [r"arcgis", r"\besri\b"],
    "Maximo / SAP PM": [r"\bmaximo\b", r"sap pm"],
}

PROTOCOLS = {
    "DNP3": [r"\bdnp\s?3\b"], "Modbus": [r"\bmodbus\b"],
    "IEC 61850 GOOSE/MMS": [r"\bgoose\b", r"\bmms\b"], "IEC 60870-5-104": [r"60870"],
    "OPC UA": [r"\bopc\b"], "Profibus / Profinet": [r"profibus", r"profinet"],
    "EtherNet/IP": [r"ethernet/ip"], "DeviceNet": [r"devicenet"], "HART": [r"\bhart\b"],
    "Foundation Fieldbus": [r"fieldbus"], "BACnet": [r"\bbacnet\b"], "RS-485 / RS-232": [r"rs[\s-]?(485|232)"],
    "CAN": [r"\bcan\s?bus\b", r"\bcan[\s-]fd\b", r"\bj1939\b"], "ARINC 429": [r"arinc"],
    "MIL-STD-1553": [r"1553"], "SpaceWire": [r"spacewire"],
    "LTE / 5G": [r"\blte\b", r"\b5g\b", r"\b4g\b"], "Wi-Fi / Bluetooth": [r"wi[\s-]?fi", r"802\.11", r"bluetooth"],
    "LoRa / Zigbee": [r"\blora\b", r"zigbee"], "GNSS / GPS": [r"\bgnss\b", r"\bgps\b"],
    "Fiber Optics": [r"fiber optic", r"fibre optic"], "SONET / Telecom Transport": [r"\bsonet\b", r"\bmpls\b"],
}

CONCEPTS = {
    "Substation Design": [r"substation"], "Transmission Lines": [r"transmission line", r"overhead line"],
    "Distribution Systems": [r"distribution (system|line|network|feeder)", r"\bfeeder"],
    "Protective Relaying": [r"protective relay", r"relaying", r"protection and control", r"\bp&c\b"],
    "Transformers": [r"transformer"], "Switchgear": [r"switchgear", r"switchboard"],
    "Circuit Breakers": [r"circuit breaker"], "Motor Control Centers": [r"\bmcc\b", r"motor control center"],
    "VFDs / Drives": [r"\bvfd\b", r"variable frequency", r"motor drive"], "UPS": [r"\bups\b", r"uninterruptible"],
    "Generators": [r"generator"], "Electric Motors": [r"\bmotors?\b"],
    "Battery Energy Storage": [r"energy storage", r"\bbess\b", r"lithium[\s-]ion"],
    "Solar PV": [r"\bsolar\b", r"photovoltaic", r"\bpv\b"], "Wind Energy": [r"\bwind\b"],
    "Microgrids": [r"microgrid"], "Inverters": [r"inverter"], "DC-DC Converters": [r"dc[\s/-]?dc", r"\bconverter"],
    "Power Electronics": [r"power electronics"], "Gate Drivers": [r"gate driver"],
    "Wide Bandgap (SiC/GaN)": [r"\bsic\b", r"\bgan\b", r"wide[\s-]bandgap"],
    "SCADA": [r"\bscada\b"], "DCS": [r"\bdcs\b"], "Instrumentation": [r"instrumentation", r"transmitters?\b"],
    "P&IDs": [r"p&id"], "Lighting Design": [r"lighting design", r"luminaire"], "Fire Alarm": [r"fire alarm"],
    "Data Centers": [r"data cent(er|re)"], "Medium Voltage": [r"medium[\s-]voltage", r"\bmv\b"],
    "High Voltage": [r"high[\s-]voltage", r"\bhv\b", r"\behv\b"], "HVDC": [r"\bhvdc\b"],
    "EMC / EMI": [r"\bemc\b", r"\bemi\b"], "RF Design": [r"\brf\b", r"radio frequency"],
    "Antennas": [r"antenna"], "Microwave": [r"microwave", r"mmwave", r"millimeter"], "Radar": [r"\bradar\b"],
    "PCB Design": [r"\bpcb\b"], "Analog Circuits": [r"analog circuit", r"op[\s-]?amp"],
    "Embedded Systems": [r"embedded", r"microcontroller", r"\bmcu\b", r"arduino", r"\bstm32\b"],
    "Avionics": [r"avionics"], "Wire Harness": [r"harness"], "Traction Power": [r"traction power", r"catenary"],
    "EV Charging": [r"ev charg", r"charging station", r"\bevse\b"], "Electric Vehicles": [r"electric vehicle", r"\bev\b"],
    "Three-Phase Power": [r"three[\s-]phase", r"3[\s-]phase"], "Power Systems": [r"power system"],
}

LANGUAGES = {
    "Python": [r"\bpython\b"], "MATLAB": [r"\bmatlab\b"], "C": [r"\bc\b(?!\+|#)"], "C++": [r"\bc\+\+"],
    "LabVIEW": [r"labview"], "VBA / Excel Macros": [r"\bvba\b", r"excel macro"],
    "Ladder Logic": [r"ladder logic", r"\bladder\b"], "Structured Text": [r"structured text"],
    "Function Block Diagram": [r"function block"], "SQL": [r"\bsql\b"], "Verilog / VHDL": [r"verilog", r"\bvhdl\b"],
}

# Project-area signal terms (used to match résumé projects to jobs)
PROJECT_SIGNALS = {
    "Substation": [r"substation"], "Solar": [r"\bsolar\b", r"photovoltaic", r"\bpv\b"],
    "Battery": [r"battery", r"\bbms\b"], "Inverter": [r"inverter"], "Converter": [r"converter", r"\bbuck\b", r"\bboost\b"],
    "Motor": [r"\bmotor"], "PLC": [r"\bplc\b", r"ladder"], "Microgrid": [r"microgrid"], "Antenna": [r"antenna"],
    "Relay": [r"\brelay"], "Transformer": [r"transformer"], "Power Flow": [r"power[\s-]?flow", r"load[\s-]?flow"],
    "EV": [r"electric vehicle", r"\bev\b", r"charging"], "Robot / Drone": [r"robot", r"\bdrone\b", r"\buav\b"],
    "PCB": [r"\bpcb\b", r"circuit board"], "RF": [r"\brf\b", r"radio"], "Lighting": [r"lighting"],
    "Wind": [r"\bwind\b"], "Grid": [r"\bgrid\b"], "SCADA": [r"\bscada\b"],
}

_ALL_DICTS = {
    "standards": STANDARDS, "studies": STUDIES, "tools": TOOLS,
    "protocols": PROTOCOLS, "concepts": CONCEPTS, "languages": LANGUAGES,
}


@dataclass
class ResumeProfileData:
    name: str = ""
    education: str = ""
    degree: str = ""
    grad_date: str = ""
    years_experience: float = 0.0
    role_focus: str = ""
    standards: list[str] = field(default_factory=list)
    studies: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    protocols: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    licenses: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    project_signals: list[str] = field(default_factory=list)
    all_skills: list[str] = field(default_factory=list)
    raw_text_len: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text(data: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _pdf_text(data)
    if name.endswith(".docx"):
        return _docx_text(data)
    # txt, tex, md, or unknown → decode as text
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return data.decode("latin-1", errors="ignore")


def _pdf_text(data: bytes) -> str:
    import fitz  # PyMuPDF
    text_parts = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text_parts.append(page.get_text())
    return "\n".join(text_parts)


def _docx_text(data: bytes) -> str:
    import docx
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


# ── Parsing ──────────────────────────────────────────────────────────────────

def _match_dict(text_l: str, d: dict[str, list[str]]) -> list[str]:
    found = []
    for canonical, pats in d.items():
        if any(re.search(p, text_l) for p in pats):
            found.append(canonical)
    return found


def _extract_education(text: str) -> tuple[str, str, str]:
    t = text.lower()
    degree = ""
    if re.search(r"\bph\.?d\.?\b|doctorate", t):
        degree = "PhD"
    elif re.search(r"\b(m\.?s\.?|master)\b", t):
        degree = "MS"
    elif re.search(r"\b(b\.?s\.?|bachelor|b\.?tech|b\.?e\.?)\b", t):
        degree = "BS"
    field_m = re.search(r"\b(electrical(?:\s+and\s+computer)?\s+engineering|computer engineering|ece|eece|power engineering|electronics engineering|electronics|mechatronics)\b", t)
    fld = field_m.group(1).upper() if field_m else ""
    grad_m = re.search(r"(?:expected|graduat\w*|class of)?\s*((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+)?(20[2-3]\d)", t)
    grad = ""
    if grad_m:
        grad = (grad_m.group(1) or "").strip().title() + " " + grad_m.group(2)
        grad = grad.strip()
    edu = " ".join(x for x in [degree, fld] if x).strip()
    return edu, degree, grad


def _extract_years(text: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years?\s+(?:of\s+)?experience", text.lower())
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return 0.0
    return 0.0


def _extract_projects(text: str) -> list[str]:
    """Pull lines from a Projects section (best-effort)."""
    lines = text.splitlines()
    projects: list[str] = []
    in_section = False
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        if re.match(r"^(academic |technical |key |relevant )?projects?\b[:\s]*$", low) or low in ("projects", "project experience"):
            in_section = True
            continue
        if in_section:
            # stop at next major section header
            if re.match(r"^(experience|work experience|education|skills|certifications|publications|awards|employment)\b", low):
                break
            if len(s) >= 6 and not s.isupper():
                # title-ish line (often "Project Name — desc" or a bullet)
                clean = re.sub(r"^[•\-\*•●▪]+\s*", "", s)
                if clean and len(clean) <= 160:
                    projects.append(clean)
            if len(projects) >= 12:
                break
    return projects[:12]


def _infer_role_focus(text_l: str) -> str:
    """The EE category this résumé reads most like, using the same vocabulary the
    job classifier uses to categorise a posting — so "focus matches category" is
    comparing like with like."""
    from .taxonomy import DESCRIPTION_CATEGORY_TERMS

    padded = f" {text_l} "
    scores = {cat: sum(1 for term in terms if term in padded)
              for cat, terms in DESCRIPTION_CATEGORY_TERMS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "Electrical Engineering (general)"


_LICENSES = {
    "PE": [r"\bp\.?e\.?\b(?=[^a-z]|$)", r"professional engineer"],
    "EIT / FE": [r"\beit\b", r"engineer[\s-]in[\s-]training", r"\bfe exam\b", r"fundamentals of engineering"],
    "Security Clearance": [r"(secret|ts/sci|top secret) clearance", r"active clearance"],
    "OSHA 10/30": [r"osha[\s-]?(10|30)"],
}


def parse_resume(data: bytes, filename: str) -> ResumeProfileData:
    text = extract_text(data, filename)
    t = text.lower()
    p = ResumeProfileData(raw_text_len=len(text))

    p.standards = _match_dict(t, STANDARDS)
    p.studies = _match_dict(t, STUDIES)
    p.licenses = _match_dict(t, _LICENSES)
    p.tools = _match_dict(t, TOOLS)
    p.protocols = _match_dict(t, PROTOCOLS)
    p.concepts = _match_dict(t, CONCEPTS)
    p.languages = _match_dict(t, LANGUAGES)
    p.project_signals = _match_dict(t, PROJECT_SIGNALS)
    p.projects = _extract_projects(text)
    p.education, p.degree, p.grad_date = _extract_education(text)
    p.years_experience = _extract_years(text)

    # name = first non-empty line that looks like a name (heuristic)
    for ln in text.splitlines():
        s = ln.strip()
        if 3 <= len(s) <= 40 and re.match(r"^[A-Za-z.\s'-]+$", s) and len(s.split()) <= 4:
            p.name = s
            break

    p.all_skills = sorted(set(
        p.standards + p.studies + p.tools + p.protocols + p.concepts + p.languages
    ))
    p.role_focus = _infer_role_focus(t)
    return p
