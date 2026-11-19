// Mirrors backend/app/models.py

export type MigrationStatus =
  | "pending"
  | "analyzing"
  | "planning"
  | "executing"
  | "verifying"
  | "completed"
  | "failed";

export type StepStatus = "pending" | "in_progress" | "completed" | "failed" | "skipped";

export interface SourceFile {
  path: string;
  content: string;
}

export interface Endpoint {
  method: string;
  path: string;
  source_file: string;
  description: string;
}

export interface Analysis {
  summary: string;
  endpoints: Endpoint[];
  dependencies: { name: string; purpose: string; python_equivalent: string }[];
  concerns: string[];
}

export interface PlanStep {
  id: string;
  title: string;
  description: string;
  source_files: string[];
  target_file: string;
  depends_on: string[];
  status: StepStatus;
  attempts: number;
  notes: string | null;
  error: string | null;
}

export interface MigratedFile {
  path: string;
  content: string;
  step_id: string;
}

export interface VerificationReport {
  passed: boolean;
  files: { path: string; syntax_ok: boolean; error: string | null }[];
  endpoints: { method: string; path: string; found: boolean; matched_route: string | null }[];
  failed_steps: string[];
  warnings: string[];
  disclaimer: string;
}

export interface Migration {
  id: string;
  status: MigrationStatus;
  source_framework: string;
  target_framework: string;
  source_files: SourceFile[];
  analysis: Analysis | null;
  plan: PlanStep[];
  migrated_files: MigratedFile[];
  verification: VerificationReport | null;
  errors: { phase: MigrationStatus; message: string; step_id: string | null }[];
  events: { at: string; message: string }[];
}
