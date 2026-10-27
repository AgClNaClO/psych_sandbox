import React, { useCallback, useEffect, useState } from 'react';
import { api, subscribeSSE } from '../services/api';
import type { CaseSummary, RunDetail, RunSummary } from '../types';
import { Play, Square, XCircle, RotateCcw, FileText } from 'lucide-react';

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

  // 运行参数
  const [selectedCaseId, setSelectedCaseId] = useState<string>('');
  const [therapyFilter, setTherapyFilter] = useState<string>('all');
  const [sessionCount, setSessionCount] = useState<number>(3);
  const [seed, setSeed] = useState<number>(42);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const fetchRuns = useCallback(() => {
    return api.getRuns().then((data) => {
      setRuns(data);
      setSelectedRunId((current) => current ?? data[0]?.run_id ?? null);
    }).catch((error: Error) => setErrorMsg(error.message));
  }, []);

  // 加载初始数据
  useEffect(() => {
    api.getCases().then((data) => {
      setCases(data);
      if (data.length > 0) setSelectedCaseId(data[0].case_id);
    }).catch(console.error);
    fetchRuns();
  }, [fetchRuns]);

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
    if (!activeJobId) return;
    const unsub = subscribeSSE(`job:${activeJobId}`, (event) => {
      if (event.type === 'simulation_progress') {
        setLiveLogs((prev) => [...prev.slice(-100), event.payload.message]);
      }
      if (['job_succeeded', 'job_stopped', 'job_failed', 'job_cancelled'].includes(event.type)) {
        setActiveJobId(null);
        if (event.type === 'job_failed') setErrorMsg(event.payload.error || '任务失败');
        fetchRuns();
        if (event.payload.run_id) {
          setSelectedRunId(event.payload.run_id);
          api.getRunDetail(event.payload.run_id).then(setSelectedRunDetail).catch(console.error);
        }
      }
    });
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
      });
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

  return (
    <div className="three-column-container">
      {/* 左栏：参数配置与历史运行列表 */}
      <div className="column-left">
        <div className="column-header">
          <span>新建仿真实验</span>
        </div>
        <div className="column-body" style={{ flex: 'none', borderBottom: '1px solid var(--border-color)' }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>
                选择案例 (共 {cases.length} 例):
              </label>
              <select
                style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-color)', background: 'var(--bg-input)' }}
                value={therapyFilter}
                onChange={(e) => {
                  const filter = e.target.value;
                  setTherapyFilter(filter);
                  const matching = cases.filter(c => filter === 'all' || normalizeTherapy(c.therapy) === filter);
                  if (matching.length > 0 && !matching.some(c => c.case_id === selectedCaseId)) {
                    setSelectedCaseId(matching[0].case_id);
                  }
                }}
              >
                <option value="all">全部五流派 ({cases.length})</option>
                <option value="cbt">CBT ({cases.filter(c => normalizeTherapy(c.therapy) === 'cbt').length})</option>
                <option value="bt">BT ({cases.filter(c => normalizeTherapy(c.therapy) === 'bt').length})</option>
                <option value="het">HET ({cases.filter(c => normalizeTherapy(c.therapy) === 'het').length})</option>
                <option value="pdt">PDT ({cases.filter(c => normalizeTherapy(c.therapy) === 'pdt').length})</option>
                <option value="pmt">PMT ({cases.filter(c => normalizeTherapy(c.therapy) === 'pmt').length})</option>
              </select>
            </div>
            <select
              style={{ width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid var(--border-color)', fontSize: 12 }}
              value={selectedCaseId}
              onChange={(e) => setSelectedCaseId(e.target.value)}
            >
              {(['cbt', 'bt', 'het', 'pdt', 'pmt'] as const).map((th) => {
                if (therapyFilter !== 'all' && therapyFilter !== th) return null;
                const groupCases = cases.filter(c => normalizeTherapy(c.therapy) === th);
                if (groupCases.length === 0) return null;
                const thNames: Record<string, string> = {
                  cbt: 'CBT 认知行为疗法',
                  bt: 'BT 行为疗法',
                  het: 'HET 人本体验疗法',
                  pdt: 'PDT 心理动力疗法',
                  pmt: 'PMT 后现代疗法'
                };
                return (
                  <optgroup key={th} label={`${thNames[th]} (${groupCases.length} 例)`}>
                    {groupCases.map((c) => (
                      <option key={c.case_id} value={c.case_id}>
                        [{th.toUpperCase()}] {c.title} ({c.case_id})
                      </option>
                    ))}
                  </optgroup>
                );
              })}
            </select>
          </div>

          <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>会谈次数:</label>
              <input
                type="number"
                min={1}
                max={10}
                value={sessionCount}
                onChange={(e) => setSessionCount(parseInt(e.target.value) || 1)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>随机种子:</label>
              <input
                type="number"
                value={seed}
                onChange={(e) => setSeed(parseInt(e.target.value) || 0)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn btn-primary"
              style={{ flex: 1 }}
              disabled={loading || observerMode}
              onClick={() => handleStartSimulation()}
            >
              <Play size={14} /> {observerMode ? '观察者模式不可启动' : '启动后台实验'}
            </button>
          </div>
          {errorMsg && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>{errorMsg}</div>}
        </div>

        <div className="column-header">
          <span>历史运行记录 ({runs.length})</span>
          <button className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: 11 }} onClick={fetchRuns}>
            刷新
          </button>
        </div>
        <div className="column-body">
          {runs.map((r) => (
            <div
              key={r.run_id}
              className={`item-card ${selectedRunId === r.run_id ? 'selected' : ''}`}
              onClick={() => setSelectedRunId(r.run_id)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{r.run_id}</span>
                <span
                  className={`tag ${
                    r.status === 'completed'
                      ? 'tag-success'
                      : r.status === 'stopped'
                      ? 'tag-warning'
                      : r.status === 'running'
                      ? 'tag-info'
                      : 'tag-danger'
                  }`}
                >
                  {r.status}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                案例: {r.case_id} | 流派: {r.therapy.toUpperCase()}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                已完成: {r.completed_sessions} 场会谈
                {r.holistic_score !== null && ` | 督导分: ${r.holistic_score.toFixed(2)}`}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 中栏：实时日志 / 会谈回放与对话流 */}
      <div className="column-center">
        <div className="column-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span>运行现场与会谈回放: {selectedRunId || '未选中'}</span>
            {selectedRunDetail?.sessions && (
              <div style={{ display: 'flex', gap: 4 }}>
                {selectedRunDetail.sessions.map((s) => (
                  <button
                    key={s.session_index}
                    className={`btn ${selectedSessionIdx === s.session_index ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '4px 10px', fontSize: 12 }}
                    onClick={() => {
                      setSelectedSessionIdx(s.session_index);
                      setSelectedTurnIdx(null);
                    }}
                  >
                    第 {s.session_index} 场
                  </button>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {selectedRunDetail?.status === 'stopped' && (
              <button
                className="btn btn-secondary"
                style={{ fontSize: 12 }}
                onClick={() => handleStartSimulation(selectedRunId!)}
              >
                <RotateCcw size={13} /> 边界续跑
              </button>
            )}
            <button
              className="btn btn-secondary"
              style={{ fontSize: 12 }}
              onClick={handleStopAtBoundary}
              title="在下一会谈开始前干净停止"
            >
              <Square size={13} /> 边界停止
            </button>
            <button className="btn btn-danger" style={{ fontSize: 12 }} onClick={handleCancelJob}>
              <XCircle size={13} /> 取消任务
            </button>
            {selectedRunDetail && (
              <a
                href={`/api/runs/${selectedRunDetail.run_id}/report`}
                target="_blank"
                rel="noreferrer"
                className="btn btn-secondary"
                style={{ fontSize: 12, textDecoration: 'none' }}
              >
                <FileText size={13} /> 原始 HTML 报告
              </a>
            )}
          </div>
        </div>

        <div className="column-body">
          {/* 实时进度控制台 */}
          {liveLogs.length > 0 && (
            <div
              style={{
                backgroundColor: '#0f172a',
                color: '#38bdf8',
                fontFamily: 'monospace',
                fontSize: 12,
                padding: 12,
                borderRadius: 6,
                marginBottom: 16,
                maxHeight: 140,
                overflowY: 'auto',
              }}
            >
              <div style={{ color: '#94a3b8', borderBottom: '1px solid #334155', paddingBottom: 4, marginBottom: 4 }}>
                [实时 Worker 执行日志]
              </div>
              {liveLogs.map((log, i) => (
                <div key={i}>{log}</div>
              ))}
            </div>
          )}

          {/* 对话时间线 */}
          {currentSession ? (
            <div className="messages-timeline">
              {currentSession.turns.map((t) => (
                <div
                  key={t.turn_index}
                  style={{
                    padding: 8,
                    borderRadius: 8,
                    border: selectedTurnIdx === t.turn_index ? '2px solid var(--primary)' : '1px solid transparent',
                    cursor: 'pointer',
                  }}
                  onClick={() => setSelectedTurnIdx(t.turn_index)}
                >
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
                    轮次 #{t.turn_index} {selectedTurnIdx === t.turn_index && '(点击右侧可查决策)'}
                  </div>
                  {/* 来访者 */}
                  <div className="message-bubble-wrapper participant" style={{ marginBottom: 8 }}>
                    <div className="message-sender-label">来访者</div>
                    <div className="message-bubble participant">{t.client_utterance}</div>
                  </div>
                  {/* 咨询师 */}
                  <div className="message-bubble-wrapper counselor">
                    <div className="message-sender-label">
                      <span>咨询师</span>
                      {t.chosen_skills && t.chosen_skills.length > 0 && (
                        <span className="tag tag-info" style={{ fontSize: 10 }}>
                          技能: {t.chosen_skills.join(', ')}
                        </span>
                      )}
                    </div>
                    <div className="message-bubble counselor">{t.counselor_response}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: 80 }}>
              请在左侧选择一个仿真运行记录，或提交新仿真实验。
            </div>
          )}
        </div>
      </div>

      {/* 右栏：结构化决策面板（计划、允许记忆、选技依据与督导） */}
      <div className="column-right">
        <div className="column-header">
          <span>结构化规划、依据与督导</span>
        </div>
        <div className="column-body">
          {/* 轮次级技能决策与依据 */}
          {currentTurn ? (
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: 'var(--primary)' }}>
                轮次 #{currentTurn.turn_index} 咨询师规划与依据
              </div>
              {currentTurn.counselor_plan_summary && (
                <div style={{ background: 'var(--bg-subtle)', padding: 10, borderRadius: 6, fontSize: 12, marginBottom: 8 }}>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>规划思考与评估摘要:</div>
                  {currentTurn.counselor_plan_summary}
                </div>
              )}

              <div style={{ fontSize: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>选用技能与依据原文:</div>
                {currentTurn.skill_evidence && currentTurn.skill_evidence.length > 0 ? (
                  currentTurn.skill_evidence.map((ev, i) => (
                    <div key={i} style={{ border: '1px solid var(--border-color)', padding: 8, borderRadius: 6, marginBottom: 6 }}>
                      <div style={{ fontWeight: 600, color: '#0284c7' }}>技能 ID: {ev.skill_id}</div>
                      <div style={{ color: 'var(--text-muted)', margin: '4px 0' }}>“{ev.evidence_quote}”</div>
                      <div style={{ fontSize: 11 }}>理由: {ev.reason}</div>
                    </div>
                  ))
                ) : (
                  <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>无技能依据或未选择原子技能</div>
                )}
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
              点击中栏任意轮次，可在此查看该轮的选用技能、依据原文和决策理由。
            </div>
          )}

          {/* 会谈计划 */}
          {currentSession?.plan && (
            <div style={{ marginBottom: 20, borderTop: '1px solid var(--border-color)', paddingTop: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>会谈计划 (Plan)</div>
              <div style={{ fontSize: 12 }}>
                <div>阶段: <span className="tag tag-neutral">{currentSession.plan.stage}</span></div>
                <div style={{ marginTop: 4 }}>
                  <strong>目标:</strong>
                  <ul style={{ paddingLeft: 18, marginTop: 4 }}>
                    {currentSession.plan.objectives?.map((obj: string, i: number) => (
                      <li key={i}>{obj}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* 允许记忆投影 */}
          {currentSession?.memory_snapshot && (
            <div style={{ marginBottom: 20, borderTop: '1px solid var(--border-color)', paddingTop: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>四字段允许记忆投影</div>
              <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div>
                  <strong>已知背景事实 (Facts):</strong>
                  <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                    {currentSession.memory_snapshot.known_background?.facts?.length || 0} 条已披露证据
                  </div>
                </div>
                <div>
                  <strong>上轮作业:</strong>
                  <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                    {currentSession.memory_snapshot.last_homework?.length || 0} 项开放作业
                  </div>
                </div>
                <div>
                  <strong>事项清单:</strong>
                  <div style={{ color: 'var(--text-muted)', marginTop: 2 }}>
                    {currentSession.memory_snapshot.checklist?.open_items?.length || 0} 个未完成项
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* 全疗程整体督导评估 */}
          {selectedRunDetail?.holistic_report && (
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, color: '#15803d', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span>整体督导报告 (全疗程临床评分)</span>
                <span className="badge" style={{ background: '#dcfce7', color: '#166534', fontSize: 10, padding: '2px 6px', borderRadius: 4 }}>
                  PsychEvalSupervisor
                </span>
              </div>
              <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: 12, borderRadius: 6, fontSize: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, paddingBottom: 6, borderBottom: '1px dashed #86efac' }}>
                  <div>
                    咨询师总督导分:{' '}
                    <strong style={{ fontSize: 15, color: '#166534' }}>
                      {typeof selectedRunDetail.holistic_report.holistic_score === 'number'
                        ? selectedRunDetail.holistic_report.holistic_score.toFixed(2)
                        : (selectedRunDetail.holistic_report.counselor_overall != null
                            ? Number(selectedRunDetail.holistic_report.counselor_overall).toFixed(2)
                            : 'N/A')}
                    </strong>
                    <span style={{ color: 'var(--text-muted)', fontSize: 11 }}> / 10.0</span>
                  </div>
                  {(selectedRunDetail.holistic_report.client_score != null || selectedRunDetail.holistic_report.client_overall != null) && (
                    <div>
                      来访者评定:{' '}
                      <strong style={{ fontSize: 15, color: '#0369a1' }}>
                        {Number(selectedRunDetail.holistic_report.client_score ?? selectedRunDetail.holistic_report.client_overall).toFixed(2)}
                      </strong>
                      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}> / 10.0</span>
                    </div>
                  )}
                </div>

                {/* 细分量表小卡片 */}
                {(() => {
                  const r = selectedRunDetail.holistic_report;
                  const scales: { label: string; score: number; color: string }[] = [];

                  // 咨询师专属与通用量表
                  (r.counselor_specific || []).forEach((item: any) => {
                    if (item && item.name && typeof item.score === 'number') {
                      scales.push({ label: item.name.toUpperCase(), score: item.score, color: '#0284c7' });
                    }
                  });
                  (r.counselor_shared || []).forEach((item: any) => {
                    if (item && item.name && typeof item.score === 'number' && ['wai', 'htais', 'rro'].includes(item.name)) {
                      scales.push({ label: item.name.toUpperCase(), score: item.score, color: '#16a34a' });
                    }
                  });
                  // 来访者量表
                  (r.client_specific || []).forEach((item: any) => {
                    if (item && item.name && typeof item.score === 'number') {
                      scales.push({ label: item.name.toUpperCase(), score: item.score, color: '#d97706' });
                    }
                  });

                  if (scales.length === 0) return null;

                  return (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                      {scales.map((sc, idx) => (
                        <div
                          key={idx}
                          style={{
                            background: '#ffffff',
                            border: `1px solid ${sc.color}40`,
                            borderRadius: 4,
                            padding: '2px 6px',
                            fontSize: 11,
                          }}
                        >
                          <span style={{ color: 'var(--text-muted)', marginRight: 4 }}>{sc.label}:</span>
                          <strong style={{ color: sc.color }}>{sc.score.toFixed(2)}</strong>
                        </div>
                      ))}
                    </div>
                  );
                })()}

                <div style={{ color: '#374151', lineHeight: 1.5, marginTop: 4 }}>
                  <strong>评价意见:</strong>{' '}
                  {selectedRunDetail.holistic_report.summary
                    ? selectedRunDetail.holistic_report.summary.replaceAll('/7.0', '/10.0')
                    : '无评估摘要'}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
