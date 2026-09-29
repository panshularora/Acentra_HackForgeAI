/**
 * Wire types shared with the backend. These mirror CONTRACT.md exactly;
 * if the contract changes, this file is the only place that should need to.
 *
 * Fields added by contract v2 (template-aware detection) are optional and
 * nullable: older backends omit them and the dashboard must still render.
 */

export type Severity = 'WARNING' | 'HIGH' | 'CRITICAL';

/** One closed 10-second bucket, describing the trailing 60-second window. */
export interface StatsPoint {
  /** Bucket end, ISO-8601 UTC. */
  ts: string;
  /** Log lines in the sliding window. */
  total: number;
  /** Error lines in the sliding window. */
  errors: number;
  /** errors / total over the window, 0..1; null when the window held no lines. */
  error_rate: number | null;
  /** Rolling median of error_rate; null until the baseline is warm. */
  baseline_median: number | null;
  /** Upper edge of "normal" (median + 3.5 · MAD / 0.6745); null until warm. */
  band_upper: number | null;
  /** Modified z-score of this bucket; null until warm or when the window is empty. */
  score: number | null;
  severity: Severity | null;
  /** Contract v2: detector warm-up progress; absent on older backends. */
  learning?: LearningState | null;
}

/** Contract v2: how far the detector is through learning its baselines. */
export interface LearningState {
  state: 'learning' | 'ready';
  buckets_seen: number;
  buckets_needed: number;
  /** Distinct log templates (Drain3) seen so far. */
  templates: number;
}

/** Contract v2: the detector that opened an incident. */
export type DetectorKind = 'error_spike' | 'silence' | 'new_pattern' | 'flow_break';

/** Contract v2: the log template an incident is about, with variable parts as `<*>`. */
export interface LogTemplate {
  id: string;
  text: string;
  service: string | null;
}

/** Contract v2: the learned normal band for the incident's signal. */
export interface BaselineBand {
  median: number;
  /** Edge of normal; values above it are anomalous. */
  upper: number;
  /** e.g. "errors/60s", "seconds between lines", "incomplete flows/60s". */
  unit: string;
}

/** Contract v2: a top value of a parameter extracted from the template. */
export interface ExtractedParam {
  name: string;
  value: string;
  count: number;
  /** Fraction of the incident's lines carrying this value, 0..1. */
  share: number;
}

export type AlertStatus = 'open' | 'resolved';

export interface Contributor {
  value: string;
  count: number;
  /** Fraction of error lines in the incident attributed to this value, 0..1. */
  share: number;
}

export interface TopContributors {
  services: Contributor[];
  messages: Contributor[];
  source_ips: Contributor[];
}

export type DeliveryStatus = 'pending' | 'sent' | 'failed' | 'disabled';

export interface SnsDelivery {
  status: DeliveryStatus;
  message_id: string | null;
  error: string | null;
}

export interface CloudWatchDelivery {
  status: DeliveryStatus;
  error: string | null;
}

export interface Alert {
  id: string;
  status: AlertStatus;
  /** Peak severity reached so far. */
  severity: Severity;
  /** Peak modified z-score. */
  score: number;
  /** Error rate at peak. */
  error_rate: number;
  /** Baseline median at peak. */
  baseline_median: number;
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  /** One-sentence, human-readable explanation of the incident. */
  summary: string;
  top_contributors: TopContributors;
  /** Up to five raw log lines with PII masked by the backend. */
  sample_lines: string[];
  acknowledged: boolean;
  delivery: {
    sns: SnsDelivery;
    cloudwatch: CloudWatchDelivery;
  };
  /** Contract v2 fields below; each may be missing or null. */
  detector?: DetectorKind | null;
  template?: LogTemplate | null;
  baseline_band?: BaselineBand | null;
  /** The value that broke the band at peak, in baseline_band.unit. */
  observed?: number | null;
  /** Masked raw line that first crossed the band. */
  first_bad_line?: string | null;
  params?: ExtractedParam[] | null;
  /** Most upstream alerting service when several cards are part of a cascade. */
  suspected_origin?: string | null;
}

/** Detector timing reported by /api/health, used for chart labels and warm-up progress. */
export interface DetectorTiming {
  window_seconds: number;
  bucket_seconds: number;
  baseline_min_buckets: number;
  /** Contract v2: detectors the backend runs. */
  detectors?: DetectorKind[];
}

/** Troubleshooting counters reported by /api/health. */
export interface PipelineCounters {
  parsed_lines: number;
  malformed_lines: number;
  baseline_warm: boolean;
  websocket_clients: number;
}

/**
 * "ok", or "degraded" while the log-ingest pipeline is failing and retrying
 * (newer backends only; current main always says "ok").
 */
export type HealthStatus = 'ok' | 'degraded';

export interface Health {
  status: HealthStatus;
  /** Newer backends: the last ingest failure while degraded, else null. Absent on main. */
  ingest_error?: string | null;
  app: string;
  log_path: string;
  tailer_offset: number;
  aws: {
    sns_topic_arn: string | null;
    cloudwatch_log_group: string | null;
    endpoint: string | null;
  };
  detector: DetectorTiming;
  pipeline: PipelineCounters;
  /** Contract v2: same object as StatsPoint.learning. */
  learning?: LearningState | null;
  /** Demo faults currently injected from the dashboard. */
  faults?: FaultInjection[];
}

export interface FaultInjection {
  name: string;
  until: string;
  mode: 'lines' | 'suppress';
}

/** Server -> client WebSocket messages, discriminated on `type`. */
export type WsMessage = { type: 'stats'; data: StatsPoint } | { type: 'alert'; data: Alert };
