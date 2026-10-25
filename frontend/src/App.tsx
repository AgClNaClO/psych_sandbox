import React, { useState, useEffect } from 'react';
import { SimulationHub } from './components/SimulationHub';
import { InteractiveChatHub } from './components/InteractiveChatHub';
import { SkillLabHub } from './components/SkillLabHub';
import { EvaluationHub } from './components/EvaluationHub';
import { subscribeSSE } from './services/api';
import {
  FlaskConical,
  MessageSquare,
  GitBranch,
  BarChart2,
  Eye,
  UserCheck,
  Layers,
} from 'lucide-react';

type TabKey = 'simulation' | 'interactive' | 'skills' | 'evaluation';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('simulation');
  const [observerMode, setObserverMode] = useState<boolean>(false);
  const [sseConnected, setSseConnected] = useState<boolean>(false);
  const [lastEvent, setLastEvent] = useState<string>('就绪');

  useEffect(() => {
    // 监听后端全局事件流
    const unsubscribe = subscribeSSE(
      'jobs',
      (ev) => {
        setSseConnected(true);
        setLastEvent(`${ev.type} (#${ev.seq})`);
      },
      () => {
        setSseConnected(false);
      }
    );

    return () => {
      unsubscribe();
    };
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* 顶部主导航栏 */}
      <header
        style={{
          height: '56px',
          background: '#090d16',
          borderBottom: '1px solid #1e293b',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 20px',
          flexShrink: 0,
        }}
      >
        {/* 左侧 Logo 与名称 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #0284c7, #6366f1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff',
            }}
          >
            <Layers size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 700, fontSize: '1.05rem', color: '#f8fafc', letterSpacing: '0.02em' }}>
                PsychSandbox
              </span>
              <span style={{ fontSize: '0.7rem', color: '#94a3b8', background: '#1e293b', padding: '2px 6px', borderRadius: '4px' }}>
                科研工作台 v1.0
              </span>
            </div>
            <div style={{ fontSize: '0.7rem', color: '#64748b' }}>
              心理咨询多智能体仿真与技能演化平台
            </div>
          </div>
        </div>

        {/* 中间四大中心 Tab 切换 */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#0f172a', padding: '4px', borderRadius: '8px', border: '1px solid #1e293b' }}>
          <button
            onClick={() => setActiveTab('simulation')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 500,
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              background: activeTab === 'simulation' ? '#0284c7' : 'transparent',
              color: activeTab === 'simulation' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <FlaskConical size={16} />
            <span>自动实验台</span>
          </button>

          <button
            onClick={() => setActiveTab('interactive')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 500,
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              background: activeTab === 'interactive' ? '#0284c7' : 'transparent',
              color: activeTab === 'interactive' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <MessageSquare size={16} />
            <span>人工多会谈</span>
          </button>

          <button
            onClick={() => setActiveTab('skills')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 500,
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              background: activeTab === 'skills' ? '#0284c7' : 'transparent',
              color: activeTab === 'skills' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <GitBranch size={16} />
            <span>技能实验室</span>
          </button>

          <button
            onClick={() => setActiveTab('evaluation')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              fontWeight: 500,
              borderRadius: '6px',
              border: 'none',
              cursor: 'pointer',
              background: activeTab === 'evaluation' ? '#0284c7' : 'transparent',
              color: activeTab === 'evaluation' ? '#ffffff' : '#94a3b8',
              transition: 'all 0.15s ease',
            }}
          >
            <BarChart2 size={16} />
            <span>评测与数据</span>
          </button>
        </nav>

        {/* 右侧：视角切换与状态灯 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {/* 角色视角切换 */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#0f172a', padding: '3px 8px', borderRadius: '6px', border: '1px solid #1e293b' }}>
            <span style={{ fontSize: '0.75rem', color: '#64748b' }}>视角:</span>
            <button
              onClick={() => setObserverMode(false)}
              style={{
                border: 'none',
                background: !observerMode ? '#1e293b' : 'transparent',
                color: !observerMode ? '#38bdf8' : '#64748b',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <UserCheck size={12} />
              <span>研究员</span>
            </button>
            <button
              onClick={() => setObserverMode(true)}
              style={{
                border: 'none',
                background: observerMode ? '#1e293b' : 'transparent',
                color: observerMode ? '#a78bfa' : '#64748b',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <Eye size={12} />
              <span>访客观察</span>
            </button>
          </div>

          {/* SSE 实时连接指示灯 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontSize: '0.75rem',
              color: sseConnected ? '#4ade80' : '#94a3b8',
            }}
            title={`最近事件: ${lastEvent}`}
          >
            <span
              style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: sseConnected ? '#22c55e' : '#64748b',
                boxShadow: sseConnected ? '0 0 8px rgba(34, 197, 94, 0.6)' : 'none',
              }}
            />
            <span>{sseConnected ? '在线监听' : '已断开'}</span>
          </div>
        </div>
      </header>

      {/* 核心工作区主容器 */}
      <main style={{ flex: 1, height: 'calc(100vh - 56px)', overflow: 'hidden' }}>
        {activeTab === 'simulation' && <SimulationHub observerMode={observerMode} />}
        {activeTab === 'interactive' && <InteractiveChatHub observerMode={observerMode} />}
        {activeTab === 'skills' && <SkillLabHub observerMode={observerMode} />}
        {activeTab === 'evaluation' && <EvaluationHub observerMode={observerMode} />}
      </main>
    </div>
  );
};

export default App;
