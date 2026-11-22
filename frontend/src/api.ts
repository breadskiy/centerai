import { useSuspenseQuery, QueryClient } from "@tanstack/react-query";
import { t, useLanguage } from "./locale";

export interface GraphNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}
export interface GraphEdge {
  source: string;
  target: string;
  branch: string;
}
export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}
export interface Kind {
  title: string;
  category: string;
  description: string;
  input: string;
  output: string;
  defaults: Record<string, unknown>;
}
export interface Registry {
  types: Record<string, Kind>;
  default_graph: Graph;
  ai_graph?: Graph;
  email_available?: boolean;
  email_recipients?: string[];
}
export interface Project {
  id: string;
  name: string;
  description: string;
  source: string;
  source_type: string;
  file_count: number;
  created: number;
  runs: number;
  last_run: number | null;
  latest_completed?: {
    id: string;
    finished: number | null;
    levels: Record<string, number>;
  } | null;
}
export interface Flow {
  description: string;
  updated: number | null;
  last_run: number | null;
  id: string;
  project_id: string;
  name: string;
  revision: number;
  graph: Graph;
  next_due: number | null;
  last_status: string | null;
}
export interface Run {
  levels?: Record<string, number>;
  cancel_requested: boolean;
  id: string;
  project_id: string;
  project_name: string;
  workflow_id: string;
  workflow_name: string;
  revision: number;
  trigger: string;
  status: string;
  created: number;
  started: number | null;
  finished: number | null;
  count: number;
  error: string | null;
}
export interface RunDetails extends Run {
  project_archived?: boolean;
  report_email?: {
    status:
      "queued" | "sending" | "accepted" | "failed" | "uncertain" | "skipped";
    attempts: number;
    error: string | null;
  } | null;
  graph: Graph;
  stage_order: string[];
  nodes: {
    node_id: string;
    status: string;
    output: {
      count?: number;
      levels?: Record<string, number>;
      files?: number;
      branch?: string;
      ai?: {
        status: string;
        model: string;
        summary?: string;
        explained?: number;
        total?: number;
      };
    };
  }[];
  events: RunEvent[];
}
export interface StageSummary {
  count: number;
  levels: Record<string, number>;
  preview: Pick<Finding, "id" | "title" | "severity" | "path" | "line">[];
}
export interface RunEvent {
  id: number;
  node_id: string | null;
  status: string;
  message: string;
  created: number;
  stage: StageSummary | null;
}
export interface Finding {
  id: string;
  run_id: string;
  title: string;
  category: string;
  severity: string;
  path: string;
  line: number;
  class: string;
  description: string;
  remediation: string;
  evidence: string;
  ai?: {
    model: string;
    explanation: string;
    technical_details: string;
    business_impact: string;
    remediation_steps: string[];
    false_positive_notes: string;
    evidence_status: string;
  };
  advisoryId?: string;
  aliases?: string[];
  rule_id: string;
}
export interface Settings {
  email_recipient: string;
  smtp: boolean;
  demo_mailbox: boolean;
  telegram: boolean;
  worker: string;
  repositories: string[];
}
export const levels = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
export const cache = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
  },
});
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch("/api/v1" + path, {
    method,
    headers:
      form || body === undefined ? {} : { "Content-Type": "application/json" },
    body: form ? body : body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("centerai-session-check"));
    let message = t("Сервер вернул ошибку") + " " + response.status;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(t(message));
  }
  return response.json();
}
export function useData<T>(path: string) {
  return useSuspenseQuery({ queryKey: [path], queryFn: () => api<T>(path) })
    .data;
}
export const date = (timestamp: number | null) =>
  timestamp
    ? new Date(timestamp * 1000).toLocaleString(
        useLanguage.getState().language === "en" ? "en-GB" : "ru-RU",
        {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        },
      )
    : "—";
export const duration = (r: Run) =>
  r.started && r.finished
    ? Math.max(0, r.finished - r.started).toFixed(1) +
      (useLanguage.getState().language === "en" ? " s" : " с")
    : "—";
