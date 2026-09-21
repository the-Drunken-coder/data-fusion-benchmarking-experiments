export type Mode = 'ungrouped' | 'grouped';
export type Scenario = 'clean' | 'overlap' | 'crossing' | 'lifecycle' | 'noisy' | 'delayed' | 'turning';
export type Point = [number, number];
export interface System { id: string; name: string; version: string; description: string; modes: Mode[] }
export interface Config {
  scenario: Scenario; seed: number; partition: 'tuning' | 'evaluation'; kind: 'fixed' | 'exploratory';
  object_count?: number | null; noise_m?: number | null; detection_probability?: number | null; outage_ms?: number | null;
}
export interface Case { case_id: string; config: Config; observation_count: number; delivered_count: number }
export interface Summary {
  mean_gospa_m: number | null; position_rmse_m: number | null; coverage: number | null;
  matched_states: number; eligible_states: number; missed_states: number; false_states: number;
  identity_switches: number; scored_ticks: number; expected_ticks: number;
  mota: number | null; motp_m: number | null; velocity_rmse_mps: number | null;
  velocity_matched_states: number;
  gospa_components_mean_m2: { localisation: number | null; missed: number | null; false: number | null };
}
export interface Run {
  run_id: string; case_id: string; system: System; system_hash: string; mode: Mode;
  status: 'running' | 'complete' | 'failed'; failure: string | null; summary?: Summary;
  config: Config; created_at: string; observations_delivered: number; observations_acknowledged: number;
  timeouts: number; invalid_outputs: number; successful_steps: number;
  latency_ms?: { median: number | null; p95: number | null; max: number | null };
  summary_scope?: string;
}
export interface Job { job_id: string; status: 'running' | 'complete' | 'failed'; case_id: string | null; run_ids: string[]; requested: number; error: string | null }
export interface Catalog { scenarios: Scenario[]; systems: System[]; cases: Case[]; runs: Run[]; jobs: Job[] }
export interface ObjectState { truth_id: string; position_m: Point; velocity_mps: Point }
export interface Track { track_id: string; position_m: Point; velocity_mps?: Point }
export interface Observation { observation_id: string; sensor_id: string; measured_at_ms: number; arrived_at_ms: number; position_m: Point; group_key?: string }
export interface Match { truth_id: string; track_id: string; distance_m: number; identity_switch: boolean }
export interface Tick { time_ms: number; matches: Match[]; missed_ids: string[]; false_ids: string[]; gospa: { distance: number; localisation: number; missed: number; false: number } }
export interface Detail {
  result: Run;
  truth: { time_ms: number; objects: ObjectState[] }[];
  outputs: { time_ms: number; tracks: Track[] }[];
  requests: { time_ms: number; observations: Observation[] }[];
  metrics: { ticks: Tick[]; summary: Summary; identity_method: string } | null;
  timing: { time_ms: number; latency_ms: number; observations: number }[];
}
