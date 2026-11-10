import type { JobItem, RunDetail, SimulationProgress } from '../types.ts';

export const phaseLabels: Record<string, string> = {
  preparing: '准备实验', planning: '准备会谈', generating: '生成对话', scoring: '候选评估',
  consolidating: '会后整理', committed: '会谈已提交', holistic: '全程督导',
  report: '生成报告', finished: '保存轨迹', failed: '执行中断',
};

export function newerProgress(a?: SimulationProgress | null, b?: SimulationProgress | null): SimulationProgress | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return b.attempt > a.attempt || (b.attempt === a.attempt && b.revision > a.revision) ? b : a;
}

export function progressView(job?: JobItem, run?: RunDetail | null, live?: SimulationProgress | null) {
  const runId = job?.run_id ?? job?.result?.run_id;
  const relatedRun = !job || run?.run_id === runId ? run : null;
  const latest = newerProgress(job?.progress, live);
  const progress = latest && (!job || latest.attempt >= job.attempt) ? latest : null;
  const status = relatedRun?.status === 'safety_hold' ? 'safety_hold' : job?.status ?? relatedRun?.status ?? 'queued';
  const running = status === 'running' || status === 'queued';
  const total = progress?.sessions_total ?? job?.payload.session_count ?? relatedRun?.requested_sessions ?? null;
  const completed = Math.max(progress?.sessions_completed ?? 0, relatedRun?.sessions.length ?? 0, job?.result?.sessions_completed ?? 0);
  const phase = progress?.phase ?? 'preparing';
  const labels: Record<string, string> = { succeeded: '实验已完成', completed: '实验已完成',
    failed: '实验失败', stopped: '已在会谈边界停止', cancelled: '实验已取消', safety_hold: '安全暂停' };
  let title = labels[status] ?? (progress ? phaseLabels[phase] : null) ?? '实验进行中';
  if (status === 'queued') title = '排队等待执行';
  if (running && job?.stop_requested) title = '等待当前会谈提交后停止';
  if (running && job?.cancel_requested) title = '正在取消实验';
  return { progress, status, running, total: typeof total === 'number' && total > 0 ? total : null,
    completed: Math.max(0, completed), phase, title,
    success: status === 'succeeded' || status === 'completed',
    error: status === 'failed' || status === 'safety_hold' };
}

export function elapsedText(seconds: number): string {
  const elapsed = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(elapsed / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}时${minutes % 60}分` : minutes > 0 ? `${minutes}分${elapsed % 60}秒` : `${elapsed}秒`;
}
