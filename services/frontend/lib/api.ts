import type { ChatMessage } from "./types";

const AGENT_URL = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:8000";

export type ChatApiResponse = {
  response: string;
  session_id?: string | null;
};

export async function sendMessage(
  messages: ChatMessage[],
  sessionId?: string | null,
): Promise<ChatApiResponse> {
  const res = await fetch(`${AGENT_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages,
      ...(sessionId ? { session_id: sessionId } : {}),
    }),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || res.statusText);
  }

  const data = await res.json();

  return {
    response: data.response as string,
    session_id: data.session_id ?? null,
  };
}