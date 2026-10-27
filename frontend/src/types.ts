// 科研 Web 工作台统一前端类型定义

export type TherapyId = 'behavioral' | 'cbt' | 'humanistic_existential' | 'psychodynamic' | 'postmodern';

export interface StageInfo {
  stage_id: string;
  name: string;
  description: string;
}

export interface TherapyDefinition {
  therapy: TherapyId;
  name: string;
  description: string;
  stages: StageInfo[];
  instruments: string[];
}

export interface CaseSummary {
  case_id: string;
  therapy: string;
  title: string;
  client_name: string;
  client_gender: string;
  client_age: number | null;
  client_occupation: string | null;
  summary: string;
  available_sessions: number;
}

export interface RunSummary {
  run_id: string;
  case_id: string;
  therapy: string;
  provider: string;
  seed: number;
  status: 'running' | 'completed' | 'stopped' | 'failed' | 'safety_hold';
  completed_sessions: number;
  created_at: string;
  completed_at: string | null;
  has_html_report: boolean;
  holistic_score: number | null;
}

export interface SkillEvidenceItem {
  skill_id: string;
  evidence_quote: string;
  reason: string;
}

export interface ProjectedTurn {
  turn_index: number;
  client_utterance?: string;
  counselor_response?: string;
  counselor_plan_summary?: string;
  chosen_skills?: string[];
  skill_evidence?: SkillEvidenceItem[];
  safety_events?: any[];
  context_snapshot_available?: boolean;
}

export interface ProjectedSession {
  session_index: number;
  plan?: any;
  summary?: string;
  clinical_summary?: any;
  counselor_review?: any;
  longitudinal_report?: any;
  safety_verdict?: any;
  turns: ProjectedTurn[];
  memory_snapshot?: any;
  end_reason?: string;
}

export interface RunDetail {
  run_id: string;
  case_id: string;
  therapy: string;
  provider: string;
  seed: number;
  status: string;
  created_at: string;
  completed_at: string | null;
  sessions: ProjectedSession[];
  holistic_report?: any;
  rft_batches?: any[];
  config: Record<string, any>;
}

export interface JobItem {
  job_id: string;
  kind: string;
  lane: 'long' | 'short';
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'stopped' | 'cancelled';
  payload: Record<string, any>;
  attempt: number;
  max_attempts: number;
  stop_requested: boolean;
  cancel_requested: boolean;
  result?: any;
  error?: string | null;
  run_id?: string | null;
  course_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Course {
  course_id: string;
  therapy: string;
  title: string;
  input_mode: 'natural' | 'roleplay';
  roleplay_card: string | null;
  status: 'active' | 'closed';
  close_reason: string | null;
  skill_release_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  completed_sessions: number;
  current_session: number;
}

export interface CourseMessage {
  message_id: string;
  course_id: string;
  session_index: number;
  role: 'counselor' | 'participant' | 'system';
  source: 'participant_natural' | 'participant_roleplay' | 'counselor' | 'system';
  content: string;
  metadata?: Record<string, any>;
  created_at: string;
}

export interface CloseStepRecord {
  step_name: string;
  status: 'succeeded' | 'failed' | 'skipped';
  input_summary: Record<string, any>;
  output?: Record<string, any> | null;
  error?: string | null;
  created_at: string;
}

export interface OperationRecord {
  operation_id: string;
  course_id: string;
  session_index: number;
  kind: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  expected_version: number;
  payload: Record<string, any>;
  result?: Record<string, any> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CourseSessionDetail {
  course_id: string;
  course_version?: number;
  session_index: number;
  status: 'open' | 'closing' | 'closed' | 'close_failed';
  plan: Record<string, any>;
  memory_before: Record<string, any>;
  memory_after?: Record<string, any> | null;
  next_plan?: Record<string, any> | null;
  review?: Record<string, any> | null;
  close_reason?: string | null;
  created_at: string;
  closed_at?: string | null;
  messages: CourseMessage[];
  close_steps: CloseStepRecord[];
  active_operation?: OperationRecord | null;
  last_operation?: OperationRecord | null;
}

export interface SkillRelease {
  release_id: string;
  therapy: string;
  name: string;
  description: string;
  tree_hash: string;
  parent_release_id?: string | null;
  overlay_skills: Record<string, any>;
  created_by: string;
  created_at: string;
  is_active: boolean;
}

export interface SkillProposal {
  proposal_id: string;
  therapy: string;
  base_release_id: string;
  title: string;
  target_skill_id?: string | null;
  parent_meta_id: string;
  stage: string;
  content: {
    name: string;
    description: string;
    timing: string;
    triggers: string[];
    [key: string]: any;
  };
  status: 'draft' | 'validated' | 'replayed' | 'simulated' | 'reviewed' | 'approved' | 'rejected' | 'published';
  justification: string;
  author: string;
  validation_summary: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ComparisonRow {
  run_id: string;
  case_id: string;
  therapy: string;
  status: string;
  sessions_completed: number;
  model_supervisor_score: number | null;
  human_feedback_score: number | null;
  auto_sim_score: number | null;
  cost_estimate_cny: number | null;
  latency_sec_avg: number | null;
  failure_rate: number;
  created_at: string;
}

export interface ExportAudit {
  export_id: string;
  export_type: 'sft' | 'dpo';
  criteria: Record<string, any>;
  output_path: string;
  row_count: number;
  split_info: Record<string, number>;
  sha256: string;
  created_by: string;
  created_at: string;
}
