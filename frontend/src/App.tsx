import { AlertFeed } from './components/AlertFeed';
import { ConnectionBanner } from './components/ConnectionBanner';
import { ErrorRateChart } from './components/ErrorRateChart';
import { StatusBar } from './components/StatusBar';
import { SummaryStrip } from './components/SummaryStrip';
import { useAlertStream } from './hooks/useAlertStream';
import { useNow } from './hooks/useNow';
import { baselineState } from './lib/detector';

export function App() {
  const stream = useAlertStream();
  const now = useNow();
  const baseline = baselineState(stream.stats);
  const latest = stream.stats[stream.stats.length - 1];

  return (
    <div className="app">
      <StatusBar
        connection={stream.connection}
        baseline={baseline}
        health={stream.health}
        now={now}
      />
      <ConnectionBanner connection={stream.connection} lastUpdate={latest?.ts} />
      <main className="layout">
        <div className="layout__primary">
          <SummaryStrip latest={latest} alerts={stream.alerts} now={now} />
          <ErrorRateChart stats={stream.stats} baseline={baseline} connection={stream.connection} />
        </div>
        <div className="layout__feed">
          <AlertFeed
            alerts={stream.alerts}
            liveArrivals={stream.liveArrivals}
            connection={stream.connection}
            now={now}
            onAcknowledge={stream.acknowledge}
          />
        </div>
      </main>
      <div className="visually-hidden" aria-live="polite" aria-atomic="true">
        {stream.announcement}
      </div>
    </div>
  );
}
