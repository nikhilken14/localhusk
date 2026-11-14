import { API_BASE_URL } from "../../api-base";
const API_BASE = API_BASE_URL;

export interface StoredMessage { id: string; role: "user" | "assistant"; content: string; created_at?: string }
export async function createConversation(title: string): Promise<string> {
  const response = await fetch(`${API_BASE}/conversations`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  });
  if (!response.ok) throw new Error(await responseMessage(response, "Failed to create conversation"));
  return (await response.json()).id;
}
async function responseMessage(response: Response, fallback: string) {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  return typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((e: any) => e.msg ?? "Invalid request").join("; ") : fallback;
}
export async function loadConversationMessages(conversationId: string): Promise<StoredMessage[]> {
  const response = await fetch(`${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages?limit=200&offset=0&order=asc`);
  if (!response.ok) throw new Error(await responseMessage(response, "Failed to load conversation"));
  const body = await response.json();
  return (body.items ?? []).filter((m: any) => m.role === "user" || m.role === "assistant").map((m: any) => ({
    id: m.id, role: m.role, content: m.content ?? "", created_at: m.created_at,
  }));
}

/** Streams SSE safely across arbitrary network chunk boundaries and surfaces backend errors. */
export interface UploadedAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  extracted_chars: number;
  preview?: string;
}

export async function uploadAttachment(
  conversationId: string,
  file: File,
): Promise<UploadedAttachment> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(
    `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/attachments`,
    { method: "POST", body: form },
  );
  if (!response.ok) throw new Error(await responseMessage(response, "Failed to upload attachment"));
  return response.json();
}

export async function streamMessage(
  conversationId: string,
  content: string,
  onDelta: (text: string) => void,
  attachmentIds: string[] = [],
): Promise<void> {
  const response = await fetch(`${API_BASE}/conversations/${encodeURIComponent(conversationId)}/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, attachment_ids: attachmentIds }),
  });
  if (!response.ok) throw new Error(await responseMessage(response, "Failed to stream response"));
  if (!response.body) throw new Error("The backend did not provide a response stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistantText = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() ?? "";
      for (const event of events) {
        const data = event.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        let payload: any;
        try { payload = JSON.parse(data); } catch { continue; }
        if (payload.type === "error") throw new Error(payload.error ?? "The assistant response failed.");
        if (payload.type === "delta" && typeof payload.delta === "string") {
          assistantText += payload.delta;
          onDelta(assistantText);
        }
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}
