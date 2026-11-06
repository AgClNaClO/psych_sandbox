import type { RunDetail, SimulationJobPayload } from '../types.ts';

export function getSessionResumePayload(run: RunDetail): (SimulationJobPayload & { session_count: number }) | null {
  const total = run.requested_sessions;
  if (!['stopped', 'failed'].includes(run.status)
      || typeof total !== 'number' || !Number.isInteger(total) || total < 1 || total > 100
      || total < run.sessions.length
      || run.sessions.at(-1)?.longitudinal_report?.stage_action === 'close') return null;

  // Omit new-experiment settings: the worker restores the saved configuration.
  return {
    case_id: run.case_id,
    therapy: run.therapy,
    seed: run.seed,
    session_count: total,
    resume_run_id: run.run_id,
  };
}
