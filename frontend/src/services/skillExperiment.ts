export interface ExperimentSkill {
  skill_id: string; name: string; description: string; when_to_use: string;
  triggers: string[]; contraindications: string[]; meta_skill_id: string; stages: string[];
}
export interface ExperimentSource {
  run_id: string; session_index: number; therapy: string; objectives: string[];
  source_kind: string;
}
export interface ExperimentSummary {
  id: string; created_at: string; therapy: string; source_label: string; current_version: number;
}
export interface ExperimentCandidate {
  id: string; base_version: number; action: 'append' | 'merge' | 'skip'; reason: string;
  meta_skill_id: string; branch_reason: string; before: ExperimentSkill | null;
  after: ExperimentSkill | null; draft: ExperimentSkill;
  evidence: { message_index: number; text: string }[]; applied_version: number | null;
  similar: { similarity: number; skill: ExperimentSkill }[];
}
export interface ExperimentVersion {
  version: number; parent: number | null; action: string; hash: string;
  skills: Record<string, ExperimentSkill>; changed_skill_id?: string;
}
export interface ReplayTurn {
  response?: string;
  decision?: { selected_atomic_skill_ids?: string[]; skill_evidence?: unknown[] };
  observation?: { atomic_skills?: ExperimentSkill[] };
}
export interface ExperimentJob {
  id: string; status: string; request: { kind: string; version: number };
  error: string | null; progress: { time: string; text: string }[];
  result: null | {
    type?: string; version?: number; interpretation?: string;
    outputs?: Record<string, ReplayTurn & Record<string, unknown>>;
    context_hash?: string; model?: string; temperature?: number;
  };
}
export interface SkillExperiment extends ExperimentSummary {
  baseline_hash: string;
  source: { plan: { stage: string; objectives: string[] }; source_kind: string;
    messages: { role: string; content: string; turn_index: number }[]; memory_recorded: boolean };
  meta_skills: Record<string, { name: string }>;
  versions: ExperimentVersion[]; candidates: ExperimentCandidate[]; jobs: ExperimentJob[];
}
async function request<T>(path: string, payload?: unknown): Promise<T> {
  const response = await fetch(`/api/skill-experiments${path}`, payload === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data as T;
}
export const experimentApi = {
  status: () => request<{ enabled: boolean }>('/status'),
  sources: () => request<ExperimentSource[]>('/sources'),
  list: () => request<ExperimentSummary[]>(''),
  get: (id: string) => request<SkillExperiment>(`/${id}`),
  recover: (id: string) => request<SkillExperiment>(`/${id}/recover`, {}),
  create: (source: ExperimentSource) => request<SkillExperiment>('', { run_id: source.run_id, session_index: source.session_index }),
  job: (id: string, kind: string, version: number, options: Record<string, number> = {}) =>
    request<ExperimentJob>(`/${id}/jobs`, { kind, version, ...options }),
  apply: (id: string, candidate: string) => request<SkillExperiment>(`/${id}/candidates/${candidate}/apply`, {}),
  select: (id: string, version: number) => request<SkillExperiment>(`/${id}/versions/${version}/select`, {}),
};
