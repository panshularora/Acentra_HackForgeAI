import type { Health } from '../types';

/** Where alerts go: "local emulator" when an endpoint override is set, AWS otherwise. */
export function deliveryTarget(health: Health | null): string {
  if (!health) return '\u2014';
  if (!health.aws.sns_topic_arn && !health.aws.cloudwatch_log_group) return 'Delivery disabled';
  return health.aws.endpoint ? 'Local AWS emulator' : 'AWS';
}
