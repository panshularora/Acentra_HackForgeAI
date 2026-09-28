export type Runner = 'make' | 'docker';

export interface Fault {
  name: string;
  title: string;
  effect: string;
  make: string;
  duration: number;
}

/**
 * The faults the live detector (error_spike) catches. The log generator can
 * also inject heartbeat-stop and flow-break, but no detector watches for
 * those yet, so they are listed separately and never offered as a demo.
 */
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
];

export const UNDETECTED_FAULTS = ['heartbeat-stop', 'flow-break'] as const;

export function faultCommand(fault: Fault, runner: Runner): string {
  return runner === 'make'
    ? fault.make
    : `docker compose exec loggen python tools/loggen.py --incident ${fault.name} --duration ${fault.duration}`;
}
