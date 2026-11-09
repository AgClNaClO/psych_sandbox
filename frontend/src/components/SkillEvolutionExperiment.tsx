import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FlaskConical, GitBranch, Plus, RefreshCw, Play, ArrowRight } from 'lucide-react';
import { experimentApi } from '../services/skillExperiment';
import type { ExperimentCandidate, ExperimentJob, ExperimentSkill, ExperimentSource, ExperimentSummary, SkillExperiment } from '../services/skillExperiment';
import './SkillEvolutionExperiment.css';

const actionName: Record<string, string> = { append: '新增', merge: '合并', skip: '跳过', baseline: '基线' };
const statusName: Record<string, string> = { queued: '等待启动', running: '执行中', completed: '已完成', failed: '失败' };

function Definition({ skill }: { skill: ExperimentSkill | null }) {
  if (!skill) return <p className="evo-muted">该版本中没有此技能</p>;
  return <div className="evo-definition"><strong>{skill.name}</strong><p>{skill.description}</p>
    <p><b>使用时机</b> {skill.when_to_use}</p><p><b>触发线索</b> {skill.triggers.join('、')}</p>
    <p><b>禁忌</b> {skill.contraindications.join('、') || '未额外声明'}</p></div>;
}

function Comparison({ job, changedIds }: { job: ExperimentJob; changedIds: string[] }) {
  const result = job.result;
  if (!result?.outputs) return null;
  return <section className="evo-card"><h3>{result.type === 'fixed_context' ? '固定上下文回复对比' : '独立模拟对比'} · v{job.request.version}</h3>
    <p className="evo-muted">{result.interpretation}</p>
    {result.context_hash && <p className="evo-muted">上下文 {result.context_hash.slice(0, 16)} · {result.model} · 温度 {result.temperature}</p>}
    <div className="evo-diff">{Object.entries(result.outputs).map(([label, output]) => <div key={label}>
      <h4>{label === 'baseline' ? '原始基线' : `实验 v${job.request.version}`}</h4>
      {result.type === 'fixed_context' ? <>
        <p className="evo-response">{output.response}</p>
        {label === 'experimental' && <p className="evo-badge append">进化技能：{(output.decision?.selected_atomic_skill_ids || []).some(id => changedIds.includes(id)) ? '已实际选中' : (output.observation?.atomic_skills || []).some(s => changedIds.includes(s.skill_id)) ? '已进入候选，本次未选中' : '本次未进入最终候选目录'}</p>}
        <p><b>实际选中技能</b></p>
        {(output.decision?.selected_atomic_skill_ids || []).length
          ? <ul>{output.decision?.selected_atomic_skill_ids?.map(id => <li key={id}><code>{id}</code></li>)}</ul>
          : <p className="evo-muted">本次未选用原子技能</p>}
        <details><summary>候选目录与选技证据</summary><pre>{JSON.stringify({ observation: output.observation, decision: output.decision }, null, 2)}</pre></details>
      </> : <><p>独立轨迹已完成</p><details open><summary>完整会谈与整体督导</summary><pre>{JSON.stringify(output, null, 2)}</pre></details></>}
    </div>)}</div>
  </section>;
}

