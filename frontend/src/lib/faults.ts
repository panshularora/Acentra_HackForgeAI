export type Runner = 'make' | 'docker';

export interface Fault {
  name: string;
  title: string;
  effect: string;
  make: string;
  duration: number;
}

/** Demo faults the live detectors catch. Inject from the dashboard. */
export const DEMO_FAULTS: readonly Fault[] = [
  {
    name: 'db-outage',
    title: 'Database outage',
    effect: 'claim-adjudication times out on its database, about 3 errors/s',
    make: 'make incident-db',
    duration: 45,
  },
  {
    name: 'cred-stuffing',
    title: 'Credential stuffing',
    effect: 'one IP floods member-auth with failed logins, about 6 errors/s',
    make: 'make incident-auth',
    duration: 30,
  },
  {
    name: 'new-error',
    title: 'New error type',
    effect: 'a never-seen TLS failure calling the payer gateway, about 0.5/s',
    make: 'make incident-new',
    duration: 45,
  },
  {
    name: 'heartbeat-stop',
    title: 'Heartbeat stop',
    effect: 'eligibility-sync stops sending heartbeats (needs loggen running)',
    make: 'make incident-silence',
    duration: 60,
  },
  {
    name: 'flow-break',
    title: 'Claim flow break',
    effect: 'validated claims stop being adjudicated (needs loggen running)',
    make: 'make incident-flow',
    duration: 60,
  },
];

export function faultCommand(fault: Fault, runner: Runner): string {
  return runner === 'make'
    ? fault.make
    : `docker compose exec loggen python tools/loggen.py --incident ${fault.name} --duration ${fault.duration}`;
}
