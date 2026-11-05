import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, subscribeSSE } from '../services/api';
import type { CaseSummary, JobItem, RunDetail, RunSummary } from '../types';
import {
  Play, Square, XCircle, RotateCcw, FileText, FlaskConical, History,
  MessageSquare, ChevronDown, ChevronRight, PanelRightOpen, Settings2,
  Terminal, ShieldCheck, BookOpen, Brain, X, Check, Circle,
} from 'lucide-react';
import { getReplayMessages } from '../utils/replay';
import './SimulationHub.css';

const therapyNames: Record<string, string> = {
  bt: '行为治疗', cbt: '认知行为', het: '人本存在', pdt: '精神动力', pmt: '后现代',
};
const statusLabels: Record<string, string> = {
  completed: '已完成', running: '运行中', stopped: '已停止', failed: '失败',
  safety_hold: '安全暂停', queued: '排队中', succeeded: '已完成', cancelled: '已取消',
};
const statusTone = (status?: string) =>
  ['completed', 'succeeded'].includes(status ?? '') ? 'success'
  : ['running', 'queued'].includes(status ?? '') ? 'info'
  : ['stopped', 'cancelled'].includes(status ?? '') ? 'neutral' : 'warning';
const formatScore = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';

interface SimulationHubProps {
  observerMode?: boolean;
}

const normalizeTherapy = (th?: string): string => {
  if (!th) return '';
  const s = th.toLowerCase().trim().replace('-', '_');
  if (s === 'bt' || s === 'behavioral') return 'bt';
  if (s === 'cbt') return 'cbt';
  if (s === 'het' || s === 'humanistic_existential') return 'het';
  if (s === 'pdt' || s === 'psychodynamic') return 'pdt';
  if (s === 'pmt' || s === 'postmodern') return 'pmt';
  return s;
};

