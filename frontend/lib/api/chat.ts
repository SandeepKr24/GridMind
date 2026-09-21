import { request } from "./client";
import type { ChatResponse } from "./types";

/**
 * The backend returns promptly with a job id when ingestion is required, rather
 * than holding the connection open for two minutes — so a normal timeout is fine.
 */
export function sendChatMessage(
  message: string,
  conversationId: string | null,
  signal?: AbortSignal
): Promise<ChatResponse> {
  return request<ChatResponse>(`/api/chat`, {
    method: "POST",
    body: { message, conversation_id: conversationId },
    timeoutMs: 30_000,
    signal,
  });
}
