import { apiFetch } from './api';
import type { PeopleListResponse, PersonProfile } from './types';

export async function fetchPeople(apiKey: string): Promise<PeopleListResponse> {
  const resp = await apiFetch(apiKey, '/people');
  return (await resp.json()) as PeopleListResponse;
}

export async function fetchPersonProfile(apiKey: string, entityId: string): Promise<PersonProfile> {
  const resp = await apiFetch(apiKey, `/people/${entityId}`);
  return (await resp.json()) as PersonProfile;
}

// Spanish labels for the fixed claim_type vocabulary the domain agents use
// (see domain_agent.py's add_claim docstring) — anything else (untyped
// claims land in "general", or a type not in this list) falls back to a
// capitalized version of the raw key, never an "unknown" placeholder.
const CLAIM_TYPE_LABELS: Record<string, string> = {
  role: 'Rol',
  relationship_to_user: 'Vínculo conmigo',
  communication_style: 'Estilo de comunicación',
  decision_authority: 'Qué puede decidir',
  agreement_style: 'Cómo llegar a acuerdos',
  general: 'Otros',
};

export function claimTypeLabel(claimType: string): string {
  return CLAIM_TYPE_LABELS[claimType] ?? claimType.charAt(0).toUpperCase() + claimType.slice(1);
}

// Fixed display order so the profile reads like a coherent brief (role
// first, general/untyped last) instead of whatever order the backend's
// dict happens to iterate in.
const CLAIM_TYPE_ORDER = [
  'role', 'relationship_to_user', 'communication_style', 'decision_authority', 'agreement_style', 'general',
];

export function sortClaimTypes(claimTypes: string[]): string[] {
  return [...claimTypes].sort((a, b) => {
    const ia = CLAIM_TYPE_ORDER.indexOf(a);
    const ib = CLAIM_TYPE_ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });
}
