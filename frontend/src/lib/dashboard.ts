/**
 * Dashboard data — GET /briefing/{user_id} calls Claude to generate
 * briefing_text on every request, so this is NOT something to poll:
 * fetched once per session (module-level cache) and only re-fetched when
 * the user explicitly asks via a refresh action.
 */
import { apiFetch } from './api';

export interface AgendaItem {
  subject: string;
  timestamp: string;
  local_time?: string;
  organizer?: string;
  attendees?: string[];
}

export interface CommitmentSource {
  platform: string;
  subject?: string;
  author?: string;
}

export interface CommitmentItem {
  id: string;
  commitment_text: string;
  owner: string;
  due_date: string | null;
  status: string;
  priority: number;
  source: CommitmentSource | null;
}

export interface BriefingData {
  agenda: AgendaItem[];
  pending_commitments: CommitmentItem[];
  overdue_commitments: CommitmentItem[];
  contextual_alerts: string[];
  briefing_text: string;
  generated_at: string;
}

let cachedUserId: string | null = null;
let cachedBriefing: Promise<BriefingData> | null = null;

async function fetchCurrentUserId(apiKey: string): Promise<string> {
  if (cachedUserId) return cachedUserId;
  const resp = await apiFetch(apiKey, '/users/me');
  const data = (await resp.json()) as { id: string };
  cachedUserId = data.id;
  return cachedUserId;
}

/** Clear the cached user id/briefing — call on logout so a different user
 * on the same machine never sees the previous user's dashboard data. */
export function resetDashboardCache(): void {
  cachedUserId = null;
  cachedBriefing = null;
}

export async function fetchBriefing(apiKey: string, forceRefresh = false): Promise<BriefingData> {
  if (cachedBriefing && !forceRefresh) return cachedBriefing;
  cachedBriefing = (async () => {
    const userId = await fetchCurrentUserId(apiKey);
    const resp = await apiFetch(apiKey, `/briefing/${userId}`);
    return (await resp.json()) as BriefingData;
  })();
  return cachedBriefing;
}

/** A single consolidated, cross-source "your pending items" list — one
 * entry per commitment, each carrying its own source as a secondary
 * label (e.g. "vía Slack") rather than being grouped into a card per
 * platform. The backend has already filtered these to commitments that
 * clearly belong to the user (see commitment_service.is_owned_by_user);
 * this only merges pending + overdue and orders them: overdue first,
 * then by due date (soonest first, undated last). */
export function consolidatePendingItems(
  pending: CommitmentItem[],
  overdue: CommitmentItem[],
): CommitmentItem[] {
  const overdueIds = new Set(overdue.map((c) => c.id));
  const merged = [...overdue, ...pending.filter((c) => !overdueIds.has(c.id))];
  return merged.sort((a, b) => {
    const aOverdue = overdueIds.has(a.id);
    const bOverdue = overdueIds.has(b.id);
    if (aOverdue !== bOverdue) return aOverdue ? -1 : 1;
    if (!a.due_date && !b.due_date) return 0;
    if (!a.due_date) return 1;
    if (!b.due_date) return -1;
    return new Date(a.due_date).getTime() - new Date(b.due_date).getTime();
  });
}
