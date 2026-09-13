import { apiFetch } from './api';
import type { SystemsStatusResponse } from './types';

export async function fetchSystemsStatus(apiKey: string): Promise<SystemsStatusResponse> {
  const resp = await apiFetch(apiKey, '/systems/status');
  return (await resp.json()) as SystemsStatusResponse;
}

// Friendly display names for sources we know about — anything else (a
// source connected tomorrow that doesn't exist yet) falls back to a
// capitalized version of its raw key, never a "unknown" placeholder.
const KNOWN_LABELS: Record<string, string> = {
  outlook: 'Outlook',
  slack: 'Slack',
  teams: 'Teams',
  fathom: 'Fathom',
  notion: 'Notion',
  rd: 'I+D',
};

export function sourceLabel(source: string): string {
  return KNOWN_LABELS[source] ?? source.charAt(0).toUpperCase() + source.slice(1);
}
