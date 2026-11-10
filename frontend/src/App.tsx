import React, { useState, useEffect } from 'react';
import { SimulationHub } from './components/SimulationHub';
import { InteractiveChatHub } from './components/InteractiveChatHub';
import { SkillLabHub } from './components/SkillLabHub';
import { EvaluationHub } from './components/EvaluationHub';
import { SkillEvolutionExperiment } from './components/SkillEvolutionExperiment';
import { subscribeSSE } from './services/api';
import { FlaskConical, MessageSquare, GitBranch, BarChart2, Eye, UserCheck, Layers } from 'lucide-react';
import './App.css';

type TabKey = 'simulation' | 'interactive' | 'skills' | 'evaluation' | 'skill-experiment';

const tabs = [
  { key: 'simulation', label: '自动实验台', icon: FlaskConical },
  { key: 'interactive', label: '人工多会谈', icon: MessageSquare },
  { key: 'skills', label: '技能实验室', icon: GitBranch },
  { key: 'skill-experiment', label: '进化试验', icon: FlaskConical },
  { key: 'evaluation', label: '评测与数据', icon: BarChart2 },
] as const;

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>('simulation');
  const [observerMode, setObserverMode] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState('就绪');

  useEffect(() => subscribeSSE(
    'jobs',
    (event) => { setSseConnected(true); setLastEvent(`${event.type} (#${event.seq})`); },
    () => setSseConnected(false),
    () => setSseConnected(true),
  ), []);

  return (
    <div className="app-shell">
      <header className="workbench-header">
        <div className="workbench-brand">
          <div className="workbench-mark"><Layers size={18} strokeWidth={1.8} /></div>
          <div>
            <div className="workbench-brand-name">PsychSandbox <span>科研工作台</span></div>
            <p className="workbench-brand-description">心理咨询多智能体仿真与技能演化平台</p>
          </div>
        </div>
        <nav className="workbench-nav" aria-label="工作台导航">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button key={key} className={`workbench-nav-item ${activeTab === key ? 'active' : ''}`}
              onClick={() => setActiveTab(key)} aria-pressed={activeTab === key}>
              <Icon size={15} strokeWidth={1.8} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="workbench-header-tools">
          <div className="view-switch" role="group" aria-label="角色视角">
            <button className={!observerMode ? 'active' : ''} aria-pressed={!observerMode} onClick={() => setObserverMode(false)}>
              <UserCheck size={12} />研究员
            </button>
            <button className={observerMode ? 'active' : ''} aria-pressed={observerMode} onClick={() => setObserverMode(true)}>
              <Eye size={12} />访客观察
            </button>
          </div>
          <div className={`connection-status ${sseConnected ? 'connected' : ''}`} title={`最近事件: ${lastEvent}`}>
            <span /><span>{sseConnected ? '在线监听' : '连接中'}</span>
          </div>
        </div>
      </header>
      <main className="workbench-main">
        {activeTab === 'simulation' && <SimulationHub observerMode={observerMode} />}
        {activeTab === 'interactive' && <InteractiveChatHub observerMode={observerMode} />}
        {activeTab === 'skills' && <SkillLabHub observerMode={observerMode} />}
        {activeTab === 'skill-experiment' && <SkillEvolutionExperiment observerMode={observerMode} />}
        {activeTab === 'evaluation' && <EvaluationHub observerMode={observerMode} />}
      </main>
    </div>
  );
};

export default App;
