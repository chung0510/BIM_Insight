import type { ClashReport, ProcessingStats } from "./inspection-api";

export type ClashProgress = ProcessingStats & {
  phase: string;
  elapsed_seconds?: number;
  source_name?: string;
  source_index?: number;
  source_count?: number;
  done?: number;
  total?: number;
  issues?: number;
};

function streamError(code: string) {
  return Object.assign(new Error(code), { code });
}

export async function readClashStream(response: Response, progress: (value: ClashProgress) => void): Promise<ClashReport> {
  if (!response.headers.get("Content-Type")?.includes("application/x-ndjson")) return response.json();
  const reader = response.body?.getReader();
  if (!reader) throw streamError("clash_connection_lost");
  const decoder = new TextDecoder();
  let parts: string[] = [], length = 0;
  let completed = false;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) throw streamError("clash_connection_lost");
      const lines = decoder.decode(chunk.value, { stream: true }).split("\n");
      for (let index = 0; index < lines.length; index++) {
        if (lines[index]) parts.push(lines[index]);
        length += lines[index].length;
        if (length > 256 * 1024 ** 2) throw streamError("processing_output_limit");
        if (index === lines.length - 1) continue;
        const line = parts.join("");
        parts = []; length = 0;
        if (!line.trim()) continue;
        let event;
        try { event = JSON.parse(line); } catch { throw streamError("clash_connection_lost"); }
        if (event.type === "progress") progress(event);
        else if (event.type === "error") throw streamError(typeof event.code === "string" ? event.code : "processing_failed");
        else if (event.type === "result" && event.report && Array.isArray(event.report.issues) && Array.isArray(event.report.diagnostics)) { completed = true; return event.report; }
        else throw streamError("clash_connection_lost");
      }
    }
  } finally {
    if (!completed) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