export const SimulationHub: React.FC<SimulationHubProps> = ({ observerMode = false }) => {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<RunDetail | null>(null);
  const [selectedSessionIdx, setSelectedSessionIdx] = useState<number>(1);
  const [selectedTurnIdx, setSelectedTurnIdx] = useState<number | null>(null);

  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const sessionTabsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const closePanels = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setInspectorOpen(false); setConfigOpen(false); }
    };
    window.addEventListener('keydown', closePanels);
    return () => window.removeEventListener('keydown', closePanels);
  }, []);

  // 运行参数
  const [selectedCaseId, setSelectedCaseId] = useState<string>('');
  const [therapyFilter, setTherapyFilter] = useState<string>('all');
  const [sessionCount, setSessionCount] = useState<number>(3);
  const [seed, setSeed] = useState<number>(42);
  const [maxTurns, setMaxTurns] = useState(20);
  const [individualLimits, setIndividualLimits] = useState(false);
  const [turnLimits, setTurnLimits] = useState<number[]>([]);
  const [rftEnabled, setRftEnabled] = useState(false);
  const [candidates, setCandidates] = useState(3);
  const [defaultsReady, setDefaultsReady] = useState(false);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [connected, setConnected] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const trackedJob = jobs.find((job) => job.job_id === activeJobId);
  const jobRunning = trackedJob?.status === 'queued' || trackedJob?.status === 'running';

  const fetchRuns = useCallback(() => {
    return api.getRuns().then((data) => {
      setRuns(data);
      setSelectedRunId((current) => current ?? data[0]?.run_id ?? null);
    }).catch((error: Error) => setErrorMsg(error.message));
  }, []);

  // 加载初始数据
  useEffect(() => {
    let cancelled = false;
    api.getSimulationDefaults().then((data) => {
      if (cancelled) return;
      setMaxTurns(data.max_turns_per_session);
      setRftEnabled(data.rft.enabled);
      setCandidates(data.rft.candidates);
      setDefaultsReady(true);
    }).catch((error: Error) => { if (!cancelled) setErrorMsg(error.message); });
    api.getCases().then((data) => {
      setCases(data);
      if (data.length > 0) setSelectedCaseId(data[0].case_id);
    }).catch(console.error);
    fetchRuns();
    return () => { cancelled = true; };
  }, [fetchRuns]);

  // Restore from the durable job list, including a job that completed while away.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const data = (await api.getJobs('long')).filter((job) => job.kind === 'simulation');
        let saved: string | null = null;
        try { saved = localStorage.getItem('simulationJobId'); } catch { /* storage unavailable */ }
        if (saved && !data.some((job) => job.job_id === saved)) {
          // The restored job can be older than the list endpoint's latest page.
          try {
            const job = await api.getJob(saved);
            if (job.kind === 'simulation') data.push(job);
          } catch { /* deleted or inaccessible job; fall back to the live list */ }
        }
        if (cancelled) return;
        setJobs(data);
        setActiveJobId((current) => {
          if (current) return current;
          return data.find((job) => job.job_id === saved)?.job_id
            ?? data.find((job) => ['queued', 'running'].includes(job.status))?.job_id ?? null;
        });
      } catch (error) {
        if (!cancelled) setErrorMsg((error as Error).message);
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!activeJobId) return;
    try { localStorage.setItem('simulationJobId', activeJobId); } catch { /* storage unavailable */ }
  }, [activeJobId]);

  const trackedRunId = trackedJob?.run_id ?? trackedJob?.result?.run_id;
  useEffect(() => {
    if (!trackedRunId) return;
    let cancelled = false;
    api.getRunDetail(trackedRunId).then((data) => {
      if (!cancelled) {
        setSelectedRunId(trackedRunId);
        setSelectedRunDetail(data);
      }
    }).catch(console.error);
    void fetchRuns();
    return () => { cancelled = true; };
  }, [trackedRunId, trackedJob?.updated_at, fetchRuns]);

  // 加载选中运行详情
  useEffect(() => {
    if (!selectedRunId) {
      return;
    }
    let cancelled = false;
    api.getRunDetail(selectedRunId).then((data) => {
      if (cancelled) return;
      setSelectedRunDetail(data);
      if (data.sessions.length > 0) {
        setSelectedSessionIdx(data.sessions[0].session_index);
        setSelectedTurnIdx(null);
      }
    }).catch((error: Error) => { if (!cancelled) setErrorMsg(error.message); });
    return () => { cancelled = true; };
  }, [selectedRunId]);

  // SSE 实时进度监听
  useEffect(() => {
    // Reset the view when attaching to a different external event stream.
    // oxlint-disable-next-line react/set-state-in-effect
    setLiveLogs([]);
    if (!activeJobId) return;
    setConnected(false);
    const unsub = subscribeSSE(`job:${activeJobId}`, (event) => {
      if (event.type === 'simulation_progress') {
        setLiveLogs((prev) => [...prev.slice(-100), event.payload.message]);
      }
      if (['job_succeeded', 'job_stopped', 'job_failed', 'job_cancelled'].includes(event.type)) {
        setJobs((prev) => prev.map((job) => job.job_id === activeJobId
          ? { ...job, status: event.type === 'job_succeeded' ? 'succeeded' : event.type === 'job_stopped' ? 'stopped' : event.type === 'job_failed' ? 'failed' : 'cancelled' }
          : job));
        if (event.type === 'job_failed') setErrorMsg(event.payload.error || '任务失败');
        fetchRuns();
        if (event.payload.run_id) {
          setSelectedRunId(event.payload.run_id);
          api.getRunDetail(event.payload.run_id).then(setSelectedRunDetail).catch(console.error);
        }
      }
    }, () => setConnected(false), () => setConnected(true));
    return unsub;
  }, [activeJobId, fetchRuns]);

  const handleStartSimulation = async (resumeId?: string) => {
    try {
      setLoading(true);
      setErrorMsg(null);
      setLiveLogs([]);
      const resumeRun = resumeId ? runs.find((run) => run.run_id === resumeId) : undefined;
      const job = await api.createSimulationJob({
        case_id: resumeRun?.case_id ?? selectedCaseId,
        therapy: resumeRun?.therapy,
        session_count: sessionCount,
        seed: resumeRun?.seed ?? seed,
        resume_run_id: resumeId,
        ...(!resumeId ? {
          max_turns_per_session: maxTurns,
          session_turn_limits: individualLimits ? Array.from({ length: sessionCount }, (_, i) => turnLimits[i] ?? maxTurns) : undefined,
          rft: { enabled: rftEnabled, candidates },
        } : {}),
      });
      setConfigOpen(false);
      setJobs((prev) => [job, ...prev]);
      setSelectedRunId(job.run_id ?? null);
      setSelectedRunDetail(null);
      setActiveJobId(job.job_id);
      setLiveLogs([`任务已提交至后台 Long Lane (ID: ${job.job_id})...`]);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleStopAtBoundary = async () => {
    if (!activeJobId) return;
    try {
      await api.stopJob(activeJobId);
      setLiveLogs((prev) => [...prev, '>>> 已发送在会谈边界停止请求，等待当前会谈提交后退出...']);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleCancelJob = async () => {
    if (!activeJobId) return;
    try {
      await api.cancelJob(activeJobId);
      setLiveLogs((prev) => [...prev, '>>> 已发送立即取消请求...']);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const currentSession = selectedRunDetail?.run_id === selectedRunId
    ? selectedRunDetail.sessions.find((s) => s.session_index === selectedSessionIdx) : undefined;
  const currentTurn = currentSession?.turns.find((t) => t.turn_index === selectedTurnIdx);

  useEffect(() => {
    const tabs = sessionTabsRef.current;
    if (!tabs) return;
    const revealSelectedSession = () => {
      const active = tabs.querySelector('.session-tab.active');
      if (!active) return;
      const item = active.getBoundingClientRect();
      const viewport = tabs.getBoundingClientRect();
      if (item.left < viewport.left) tabs.scrollLeft += item.left - viewport.left;
      else if (item.right > viewport.right) tabs.scrollLeft += item.right - viewport.right;
    };
    const observer = new ResizeObserver(revealSelectedSession);
    observer.observe(tabs);
    revealSelectedSession();
    return () => observer.disconnect();
  }, [selectedSessionIdx, selectedRunId, selectedRunDetail?.run_id, selectedRunDetail?.sessions.length]);

  const runSummary = runs.find((run) => run.run_id === selectedRunId);
  const displayedRun = selectedRunDetail?.run_id === selectedRunId ? selectedRunDetail : null;
  const runCase = cases.find((item) => item.case_id === (displayedRun?.case_id ?? runSummary?.case_id));
  const filteredCases = cases.filter((item) => therapyFilter === 'all' || normalizeTherapy(item.therapy) === therapyFilter);
  const report = displayedRun?.holistic_report;
  const scales: { label: string; score: number; role: string }[] = [];
  for (const [group, role] of [[report?.counselor_specific, 'counselor'], [report?.counselor_shared, 'shared'], [report?.client_specific, 'client']] as const) {
    for (const item of group ?? []) {
      if (item?.name && typeof item.score === 'number'
        && (role !== 'shared' || ['wai', 'htais', 'rro'].includes(item.name))) {
        scales.push({ label: item.name.toUpperCase(), score: item.score, role });
      }
    }
  }

  return (
    <div className={`three-column-container simulation-workspace ${inspectorOpen ? 'inspector-open' : ''} ${configOpen ? 'config-open' : ''}`}>
      {(inspectorOpen || configOpen) && <button className="workspace-scrim" aria-label="关闭侧栏"
        onClick={() => { setInspectorOpen(false); setConfigOpen(false); }} />}

      <aside id="simulation-config" className="column-left sim-sidebar" aria-label="实验配置与历史记录">
        <div className="sim-panel-heading">
          <span className="panel-heading-icon"><FlaskConical size={18} /></span>
          <div><h2>实验配置</h2><p>设置参数，开始一次仿真</p></div>
          <button className="icon-button config-close" aria-label="关闭实验配置" onClick={() => setConfigOpen(false)}><X size={17} /></button>
        </div>
        <div className="column-body sim-sidebar-body">
          <section className="sim-config" aria-label="新建仿真实验">
            <div className="sim-config-fields">
              <div className="sim-field therapy-filter-field">
                <div className="field-label-row"><label htmlFor="therapy-filter">案例库</label><span>{cases.length} 个案例</span></div>
                <select id="therapy-filter" value={therapyFilter} onChange={(event) => {
                  const filter = event.target.value;
                  setTherapyFilter(filter);
                  const matching = cases.filter((item) => filter === 'all' || normalizeTherapy(item.therapy) === filter);
                  if (!matching.some((item) => item.case_id === selectedCaseId)) setSelectedCaseId(matching[0]?.case_id ?? '');
                }}>
                  <option value="all">全部流派</option>
                  {Object.entries(therapyNames).map(([id, name]) => <option key={id} value={id}>
                    {id.toUpperCase()} · {name}（{cases.filter((item) => normalizeTherapy(item.therapy) === id).length}）
                  </option>)}
                </select>
              </div>
              <div className="sim-field">
                <label htmlFor="simulation-case">来访者案例</label>
                <select id="simulation-case" value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)}>
                  {filteredCases.length === 0 && <option value="">暂无可用案例</option>}
                  {Object.entries(therapyNames).map(([id, name]) => {
                    const group = filteredCases.filter((item) => normalizeTherapy(item.therapy) === id);
                    return group.length > 0 && <optgroup key={id} label={`${id.toUpperCase()} · ${name}`}>
                      {group.map((item) => <option key={item.case_id} value={item.case_id}>[{id.toUpperCase()}] {item.title} ({item.case_id})</option>)}
                    </optgroup>;
                  })}
                </select>
              </div>
              <div className="sim-field-grid">
                <div className="sim-field">
                  <label htmlFor="session-count">会谈次数</label>
                  <input id="session-count" type="number" min={1} max={100} value={sessionCount}
                    onChange={(event) => setSessionCount(Math.min(100, Math.max(1, parseInt(event.target.value) || 1)))} />
                </div>
                <div className="sim-field">
                  <label htmlFor="simulation-seed">随机种子</label>
                  <input id="simulation-seed" type="number" value={seed} onChange={(event) => setSeed(parseInt(event.target.value) || 0)} />
                </div>
              </div>
              <div className="sim-field">
                <div className="field-label-row"><label htmlFor="max-turns">每场轮数上限</label><span>1–50 轮</span></div>
                <input id="max-turns" aria-label="每场轮数上限" type="number" min={1} max={50} value={maxTurns}
                  onChange={(event) => setMaxTurns(Math.min(50, Math.max(1, parseInt(event.target.value) || 1)))} />
                <p className="field-help">咨询师可根据会谈进展提前结束。</p>
              </div>
              <label className="check-field">
                <input type="checkbox" checked={individualLimits} onChange={(event) => setIndividualLimits(event.target.checked)} />逐场设置轮数上限
              </label>
              {individualLimits && <div className="session-limit-list">
                {Array.from({ length: sessionCount }, (_, index) => <label key={index}>第 {index + 1} 场
                  <input aria-label={`第${index + 1}场轮数上限`} type="number" min={1} max={50} value={turnLimits[index] ?? maxTurns}
                    onChange={(event) => setTurnLimits((previous) => {
                      const next = [...previous];
                      next[index] = Math.min(50, Math.max(1, parseInt(event.target.value) || 1));
                      return next;
                    })} />
                </label>)}
              </div>}
              <div className="rft-setting">
                <label className="check-field"><input type="checkbox" checked={rftEnabled} onChange={(event) => setRftEnabled(event.target.checked)} />
                  <span>RFT 会谈候选选优</span><span className="small-label">可选</span>
                </label>
                {rftEnabled && <>
                  <div className="rft-candidates"><label htmlFor="rft-candidates">每场候选数</label>
                    <input id="rft-candidates" aria-label="RFT候选数" type="number" min={2} max={32} value={candidates}
                      onChange={(event) => setCandidates(Math.min(32, Math.max(2, parseInt(event.target.value) || 2)))} />
                  </div>
                  <p className="field-help">候选评分选优会增加 API 费用与耗时。</p>
                </>}
              </div>
            </div>
            <button className="btn btn-primary start-simulation" disabled={loading || observerMode || jobRunning || !defaultsReady || !selectedCaseId}
              onClick={() => handleStartSimulation()}>
              {loading ? <RotateCcw size={15} className="animate-spin" /> : <Play size={15} />}
              {observerMode ? '观察者模式' : loading ? '正在提交…' : jobRunning ? '实验进行中' : '启动后台实验'}
            </button>
            {errorMsg && <div className="sim-error" role="alert">{errorMsg}</div>}
          </section>

          <section className="sim-history" aria-label="历史运行记录">
            <div className="section-label"><History size={15} /><h3>历史运行</h3><span className="count-badge">{runs.length}</span>
              <button className="icon-button" onClick={fetchRuns} aria-label="刷新运行记录" title="刷新运行记录"><RotateCcw size={14} /></button>
            </div>
            <div className="sim-run-list">
              {runs.length === 0 && <p className="sidebar-empty">暂无运行记录，启动实验后会显示在这里。</p>}
              {runs.map((run) => <button key={run.run_id} className={`sim-run-card ${selectedRunId === run.run_id ? 'selected' : ''}`}
                aria-pressed={selectedRunId === run.run_id} onClick={() => {
                  setSelectedRunId(run.run_id);
                  setActiveJobId(jobs.find((job) => job.run_id === run.run_id || job.result?.run_id === run.run_id)?.job_id ?? null);
                  setConfigOpen(false);
                }}>
                <div className="run-card-title"><strong>{cases.find((item) => item.case_id === run.case_id)?.title ?? run.case_id}</strong>
                  <span className={`tag tag-${statusTone(run.status)}`}>{statusLabels[run.status] ?? run.status}</span>
                </div>
                <div className="run-card-meta"><span>{normalizeTherapy(run.therapy).toUpperCase()}</span><span>{run.completed_sessions} 场会谈</span>
                  {run.holistic_score != null && <span>督导 {formatScore(run.holistic_score)}</span>}
                </div>
                <div className="run-card-id">{run.run_id}{selectedRunId === run.run_id && <Check size={13} />}</div>
              </button>)}
            </div>
          </section>
        </div>
      </aside>

      <section className="column-center sim-main" aria-label="运行现场与会谈回放">
        <header className="replay-heading">
          <div className="replay-heading-title">
            <div className="replay-eyebrow"><MessageSquare size={14} />运行现场 / 会谈回放</div>
            <div className="replay-title-row"><h1>{runCase?.title ?? (selectedRunId ? '仿真会谈' : '自动实验台')}</h1>
              {runSummary && <span className={`tag tag-${statusTone(runSummary.status)}`}>{statusLabels[runSummary.status] ?? runSummary.status}</span>}
            </div>
            {selectedRunId && <p className="replay-run-id">{selectedRunId}<span>·</span>{normalizeTherapy(displayedRun?.therapy ?? runSummary?.therapy).toUpperCase()}</p>}
          </div>
          <div className="replay-actions">
            <button className="btn btn-secondary config-toggle" aria-controls="simulation-config" aria-expanded={configOpen} onClick={() => { setConfigOpen(true); setInspectorOpen(false); }}><Settings2 size={14} />实验配置</button>
            {displayedRun?.status === 'stopped' && <button className="btn btn-secondary" onClick={() => handleStartSimulation(selectedRunId!)}
              disabled={loading || observerMode || jobRunning} title="沿用原实验的轮数上限与 RFT 配置"><RotateCcw size={13} />边界续跑</button>}
            <button className="btn btn-secondary" onClick={handleStopAtBoundary} disabled={!jobRunning || observerMode} title="在下一会谈开始前停止"><Square size={13} />边界停止</button>
            <button className="btn btn-quiet-danger" onClick={handleCancelJob} disabled={!jobRunning || observerMode}><XCircle size={14} />取消任务</button>
            {displayedRun && runSummary?.has_html_report && <a href={`/api/runs/${displayedRun.run_id}/report`} target="_blank" rel="noreferrer" className="btn btn-secondary report-link"><FileText size={14} />查看报告</a>}
            <button className="btn btn-secondary inspector-toggle" aria-controls="simulation-inspector" aria-expanded={inspectorOpen} onClick={() => { setInspectorOpen(!inspectorOpen); setConfigOpen(false); }}><PanelRightOpen size={14} />分析与督导</button>
          </div>
        </header>

        {displayedRun && displayedRun.sessions.length > 0 && <div className="session-navigation">
          <div ref={sessionTabsRef} className="session-tabs" role="group" aria-label="选择会谈">
            {displayedRun.sessions.map((session) => <button key={session.session_index} className={`session-tab ${selectedSessionIdx === session.session_index ? 'active' : ''}`}
              aria-pressed={selectedSessionIdx === session.session_index} onClick={() => { setSelectedSessionIdx(session.session_index); setSelectedTurnIdx(null); }}>
              <span className="session-tab-number">{String(session.session_index).padStart(2, '0')}</span>第 {session.session_index} 场
            </button>)}
          </div>
          <span className="session-total">共 {displayedRun.sessions.length} 场</span>
        </div>}

        {jobs.length > 0 && <div className="job-monitor">
          <div className="job-monitor-row"><Terminal size={14} /><label htmlFor="background-job">后台任务</label>
            <select id="background-job" aria-label="后台任务" value={activeJobId ?? ''} onChange={(event) => setActiveJobId(event.target.value || null)}>
              <option value="">选择任务查看进度</option>
              {jobs.map((job) => <option key={job.job_id} value={job.job_id}>{job.job_id} · {job.payload.case_id} · {statusLabels[job.status] ?? job.status}</option>)}
            </select>
            {trackedJob && <span className={`tag tag-${statusTone(trackedJob.status)}`}>{statusLabels[trackedJob.status] ?? trackedJob.status}</span>}
          </div>
          {activeJobId && <div className="job-monitor-caption"><span className={`monitor-dot ${connected ? 'connected' : ''}`} />
            {connected ? '进度已连接' : '进度连接中，自动重连'}<span>· 返回页面后自动恢复</span>
          </div>}
          {trackedJob?.error && <div className="sim-error" role="alert">{trackedJob.error}</div>}
          {liveLogs.length > 0 && <details className="progress-log">
            <summary><Terminal size={13} /><span>运行日志</span><span className="latest-log">{liveLogs[liveLogs.length - 1]}</span><ChevronDown size={14} /></summary>
            <div className="progress-log-content" aria-label="运行日志内容">{liveLogs.map((log, index) => <div key={index}>{log}</div>)}</div>
          </details>}
        </div>}

        <div className="column-body sim-transcript" key={`${selectedRunId}-${selectedSessionIdx}`}>
          {currentSession ? <>
            <div className="transcript-caption"><span>第 {currentSession.session_index} 场会谈<span className="caption-dot">·</span>{currentSession.turns.length} 轮对话</span><span>选择轮次，查看咨询师决策</span></div>
            <div className="messages-timeline replay-timeline">
              {currentSession.turns.map((turn) => <article key={turn.turn_index} className={`replay-turn ${selectedTurnIdx === turn.turn_index ? 'selected' : ''}`}>
                <button className="turn-selector" aria-label={`查看轮次 ${turn.turn_index} 的决策依据`} aria-pressed={selectedTurnIdx === turn.turn_index}
                  onClick={() => { setSelectedTurnIdx(turn.turn_index); setInspectorOpen(true); }}>
                  <span>轮次 {String(turn.turn_index).padStart(2, '0')}</span><span>{selectedTurnIdx === turn.turn_index ? '正在查看决策' : '查看决策'}<ChevronRight size={12} /></span>
                </button>
                {getReplayMessages(turn).map((message) => <div key={message.role} className={`replay-message ${message.role}`}>
                  <div className="speaker-avatar" aria-hidden="true">{message.role === 'counselor' ? '咨' : '访'}</div>
                  <div className="replay-message-content">
                    <div className="message-sender-label"><strong>{message.role === 'counselor' ? '咨询师' : '来访者'}</strong>
                      {message.role === 'counselor' && !!turn.chosen_skills?.length && <span className="message-skill-count" title={turn.chosen_skills.join('、')}><Brain size={11} />{turn.chosen_skills.length} 项技能</span>}
                    </div>
                    <div className={`message-bubble ${message.role}`}>{message.content}</div>
                  </div>
                </div>)}
              </article>)}
            </div>
            {currentSession.turns.length === 0 && <p className="sidebar-empty">本场会谈暂无已提交的对话。</p>}
            {currentSession.turns.length > 0 && <div className="transcript-end"><span />本场会谈记录结束<span /></div>}
          </> : <div className="simulation-empty">
            <div className="empty-state-icon"><MessageSquare size={28} strokeWidth={1.5} /></div>
            <h2>{selectedRunId ? '正在加载会谈记录' : '从一次会谈开始'}</h2>
            <p>{selectedRunId ? '正在读取已保存的轨迹与分析结果。' : '在左侧选择来访者案例并启动实验，或选择历史运行查看完整会谈。'}</p>
            <div className="empty-state-steps"><span><Circle size={10} />配置实验</span><ChevronRight size={12} /><span><Circle size={10} />回放会谈</span><ChevronRight size={12} /><span><Circle size={10} />查看督导</span></div>
            <button className="btn btn-primary config-toggle" onClick={() => setConfigOpen(true)}><Settings2 size={14} />配置实验</button>
          </div>}
        </div>
      </section>

      <aside id="simulation-inspector" className="column-right sim-inspector" aria-label="分析与督导">
        <div className="sim-panel-heading"><span className="panel-heading-icon inspector-icon"><ShieldCheck size={18} /></span>
          <div><h2>分析与督导</h2><p>规划、证据与全疗程评估</p></div>
          <button className="icon-button inspector-close" aria-label="关闭分析与督导" onClick={() => setInspectorOpen(false)}><X size={17} /></button>
        </div>
        <div className="column-body sim-inspector-body">
          {report && <section className="supervision-card" aria-label="整体督导报告">
            <div className="insight-card-title"><ShieldCheck size={15} /><h3>整体督导报告</h3><span className="small-label">全疗程</span></div>
            <div className="supervision-scores">
              <div><span>咨询师总督导分</span><p><strong>{formatScore(report.holistic_score ?? report.counselor_overall)}</strong><span>/ 10</span></p></div>
              <div><span>来访者评定</span><p><strong>{formatScore(report.client_score ?? report.client_overall)}</strong><span>/ 10</span></p></div>
            </div>
            {scales.length > 0 && <div className="scale-scores">{scales.map((scale, index) => <span key={index} className={`scale-score ${scale.role}`}><span>{scale.label}</span><strong>{formatScore(scale.score)}</strong></span>)}</div>}
            <details className="supervision-summary"><summary>评估摘要<ChevronDown size={13} /></summary><p>{report.summary || '暂无评估摘要。'}</p></details>
            <div className="supervision-source">PsychEvalSupervisor<span>· 完整轨迹后评分</span></div>
          </section>}

          <section className="insight-card turn-insight" aria-label="轮次决策">
            <div className="insight-card-title"><Brain size={15} /><h3>{currentTurn ? `轮次 ${String(currentTurn.turn_index).padStart(2, '0')} · 决策依据` : '咨询师决策依据'}</h3></div>
            {currentTurn ? <>
              {currentTurn.counselor_plan_summary && <div className="planning-summary"><h4>规划与评估摘要</h4><p>{currentTurn.counselor_plan_summary}</p></div>}
              {!!currentTurn.chosen_skills?.length && <div className="selected-skill-list">{currentTurn.chosen_skills.map((skill) => <span className="tag tag-info" key={skill}>{skill}</span>)}</div>}
              <h4 className="evidence-heading">技能与证据原文</h4>
              {currentTurn.skill_evidence?.length ? currentTurn.skill_evidence.map((evidence, index) => <div className="skill-evidence" key={index}>
                <strong>{evidence.skill_id}</strong><blockquote>{evidence.evidence_quote}</blockquote><p>{evidence.reason}</p>
              </div>) : <p className="insight-muted">本轮未记录技能依据。</p>}
            </> : <div className="decision-placeholder"><div><MessageSquare size={20} strokeWidth={1.5} /></div><p>选择对话中的「查看决策」</p><span>查看该轮规划、技能与证据原文</span></div>}
          </section>

          {currentSession?.plan && <details className="insight-card insight-details" open>
            <summary><BookOpen size={15} /><h3>会谈计划</h3><ChevronDown size={14} /></summary>
            <div className="plan-stage">当前阶段<span className="tag tag-neutral">{currentSession.plan.stage}</span></div>
            <h4>本场目标</h4><ul className="plan-objectives">{currentSession.plan.objectives?.map((objective: string, index: number) => <li key={index}>{objective}</li>)}</ul>
          </details>}

          {currentSession?.memory_snapshot && <details className="insight-card insight-details" open>
            <summary><History size={15} /><h3>允许记忆</h3><ChevronDown size={14} /></summary>
            <div className="memory-counts"><div><strong>{currentSession.memory_snapshot.known_background?.facts?.length ?? 0}</strong><span>已披露证据</span></div>
              <div><strong>{currentSession.memory_snapshot.last_homework?.length ?? 0}</strong><span>开放作业</span></div>
              <div><strong>{currentSession.memory_snapshot.checklist?.open_items?.length ?? 0}</strong><span>未完成事项</span></div>
            </div>
          </details>}
          {!report && <div className="supervision-pending"><ShieldCheck size={16} /><p>整体督导在完整轨迹结束后评分。<br />已有报告会显示在这里。</p></div>}
        </div>
      </aside>
    </div>
  );
};
