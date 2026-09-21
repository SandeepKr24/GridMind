import { request } from "./client";
import type { ChatResponse } from "./types";

/**
 * The backend returns promptly with a job id when ingestion is required, rather
 * than holding the connection open for two minutes — so a normal timeout is fine.
 *
 * Contract the backend must honour: a `conversation_id` it no longer holds (it
 * forgets them on restart) is answered with 404. The chat page then retries once
 * as a new conversation.
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
