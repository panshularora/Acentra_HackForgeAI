import { useState } from 'react';
import { DEMO_FAULTS, UNDETECTED_FAULTS, faultCommand, type Runner } from '../lib/faults';

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
 * How to trigger a demo incident. The backend has no API for this: faults
 * are injected by the log generator on the backend host, so the panel hands
 * over the exact command to run.
 */
export function FaultPanel() {
  const [runner, setRunner] = useState<Runner>('make');

  return (
    <section className="panel fault-panel" aria-labelledby="fault-title">
      <header className="panel__header">
        <div>
          <h2 id="fault-title" className="panel__title">
            Demo faults
          </h2>
          <p className="panel__subtitle">
            Run one on the backend host; an incident opens within a bucket or two.
          </p>
        </div>
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
      </header>
      <ul className="fault-list">
        {DEMO_FAULTS.map((fault) => {
          const command = faultCommand(fault, runner);
          return (
            <li key={fault.name} className="fault">
              <div className="fault__text">
                <span className="fault__title">{fault.title}</span>
                <span className="fault__effect">{fault.effect}</span>
                <code className="fault__command mono">{command}</code>
              </div>
              <CopyButton text={command} label={`Copy command for ${fault.title}`} />
            </li>
          );
        })}
      </ul>
      <p className="fault-panel__note">
        <span className="mono">{UNDETECTED_FAULTS.join(', ')}</span> can be injected too, but are
        not detected yet (no silence or flow detector is running).
      </p>
    </section>
  );
}
