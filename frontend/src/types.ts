/**
 * Wire types shared with the backend. These mirror CONTRACT.md exactly;
 * if the contract changes, this file is the only place that should need to.
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
  /** errors / total over the window, 0..1. */
  error_rate: number;
  /** Rolling median of error_rate; null until the baseline is warm. */
  baseline_median: number | null;
  /** Upper edge of "normal" (median + 3.5 · MAD / 0.6745); null until warm. */
  band_upper: number | null;
  /** Modified z-score of this bucket; null until warm. */
  score: number | null;
  severity: Severity | null;
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
}

/** Detector timing reported by /api/health, used for chart labels and warm-up progress. */
export interface DetectorTiming {
  window_seconds: number;
  bucket_seconds: number;
  baseline_min_buckets: number;
}

/** Troubleshooting counters reported by /api/health. */
export interface PipelineCounters {
  parsed_lines: number;
  malformed_lines: number;
  baseline_warm: boolean;
  websocket_clients: number;
}

export interface Health {
  status: 'ok';
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
}

/** Server -> client WebSocket messages, discriminated on `type`. */
export type WsMessage = { type: 'stats'; data: StatsPoint } | { type: 'alert'; data: Alert };
