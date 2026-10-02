"""Golden titles: hand-labelled postings the classifier must get right.

Every entry is a title of the shape real employers post (utilities, EPC firms,
OEMs, data-center operators, aerospace). A change to app/taxonomy.py has to keep
the whole set passing; add a case here whenever a real posting is misfiled.

``None`` means "must be rejected". Rejections matter as much as acceptances —
most of this list exists to keep false friends (Power BI, SOX controls, data
protection, electricians, chip design) off the board.
"""

import pytest

from backend.app import taxonomy as tx
from backend.app.taxonomy import (
    CONTROLS, DESIGN, EMC, ENERGY, INDUSTRIAL, INFRASTRUCTURE, INSTRUMENTATION, MACHINES,
    POWER, POWER_ELECTRONICS, RF, TRANSPORT,
)

GOLDEN: list[tuple[str, str | None]] = [
    # ── Power ────────────────────────────────────────────────────────────────
    ("Power Systems Engineer", POWER),
    ("Power Systems Engineer II", POWER),
    ("Senior Power Systems Engineer - Transmission Planning", POWER),
    ("Power Engineer", POWER),
    ("Transmission Engineer", POWER),
    ("Transmission Line Design Engineer", POWER),
    ("Engineer I - Transmission Planning", POWER),
    ("Distribution Engineer", POWER),
    ("Distribution Design Engineer - Underground", POWER),
    ("Distribution Planning Engineer III", POWER),
    ("Substation Engineer", POWER),
    ("Substation Physical Design Engineer", POWER),
    ("Electrical Engineer - Substation", POWER),
    ("Protection & Controls Engineer", POWER),
    ("Protection and Control Engineer II", POWER),
    ("P&C Engineer", POWER),
    ("Power System Protection Engineer", POWER),
    ("System Protection Engineer", POWER),
    ("Relay Settings Engineer", POWER),
    ("Grid Engineer", POWER),
    ("Grid Modernization Engineer", POWER),
    ("Power Planning Engineer", POWER),
    ("Power Quality Engineer", POWER),
    ("High Voltage Engineer", POWER),
    ("High-Voltage Test Engineer", POWER),
    ("HVDC Engineer", POWER),
    ("HVDC Systems Engineer", POWER),
    ("Utility Engineer", POWER),
    ("Electric Utility Engineer", POWER),
    ("Interconnection Engineer", POWER),
    ("NERC Compliance Engineer", POWER),
    ("Overhead Line Design Engineer", POWER),
    ("Short Circuit and Arc Flash Studies Engineer", POWER),
    ("EMS Engineer", POWER),
    ("ADMS Engineer", POWER),
    ("Metering Engineer", POWER),
    ("Medium Voltage Engineer", POWER),
    ("T&D Engineer", POWER),

    # ── Renewable energy ─────────────────────────────────────────────────────
    ("Renewable Energy Engineer", ENERGY),
    ("Solar Electrical Engineer", ENERGY),
    ("Solar PV Design Engineer", ENERGY),
    ("Photovoltaic Systems Engineer", ENERGY),
    ("Wind Electrical Engineer", ENERGY),
    ("Wind Turbine Electrical Engineer", ENERGY),
    ("Energy Systems Engineer", ENERGY),
    ("Grid Integration Engineer", ENERGY),
    ("Microgrid Engineer", ENERGY),
    ("Energy Storage Engineer", ENERGY),
    ("BESS Electrical Engineer", ENERGY),
    ("Battery Energy Storage Systems Engineer", ENERGY),
    ("EV Charging Infrastructure Engineer", ENERGY),
    ("Hydrogen Electrical Engineer", ENERGY),

    # ── Industrial ───────────────────────────────────────────────────────────
    ("Industrial Electrical Engineer", INDUSTRIAL),
    ("Plant Electrical Engineer", INDUSTRIAL),
    ("Electrical Maintenance Engineer", INDUSTRIAL),
    ("Electrical Reliability Engineer", INDUSTRIAL),
    ("Electrical Project Engineer", INDUSTRIAL),
    ("Project Engineer - Electrical", INDUSTRIAL),
    ("Electrical Field Engineer", INDUSTRIAL),
    ("Manufacturing Electrical Engineer", INDUSTRIAL),
    ("Mining Electrical Engineer", INDUSTRIAL),
    ("Water/Wastewater Electrical Engineer", INDUSTRIAL),

    # ── Controls ─────────────────────────────────────────────────────────────
    ("Controls Engineer", CONTROLS),
    ("Control Systems Engineer", CONTROLS),
    ("Automation Engineer", CONTROLS),
    ("Industrial Controls Engineer", CONTROLS),
    ("Process Controls Engineer", CONTROLS),
    ("PLC Engineer", CONTROLS),
    ("PLC Programmer", CONTROLS),
    ("SCADA Engineer", CONTROLS),
    ("DCS Engineer", CONTROLS),
    ("Senior Controls Engineer - Robotics", CONTROLS),
    ("Controls Software Engineer", CONTROLS),
    ("Electrical & Controls Engineer", CONTROLS),
    ("Building Automation Engineer", CONTROLS),
    ("Engineer, Controls", CONTROLS),

    # ── Instrumentation ──────────────────────────────────────────────────────
    ("Instrumentation & Controls Engineer", INSTRUMENTATION),
    ("I&C Engineer", INSTRUMENTATION),
    ("Instrumentation Engineer", INSTRUMENTATION),
    ("Electrical and Instrumentation Engineer", INSTRUMENTATION),
    ("Instrument and Controls Engineer", INSTRUMENTATION),

    # ── Electrical design ────────────────────────────────────────────────────
    ("Electrical Engineer", DESIGN),
    ("Electrical Engineer I", DESIGN),
    ("Senior Electrical Engineer", DESIGN),
    ("Electrical Design Engineer", DESIGN),
    ("Electrical Systems Engineer", DESIGN),
    ("Electrical Equipment Engineer", DESIGN),
    ("Electrical Hardware Engineer", DESIGN),
    ("Hardware Engineer - Board Design", DESIGN),
    ("Electronics Engineer", DESIGN),
    ("PCB Design Engineer", DESIGN),
    ("Electrical Test Engineer", DESIGN),
    ("Electrical Designer", DESIGN),
    ("Electrical Engineering Intern", DESIGN),
    ("Electrical Engineer in Training (EIT)", DESIGN),

    # ── Machines ─────────────────────────────────────────────────────────────
    ("Motor Engineer", MACHINES),
    ("Motor Design Engineer", MACHINES),
    ("Electrical Machines Engineer", MACHINES),
    ("Electric Machine Design Engineer", MACHINES),
    ("Generator Engineer", MACHINES),
    ("Generator Electrical Engineer", MACHINES),
    ("Transformer Design Engineer", MACHINES),

    # ── Power electronics ────────────────────────────────────────────────────
    ("Power Electronics Engineer", POWER_ELECTRONICS),
    ("Senior Power Electronics Engineer", POWER_ELECTRONICS),
    ("Power Conversion Engineer", POWER_ELECTRONICS),
    ("Inverter Engineer", POWER_ELECTRONICS),
    ("Inverter Hardware Engineer", POWER_ELECTRONICS),
    ("Power Supply Engineer", POWER_ELECTRONICS),
    ("Power Supply Design Engineer", POWER_ELECTRONICS),
    ("DC-DC Converter Design Engineer", POWER_ELECTRONICS),
    ("Motor Drives Engineer", POWER_ELECTRONICS),
    ("Magnetics Design Engineer", POWER_ELECTRONICS),

    # ── RF & communications ──────────────────────────────────────────────────
    ("RF Engineer", RF),
    ("RF Systems Engineer", RF),
    ("RF Design Engineer", RF),
    ("Microwave Engineer", RF),
    ("Antenna Engineer", RF),
    ("Antenna Design Engineer", RF),
    ("Electromagnetics Engineer", RF),
    ("Wireless Engineer", RF),
    ("Telecommunications Engineer", RF),
    ("Telecom Engineer - Utility Communications", POWER),  # utility wins (P&C/telecom at utilities)
    ("Radar Systems Engineer", RF),
    ("Phased Array Antenna Engineer", RF),

    # ── EMC ──────────────────────────────────────────────────────────────────
    ("EMC Engineer", EMC),
    ("EMI Engineer", EMC),
    ("EMC/EMI Test Engineer", EMC),
    ("Electromagnetic Compatibility Engineer", EMC),
    ("Signal Integrity Engineer", EMC),

    # ── Buildings & infrastructure ───────────────────────────────────────────
    ("Building Electrical Engineer", INFRASTRUCTURE),
    ("MEP Electrical Engineer", INFRASTRUCTURE),
    ("Electrical Infrastructure Engineer", INFRASTRUCTURE),
    ("Lighting Design Engineer", INFRASTRUCTURE),
    ("Data Center Electrical Engineer", INFRASTRUCTURE),
    ("Critical Facilities Engineer", INFRASTRUCTURE),
    ("Electrical Commissioning Engineer", INFRASTRUCTURE),
    ("Commissioning Engineer - Electrical", INFRASTRUCTURE),
    ("Mission Critical Electrical Engineer", INFRASTRUCTURE),

    # ── Transportation & aerospace ───────────────────────────────────────────
    ("Aerospace Electrical Engineer", TRANSPORT),
    ("Aircraft Electrical Engineer", TRANSPORT),
    ("Avionics Engineer", TRANSPORT),
    ("Spacecraft Electrical Engineer", TRANSPORT),
    ("Marine Electrical Engineer", TRANSPORT),
    ("Rail Electrical Engineer", TRANSPORT),
    ("Traction Power Engineer", TRANSPORT),
    ("EWIS Design Engineer", TRANSPORT),
    ("Vehicle Electrical Engineer", TRANSPORT),
    ("Wire Harness Electrical Engineer", TRANSPORT),
    ("Satellite Electrical Engineer", TRANSPORT),

    # ── Real titles from a live board (Hitachi Energy, 2026-10-01) ───────────
    ("High Voltage (HV) Test Engineer - Transformers", POWER),
    ("Protection & Control Commissioning Engineer", POWER),
    ("Senior Auxiliary Power Systems Engineer", POWER),
    ("FACTS Control Network and HMI/SCADA Engineer", POWER),
    ("FACTS Control Application Engineer", POWER),
    ("Field Service Engineer – Gas Insulated Switchgear (GIS)", POWER),
    ("Field Service Engineer – High Voltage (Hillsboro, OR)", POWER),
    ("Power Lead Engineer", POWER),
    ("Power Electronics Controls Research and Development Engineer", POWER_ELECTRONICS),
    ("Research Scientist - AI for Power Electronics", POWER_ELECTRONICS),
    ("Controls Design Engineer II", CONTROLS),
    ("Controls Project Engineer", CONTROLS),
    ("Controls Engineering Manager", CONTROLS),
    ("Automation Commissioning Engineer", CONTROLS),
    ("Senior Transformer Engineer", MACHINES),
    ("Electrical R&D Engineer - Transformers", MACHINES),
    ("Lead Electrical Engineer - Data Center", INFRASTRUCTURE),
    ("Electro-Mechanical Engineer", DESIGN),
    ("Project Engineer - Electromechanical", INDUSTRIAL),
    ("Senior Linux Systems Engineer", None),
    ("Customer System Security Engineer", None),
    ("Engineering Tools & Design Automation Engineer", None),
    ("R&D GMS Quality Assurance Engineer", None),
    ("Project Control Lead for FACTS and Power Electronics", None),
    ("Senior Developer EMS", None),
    ("Supplier Quality Engineer", None),
    ("Mechanical Project Engineer", None),

    # ── Real titles from live boards (verification pass, 2026-10-01) ─────────
    ("Sr Substation Engineer - BGE Trans & Sub", POWER),
    ("Sr Engineer - Relay and Protection Engineering", POWER),
    ("System Protection Engineer III", POWER),
    ("Field Engineer (Substation)", POWER),
    ("Staff Power Electronics Engineer", POWER_ELECTRONICS),
    ("Antenna Engineer - Parabolic & Waveguide", RF),
    ("Senior EMC & Radio Test Engineer", EMC),
    ("Avionics Automation Test Engineer II", TRANSPORT),
    ("Senior Instrumentation & Controls Engineer", INSTRUMENTATION),
    ("BESS Engineer", ENERGY),
    ("High Voltage Power Engineer", POWER),
    ("Early Career: Engineer II - Svcs RF", RF),
    ("Entry Level: Microwave Design Engineer", RF),
    ("Electrical Engineer/Designer III - Senior", DESIGN),
    ("AMS Verification Engineer (RFIC Engineering)", None),
    ("CPU Physical Electrical Analysis Engineer", None),
    ("Software Engineer (Test & Automation)", None),
    ("Service Automation Software Engineer", None),
    ("Machine Learning Automation Engineer", None),
    ("Data Center Security Engineer - WIDS", None),

    # ── False friends: an EE word, not an EE engineering job ─────────────────
    ("Power BI Developer", None),
    ("Power BI Engineer", None),
    ("Power Platform Engineer", None),
    ("PowerShell Automation Engineer", None),
    ("SOX Controls Analyst", None),
    ("Internal Controls Engineer", None),
    ("Project Controls Engineer", None),
    ("Quality Control Engineer", None),
    ("Document Controls Specialist", None),
    ("Data Protection Engineer", None),
    ("Fire Protection Engineer", None),
    ("Cathodic Protection Engineer", None),
    ("Distribution Center Engineer", None),
    ("Lighting Artist", None),
    ("Wireless Retail Consultant", None),
    ("Network Engineer", None),
    ("Grid Computing Engineer", None),
    ("Transmission Calibration Engineer", None),
    ("Financial Controller", None),

    # ── Trades and non-engineering ───────────────────────────────────────────
    ("Electrician", None),
    ("Journeyman Electrician", None),
    ("Lineman", None),
    ("Apprentice Lineworker", None),
    ("Substation Technician", None),
    ("Relay Technician", None),
    ("Electrical Technician", None),
    ("Field Service Technician", None),
    ("Electrical Drafter", None),
    ("Meter Reader", None),
    ("Electrical Sales Engineer", None),
    ("Account Manager - Power Systems", None),
    ("Project Manager - Substations", None),
    ("Power Systems Recruiter", None),
    ("System Operator", None),
    ("Distribution Planner", None),

    # ── Software and other disciplines ───────────────────────────────────────
    ("Software Engineer", None),
    ("Software Engineer - Grid Optimization", None),
    ("Embedded Software Engineer", None),
    ("Firmware Engineer", None),
    ("Data Engineer - Energy", None),
    ("Mechanical Engineer", None),
    ("Civil Engineer - Substations", None),
    ("Structural Engineer", None),
    ("HVAC Engineer", None),
    ("Manufacturing Engineer", None),
    ("Process Engineer", None),
    ("Cybersecurity Engineer - OT", None),

    # ── Chip design (Ashborne Silicon's territory) ───────────────────────────
    ("ASIC Design Verification Engineer", None),
    ("RTL Design Engineer", None),
    ("FPGA Engineer", None),
    ("Analog IC Design Engineer", None),
    ("Physical Design Engineer", None),
    ("Data Converter Design Engineer", None),
    ("PMIC Design Engineer", None),
    ("Silicon Validation Engineer", None),
]


