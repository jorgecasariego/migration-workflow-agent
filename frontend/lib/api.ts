import type { Migration, SourceFile } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function startMigration(files: SourceFile[]): Promise<{ id: string }> {
  const res = await fetch(`${API_URL}/migrate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_framework: "express", target_framework: "fastapi", files }),
  });
  return handle(res);
}

export async function getMigration(id: string): Promise<Migration> {
  const res = await fetch(`${API_URL}/migrations/${id}`, { cache: "no-store" });
  return handle(res);
}
