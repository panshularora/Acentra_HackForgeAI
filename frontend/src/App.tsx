import { useMemo } from 'react';
import { AlertFeed } from './components/AlertFeed';
import { ConnectionBanner } from './components/ConnectionBanner';
import { DeliveryPanel } from './components/DeliveryPanel';
import { ErrorRateChart } from './components/ErrorRateChart';
import { FaultPanel } from './components/FaultPanel';
import { DetectorScene } from './components/scene/DetectorScene';
import { StatusBar } from './components/StatusBar';
import { StatusHero } from './components/StatusHero';
import { SummaryStrip } from './components/SummaryStrip';
import { useAlertStream } from './hooks/useAlertStream';
import { useNow } from './hooks/useNow';
import { currentBaselineState, detectorTiming } from './lib/detector';
import { monitoringStatus } from './lib/health';
import { sceneModel } from './lib/scene';

export function App() {
  const stream = useAlertStream();
  const now = useNow();
  const timing = detectorTiming(stream.health);
  const baseline = currentBaselineState(stream.stats, stream.health);
  const latest = stream.stats[stream.stats.length - 1];
  const monitoring = useMemo(() => monitoringStatus(stream.health), [stream.health]);
  const model = useMemo(
    () =>
      sceneModel({
        connection: stream.connection,
        monitoring,
        baseline,
        latest,
        alerts: stream.alerts,
        windowSeconds: timing.window_seconds,
      }),
    // baseline is a fresh object each render; its kind is what matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stream.connection, monitoring, baseline.kind, latest, stream.alerts, timing.window_seconds],
  );

  return (
    <div className="app">
      <StatusBar
        connection={stream.connection}
        baseline={baseline}
        health={stream.health}
        now={now}
        monitoring={monitoring}
      />
      <ConnectionBanner
        connection={stream.connection}
        lastUpdate={latest?.ts}
        monitoring={monitoring}
      />
      <main className="layout">
        <section className={`panel hero hero--${model.tone}`} aria-label="Detector status">
          <div className="hero__text">
            <StatusHero
              model={model}
              monitoring={monitoring}
              baseline={baseline}
              latest={latest}
              now={now}
              windowSeconds={timing.window_seconds}
            />
          </div>
          <DetectorScene model={model} />
          <SummaryStrip
            latest={latest}
            alerts={stream.alerts}
            now={now}
            windowSeconds={timing.window_seconds}
          />
        </section>
        <div className="layout__chart">
          <ErrorRateChart
            stats={stream.stats}
            baseline={baseline}
            connection={stream.connection}
            timing={timing}
          />
        </div>
        <div className="layout__feed">
          <AlertFeed
            alerts={stream.alerts}
            liveArrivals={stream.liveArrivals}
            connection={stream.connection}
            baseline={baseline}
            now={now}
            onAcknowledge={stream.acknowledge}
          />
        </div>
        <div className="layout__ops">
          <DeliveryPanel health={stream.health} alerts={stream.alerts} now={now} />
          <FaultPanel />
        </div>
      </main>
      <div className="visually-hidden" aria-live="polite" aria-atomic="true">
        {stream.announcement}
      </div>
    </div>
  );
}
