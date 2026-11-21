// Typed calls to the platform API (shapes in ../types.ts, contract in docs/interfaces.md).
// Until an endpoint exists the call rejects with an ApiError carrying the status, and the UI
// shows an empty state instead of breaking.

import type {
  ChatReply,
  Clock,
  Conversation,
  ConversationSummary,
  DayRisks,
  FieldCollection,
  FieldDayRisks,
  FieldDetails,
  FieldRisksSeries,
  Health,
  Threat,
} from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface Api {
  health(): Promise<Health>;
  getClock(): Promise<Clock>;
  getFields(): Promise<FieldCollection>;
  getField(id: number): Promise<FieldDetails>;
  getThreats(): Promise<Threat[]>;
  getRisks(date: string): Promise<DayRisks>;
  getFieldRisks(fieldId: number, from: string, to: string): Promise<FieldRisksSeries>;
  getFieldRisksOn(fieldId: number, date: string): Promise<FieldDayRisks>;
  sendChat(body: { conversation_id: number | null; message: string; field_id: number | null }): Promise<ChatReply>;
  getConversations(): Promise<ConversationSummary[]>;
  getConversation(id: number): Promise<Conversation>;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload?.detail) detail = payload.detail;
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

export const api: Api = {
  health: () => request("GET", "/api/health/"),
  getClock: () => request("GET", "/api/clock/"),
  getFields: () => request("GET", "/api/fields/"),
  getField: (id) => request("GET", `/api/fields/${id}/`),
  getThreats: () => request("GET", "/api/threats/"),
  getRisks: (date) => request("GET", `/api/risks/?date=${encodeURIComponent(date)}`),
  getFieldRisks: (fieldId, from, to) =>
    request("GET", `/api/fields/${fieldId}/risks/?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  getFieldRisksOn: (fieldId, date) => request("GET", `/api/fields/${fieldId}/risks/${encodeURIComponent(date)}/`),
  sendChat: (body) => request("POST", "/api/chat/", body),
  getConversations: () => request("GET", "/api/chat/conversations/"),
  getConversation: (id) => request("GET", `/api/chat/conversations/${id}/`),
};

export function humaniseError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "Endpoint API jeszcze nie ma – dane pojawią się, gdy backend go doda.";
    return `Błąd API (${error.status}): ${error.message}`;
  }
  if (error instanceof TypeError) return "Brak połączenia z platformą (czy serwer działa?).";
  return error instanceof Error ? error.message : String(error);
}