@pytest.mark.parametrize("title,expected", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_golden_title(title, expected):
    v = tx.classify(title)
    if expected is None:
        assert not v.relevant, f"{title!r} accepted as {v.category} ({v.reason})"
    else:
        assert v.relevant, f"{title!r} rejected: {v.reason}"
        assert v.category == expected, f"{title!r} -> {v.category}, expected {expected} ({v.reason})"


# Discipline-free titles: rejected without a description, accepted with an EE one.
AMBIGUOUS = [
    "Project Engineer",
    "Field Engineer",
    "Engineer I",
    "Systems Engineer",
    "Design Engineer",
    "Reliability Engineer",
    "Commissioning Engineer",
]

EE_BODY = (
    "Prepare one-line diagrams, short circuit and arc flash studies for 34.5 kV "
    "switchgear and substation transformers. Coordinate protective relay settings "
    "per IEEE and NEC requirements."
)
NON_EE_BODY = (
    "Manage HVAC equipment, piping layouts and structural steel. Coordinate with "
    "the civil team on grading and drainage."
)


@pytest.mark.parametrize("title", AMBIGUOUS)
def test_ambiguous_title_needs_ee_description(title):
    assert not tx.classify(title).relevant
    assert not tx.classify(title, NON_EE_BODY).relevant
    v = tx.classify(title, EE_BODY)
    assert v.relevant, v.reason
    assert v.category == POWER or title == "Commissioning Engineer"


def test_generic_electrical_title_categorised_from_body():
    v = tx.classify("Electrical Engineer II", EE_BODY)
    assert v.relevant and v.category == POWER
    plc_body = "Program Allen-Bradley PLC and HMI screens in Studio 5000; SCADA integration."
    assert tx.classify("Electrical Engineer", plc_body).category == CONTROLS


def test_description_never_rescues_an_excluded_title():
    for title in ("Electrician", "Power BI Developer", "Software Engineer", "RTL Design Engineer"):
        assert not tx.classify(title, EE_BODY).relevant, title


def test_requirement_tags():
    body = ("PE license required within 2 years. Must be able to obtain a security clearance. "
            "Travel up to 25%. Participate in storm restoration and on-call rotation. NERC CIP.")
    assert tx.requirement_tags(body) == ["PE license", "NERC", "Clearance", "Travel", "On-call / storm duty"]
    assert tx.requirement_tags("EIT certification preferred") == ["EIT / FE"]
    assert tx.requirement_tags("") == []


def test_golden_set_covers_every_category():
    covered = {cat for _t, cat in GOLDEN if cat}
    assert covered == set(tx.CATEGORIES)