export function SkillEvolutionExperiment({ observerMode = false }: { observerMode?: boolean }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [sources, setSources] = useState<ExperimentSource[]>([]);
  const [sourceIndex, setSourceIndex] = useState('0');
  const [history, setHistory] = useState<ExperimentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => localStorage.getItem('skill-experiment-id'));
  const [doc, setDoc] = useState<SkillExperiment | null>(null);
  const [candidateId, setCandidateId] = useState<string | null>(null);
  const [messageCount, setMessageCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sessions, setSessions] = useState('1');
  const [turns, setTurns] = useState('8');
  const selectedRef = useRef(selectedId);
  useLayoutEffect(() => { selectedRef.current = selectedId; }, [selectedId]);

  useEffect(() => {
    let live = true;
    experimentApi.status().then(status => {
      if (!live) return;
      setEnabled(status.enabled);
      if (status.enabled) Promise.all([experimentApi.sources(), experimentApi.list()]).then(([s, h]) => {
        if (live) { setSources(s); setHistory(h); }
      }).catch(e => { if (live) setError(String(e.message)); });
    }).catch(e => { if (live) setError(String(e.message)); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (!enabled || !selectedId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const data = await experimentApi.get(selectedId);
        if (!live) return;
        setDoc(data);
        setCandidateId(current => data.candidates.some(c => c.id === current) ? current : data.candidates.at(-1)?.id ?? null);
        setMessageCount(current => current || data.source.messages.reduce((last, m, index) => m.role === 'client' ? index + 1 : last, 0));
        setHistory(current => current.map(item => item.id === data.id ? { ...item, current_version: data.current_version } : item));
      } catch (e) { if (live) setError(e instanceof Error ? e.message : String(e)); }
      if (live) timer = setTimeout(refresh, 2500);
    };
    void refresh();
    return () => { live = false; clearTimeout(timer); };
  }, [enabled, selectedId]);

  function choose(id: string) {
    setSelectedId(id); setDoc(null); setCandidateId(null); setMessageCount(0); setError('');
    localStorage.setItem('skill-experiment-id', id);
  }
  async function action(work: () => Promise<unknown>) {
    if (observerMode || busy) return;
    setBusy(true); setError('');
    const expected = selectedRef.current;
    try {
      await work();
      if (expected && selectedRef.current === expected) {
        const data = await experimentApi.get(expected);
        if (selectedRef.current === expected) setDoc(data);
      }
    } catch (e) { if (selectedRef.current === expected) setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function create() {
    const source = sources[Number(sourceIndex)];
    if (!source) return;
    await action(async () => {
      const data = await experimentApi.create(source);
      setHistory(await experimentApi.list()); choose(data.id); setDoc(data);
    });
  }
  const pending = doc?.jobs.some(j => ['queued', 'running'].includes(j.status)) ?? false;
  const disabled = observerMode || busy || pending;
  const candidate = doc?.candidates.find(c => c.id === candidateId);
  const snapshot = doc?.versions[doc.current_version];
  const branch = candidate?.meta_skill_id;
  const visibleSkills = snapshot ? Object.values(snapshot.skills).filter(s => s.stages.includes(doc!.source.plan.stage) && (!branch || s.meta_skill_id === branch)) : [];
  const changes = snapshot && doc ? Object.values(snapshot.skills).filter(s => JSON.stringify(s) !== JSON.stringify(doc.versions[0].skills[s.skill_id])) : [];
  const comparisons = doc?.jobs.filter(j => j.status === 'completed' && j.result?.outputs) ?? [];

  return <div className="evo-shell">
    <div className="evo-banner"><div><span className="evo-kicker">EXPERIENCE → SKILL → EXPERIMENT</span><h2><FlaskConical size={23} /> 技能进化试验</h2>
      <p>从会谈经验提取技能，观察知识如何变化、是否被实际使用。</p></div>
      <span className="evo-isolation">独立存储 · 正式技能库只读</span></div>
    {error && <div role="alert" className="evo-error">{error}</div>}
    {enabled === false ? <section className="evo-card evo-disabled"><h3>实验功能默认关闭</h3><p>在启动工作台的终端中设置以下变量，再启动服务。原有工作台功能可继续使用。</p>
      <code>$env:PSYCHSANDBOX_SKILL_EXPERIMENT = '1'</code><p>也可以运行项目根目录的 <code>run_skill_experiment.bat</code>。</p></section>
      : enabled === null ? <p>正在检查实验状态…</p> : <div className="evo-layout">
      <aside className="evo-sidebar"><section className="evo-card"><h3>01 / 选择经验</h3>
        <label>已提交会谈<select value={sourceIndex} onChange={e => setSourceIndex(e.target.value)} disabled={busy}>
          {sources.map((s, index) => <option key={`${s.run_id}-${s.session_index}`} value={index}>{s.therapy.toUpperCase()} · {s.run_id} · 第{s.session_index}场</option>)}
        </select></label>
        {sources.length ? <p className="evo-muted">{sources[Number(sourceIndex)]?.source_kind === 'rft_winner' ? '已提交 RFT 赢家' : '普通会谈：仅作探索经验'}</p>
          : <p className="evo-muted">暂无已提交会谈。请先在自动实验台完成一次会谈。</p>}
        <button className="evo-primary" disabled={observerMode || busy || !sources.length} onClick={() => void create()}><Plus size={15} /> 创建独立实验</button>
      </section><section className="evo-card"><h3>实验记录</h3>{history.map(item => <button key={item.id} className={`evo-history ${item.id === selectedId ? 'active' : ''}`} disabled={busy} onClick={() => choose(item.id)}>
        <b>{item.therapy.toUpperCase()} · v{item.current_version}</b><span>{item.source_label}</span><small>{item.created_at.slice(0, 16).replace('T', ' ')}</small>
      </button>)}{!history.length && <p className="evo-muted">每次实验独立保留，可离开后继续查看。</p>}</section></aside>
      {doc && snapshot ? <>
      <div className="evo-main"><section className="evo-card"><h3>02 / 从经验到技能</h3><p>{doc.source.plan.objectives.join('；')}</p>
        <p className="evo-muted">{doc.source_label} · {doc.source.memory_recorded ? '已记录会前记忆' : '会前记忆缺失：使用空记忆，局部对比不代表历史原始上下文'}</p>
        <div className="evo-flow">{['目标与证据', '定向提取', '同分支查重', '新增 / 合并', '实验验证'].map((step, i) => <span key={step}>{i > 0 && <ArrowRight size={13} />}{step}</span>)}</div>
        <div className="evo-actions"><button className="evo-primary" disabled={disabled} onClick={() => void action(() => experimentApi.job(doc.id, 'extract', doc.current_version))}><GitBranch size={15} /> 从 v{doc.current_version} 提取技能</button>
          <button disabled={observerMode || busy || pending || doc.current_version === 0} onClick={() => void action(() => experimentApi.select(doc.id, 0))}><RefreshCw size={14} /> 恢复实验基线</button></div>
        {pending && <button disabled={observerMode || busy} onClick={() => void action(() => experimentApi.recover(doc.id))}>检查中断任务</button>}
      </section>
      {doc.candidates.length > 0 && <section className="evo-card"><h3>候选与管理决策</h3><div className="evo-candidate-tabs">{doc.candidates.map((c, i) => <button key={c.id} className={c.id === candidateId ? 'active' : ''} onClick={() => setCandidateId(c.id)}>#{i + 1} {actionName[c.action]}</button>)}</div>
        {candidate && <Candidate candidate={candidate} doc={doc} disabled={disabled} apply={() => void action(() => experimentApi.apply(doc.id, candidate.id))} />}
      </section>}
      <section className="evo-card"><h3>03 / 验证是否实际使用</h3>
        <label>固定上下文截止位置<select value={messageCount} onChange={e => setMessageCount(Number(e.target.value))}>{doc.source.messages.map((m, index) => m.role === 'client' && <option key={index} value={index + 1}>消息 {index + 1} · {m.content.slice(0, 50)}</option>)}</select></label>
        <div className="evo-actions"><button disabled={disabled || !messageCount || doc.current_version === 0} onClick={() => void action(() => experimentApi.job(doc.id, 'replay', doc.current_version, { message_count: messageCount }))}><Play size={14} /> 基线 vs v{doc.current_version} 单轮对比</button></div>
        <div className="evo-sim-options"><label>模拟会谈数<input type="number" min="1" max="3" value={sessions} onChange={e => setSessions(e.target.value)} /></label><label>每场轮数上限<input type="number" min="1" max="50" value={turns} onChange={e => setTurns(e.target.value)} /></label></div>
        <button disabled={disabled || doc.current_version === 0} onClick={() => {
          const s = Number(sessions), t = Number(turns);
          if (!Number.isInteger(s) || s < 1 || s > 3 || !Number.isInteger(t) || t < 1 || t > 50) { setError('会谈数须为 1–3 的整数，轮数须为 1–50 的整数'); return; }
          void action(() => experimentApi.job(doc.id, 'simulation', doc.current_version, { sessions: s, max_turns: t }));
        }}>运行两组独立完整模拟</button><p className="evo-muted">此操作会调用模型 API。两组使用相同病例、种子与配置，各自生成全新轨迹。</p>
      </section>
      {doc.jobs.slice().reverse().map(job => <section className="evo-card evo-job" key={job.id}><h4>{({ extract: '技能提取', replay: '单轮对比', simulation: '独立模拟' } as Record<string, string>)[job.request.kind]} · v{job.request.version} <span className={`evo-badge ${job.status}`}>{statusName[job.status] || job.status}</span></h4>
        {job.progress.map((p, i) => <p key={i}>{p.text}</p>)}{job.error && <p className="evo-error">{job.error}</p>}
      </section>)}
      {comparisons.slice().reverse().map(job => <Comparison key={job.id} job={job} changedIds={Object.values(doc.versions[job.request.version].skills).filter(s => JSON.stringify(s) !== JSON.stringify(doc.versions[0].skills[s.skill_id])).map(s => s.skill_id)} />)}
      <details className="evo-card"><summary>来源公开对话</summary>{doc.source.messages.map((m, i) => <p key={i}><b>{i + 1} · {m.role === 'client' ? '来访者' : '咨询师'}</b> {m.content}</p>)}</details>
      </div>
      <aside className="evo-sidebar evo-tree"><section className="evo-card"><h3>实验版本</h3><p className="evo-muted">未经专家批准 · 仅当前实验使用</p>
        {doc.versions.map(v => <button className={`evo-version ${v.version === doc.current_version ? 'active' : ''}`} key={v.version} disabled={disabled} onClick={() => void action(() => experimentApi.select(doc.id, v.version))}>
          <b>v{v.version} {actionName[v.action]}</b><span>{v.parent === null ? '原始技能树快照' : `来自 v${v.parent}`} · {Object.keys(v.skills).length} 项</span><small>{v.hash.slice(0, 16)}</small>
        </button>)}
      </section><section className="evo-card"><h3>技能树 · v{snapshot.version}</h3><p className="evo-muted">{doc.therapy.toUpperCase()} / {doc.source.plan.stage}</p>
        <p><span className="evo-badge append">{changes.length} 项变化</span> {branch ? doc.meta_skills[branch]?.name : '全部末级分支'}</p>
        <div className="evo-tree-scroll">{visibleSkills.map(s => {
          const original = doc.versions[0].skills[s.skill_id];
          const changed = JSON.stringify(s) !== JSON.stringify(original);
          return <details key={s.skill_id} className={`evo-tree-node ${changed ? 'changed' : ''}`}><summary>{changed && <span className="evo-badge append">{original ? '修改' : '新增'}</span>} {s.name}</summary><Definition skill={s} /><code>{s.skill_id}</code></details>;
        })}</div>
      </section></aside>
      </> : <section className="evo-card evo-empty"><FlaskConical size={38} /><h3>{selectedId ? '正在加载实验…' : '创建第一个技能进化实验'}</h3><p>选择一场已提交会谈，观察技能如何从经验中产生。</p><p className="evo-muted">实验版本不会发布到正式技能库。</p></section>}
    </div>}
  </div>;
}

function Candidate({ candidate: c, doc, disabled, apply }: { candidate: ExperimentCandidate; doc: SkillExperiment; disabled: boolean; apply: () => void }) {
  return <><div className="evo-decision"><span className={`evo-badge ${c.action}`}>{actionName[c.action]}</span><b>{c.after?.name || c.draft.name}</b></div>
    <p>{c.reason}</p><p className="evo-muted">归属分支：{doc.meta_skills[c.meta_skill_id]?.name} · {c.branch_reason}</p>
    <div className="evo-diff"><div><h4>进化前</h4><Definition skill={c.before} /></div><div><h4>{c.action === 'skip' ? '提取草稿（未应用）' : '进化后'}</h4><Definition skill={c.after || c.draft} /></div></div>
    <div className="evo-evidence"><b>来源证据</b>{c.evidence.map((q, i) => <blockquote key={i}>“{q.text}”<small>来源消息 {q.message_index + 1}</small></blockquote>)}</div>
    <details><summary>相近技能（相似度不是疗效分）</summary>{c.similar.map(item => <p key={item.skill.skill_id}>{item.similarity.toFixed(3)} · {item.skill.name}</p>)}</details>
    {c.action !== 'skip' && <button className="evo-primary" disabled={disabled || c.applied_version !== null} onClick={apply}>{c.applied_version !== null ? `已保存为实验 v${c.applied_version}` : `保存为实验快照（来自 v${c.base_version}）`}</button>}
  </>;
}
