"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getMigration, startMigration } from "@/lib/api";
import { SAMPLE_FILES } from "@/lib/sample";
import type { Migration, MigrationStatus, SourceFile } from "@/lib/types";

const PHASES: { key: MigrationStatus; label: string }[] = [
  { key: "analyzing", label: "1. Analysis" },
  { key: "planning", label: "2. Planning" },
  { key: "executing", label: "3. Execution" },
  { key: "verifying", label: "4. Verification" },
];
const TERMINAL: MigrationStatus[] = ["completed", "failed"];
const POLL_MS = 1500;

function phaseState(m: Migration | null, key: MigrationStatus): "" | "active" | "done" | "failed" {
  if (!m) return "";
  const idx = PHASES.findIndex((p) => p.key === key);
  if (m.status === "completed") return "done";
  let current = PHASES.findIndex((p) => p.key === m.status);
  if (m.status === "failed") {
    const failedPhase = m.errors.length ? m.errors[m.errors.length - 1].phase : "analyzing";
    current = Math.max(0, PHASES.findIndex((p) => p.key === failedPhase));
    return idx < current ? "done" : idx === current ? "failed" : "";
  }
  if (current < 0) return "";
  return idx < current ? "done" : idx === current ? "active" : "";
}

export default function Home() {
  const [files, setFiles] = useState<SourceFile[]>([{ path: "server.js", content: "" }]);
  const [migration, setMigration] = useState<Migration | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const running = !!migration && !TERMINAL.includes(migration.status);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function poll(id: string) {
    getMigration(id)
      .then((m) => {
        setMigration(m);
        setPollError(null);
        if (!TERMINAL.includes(m.status)) timer.current = setTimeout(() => poll(id), POLL_MS);
      })
      .catch((e: Error) => {
        setPollError(`Polling failed: ${e.message}. Retrying…`);
        timer.current = setTimeout(() => poll(id), POLL_MS * 2);
      });
  }

  async function onStart() {
    setSubmitError(null);
    setMigration(null);
    setSelected(null);
    if (timer.current) clearTimeout(timer.current);
    const clean = files.filter((f) => f.content.trim());
    if (!clean.length) {
      setSubmitError("Paste at least one Express.js file.");
      return;
    }
    setSubmitting(true);
    try {
      const { id } = await startMigration(clean);
      poll(id);
    } catch (e) {
      setSubmitError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  function updateFile(i: number, patch: Partial<SourceFile>) {
    setFiles((fs) => fs.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  }

  const migrated = migration?.migrated_files ?? [];
  const current = migrated.find((f) => f.path === selected) ?? migrated[0];
  const originals = useMemo(() => {
    if (!migration || !current) return [];
    const step = migration.plan.find((s) => s.id === current.step_id);
    const wanted = step?.source_files ?? [];
    const match = migration.source_files.filter((f) => wanted.includes(f.path));
    return match.length ? match : migration.source_files;
  }, [migration, current]);

  return (
    <main>
      <h1>Migration Workflow Agent</h1>
      <p className="sub">Paste Express.js files, and the agent analyses, plans, migrates and verifies them as FastAPI.</p>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <label>
              Source framework
              <select value="express" disabled={running} onChange={() => {}}>
                <option value="express">Express.js</option>
              </select>
            </label>
            <label>
              Target framework
              <select value="fastapi" disabled={running} onChange={() => {}}>
                <option value="fastapi">FastAPI (Python)</option>
              </select>
            </label>
          </div>
          <div className="row">
            <button onClick={() => setFiles(SAMPLE_FILES.map((f) => ({ ...f })))} disabled={running}>
              Load sample
            </button>
            <button onClick={() => setFiles((fs) => [...fs, { path: `file${fs.length + 1}.js`, content: "" }])}
              disabled={running || files.length >= 10}>
              + Add file
            </button>
            <button className="primary" onClick={onStart} disabled={running || submitting}>
              {running ? "Migrating…" : submitting ? "Starting…" : "Start migration"}
            </button>
          </div>
        </div>

        {files.map((f, i) => (
          <div className="file-editor" key={i}>
            <div className="row" style={{ marginBottom: 8 }}>
              <input aria-label="File path" value={f.path} disabled={running}
                onChange={(e) => updateFile(i, { path: e.target.value })} />
              {files.length > 1 && (
                <button onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))} disabled={running}>
                  Remove
                </button>
              )}
            </div>
            <textarea aria-label={`Contents of ${f.path}`} placeholder="Paste Express.js code here…" value={f.content}
              disabled={running} spellCheck={false} onChange={(e) => updateFile(i, { content: e.target.value })} />
          </div>
        ))}
        {submitError && <p className="bad">{submitError}</p>}
      </section>

      {migration && (
        <>
          <section className="panel">
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>Progress</h2>
              <span className={`badge s-${migration.status === "completed" ? "completed" : migration.status === "failed" ? "failed" : "in_progress"}`}>
                {migration.status}
              </span>
            </div>
            <div className="phases">
              {PHASES.map((p) => (
                <div key={p.key} className={`phase ${phaseState(migration, p.key)}`}>{p.label}</div>
              ))}
            </div>
            {pollError && <p className="warn">{pollError}</p>}
            {migration.events.length > 0 && (
              <p className="muted" style={{ marginTop: 12 }}>
                Latest: {migration.events[migration.events.length - 1].message}
              </p>
            )}
          </section>

          {migration.analysis && (
            <section className="panel">
              <h2>Analysis</h2>
              <p>{migration.analysis.summary}</p>
              <table>
                <thead><tr><th>Method</th><th>Path</th><th className="hide-sm">File</th><th>Description</th></tr></thead>
                <tbody>
                  {migration.analysis.endpoints.map((e, i) => (
                    <tr key={i}><td>{e.method}</td><td><code>{e.path}</code></td>
                      <td className="hide-sm muted">{e.source_file}</td><td>{e.description}</td></tr>
                  ))}
                </tbody>
              </table>
              {migration.analysis.concerns.length > 0 && (
                <>
                  <h2 style={{ marginTop: 16 }}>Migration concerns</h2>
                  <ul>{migration.analysis.concerns.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </>
              )}
            </section>
          )}

          {migration.plan.length > 0 && (
            <section className="panel">
              <h2>Plan</h2>
              <table>
                <thead><tr><th>ID</th><th>Step</th><th className="hide-sm">Target</th><th className="hide-sm">Depends on</th><th>Status</th></tr></thead>
                <tbody>
                  {migration.plan.map((s) => (
                    <tr key={s.id}>
                      <td>{s.id}</td>
                      <td>
                        <strong>{s.title}</strong>
                        <div className="muted">{s.description}</div>
                        {s.error && <div className="bad">{s.error}</div>}
                      </td>
                      <td className="hide-sm"><code>{s.target_file}</code></td>
                      <td className="hide-sm muted">{s.depends_on.join(", ") || "—"}</td>
                      <td>
                        <span className={`badge s-${s.status}`}>{s.status.replace("_", " ")}</span>
                        {s.attempts > 1 && <div className="muted">{s.attempts} attempts</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {migrated.length > 0 && current && (
            <section className="panel">
              <h2>Original vs migrated</h2>
              <div className="tabs">
                {migrated.map((f) => (
                  <button key={f.path} className={f.path === current.path ? "sel" : ""} onClick={() => setSelected(f.path)}>
                    {f.path}
                  </button>
                ))}
              </div>
              <div className="compare" style={{ marginTop: 12 }}>
                <div>
                  <div className="muted">Original (Express.js): {originals.map((o) => o.path).join(", ")}</div>
                  {originals.map((o) => <pre className="code" key={o.path}>{o.content}</pre>)}
                </div>
                <div>
                  <div className="muted">Migrated (FastAPI): {current.path}</div>
                  <pre className="code">{current.content}</pre>
                </div>
              </div>
            </section>
          )}

          {migration.verification && (
            <section className="panel">
              <h2>
                Verification:{" "}
                <span className={migration.verification.passed ? "ok" : "bad"}>
                  {migration.verification.passed ? "passed" : "problems found"}
                </span>
              </h2>
              <p className="muted">{migration.verification.disclaimer}</p>
              <table>
                <thead><tr><th>File</th><th>Syntax</th></tr></thead>
                <tbody>
                  {migration.verification.files.map((f) => (
                    <tr key={f.path}><td><code>{f.path}</code></td>
                      <td className={f.syntax_ok ? "ok" : "bad"}>{f.syntax_ok ? "valid" : f.error}</td></tr>
                  ))}
                </tbody>
              </table>
              <table style={{ marginTop: 12 }}>
                <thead><tr><th>Endpoint</th><th>Found in migrated code</th></tr></thead>
                <tbody>
                  {migration.verification.endpoints.map((e, i) => (
                    <tr key={i}><td><code>{e.method} {e.path}</code></td>
                      <td className={e.found ? "ok" : "bad"}>{e.found ? `yes (${e.matched_route})` : "missing"}</td></tr>
                  ))}
                </tbody>
              </table>
              {migration.verification.warnings.length > 0 && (
                <ul style={{ marginTop: 12 }}>
                  {migration.verification.warnings.map((w, i) => <li key={i} className="warn">{w}</li>)}
                </ul>
              )}
            </section>
          )}

          {migration.errors.length > 0 && (
            <section className="panel error-box">
              <h2 className="bad">Errors</h2>
              <ul>
                {migration.errors.map((e, i) => (
                  <li key={i}><span className="muted">[{e.phase}{e.step_id ? ` / ${e.step_id}` : ""}]</span> {e.message}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </main>
  );
}
