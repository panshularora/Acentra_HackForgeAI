import { arnResourceName, formatCount, formatRelative } from '../lib/format';
import { deliveryTarget } from '../lib/delivery';
import type { Alert, DeliveryStatus, Health } from '../types';

interface DeliveryPanelProps {
  health: Health | null;
  alerts: Alert[];
  now: number;
}

type Channel = 'sns' | 'cloudwatch';

const STATUS_TEXT: Record<DeliveryStatus, string> = {
  sent: 'Sent',
  pending: 'Pending',
  failed: 'Failed',
  disabled: 'Off',
};

function tally(alerts: Alert[], channel: Channel) {
  const counts: Record<DeliveryStatus, number> = { sent: 0, pending: 0, failed: 0, disabled: 0 };
  for (const alert of alerts) counts[alert.delivery[channel].status] += 1;
  return counts;
}

function ChannelRow({
  name,
  target,
  alerts,
  channel,
  now,
}: {
  name: string;
  target: string | null;
  alerts: Alert[];
  channel: Channel;
  now: number;
}) {
  // Newest activity first, so "last delivery" follows escalations and resolutions too.
  const latest = [...alerts].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0];
  const last = latest?.delivery[channel];
  const counts = tally(alerts, channel);
  const status: DeliveryStatus | null = target ? (last?.status ?? null) : 'disabled';
  const error = last && 'error' in last ? last.error : null;

  return (
    <div className="delivery-row">
      <dt className="delivery-row__name">
        {name}
        <span className="delivery-row__target mono">{target ?? 'disabled'}</span>
      </dt>
      <dd className="delivery-row__state">
        {status ? (
          <span className={`delivery-status delivery-status--${status}`} title={error ?? undefined}>
            <span className="delivery-status__dot" aria-hidden="true" />
            {target ? `Last alert: ${STATUS_TEXT[status].toLowerCase()}` : 'Off'}
          </span>
        ) : (
          <span className="muted">No alerts yet</span>
        )}
        {target && latest && (
          <span className="delivery-row__meta">
            <span className="mono">{formatCount(counts.sent)}</span> sent
            {counts.failed > 0 && (
              <>
                , <span className="mono">{formatCount(counts.failed)}</span> failed
              </>
            )}
            {counts.pending > 0 && (
              <>
                , <span className="mono">{formatCount(counts.pending)}</span> pending
              </>
            )}{' '}
            &middot; {formatRelative(latest.updated_at, now)}
          </span>
        )}
        {status === 'failed' && error && <span className="delivery-row__error mono">{error}</span>}
      </dd>
    </div>
  );
}

/** Where alerts are delivered and whether the latest one got there. */
export function DeliveryPanel({ health, alerts, now }: DeliveryPanelProps) {
  const topic = health ? arnResourceName(health.aws.sns_topic_arn) : null;
  const group = health?.aws.cloudwatch_log_group ?? null;

  return (
    <section className="panel delivery-panel" aria-labelledby="delivery-title">
      <header className="panel__header">
        <div>
          <h2 id="delivery-title" className="panel__title">
            Alert delivery
          </h2>
          <p className="panel__subtitle">{deliveryTarget(health)}</p>
        </div>
      </header>
      <dl className="delivery-panel__rows">
        <ChannelRow
          name="SNS"
          target={health ? topic : null}
          alerts={alerts}
          channel="sns"
          now={now}
        />
        <ChannelRow
          name="CloudWatch Logs"
          target={health ? group : null}
          alerts={alerts}
          channel="cloudwatch"
          now={now}
        />
        <div className="delivery-row">
          <dt className="delivery-row__name">
            Log source
            <span className="delivery-row__target mono">{health?.log_path ?? '\u2014'}</span>
          </dt>
          <dd className="delivery-row__state">
            {health ? (
              <span className="delivery-row__meta">
                <span className="mono">{formatCount(health.pipeline.parsed_lines)}</span> lines
                parsed
                {health.pipeline.malformed_lines > 0 && (
                  <>
                    , <span className="mono">{formatCount(health.pipeline.malformed_lines)}</span>{' '}
                    malformed
                  </>
                )}
              </span>
            ) : (
              <span className="muted">&mdash;</span>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}
