/**
 * Read/write helpers for the generative UI protocol's two artifact types:
 * request_user_input's UIRequest (a structured question) and
 * propose_action's Artifact (an approve/reject preview). See
 * app/api/schemas/interactions.py for the response shapes and
 * app/api/schemas/ui_protocol.py for what `spec`/`artifact` actually
 * contain — this file never interprets their content, just moves it.
 */
import { apiFetch } from './api';
import type { UIRequest } from './types';

export interface InteractionDetail {
  id: string;
  status: 'open' | 'answered' | 'cancelled' | 'expired';
  spec: UIRequest;
  answer: Record<string, unknown> | null;
  expires_at: string;
}

export async function fetchInteraction(apiKey: string, interactionId: string): Promise<InteractionDetail> {
  const resp = await apiFetch(apiKey, `/interactions/${interactionId}`);
  return (await resp.json()) as InteractionDetail;
}

export interface EmailAddress {
  name?: string;
  address: string;
}

export interface EmailDraftArtifact {
  kind: 'email_draft';
  to: EmailAddress[];
  cc: EmailAddress[];
  subject: string;
  body_paragraphs: string[];
  footnote_token?: 'drafted_by_assistant';
}

export interface KeyValueRow {
  label: string;
  value: string;
  tone: 'neutral' | 'good' | 'warn';
}

export interface KeyValuesArtifact {
  kind: 'key_values';
  title: string;
  rows: KeyValueRow[];
}

export type Artifact = EmailDraftArtifact | KeyValuesArtifact;

export interface ProposedActionDetail {
  id: string;
  action_type: string;
  status: 'proposed' | 'approved' | 'executing' | 'executed' | 'failed' | 'rejected' | 'expired';
  risk: 'low' | 'high';
  artifact: Artifact;
  payload_sha256: string;
  expires_at: string;
  error?: string | null;
}

export async function fetchProposedAction(apiKey: string, actionId: string): Promise<ProposedActionDetail> {
  const resp = await apiFetch(apiKey, `/interactions/actions/${actionId}`);
  return (await resp.json()) as ProposedActionDetail;
}

export async function approveAction(apiKey: string, actionId: string, payloadSha256: string): Promise<void> {
  await apiFetch(apiKey, `/interactions/actions/${actionId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload_sha256: payloadSha256 }),
  });
}

export async function rejectAction(apiKey: string, actionId: string): Promise<void> {
  await apiFetch(apiKey, `/interactions/actions/${actionId}/reject`, { method: 'POST' });
}
