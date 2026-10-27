import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import type { SkillProposal, SkillRelease, TherapyDefinition } from '../types';
import { GitBranch, ShieldCheck, Plus, RotateCcw } from 'lucide-react';

interface SkillLabHubProps {
  observerMode?: boolean;
}

export const SkillLabHub: React.FC<SkillLabHubProps> = ({ observerMode = false }) => {
  const [therapies, setTherapies] = useState<TherapyDefinition[]>([]);
  const [selectedTherapy, setSelectedTherapy] = useState<string>('cbt');
  const [releases, setReleases] = useState<SkillRelease[]>([]);
  const [selectedReleaseId, setSelectedReleaseId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<SkillProposal[]>([]);
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);

  // 技能树与预览
  const [skillTreeData, setSkillTreeData] = useState<any>(null);
  const [expandedStage, setExpandedStage] = useState<string | null>('stage1');

  // 提交提案表单
  const [showProposalModal, setShowProposalModal] = useState<boolean>(false);
  const [propTitle, setPropTitle] = useState<string>('认知重组技术细化');
  const [propParentMeta, setPropParentMeta] = useState<string>('285');
  const [propStage, setPropStage] = useState<string>('intervention');
  const [propName, setPropName] = useState<string>('负性信念证据检验法');
  const [propDesc, setPropDesc] = useState<string>('通过双栏表格列出支持和反对负性自动思维的客观事实');
  const [propTiming, setPropTiming] = useState<string>('当来访者识别出明确自动思维且愿意通过理性证据进行检验时');
  const [propTriggers, setPropTriggers] = useState<string>('证据,事实,证明,根据');
  const [propJustification, setPropJustification] = useState<string>('针对自动化思维固化的来访者，缺少明确事实检验步骤导致重组效果打折');
  const [propAuthor, setPropAuthor] = useState<string>('Dr_Clinical_Researcher');

  // 专家审核表单
  const [showReviewModal, setShowReviewModal] = useState<boolean>(false);
  const [reviewerId, setReviewerId] = useState<string>('expert_evaluator_01');
  const [reviewerName, setReviewerName] = useState<string>('王督导 (主任医师)');
  const [reviewVerdict, setReviewVerdict] = useState<'approve' | 'reject' | 'revise'>('approve');
  const [reviewRationale, setReviewRationale] = useState<string>('经审查，该技能符合认知行为流派标准技术规范，适用时机与触发条件严谨，准予发布。');
  const [safetyChecked, setSafetyChecked] = useState<boolean>(true);
  const [evidenceChecked, setEvidenceChecked] = useState<boolean>(true);

  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const therapyRef = useRef(selectedTherapy);
  useLayoutEffect(() => { therapyRef.current = selectedTherapy; }, [selectedTherapy]);

  useEffect(() => {
    api.getTherapies().then((t) => {
      setTherapies(t);
      if (t.length > 0) setSelectedTherapy(t[0].therapy);
    }).catch(console.error);
  }, []);

  const fetchReleases = useCallback(() => {
    api.getSkillReleases(selectedTherapy).then((data) => {
      if (therapyRef.current !== selectedTherapy) return;
      setReleases(data);
      setSelectedReleaseId((current) => data.some((item) => item.release_id === current)
        ? current : data.find((item) => item.is_active)?.release_id ?? data[0]?.release_id ?? null);
    }).catch(console.error);
  }, [selectedTherapy]);

  const fetchProposals = useCallback(() => {
    api.getProposals(selectedTherapy).then((data) => {
      if (therapyRef.current !== selectedTherapy) return;
      setProposals(data);
      setSelectedProposalId((current) => data.some((item) => item.proposal_id === current)
        ? current : data[0]?.proposal_id ?? null);
    }).catch(console.error);
  }, [selectedTherapy]);

  const fetchSkillTree = useCallback(() => {
    api.getSkillTree(selectedTherapy).then((data) => {
      if (therapyRef.current === selectedTherapy) setSkillTreeData(data);
    }).catch(console.error);
  }, [selectedTherapy]);

  useEffect(() => {
    fetchReleases();
    fetchProposals();
    fetchSkillTree();
  }, [fetchReleases, fetchProposals, fetchSkillTree]);

  const handleSubmitProposal = async () => {
    try {
      setLoading(true);
      setErrorMsg(null);
      await api.submitProposal({
        therapy: selectedTherapy,
        base_release_id: selectedReleaseId || undefined,
        title: propTitle,
        parent_meta_id: propParentMeta,
        stage: propStage,
        content: {
          name: propName,
          description: propDesc,
          timing: propTiming,
          triggers: propTriggers.split(',').map((s) => s.trim()).filter(Boolean),
        },
        justification: propJustification,
        author: propAuthor,
      });
      setShowProposalModal(false);
      setSuccessMsg('技能提案提交成功！已通过静态校验，等待回放验证与专家审核。');
      fetchProposals();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleReviewSubmit = async () => {
    if (!selectedProposalId) return;
    try {
      setLoading(true);
      setErrorMsg(null);
      await api.reviewProposal(selectedProposalId, {
        reviewer_id: reviewerId,
        reviewer_name: reviewerName,
        verdict: reviewVerdict,
        rationale: reviewRationale,
        checklist: {
          clinical_safety: safetyChecked,
          evidence_grounding: evidenceChecked,
        },
      });
      setShowReviewModal(false);
      setSuccessMsg('专家审核已提交！');
      fetchProposals();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async (prop: SkillProposal) => {
    if (!confirm(`确定将提案 [${prop.title}] 合并发布为不可变新版本吗？`)) return;
    try {
      setLoading(true);
      setErrorMsg(null);
      await api.publishProposal(prop.proposal_id, reviewerName, `${prop.title} - 发布版`);
      setSuccessMsg('已成功生成新的不可变技能快照并更新活动指针！');
      fetchReleases();
      fetchProposals();
      fetchSkillTree();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async (releaseId: string) => {
    if (!confirm('确定将当前活动技能指针回滚到此历史版本吗？')) return;
    try {
      setLoading(true);
      setErrorMsg(null);
      await api.rollbackRelease(releaseId, selectedTherapy);
      setSuccessMsg('已成功回滚活动技能版本指针！');
      fetchReleases();
      fetchSkillTree();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="three-column-container">
      {/* 左栏：流派选择与版本快照 */}
      <div className="column-left">
        <div className="column-header">
          <span>流派与不可变发布快照</span>
        </div>
        <div className="column-body" style={{ flex: 'none', borderBottom: '1px solid var(--border-color)' }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>选择流派 (隔离管理):</label>
          <select
            style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
            value={selectedTherapy}
            onChange={(e) => {
              setReleases([]); setProposals([]); setSkillTreeData(null);
              setSelectedReleaseId(null); setSelectedProposalId(null);
              setSelectedTherapy(e.target.value);
            }}
          >
            {therapies.map((t) => (
              <option key={t.therapy} value={t.therapy}>
                {t.name} ({t.therapy.toUpperCase()})
              </option>
            ))}
          </select>
        </div>

        <div className="column-header">
          <span>不可变发布版本 (SkillRelease)</span>
        </div>
        <div className="column-body">
          {releases.map((rel) => (
            <div
              key={rel.release_id}
              className={`item-card ${selectedReleaseId === rel.release_id ? 'selected' : ''}`}
              onClick={() => setSelectedReleaseId(rel.release_id)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{rel.name}</span>
                {rel.is_active && <span className="tag tag-success">当前活动</span>}
              </div>
              <div style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                哈希: {rel.tree_hash.slice(0, 16)}...
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                扩展技能: {Object.keys(rel.overlay_skills).length} 项 | 发布者: {rel.created_by}
              </div>
              {!rel.is_active && (
                <button
                  className="btn btn-secondary"
                  style={{ padding: '2px 8px', fontSize: 11, marginTop: 6 }}
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRollback(rel.release_id);
                  }}
                >
                  <RotateCcw size={11} /> 回滚至此版本
                </button>
              )}
            </div>
          ))}

          {releases.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', marginTop: 20 }}>
              该流派暂无独立发布记录，默认使用资产库原始只读技能树。
            </div>
          )}
        </div>
      </div>

      {/* 中栏：演化闭环提案与验证流程 */}
      <div className="column-center">
        <div className="column-header">
          <span>技能修改提案与演化闭环 ({selectedTherapy.toUpperCase()})</span>
          <button
            className="btn btn-primary"
            style={{ padding: '4px 10px', fontSize: 12 }}
            disabled={observerMode}
            onClick={() => setShowProposalModal(true)}
          >
            <Plus size={13} /> {observerMode ? '观察者模式不可提提案' : '提交新提案'}
          </button>
        </div>

        <div className="column-body">
          {errorMsg && (
            <div style={{ background: '#fee2e2', border: '1px solid #f87171', color: '#b91c1c', padding: 8, borderRadius: 6, marginBottom: 12, fontSize: 12 }}>
              {errorMsg}
            </div>
          )}
          {successMsg && (
            <div style={{ background: '#dcfce7', border: '1px solid #86efac', color: '#15803d', padding: 8, borderRadius: 6, marginBottom: 12, fontSize: 12 }}>
              {successMsg}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {proposals.map((prop) => (
              <div
                key={prop.proposal_id}
                style={{
                  padding: 14,
                  borderRadius: 8,
                  border: selectedProposalId === prop.proposal_id ? '2px solid var(--primary)' : '1px solid var(--border-color)',
                  background: 'white',
                  cursor: 'pointer',
                }}
                onClick={() => setSelectedProposalId(prop.proposal_id)}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{prop.title}</span>
                  <span
                    className={`tag ${
                      prop.status === 'published'
                        ? 'tag-success'
                        : prop.status === 'approved'
                        ? 'tag-info'
                        : prop.status === 'rejected'
                        ? 'tag-danger'
                        : 'tag-warning'
                    }`}
                  >
                    {prop.status.toUpperCase()}
                  </span>
                </div>

                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
                  技能名称: <strong>{prop.content.name}</strong> | 阶段: {prop.stage} | 作者: {prop.author}
                </div>

                <div style={{ fontSize: 12, background: 'var(--bg-subtle)', padding: 8, borderRadius: 4, marginBottom: 8 }}>
                  <div><strong>说明:</strong> {prop.content.description}</div>
                  <div style={{ marginTop: 4 }}><strong>使用时机:</strong> {prop.content.timing}</div>
                  <div style={{ marginTop: 4 }}><strong>触发词:</strong> {prop.content.triggers?.join(', ')}</div>
                </div>

                <div style={{ fontSize: 12, marginBottom: 8 }}>
                  <strong>修改理由:</strong> {prop.justification}
                </div>

                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', borderTop: '1px solid var(--border-color)', paddingTop: 8 }}>
                  {prop.status !== 'published' && prop.status !== 'approved' && (
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: 12 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedProposalId(prop.proposal_id);
                        setShowReviewModal(true);
                      }}
                    >
                      <ShieldCheck size={13} /> 专家审核
                    </button>
                  )}

                  {prop.status === 'approved' && (
                    <button
                      className="btn btn-primary"
                      style={{ fontSize: 12 }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePublish(prop);
                      }}
                    >
                      <GitBranch size={13} /> 批准发布新快照
                    </button>
                  )}
                </div>
              </div>
            ))}

            {proposals.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', marginTop: 80 }}>
                暂无技能演化提案。点击右上角“提交新提案”开始闭环演化。
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 右栏：原始技能树与扩展详情 */}
      <div className="column-right">
        <div className="column-header">
          <span>技能树预览与合规原则</span>
        </div>
        <div className="column-body">
          <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', padding: 10, borderRadius: 6, fontSize: 12, marginBottom: 16 }}>
            <div style={{ fontWeight: 600, color: '#1e40af', marginBottom: 4 }}>科研合规原则</div>
            <ul style={{ paddingLeft: 16, lineHeight: 1.6 }}>
              <li>原始五流派技能树永久只读，不可篡改；</li>
              <li>修改必须通过扩展层提案与不可变发布快照；</li>
              <li>严格执行专家审核回避原则（作者不可自审）；</li>
              <li>严禁按分数自动晋升或冒充专家批准。</li>
            </ul>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>当前技能树结构 (只读):</div>
            {skillTreeData?.raw_tree?.total_meta_count !== undefined && (
              <span className="tag tag-neutral" style={{ fontSize: 10 }}>
                {skillTreeData.raw_tree.total_meta_count} 元技能 / {skillTreeData.raw_tree.total_micro_count} 原子技能
              </span>
            )}
          </div>

          {skillTreeData?.raw_tree?.stages ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {Object.entries(skillTreeData.raw_tree.stages).map(([sKey, sVal]: [string, any]) => {
                const isExp = expandedStage === sKey;
                return (
                  <div key={sKey} style={{ border: '1px solid var(--border-color)', borderRadius: 6, overflow: 'hidden' }}>
                    <div
                      onClick={() => setExpandedStage(isExp ? null : sKey)}
                      style={{
                        padding: '8px 12px',
                        background: isExp ? 'var(--bg-subtle)' : '#fff',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontSize: 12,
                        fontWeight: 600,
                      }}
                    >
                      <span>{sVal.title}</span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {sVal.meta_count} 元 / {sVal.micro_count} 原子 {isExp ? '▲' : '▼'}
                      </span>
                    </div>

                    {isExp && (
                      <div style={{ padding: '8px 12px', background: '#fafafa', borderTop: '1px solid var(--border-color)', maxHeight: 220, overflowY: 'auto' }}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
                          核心元技能列表 (点击可带入提案父节点 ID):
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {Object.entries(sVal.meta_skills || {}).slice(0, 30).map(([mId, mObj]: [string, any]) => (
                            <div
                              key={mId}
                              onClick={() => {
                                setPropParentMeta(mId);
                                setPropStage(sKey === 'stage1' ? 'conceptualization' : sKey === 'stage2' ? 'intervention' : 'consolidation');
                              }}
                              style={{
                                padding: '4px 8px',
                                background: '#fff',
                                border: '1px solid #e2e8f0',
                                borderRadius: 4,
                                fontSize: 11,
                                cursor: 'pointer',
                              }}
                              title="点击填入提案父节点ID"
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <strong style={{ color: 'var(--primary)' }}>[{mId}] {mObj.skill_name}</strong>
                              </div>
                              {mObj.skill_description && (
                                <div style={{ color: 'var(--text-muted)', marginTop: 2, fontSize: 10 }}>
                                  {mObj.skill_description.slice(0, 50)}...
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : skillTreeData?.raw_tree ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', background: 'var(--bg-subtle)', padding: 12, borderRadius: 6, maxHeight: 300, overflowY: 'auto' }}>
              <pre style={{ margin: 0, fontFamily: 'monospace', fontSize: 11, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(skillTreeData.raw_tree, null, 2).slice(0, 1500)}...
              </pre>
            </div>
          ) : (
            <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12, background: 'var(--bg-subtle)', borderRadius: 6 }}>
              加载原始技能树中...
            </div>
          )}
        </div>
      </div>

      {/* 提交提案弹窗 */}
      {showProposalModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: 'white', borderRadius: 8, width: 500, padding: 20 }}>
            <h3 style={{ marginBottom: 14 }}>提交技能修改提案</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>提案标题:</label>
                <input
                  type="text"
                  value={propTitle}
                  onChange={(e) => setPropTitle(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>提案作者 (用于回避):</label>
                <input
                  type="text"
                  value={propAuthor}
                  onChange={(e) => setPropAuthor(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>原子技能名称:</label>
                <input
                  type="text"
                  value={propName}
                  onChange={(e) => setPropName(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>父节点ID (分类/阶段元ID):</label>
                <input
                  type="text"
                  value={propParentMeta}
                  onChange={(e) => setPropParentMeta(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>所属阶段:</label>
              <select
                value={propStage}
                onChange={(e) => setPropStage(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              >
                <option value="conceptualization">概念化阶段</option>
                <option value="intervention">干预阶段</option>
                <option value="consolidation">巩固阶段</option>
              </select>
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>技能具体说明:</label>
              <textarea
                value={propDesc}
                onChange={(e) => setPropDesc(e.target.value)}
                style={{ width: '100%', height: 50, padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>使用时机与触发条件:</label>
              <input
                type="text"
                value={propTiming}
                onChange={(e) => setPropTiming(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                placeholder="适用时机"
              />
              <input
                type="text"
                value={propTriggers}
                onChange={(e) => setPropTriggers(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                placeholder="触发关键词，逗号分隔"
              />
            </div>

            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>修改充分理由 (Justification):</label>
              <textarea
                value={propJustification}
                onChange={(e) => setPropJustification(e.target.value)}
                style={{ width: '100%', height: 50, padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn btn-secondary" onClick={() => setShowProposalModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleSubmitProposal} disabled={loading}>提交提案</button>
            </div>
          </div>
        </div>
      )}

      {/* 专家审核弹窗 */}
      {showReviewModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: 'white', borderRadius: 8, width: 480, padding: 20 }}>
            <h3 style={{ marginBottom: 14 }}>独立临床专家审核</h3>
            <div style={{ background: '#fef3c7', border: '1px solid #fde68a', color: '#b45309', padding: 8, borderRadius: 4, fontSize: 12, marginBottom: 12 }}>
              注意：系统强制作者回避。若审核人与提案作者一致，后端将直接拒绝。
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 10 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>专家工号 / ID:</label>
                <input
                  type="text"
                  value={reviewerId}
                  onChange={(e) => setReviewerId(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600 }}>专家姓名及职称:</label>
                <input
                  type="text"
                  value={reviewerName}
                  onChange={(e) => setReviewerName(e.target.value)}
                  style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                />
              </div>
            </div>

            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>审核结论:</label>
              <select
                value={reviewVerdict}
                onChange={(e: any) => setReviewVerdict(e.target.value)}
                style={{ width: '100%', padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              >
                <option value="approve">准予批准 (Approve)</option>
                <option value="reject">否决提案 (Reject)</option>
                <option value="revise">发回修改 (Revise)</option>
              </select>
            </div>

            <div style={{ marginBottom: 10, fontSize: 12 }}>
              <label style={{ fontWeight: 600, display: 'block', marginBottom: 4 }}>合规检查清单:</label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <input type="checkbox" checked={safetyChecked} onChange={(e) => setSafetyChecked(e.target.checked)} />
                已核对临床伦理与安全规范，无诱导风险
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox" checked={evidenceChecked} onChange={(e) => setEvidenceChecked(e.target.checked)} />
                技术时机与触发条件具有充分理论依据
              </label>
            </div>

            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>专家书面审查意见 (必须详实，不少于10字):</label>
              <textarea
                value={reviewRationale}
                onChange={(e) => setReviewRationale(e.target.value)}
                style={{ width: '100%', height: 60, padding: '6px 8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn btn-secondary" onClick={() => setShowReviewModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleReviewSubmit} disabled={loading}>提交专家审核</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
