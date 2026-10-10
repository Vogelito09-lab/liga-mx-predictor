export interface Team { id: number; name: string; abbreviation: string | null; logo_url: string | null }
export interface ScoreProb { home: number; away: number; p: number }
export interface Factor { key: string; text: string }

export interface Prediction {
  id: number; match_id: number; generated_at: string; data_cutoff: string; model_version: string
  p_home: number; p_draw: number; p_away: number
  most_likely_outcome: 'local' | 'empate' | 'visitante'
  exp_home_goals: number | null; exp_away_goals: number | null
  top_score_home: number | null; top_score_away: number | null; top_score_prob: number | null
  top_scores: ScoreProb[] | null; uncertainty: 'baja' | 'media' | 'alta'; entropy: number
  factors: Factor[] | null; is_pre_kickoff_final: boolean
}

export type MatchStatus = 'scheduled' | 'in_progress' | 'finished' | 'postponed' | 'suspended' | 'canceled'

export interface Match {
  id: number; espn_id: string; season: string; tournament: string; stage: string; stage_detail: string | null
  round: number | null; kickoff_utc: string; status: MatchStatus; status_detail: string | null
  live_clock: string | null; home: Team; away: Team
  home_goals: number | null; away_goals: number | null
  home_goals_final: number | null; away_goals_final: number | null
  home_penalties: number | null; away_penalties: number | null; extra_time: boolean
  updated_at: string; prediction: Prediction | null; prediction_hit: boolean | null
}

export interface Paginated { total: number; items: Match[] }

export interface Status {
  data_version: number; server_time: string; last_sync_success: string | null; last_sync_attempt: string | null
  last_sync_error: string | null; is_stale: boolean; source: string; live_matches: number
  next_kickoff: string | null; active_model: string | null; model_trained_at: string | null
  model_data_cutoff: string | null; matches_total: number; first_match: string | null
  last_finished_match: string | null; refresh_hint_seconds: number; message: string | null
}

export interface SeasonRow { season: string; tournament: string; matches: number; finished: number; start: string; end: string }

export interface MetricSummary {
  n: number; accuracy?: number; log_loss?: number; brier?: number; rps?: number
  confusion?: number[][]; mean_probs?: number[]; observed_freq?: number[]
  calibration?: Record<string, { bin: string; n: number; predicted: number; observed: number }[]>
  goals?: { mae_expected_goals: number; mae_top_score: number; exact_score_hit_rate: number }
  by_tournament?: Record<string, { n: number; accuracy: number; log_loss: number; brier: number }>
  by_stage?: Record<string, { n: number; accuracy: number; log_loss: number; brier: number }>
  recall_by_outcome?: Record<string, number | null>
  message?: string
}

export interface MetricsResponse {
  available: boolean; message?: string; backtest_run_id?: number; created_at?: string
  summary?: {
    selected_model: string; selection_metric: string; validation_log_loss: Record<string, number>
    folds: { warmup: string[]; validation: string[]; test: string[]; excluded: string[] }
    feature_params: Record<string, number>; chosen_hyperparams: Record<string, unknown>
    models: Record<string, { validation: MetricSummary; test: MetricSummary }>
  }
  active_model?: { version: string; trained_at: string; data_cutoff: string; train_matches: number } | null
  live: MetricSummary
}

export interface TeamStats {
  team: Team; matches_in_database: number; form_last5: string
  recent: { match_id: number; date: string; tournament: string; home: boolean; opponent: string; gf: number; ga: number; result: 'G' | 'E' | 'P'; points: number }[]
  summary_recent: Agg; home_recent: Agg; away_recent: Agg
  by_tournament: (Agg & { tournament: string })[]
  elo_history: { match_id: number; date: string; elo: number }[]
}
export interface Agg { played: number; wins?: number; draws?: number; losses?: number; gf?: number; ga?: number; ppg?: number; gf_avg?: number; ga_avg?: number }

export interface StandingRow {
  position: number; team: Team; played: number; wins: number; draws: number; losses: number; gf: number; ga: number; gd: number; points: number
  p_qualify: number | null; p_champion: number | null
}
export interface Standings {
  tournament: string | null; current: boolean; qualify_spots?: number; note: string; rows: StandingRow[]
  simulation: { model_version: string; n_sims: number; pending_matches: number; unscheduled_matches: number; computed_at: string } | null
}

export interface JobRun { id: number; job: string; trigger: string; status: string; started_at: string; finished_at: string | null; message: string | null; stats: Record<string, unknown> }
export interface Issue { id: number; match_id: number | null; source: string; source_key: string | null; severity: string; code: string; message: string; details: unknown; created_at: string }

// ---- Quiniela ----
export interface AuthUser { id: number; email: string; display_name: string | null; email_verified: boolean; approved: boolean }
export interface AuthResult { token: string | null; user: AuthUser }
export interface AuthConfig { registration_open: boolean; invite_code_required: boolean; email_enabled: boolean }
export interface MessageResult { ok: boolean; email_sent: boolean; message: string; email_enabled?: boolean }

export interface QJornadaSummary {
  key: string; label: string; liguilla: boolean; matches: number; open_matches: number
  first_kickoff: string; last_kickoff: string; finished: boolean; missing_picks: number | null
}
export interface QJornadas {
  tournament: string; tournaments: string[]; current: string | null; liguilla_multiplier: number
  jornadas: QJornadaSummary[]
}
export type PickKind = 'exacto' | 'resultado' | 'fallo'
export interface QPick { home: number; away: number; points: number | null; kind: PickKind | null }
export interface QOtherPick extends QPick { display_name: string; is_me: boolean }
export interface QMatch {
  id: number; kickoff_utc: string; status: MatchStatus; status_detail: string | null; live_clock: string | null
  stage: string; stage_detail: string | null; round: number | null; home: Team; away: Team
  home_goals: number | null; away_goals: number | null; home_goals_final: number | null; away_goals_final: number | null
  extra_time: boolean
}
export interface QItem {
  match: QMatch; locked: boolean; scored: boolean; multiplier: number
  my_pick: QPick | null; model_pick: QPick | null; picks: QOtherPick[]
}
export interface QJornadaDetail { tournament: string; key: string; label: string; liguilla: boolean; items: QItem[] }
export interface QRow {
  position: number; user_id: number | null; display_name: string; is_model: boolean; points: number; exact: number
  outcome: number; scored_picks: number; pending_picks: number; jornadas_won: number; by_jornada: Record<string, number>
}
export interface QJornadaTable {
  key: string; label: string; liguilla: boolean; matches: number; finished_matches: number; finished: boolean
  winners: string[]; rows: QRow[]
}
export interface QTables { tournament: string; finished: boolean; winners: string[]; rows: QRow[]; jornadas: QJornadaTable[] }
export interface AdminUser extends AuthUser { created_at: string; last_login_at: string | null; picks: number }
export interface AdminUsers { email_enabled: boolean; registration_open: boolean; pending: number; items: AdminUser[] }
