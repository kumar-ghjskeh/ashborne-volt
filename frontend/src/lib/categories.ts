/**
 * EE job categories — mirrors backend/app/taxonomy.py, which is the authority.
 * backend/tests/test_category_sync.py fails the build if the two drift.
 */

export const CATEGORIES = [
  'Power Systems',
  'Renewable Energy',
  'Industrial & Plant',
  'Controls & Automation',
  'Instrumentation',
  'Electrical Design',
  'Electrical Machines',
  'Power Electronics',
  'RF & Communications',
  'EMC / EMI',
  'Buildings & Infrastructure',
  'Transportation & Aerospace',
] as const

/** Hidden from the default view (opt in with "Show other EE"). */
export const HIDDEN_CATEGORIES = new Set<string>([
  'Other EE',
  'Out of Scope',
  'Unknown',
  'Software / Compiler',
])

export const CATEGORY_BLURBS: Record<string, string> = {
  'Power Systems': 'Transmission, distribution, substations, protection & controls, grid planning, power quality, HV/HVDC, utilities',
  'Renewable Energy': 'Solar, wind, energy storage, microgrids, grid integration and interconnection, EV charging',
  'Industrial & Plant': 'Plant, maintenance, reliability, field and electrical project engineering',
  'Controls & Automation': 'Controls, PLC, SCADA, DCS, process and industrial automation',
  'Instrumentation': 'Instrumentation & controls (I&C), measurement, metering systems',
  'Electrical Design': 'Electrical design, systems and equipment, hardware and board-level design',
  'Electrical Machines': 'Motors, generators and rotating electrical machines, transformers',
  'Power Electronics': 'Power electronics, converters, inverters, power supplies, drives',
  'RF & Communications': 'RF, microwave, antennas, electromagnetics, wireless and telecom engineering',
  'EMC / EMI': 'EMC / EMI design, test and compliance',
  'Buildings & Infrastructure': 'Building/MEP electrical, data centers, critical facilities, lighting, commissioning',
  'Transportation & Aerospace': 'Aerospace, aircraft, avionics, spacecraft, marine, rail, traction power, automotive/EV',
}

/** Quick keyword chips in the filter sidebar. */
export const QUICK_KEYWORDS = [
  'substation', 'protection', 'relay', 'SCADA', 'PLC',
  'ETAP', 'PSS/E', 'NEC', 'arc flash', 'solar',
  'battery', 'inverter', 'transformer', 'RF', 'data center',
]

/** Gating requirements surfaced as badges (backend taxonomy.REQUIREMENT_TAGS). */
export const REQUIREMENT_TAGS = ['PE license', 'EIT / FE', 'NERC', 'Clearance', 'Travel', 'On-call / storm duty'] as const

/** Company sectors used on the Companies page. */
export const SECTORS = [
  'Utility',
  'Grid & Power OEM',
  'Industrial & Automation',
  'EPC & Consulting',
  'Renewables & Storage',
  'Data Centers & Facilities',
  'Aerospace & Defense',
  'Automotive & EV',
  'Rail & Transit',
  'RF & Communications',
  'Electronics & Semiconductors',
] as const
