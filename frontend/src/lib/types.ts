export interface Job {
  id: number
  /** Stable content fingerprint (company+title+location+source id). Survives a
   *  corpus rebuild, unlike `id`, so browser-held marks stay attached. */
  key?: string
  company: string
  company_category: string
  company_priority: string

  job_title: string
  normalized_title: string
  role_category: string
  experience_level: string

  is_entry_level: boolean
  is_candidate_friendly: boolean
  is_senior: boolean
  years_required_min: number | null
  years_required_max: number | null

  location: string
  location_raw: string
  display_location?: string
  remote_status: string
  is_usa: boolean
  is_remote_usa: boolean
  country: string
  state: string
  city: string
  location_confidence: number

  job_id_from_company: string
  apply_url: string
  safe_apply_url: string
  original_apply_url: string
  apply_url_status: string
  apply_url_reason: string
  source_url: string
  ats_platform: string

  posted_date: string | null
  first_seen_at: string
  last_seen_at: string
  removed_at: string | null

  active_status: string
  missed_scrapes: number

  match_score: number
  new_grad_fit: number
  experienced_fit: number
  new_grad_fit_label: string
  overall_recommendation: string
  matched_keywords: string
  /** Comma-separated skills extracted at scrape time; the primary skill source. */
  job_skills?: string
  score_breakdown_json: string
  relevance_score_label: string

  description_snippet: string
  full_description_text: string
  cleaned_description: string

  application_status: string
  notes: string
  resume_version_used: string
  follow_up_date?: string
  confirmation_id?: string
  recruiter_contact?: string
  saved_at: string | null
  applied_at: string | null
  ignored_at: string | null

  // Enrichment fields
  role_flags_json: string
  is_software_only: boolean
  is_hardware_software_codesign: boolean
  relevance_reason: string
  exclusion_reason: string
  matched_positive_terms_json: string
  data_quality_status: string

  // Eligibility & sponsorship (Phase 1)
  eligibility_risk?: string        // 'low' | 'medium' | 'high'
  eligibility_terms?: string       // matched terms, comma-separated
  /** Gating requirements: PE license, EIT / FE, NERC, Clearance, Travel, On-call / storm duty. */
  requirement_tags?: string
  /** Rows sharing this render as one card (same opening at several sites / reposts). */
  dup_group?: string
  sponsors_h1b?: boolean | null    // company-level H1B sponsorship signal

  // Classification confidence & data quality (Phase 2)
  seniority_confidence?: number
  classification_confidence?: number
  data_quality_score?: number
  source_reliability?: string      // 'High' | 'Medium' | 'Low'
  location_label?: string          // Onsite | Hybrid | Remote - USA | Multi-location USA | …
  posted_date_known?: boolean
  /** How many open requisitions this card stands for (1 = just itself). Set by
   *  the server when role grouping is on, so "+N locations" is accurate across
   *  the whole result set rather than only the current page. */
  group_count?: number

  // Resume match summary (Phase 3 — present on Resume Matches tab items)
  resume_match?: number
  defensibility?: number
  apply_priority?: string          // High | Medium | Low
  matched_skills?: string[]
  missing_skills?: string[]
}

export interface ResumeProfile {
  name: string
  education: string
  degree: string
  grad_date: string
  years_experience: number
  role_focus: string
  standards: string[]
  studies: string[]
  tools: string[]
  protocols: string[]
  concepts: string[]
  languages: string[]
  licenses?: string[]
  projects: string[]
  project_signals: string[]
  all_skills: string[]
}

export interface TailoringSuggestion {
  skill: string
  tier: 'Safe to Add' | 'Reword Only' | 'Learn First' | 'Do Not Add'
  rationale: string
}

export interface MatchBreakdown {
  skills: number
  experience: number
  projects: number
  domain: number
  tool_protocol?: number
}

export interface JobMatch {
  resume_match: number
  new_grad_fit?: number
  experienced_fit?: number
  overall_recommendation?: string
  match_breakdown?: MatchBreakdown
  defensibility: number
  apply_priority: string
  matched_skills: string[]
  missing_skills: string[]
  matched_projects: string[]
  matched_projects_detail?: { title: string; backs: string[] }[]
  recommended_resume: string
  why_matches: string[]
  tailoring_suggestions: TailoringSuggestion[]
  interview_prep: {
    rounds?: { name: string; what: string }[]
    company_focus?: string
    technical_topics: string[]
    resume_defense: string[]
  }
}

