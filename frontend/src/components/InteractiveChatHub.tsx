import React, { useEffect, useState } from 'react';
import { api, subscribeSSE } from '../services/api';
import type { Course, CourseSessionDetail, TherapyDefinition } from '../types';
import { Send, Plus, AlertCircle, PlayCircle, StopCircle, LogOut } from 'lucide-react';

interface InteractiveChatHubProps {
  observerMode?: boolean;
}

export const InteractiveChatHub: React.FC<InteractiveChatHubProps> = ({ observerMode = false }) => {
  const [courses, setCourses] = useState<Course[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [courseDetail, setCourseDetail] = useState<Course | null>(null);
  const [selectedSessionIdx, setSelectedSessionIdx] = useState<number>(1);
  const [sessionDetail, setSessionDetail] = useState<CourseSessionDetail | null>(null);
  const [therapies, setTherapies] = useState<TherapyDefinition[]>([]);

  // 新建疗程表单
  const [showCreateModal, setShowCreateModal] = useState<boolean>(false);
  const [newTitle, setNewTitle] = useState<string>('我的心理咨询疗程');
  const [newTherapy, setNewTherapy] = useState<string>('cbt');
  const [newInputMode, setNewInputMode] = useState<'natural' | 'roleplay'>('natural');
  const [newRoleplayCard, setNewRoleplayCard] = useState<string>('');

  // 聊天输入与状态
  const [inputText, setInputText] = useState<string>('');
  const [isSending, setIsSending] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    api.getTherapies().then(setTherapies).catch(console.error);
    fetchCourses();
  }, []);

  const fetchCourses = () => {
    api.getCourses().then((data) => {
      setCourses(data);
      if (!selectedCourseId && data.length > 0) {
        setSelectedCourseId(data[0].course_id);
      }
    }).catch(console.error);
  };

  useEffect(() => {
    if (!selectedCourseId) {
      setCourseDetail(null);
      setSessionDetail(null);
      return;
    }
    api.getCourse(selectedCourseId).then((c) => {
      setCourseDetail(c);
      setSelectedSessionIdx(c.current_session || 1);
    }).catch(console.error);
  }, [selectedCourseId]);

  useEffect(() => {
    if (!selectedCourseId || !selectedSessionIdx) return;
    fetchSessionDetail();
  }, [selectedCourseId, selectedSessionIdx]);

  const fetchSessionDetail = () => {
    if (!selectedCourseId) return;
    api.getSessionDetail(selectedCourseId, selectedSessionIdx)
      .then((detail) => {
        setSessionDetail(detail);
        if (!detail.active_operation) {
          setIsSending(false);
        } else {
          setIsSending(true);
        }
        if (detail.last_operation && detail.last_operation.status === 'failed') {
          setErrorMsg(`操作失败: ${detail.last_operation.error || '未知错误'}`);
        } else if (!detail.active_operation) {
          setErrorMsg(null);
        }
      })
      .catch(console.error);
  };

  // SSE 实时事件监听
  useEffect(() => {
    if (!selectedCourseId) return;
    const unsub = subscribeSSE(`course:${selectedCourseId}`, (event) => {
      fetchSessionDetail();
      if (event.type === 'counselor_replied') {
        setIsSending(false);
        setErrorMsg(null);
      }
      if (event.type === 'operation_failed') {
        setIsSending(false);
        setErrorMsg(`操作失败: ${event.payload?.error || '未知错误'}`);
      }
      if (event.type === 'session_closed') {
        setIsSending(false);
        api.getCourse(selectedCourseId).then(setCourseDetail).catch(console.error);
      }
    });
    return unsub;
  }, [selectedCourseId, selectedSessionIdx]);

  // 发送中短轮询自愈（以防网络延迟或丢帧）
  useEffect(() => {
    if (!isSending || !selectedCourseId) return;
    const timer = setInterval(() => {
      fetchSessionDetail();
    }, 1500);
    return () => clearInterval(timer);
  }, [isSending, selectedCourseId, selectedSessionIdx]);

  const handleResetLock = async () => {
    if (!courseDetail || !sessionDetail) return;
    try {
      await api.resetSessionLock(courseDetail.course_id, sessionDetail.session_index);
      setErrorMsg(null);
      setIsSending(false);
      fetchSessionDetail();
      api.getCourse(courseDetail.course_id).then(setCourseDetail).catch(console.error);
    } catch (err: any) {
      alert(`解除失败: ${err.message}`);
    }
  };

  const handleCreateCourse = async () => {
    try {
      const created = await api.createCourse({
        therapy: newTherapy,
        title: newTitle,
        input_mode: newInputMode,
        roleplay_card: newInputMode === 'roleplay' ? newRoleplayCard : undefined,
      });
      setShowCreateModal(false);
      fetchCourses();
      setSelectedCourseId(created.course_id);
    } catch (err: any) {
      alert(`创建失败: ${err.message}`);
    }
  };

  const handleTriggerOpening = async () => {
    if (!courseDetail || !sessionDetail) return;
    try {
      setIsSending(true);
      setErrorMsg(null);
      const opId = `op-open-${Date.now()}`;
      await api.triggerOpening(courseDetail.course_id, sessionDetail.session_index, opId, courseDetail.version);
    } catch (err: any) {
      setErrorMsg(err.message);
      setIsSending(false);
    }
  };

  const handleSendMessage = async () => {
    if (!inputText.trim() || !courseDetail || !sessionDetail || isSending) return;
    const textToSend = inputText;
    setInputText('');
    setIsSending(true);
    setErrorMsg(null);

    const msgId = `msg-${Date.now()}`;
    const opId = `op-msg-${Date.now()}`;

    try {
      await api.sendMessage(courseDetail.course_id, sessionDetail.session_index, {
        message_id: msgId,
        operation_id: opId,
        expected_version: courseDetail.version,
        content: textToSend,
        source: courseDetail.input_mode === 'roleplay' ? 'participant_roleplay' : 'participant_natural',
      });
      // 乐观锁成功，等待后端 short worker 生成咨询师回复
    } catch (err: any) {
      setErrorMsg(err.message);
      setInputText(textToSend); // 恢复输入
      setIsSending(false);
    }
  };

  const handleCloseSession = async () => {
    if (!courseDetail || !sessionDetail) return;
    if (!confirm('确定结束当前会谈吗？系统将启动 E.7~E.9 记忆整合、自评与下一计划生成。')) return;

    const opId = `op-close-${Date.now()}`;
    try {
      setErrorMsg(null);
      await api.closeCurrentSession(courseDetail.course_id, sessionDetail.session_index, opId, courseDetail.version);
      fetchSessionDetail();
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleStartNextSession = async () => {
    if (!courseDetail) return;
    try {
      setErrorMsg(null);
      const nextSess = await api.startNextSession(courseDetail.course_id);
      setSelectedSessionIdx(nextSess.session_index);
      api.getCourse(courseDetail.course_id).then(setCourseDetail).catch(console.error);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  const handleCloseCourse = async () => {
    if (!courseDetail) return;
    if (!confirm('确定提前结束整个疗程吗？用户主动结束记录为 participant_closed_course，不记为目标达成。')) return;

    try {
      setErrorMsg(null);
      await api.closeCourse(courseDetail.course_id, 'participant_closed_course');
      api.getCourse(courseDetail.course_id).then(setCourseDetail).catch(console.error);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  return (
    <div className="three-column-container">
      {/* 左栏：疗程列表与控制 */}
      <div className="column-left">
        <div className="column-header">
          <span>人工多会谈疗程</span>
          <button className="btn btn-primary" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => setShowCreateModal(true)}>
            <Plus size={13} /> 新建疗程
          </button>
        </div>
        <div className="column-body">
          {courses.map((c) => (
            <div
              key={c.course_id}
              className={`item-card ${selectedCourseId === c.course_id ? 'selected' : ''}`}
              onClick={() => setSelectedCourseId(c.course_id)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{c.title}</span>
                <span className={`tag ${c.status === 'active' ? 'tag-success' : 'tag-neutral'}`}>{c.status}</span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                流派: {c.therapy.toUpperCase()} | 模式: {c.input_mode === 'natural' ? '自然输入' : '角色扮演'}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                已完成会谈: {c.completed_sessions} 场 | 当前版本: v{c.version}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 中栏：会谈切换、消息流与输入控制 */}
      <div className="column-center">
        <div className="column-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontWeight: 600 }}>{courseDetail?.title || '未选择疗程'}</span>
            {courseDetail && (
              <span className={`tag ${courseDetail.status === 'active' ? 'tag-success' : 'tag-neutral'}`}>
                {courseDetail.status === 'active' ? '进行中' : `已结案 (${courseDetail.close_reason})`}
              </span>
            )}
            {/* 会谈切换按钮 */}
            {courseDetail && (
              <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
                {Array.from({ length: courseDetail.current_session }, (_, i) => i + 1).map((idx) => (
                  <button
                    key={idx}
                    className={`btn ${selectedSessionIdx === idx ? 'btn-primary' : 'btn-secondary'}`}
                    style={{ padding: '3px 8px', fontSize: 12 }}
                    onClick={() => setSelectedSessionIdx(idx)}
                  >
                    第 {idx} 场
                  </button>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            {sessionDetail?.status === 'open' && (
              <>
                {sessionDetail.messages.length === 0 && (
                  <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={handleTriggerOpening} disabled={isSending}>
                    <PlayCircle size={13} /> 咨询师开场
                  </button>
                )}
                <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={handleCloseSession} disabled={isSending}>
                  <StopCircle size={13} /> 结束当前会谈
                </button>
              </>
            )}

            {sessionDetail?.status === 'closed' && courseDetail?.status === 'active' && (
              <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={handleStartNextSession}>
                <Plus size={13} /> 开始下一场会谈
              </button>
            )}

            {courseDetail?.status === 'active' && (
              <button className="btn btn-danger" style={{ fontSize: 12 }} onClick={handleCloseCourse}>
                <LogOut size={13} /> 结束疗程
              </button>
            )}

            {(isSending || sessionDetail?.active_operation || errorMsg) && (
              <button
                className="btn btn-secondary"
                style={{ fontSize: 11, border: '1px dashed var(--border-color)', color: 'var(--text-muted)' }}
                onClick={handleResetLock}
                title="若任务卡死或失败，点击强制解除锁定"
              >
                解除死锁
              </button>
            )}
          </div>
        </div>

        <div className="column-body">
          {errorMsg && (
            <div style={{ background: '#fee2e2', border: '1px solid #f87171', color: '#b91c1c', padding: '8px 12px', borderRadius: 6, marginBottom: 12, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, marginRight: 8 }}>
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{errorMsg}</span>
              </div>
              <button
                className="btn btn-secondary"
                style={{ fontSize: 11, padding: '2px 8px', height: 26, background: '#fff', color: '#b91c1c', borderColor: '#fca5a5' }}
                onClick={handleResetLock}
              >
                清除锁定
              </button>
            </div>
          )}

          {/* 会后整理闭环步骤卡片 */}
          {sessionDetail && (sessionDetail.status === 'closing' || sessionDetail.status === 'closed' || sessionDetail.close_steps.length > 0) && (
            <div style={{ background: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                <span>会后记忆整理与自评工作流</span>
                <span className={`tag ${sessionDetail.status === 'closed' ? 'tag-success' : 'tag-warning'}`}>
                  {sessionDetail.status === 'closed' ? '已成功归档' : '整理进行中'}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 12 }}>
                {['extract', 'merge', 'summary', 'consolidate', 'review', 'plan'].map((step) => {
                  const rec = sessionDetail.close_steps.find((s) => s.step_name === step);
                  return (
                    <div
                      key={step}
                      style={{
                        padding: '6px 10px',
                        borderRadius: 4,
                        border: '1px solid var(--border-color)',
                        background: rec?.status === 'succeeded' ? '#dcfce7' : rec?.status === 'failed' ? '#fee2e2' : '#f1f5f9',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <span>{step.toUpperCase()}</span>
                      <span style={{ fontSize: 10, fontWeight: 600 }}>
                        {rec?.status === 'succeeded' ? '完成' : rec?.status === 'failed' ? '失败' : '待处理'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 对话消息列表 */}
          <div className="messages-timeline">
            {sessionDetail?.messages.map((m) => (
              <div
                key={m.message_id}
                className={`message-bubble-wrapper ${m.role === 'counselor' ? 'counselor' : 'participant'}`}
              >
                <div className="message-sender-label">
                  <span>{m.role === 'counselor' ? '咨询师引擎' : `参与者 (${m.source})`}</span>
                  <span style={{ fontSize: 10 }}>{m.created_at.slice(11, 19)}</span>
                </div>
                <div className={`message-bubble ${m.role === 'counselor' ? 'counselor' : 'participant'}`}>
                  {m.content}
                </div>
              </div>
            ))}

            {isSending && (
              <div className="message-bubble-wrapper counselor">
                <div className="message-sender-label">咨询师引擎</div>
                <div className="message-bubble counselor" style={{ color: 'var(--text-muted)' }}>
                  正在根据允许记忆与流派目标生成回复...
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 底部输入框 */}
        {sessionDetail?.status === 'open' && (
          <div className="chat-input-bar">
            <div className="chat-input-controls">
              <textarea
                className="chat-textarea"
                placeholder={
                  observerMode
                    ? '当前为访客观察者模式，仅供查看对话，不可发送消息'
                    : courseDetail?.input_mode === 'roleplay'
                    ? '以角色身份输入话语...'
                    : '在此输入您想对咨询师说的话 (自然语言输入)...'
                }
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (!observerMode) handleSendMessage();
                  }
                }}
                disabled={isSending || observerMode}
              />
              <button
                className="btn btn-primary"
                style={{ width: 80, height: 60 }}
                onClick={handleSendMessage}
                disabled={isSending || !inputText.trim() || observerMode}
              >
                <Send size={16} />
              </button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)' }}>
              <span>按 Enter 发送，Shift + Enter 换行 | 严格幂等与双标签防冲突</span>
              <span>版本: v{courseDetail?.version}</span>
            </div>
          </div>
        )}
      </div>

      {/* 右栏：允许记忆视图与阶段目标 */}
      <div className="column-right">
        <div className="column-header">
          <span>会谈上下文与允许记忆</span>
        </div>
        <div className="column-body">
          {sessionDetail?.plan && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>会谈计划与目标</div>
              <div style={{ fontSize: 12, background: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                <div>流派: <strong>{courseDetail?.therapy.toUpperCase()}</strong></div>
                <div>当前阶段: <span className="tag tag-neutral">{sessionDetail.plan.stage}</span></div>
                <div style={{ marginTop: 6 }}>
                  <strong>议程目标:</strong>
                  <ul style={{ paddingLeft: 18, marginTop: 4 }}>
                    {sessionDetail.plan.objectives?.map((obj: string, i: number) => (
                      <li key={i}>{obj}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          {courseDetail?.roleplay_card && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6, color: '#b45309' }}>
                角色扮演设定卡 (仅供人审计，不作为已知事实)
              </div>
              <div style={{ fontSize: 12, background: '#fffbeb', border: '1px solid #fde68a', padding: 8, borderRadius: 6 }}>
                {courseDetail.roleplay_card}
              </div>
            </div>
          )}

          {sessionDetail?.memory_before && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6 }}>咨询师受控允许记忆</div>
              <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div>
                  <strong>已知事实 (已披露证据):</strong>
                  <div style={{ color: 'var(--text-muted)' }}>
                    {sessionDetail.memory_before.known_background?.facts?.length || 0} 条事实已通过证据门控
                  </div>
                </div>
                <div>
                  <strong>上轮布置的开放作业:</strong>
                  <div style={{ color: 'var(--text-muted)' }}>
                    {sessionDetail.memory_before.last_homework?.length || 0} 项
                  </div>
                </div>
                <div>
                  <strong>开放事项清单:</strong>
                  <div style={{ color: 'var(--text-muted)' }}>
                    {sessionDetail.memory_before.checklist?.open_items?.length || 0} 项未结
                  </div>
                </div>
              </div>
            </div>
          )}

          {sessionDetail?.next_plan && (
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 12 }}>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6, color: 'var(--success)' }}>
                下一次会谈计划 (由会后自评与进展生成)
              </div>
              <div style={{ fontSize: 12, background: '#f0fdf4', padding: 8, borderRadius: 6 }}>
                <div>下一阶段: {sessionDetail.next_plan.stage}</div>
                <div>目标数: {sessionDetail.next_plan.objectives?.length || 0} 项</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 新建疗程模态窗 */}
      {showCreateModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: 'white', borderRadius: 8, width: 440, padding: 20 }}>
            <h3 style={{ marginBottom: 14 }}>创建新的人工咨询疗程</h3>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>疗程标题:</label>
              <input
                type="text"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                style={{ width: '100%', padding: '8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>咨询流派:</label>
              <select
                value={newTherapy}
                onChange={(e) => setNewTherapy(e.target.value)}
                style={{ width: '100%', padding: '8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
              >
                {therapies.map((t) => (
                  <option key={t.therapy} value={t.therapy}>
                    {t.name} ({t.therapy.toUpperCase()})
                  </option>
                ))}
              </select>
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, fontWeight: 600 }}>输入模式:</label>
              <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
                <label style={{ fontSize: 13 }}>
                  <input
                    type="radio"
                    name="mode"
                    checked={newInputMode === 'natural'}
                    onChange={() => setNewInputMode('natural')}
                  /> 自然表达
                </label>
                <label style={{ fontSize: 13 }}>
                  <input
                    type="radio"
                    name="mode"
                    checked={newInputMode === 'roleplay'}
                    onChange={() => setNewInputMode('roleplay')}
                  /> 角色扮演 (案例设定)
                </label>
              </div>
            </div>
            {newInputMode === 'roleplay' && (
              <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 12, fontWeight: 600 }}>角色设定卡 (仅人可见，不作为咨询师已知事实):</label>
                <textarea
                  value={newRoleplayCard}
                  onChange={(e) => setNewRoleplayCard(e.target.value)}
                  style={{ width: '100%', height: 70, padding: '8px', marginTop: 4, borderRadius: 4, border: '1px solid var(--border-color)' }}
                  placeholder="如：25岁职场新人，近期因升职压力产生失眠与焦虑..."
                />
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={() => setShowCreateModal(false)}>取消</button>
              <button className="btn btn-primary" onClick={handleCreateCourse}>确定创建</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
