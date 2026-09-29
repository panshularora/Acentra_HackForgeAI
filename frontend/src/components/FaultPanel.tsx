import { useEffect, useState } from 'react';
import { injectFault, stopAllFaults, stopFault } from '../api/client';
import { DEMO_FAULTS, faultCommand, type Fault, type Runner } from '../lib/faults';

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'error'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
    } catch {
      setState('error');
    }
    setTimeout(() => setState('idle'), 1_600);
  };
  return (
    <button type="button" className="button button--small" onClick={copy} aria-label={label}>
      {state === 'copied' ? 'Copied' : state === 'error' ? 'Select & copy' : 'Copy'}
    </button>
  );
}

/**
 * One-click inject and stop for the five demo faults. Copyable make/Docker
 * commands stay as a fallback when the dashboard cannot reach the backend.
 */
type InjectState = 'idle' | 'pending' | 'running' | 'stopping' | 'error';

export function FaultPanel({ activeNames = [] }: { activeNames?: readonly string[] }) {
  const [runner, setRunner] = useState<Runner>('make');
  const [states, setStates] = useState<Record<string, InjectState>>({});
  const [stopped, setStopped] = useState<Record<string, boolean>>({});
  const [stoppingAll, setStoppingAll] = useState(false);

  useEffect(() => {
    setStopped((current) => {
      let changed = false;
      const next = { ...current };
      for (const name of Object.keys(next)) {
        if (next[name] && !activeNames.includes(name)) {
          delete next[name];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [activeNames]);

  const isActive = (name: string, state: InjectState | undefined) =>
    !stopped[name] && (activeNames.includes(name) || state === 'running');

  const inject = async (fault: Fault) => {
    setStopped((current) => ({ ...current, [fault.name]: false }));
    setStates((current) => ({ ...current, [fault.name]: 'pending' }));
    try {
      await injectFault(fault.name, fault.duration);
      setStates((current) => ({ ...current, [fault.name]: 'running' }));
    } catch {
      setStates((current) => ({ ...current, [fault.name]: 'error' }));
    }
  };

  const stop = async (fault: Fault) => {
    setStates((current) => ({ ...current, [fault.name]: 'stopping' }));
    try {
      await stopFault(fault.name);
      setStopped((current) => ({ ...current, [fault.name]: true }));
      setStates((current) => ({ ...current, [fault.name]: 'idle' }));
    } catch {
      setStates((current) => ({ ...current, [fault.name]: 'error' }));
    }
  };

  const stopAll = async () => {
    setStoppingAll(true);
    try {
      await stopAllFaults();
      const names = Object.fromEntries(DEMO_FAULTS.map((fault) => [fault.name, true]));
      setStopped(names);
      setStates((current) => {
        const next = { ...current };
        for (const fault of DEMO_FAULTS) next[fault.name] = 'idle';
        return next;
      });
    } catch {
      setStates((current) => {
        const next = { ...current };
        for (const fault of DEMO_FAULTS) {
          if (isActive(fault.name, current[fault.name])) next[fault.name] = 'error';
        }
        return next;
      });
    } finally {
      setStoppingAll(false);
    }
  };

  const anyActive = DEMO_FAULTS.some((fault) => isActive(fault.name, states[fault.name]));

  return (
    <section className="panel fault-panel" aria-labelledby="fault-title">
      <header className="panel__header">
        <div>
          <h2 id="fault-title" className="panel__title">
            Demo faults
          </h2>
          <p className="panel__subtitle">
            Inject or stop from here. Silence and flow-break need loggen running.
          </p>
        </div>
        <div className="fault-panel__controls">
          {anyActive ? (
            <button
              type="button"
              className="button button--small"
              disabled={stoppingAll}
              onClick={() => void stopAll()}
            >
              {stoppingAll ? 'Stopping' : 'Stop all'}
            </button>
          ) : null}
          <div className="segmented" role="group" aria-label="Command style">
            {(['make', 'docker'] as const).map((value) => (
              <button
                key={value}
                type="button"
                className="segmented__option"
                aria-pressed={runner === value}
                onClick={() => setRunner(value)}
              >
                {value === 'make' ? 'Make' : 'Docker'}
              </button>
            ))}
          </div>
        </div>
      </header>
      <ul className="fault-list">
        {DEMO_FAULTS.map((fault) => {
          const command = faultCommand(fault, runner);
          const state = states[fault.name];
          const active = isActive(fault.name, state);
          const pending = state === 'pending';
          const stopping = state === 'stopping' || stoppingAll;
          const failed = state === 'error';
          return (
            <li key={fault.name} className="fault">
              <div className="fault__text">
                <span className="fault__title">{fault.title}</span>
                <span className="fault__effect">{fault.effect}</span>
                <code className="fault__command mono">{command}</code>
              </div>
              <div className="fault__actions">
                {active ? (
                  <button
                    type="button"
                    className="button button--small"
                    disabled={stopping}
                    onClick={() => void stop(fault)}
                  >
                    {stopping ? 'Stopping' : 'Stop'}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button--small button--primary"
                    disabled={pending}
                    onClick={() => void inject(fault)}
                  >
                    {pending ? 'Injecting' : 'Inject'}
                  </button>
                )}
                <CopyButton text={command} label={`Copy command for ${fault.title}`} />
              </div>
              {failed ? <p className="fault__error">Request failed. Is the backend up?</p> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