export interface SkillGap { skill: string; count: number }

export interface ResumeVersion {
  id: number
  label: string
  filename: string
  is_active: boolean
  uploaded_at: string
  role_focus: string
  skill_count: number
}

export interface Watchlist {
  id: number
  name: string
  filters: Filters
  alert_enabled: boolean
  last_checked_at: string
  total: number
  new_count: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total_count: number
  page: number
  limit: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

export interface Company {
  sector?: string
  hq?: string
  unique_jobs?: number
  id: number
  name: string
  category: string
  priority: string
  careers_url: string
  company_search_url: string
  ats_platform: string
  enabled: boolean
  last_scraped_at: string | null
  scrape_error_count: number
  /** Consecutive runs that succeeded but returned nothing — the silent failure. */
  consecutive_empty_scrapes?: number
  /** Auto-skipped after too many consecutive hard failures. */
  quarantined?: boolean
  notes: string
  total_active_jobs?: number
  relevant_active_jobs?: number
  viewable_jobs?: number
  usa_active_jobs?: number
  entry_level_jobs?: number
  new_jobs_today?: number
  scrape_status?: string
  parser_confidence?: number
  engine?: string
  auto_connected?: boolean
}

export interface JobFacets {
  role_categories: { value: string; count: number }[]
  priorities: { value: string; count: number }[]
  remote_statuses: { value: string; count: number }[]
  states: { value: string; count: number }[]
  entry_level_count: number
  candidate_friendly_count: number
  senior_count: number
  remote_count: number
  new_24h_count: number
}

export interface ScrapeRun {
  id: number
  started_at: string
  finished_at: string | null
  companies_scraped: number
  jobs_found: number
  new_jobs: number
  removed_jobs: number
  errors: number
  triggered_by: string
}

export interface AnalyticsSummary {
  total_active: number
  new_24h: number
  entry_level_count: number
  usa_count: number
  remote_count: number
  high_score_count: number
  strong_new_grad_count?: number
  saved_count: number
  applied_count: number
  total_companies: number
  strict_entry_count?: number
  candidate_friendly_count?: number
  job_inventory?: JobInventory
  last_run: ScrapeRun | null
}

export interface JobInventory {
  scanned_last_run: number | null
  total_in_db: number
  active: number
  usa_relevant: number
  non_usa_filtered: number
  software_filtered: number
  senior_roles: number
}

/** Per-engine verdict on whether scraping is actually happening. Exists so a
 *  dead pipeline is visible in the app instead of only in a workflow email. */
export interface PipelineEngine {
  engine: string
  cadence_hours: number
  status: 'ok' | 'stale' | 'down'
  hours_since_last_good_run: number | null
  last_good_run_at: string | null
  companies_scraped: number
  new_jobs: number
}

export interface PipelineHealth {
  status: 'ok' | 'stale' | 'down'
  engines: PipelineEngine[]
  last_job_seen_at: string | null
  hours_since_any_job_seen: number | null
}

/** One autocomplete row: what to search for, what kind of thing it is, and how
 *  many jobs it would return (so a dead end is visible before pressing Enter). */
export interface SearchSuggestion {
  value: string
  type: 'company' | 'title' | 'skill'
  count: number
}

export interface Filters {
  status?: string
  company?: string
  priority?: string
  role_category?: string
  experience_level?: string
  remote?: string
  min_score?: number
  new_since_hours?: number
  posted_within_hours?: number
  keyword?: string
  usa_only?: boolean
  include_senior?: boolean
  include_software?: boolean
  include_adjacent?: boolean
  view?: string
  role_flags?: string
  is_entry_level?: boolean
  state?: string
  level_filter?: string
  h1b_only?: boolean
  sort_by?: string
  skills?: string
  /** Collapse same company+role into one card (default true). */
  group_roles?: boolean
  sort_order?: string
}
