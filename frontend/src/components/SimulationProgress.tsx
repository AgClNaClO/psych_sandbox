import { useEffect, useState } from 'react';
import { Activity, AlertCircle, CheckCircle2, Clock3, WifiOff } from 'lucide-react';
import type { JobItem, RunDetail, SimulationProgress as Progress } from '../types';
import { elapsedText, progressView } from '../utils/progress';
import './SimulationProgress.css';

interface Props {
  job?: JobItem;
  run: RunDetail | null;
  progress?: Progress | null;
  connected: boolean;
  experiments: { id: string; label: string }[];
  onSelect: (id: string) => void;
}

export function SimulationProgress({ job, run, progress, connected, experiments, onSelect }: Props) {
  const view = progressView(job, run, progress);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!view.running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [view.running]);
  const state = view.progress;
  const updated = state ? Date.parse(state.updated_at) : NaN;
  const elapsed = (state?.elapsed ?? 0) + (view.running && Number.isFinite(updated) ? Math.max(0, now - updated) / 1000 : 0);
  const percent = view.total ? Math.min(100, view.completed / view.total * 100) : 0;
  const Icon = view.success ? CheckCircle2 : view.error ? AlertCircle : view.running ? Activity : Clock3;
  const candidates = state?.candidates ?? [];
  const scoring = state?.scoring;

  return <section className={`simulation-progress ${view.running ? 'is-running' : view.success ? 'is-complete' : view.error ? 'is-error' : 'is-stopped'}`} aria-label="实验进度">
    <div className="simulation-progress-heading">
      <div className="simulation-progress-title" role="status"><Icon size={14} />
        <strong>{view.title}</strong>
        {view.running && state && state.session_index > 0 && ['planning', 'generating', 'scoring', 'consolidating'].includes(view.phase)
          && <span>第 {state.session_index} 场{view.total ? ` / ${view.total}` : ''}</span>}
      </div>
      <div className="simulation-progress-meta">
        <span>{view.completed}{view.total ? ` / ${view.total}` : ''} 场已提交</span>
        {state && <span title="本次执行已用时间"><Clock3 size={11} />{elapsedText(elapsed)}</span>}
        {view.running && !connected && <span className="progress-reconnecting" title="正在重新连接进度，后台实验继续运行"><WifiOff size={12} />重新连接</span>}
        {experiments.length > 1 && <select aria-label="选择实验进度" value={job?.job_id ?? ''} onChange={event => onSelect(event.target.value)}>
          {!job && <option value="">当前运行</option>}
          {experiments.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>}
      </div>
    </div>
    {view.total && <div className="simulation-progress-track" role="progressbar" aria-label="已提交会谈" aria-valuemin={0} aria-valuemax={view.total}
      aria-valuenow={Math.min(view.completed, view.total)} aria-valuetext={`${view.completed}/${view.total} 场已提交`}>
      <span style={{ width: `${percent}%` }} />
    </div>}
    {view.running && view.showGeneration && <div className="candidate-progress-list">
      {candidates.slice(0, 4).map((item, index) => <div className="candidate-progress" key={item.label || index}>
        <span>{item.label ? `候选 ${item.label}` : '当前会谈'}</span><strong>{item.turn_index}/{item.total_turns} 轮上限</strong>
        <i><span style={{ width: `${Math.min(100, item.turn_index / Math.max(1, item.total_turns) * 100)}%` }} /></i>
      </div>)}
      {(state?.candidates_total ?? 1) > 4 && <span className="more-candidates">共 {state!.candidates_total} 个候选 · 已生成 {candidates.reduce((sum, item) => sum + item.turn_index, 0)} 轮</span>}
    </div>}
    {view.running && view.showScoring && scoring && <div className="scoring-progress">
      <span>{scoring.instruments_total > 0 ? `量表 ${scoring.instruments_done}/${scoring.instruments_total}` : `候选 ${scoring.candidates_scored}/${scoring.candidates_total}`}</span>
      <div><span style={{ width: `${Math.min(100, scoring.instruments_total > 0 ? scoring.instruments_done / scoring.instruments_total * 100 : scoring.candidates_scored / Math.max(1, scoring.candidates_total) * 100)}%` }} /></div>
      <span>已评估 {scoring.candidates_scored}/{scoring.candidates_total} 个候选</span>
      {scoring.eta > 0 && <span>约余 {elapsedText(scoring.eta)}</span>}
    </div>}
    {view.running && !state && <p className="simulation-progress-caption">{view.status === 'queued' ? '任务开始后，这里会显示会谈、候选与评估进度。' : '正在同步当前阶段，已提交的会谈可在下方查看。'}</p>}
    {job?.error && <p className="simulation-progress-error" role="alert">{job.error}</p>}
    {view.success && view.total && view.completed < view.total && <p className="simulation-progress-caption">疗程已提前结束，实际完成 {view.completed} 场。</p>}
  </section>;
}
