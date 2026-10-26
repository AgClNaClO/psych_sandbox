// 科研 Web 工作台后端 API 客户端与 SSE 封装

import type {
  CaseSummary,
  ComparisonRow,
  Course,
  CourseSessionDetail,
  ExportAudit,
  JobItem,
  RunDetail,
  RunSummary,
  SkillProposal,
  SkillRelease,
  TherapyDefinition,
} from '../types';

const API_BASE = '/api';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    let errDetail = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      if (data.detail) {
        errDetail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore
    }
    throw new Error(errDetail);
  }
  return response.json();
}

export const api = {
  // 1. 实验台
  getTherapies: () => request<TherapyDefinition[]>('/therapies'),
  getCases: () => request<CaseSummary[]>('/cases'),
  getRuns: () => request<RunSummary[]>('/runs'),
  getRunDetail: (runId: string) => request<RunDetail>(`/runs/${runId}`),
  createSimulationJob: (payload: {
    case_id: string;
    therapy?: string;
    session_count?: number;
    seed?: number;
    resume_run_id?: string;
  }) =>
    request<JobItem>('/jobs', {
      method: 'POST',
      body: JSON.stringify({
        kind: 'simulation',
        lane: 'long',
        payload,
      }),
    }),
  getJobs: (lane?: 'long' | 'short') =>
    request<JobItem[]>(lane ? `/jobs?lane=${lane}` : '/jobs'),
  stopJob: (jobId: string) =>
    request<{ status: string; job_id: string }>(`/jobs/${jobId}/stop`, { method: 'POST' }),
  cancelJob: (jobId: string) =>
    request<{ status: string; job_id: string }>(`/jobs/${jobId}/cancel`, { method: 'POST' }),

  // 2. 人工聊天
  getCourses: () => request<Course[]>('/courses'),
  createCourse: (data: {
    therapy: string;
    title: string;
    input_mode: 'natural' | 'roleplay';
    roleplay_card?: string;
    skill_release_id?: string;
  }) =>
    request<Course>('/courses', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getCourse: (courseId: string) => request<Course>(`/courses/${courseId}`),
  startNextSession: (courseId: string) =>
    request<CourseSessionDetail>(`/courses/${courseId}/sessions`, { method: 'POST' }),
  getSessionDetail: (courseId: string, sessionIndex: number) =>
    request<CourseSessionDetail>(`/courses/${courseId}/sessions/${sessionIndex}`),
  triggerOpening: (courseId: string, sessionIndex: number, operationId: string, expectedVersion: number) =>
    request(`/courses/${courseId}/sessions/${sessionIndex}/opening?operation_id=${operationId}&expected_version=${expectedVersion}`, {
      method: 'POST',
    }),
  sendMessage: (
    courseId: string,
    sessionIndex: number,
    data: {
      message_id: string;
      operation_id: string;
      expected_version: number;
      content: string;
      source?: 'participant_natural' | 'participant_roleplay';
    }
  ) =>
    request<{ message: any; operation: any }>(`/courses/${courseId}/sessions/${sessionIndex}/messages`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  closeCurrentSession: (courseId: string, sessionIndex: number, operationId: string, expectedVersion: number) =>
    request(`/courses/${courseId}/sessions/${sessionIndex}/close?operation_id=${operationId}&expected_version=${expectedVersion}`, {
      method: 'POST',
    }),
  resetSessionLock: (courseId: string, sessionIndex: number) =>
    request<{ status: string; unlocked_operations: number }>(`/courses/${courseId}/sessions/${sessionIndex}/reset-lock`, {
      method: 'POST',
    }),
  closeCourse: (courseId: string, reason = 'participant_closed_course') =>
    request<Course>(`/courses/${courseId}/close?reason=${reason}`, { method: 'POST' }),

  // 3. 技能实验室
  getSkillReleases: (therapy?: string) =>
    request<SkillRelease[]>(therapy ? `/skills/releases?therapy=${therapy}` : '/skills/releases'),
  getSkillRelease: (releaseId: string) => request<SkillRelease>(`/skills/releases/${releaseId}`),
  rollbackRelease: (releaseId: string, therapy: string) =>
    request<SkillRelease>(`/skills/releases/${releaseId}/rollback?therapy=${therapy}`, { method: 'POST' }),
  getProposals: (therapy?: string) =>
    request<SkillProposal[]>(therapy ? `/skills/proposals?therapy=${therapy}` : '/skills/proposals'),
  submitProposal: (data: any) =>
    request<SkillProposal>('/skills/proposals', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getProposal: (id: string) => request<SkillProposal>(`/skills/proposals/${id}`),
  reviewProposal: (
    proposalId: string,
    data: {
      reviewer_id: string;
      reviewer_name: string;
      verdict: 'approve' | 'reject' | 'revise';
      rationale: string;
      checklist: Record<string, boolean>;
    }
  ) =>
    request(`/skills/proposals/${proposalId}/reviews`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  publishProposal: (proposalId: string, publishedBy: string, releaseName: string) =>
    request<SkillRelease>(
      `/skills/proposals/${proposalId}/publish?published_by=${encodeURIComponent(
        publishedBy
      )}&release_name=${encodeURIComponent(releaseName)}`,
      { method: 'POST' }
    ),
  getSkillTree: (therapy: string) => request<any>(`/skills/tree/${therapy}`),

  // 4. 评测中心与数据导出
  getComparisons: () => request<ComparisonRow[]>('/analytics/comparisons'),
  exportSFT: (data: { run_ids?: string[]; include_interactive?: boolean; output_filename?: string }) =>
    request<ExportAudit>('/exports/sft', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  exportDPO: (data: { run_ids?: string[]; output_filename?: string }) =>
    request<ExportAudit>('/exports/dpo', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getExportAudits: () => request<ExportAudit[]>('/exports/audits'),
};

/**
 * 订阅后端 SSE 事件
 */
export function subscribeSSE(
  stream: string,
  onEvent: (event: { seq: number; type: string; payload: any }) => void,
  onError?: (err: any) => void,
  onOpen?: () => void
): () => void {
  const url = `${API_BASE}/events?stream=${encodeURIComponent(stream)}`;
  const es = new EventSource(url);

  es.onopen = () => {
    if (onOpen) onOpen();
  };

  es.addEventListener('connected', () => {
    if (onOpen) onOpen();
  });

  es.addEventListener('ping', () => {
    if (onOpen) onOpen();
  });

  es.onmessage = (e) => {
    try {
      const payload = JSON.parse(e.data);
      const seq = e.lastEventId ? parseInt(e.lastEventId, 10) : 0;
      onEvent({ seq, type: e.type || 'message', payload });
    } catch {
      // ignore
    }
  };

  const eventTypes = [
    'simulation_progress',
    'message_submitted',
    'counselor_replied',
    'session_closed',
    'close_requested',
    'operation_failed',
    'operation_succeeded',
    'job_failed',
    'job_succeeded',
  ];

  eventTypes.forEach((type) => {
    es.addEventListener(type, (e: any) => {
      try {
        const payload = JSON.parse(e.data);
        const seq = e.lastEventId ? parseInt(e.lastEventId, 10) : 0;
        onEvent({ seq, type, payload });
      } catch {
        onEvent({ seq: 0, type, payload: e.data });
      }
    });
  });

  es.onerror = (err) => {
    // 仅在明确彻底关闭时才通知断开；如果处于自动重连中则等待重连握手
    if (es.readyState === EventSource.CLOSED) {
      if (onError) onError(err);
    }
  };

  return () => {
    es.close();
  };
}
