import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import type { ComparisonRow, ExportAudit } from '../types';
import {
  Download,
  ShieldCheck,
  FileCheck,
  AlertCircle,
  RefreshCw,
  Sliders,
  CheckCircle2,
} from 'lucide-react';

interface EvaluationHubProps {
  observerMode?: boolean;
}

export const EvaluationHub: React.FC<EvaluationHubProps> = ({ observerMode = false }) => {
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [audits, setAudits] = useState<ExportAudit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 筛选与表单
  const [selectedTherapy, setSelectedTherapy] = useState<string>('all');
  const [sftFilename, setSftFilename] = useState<string>('sft_export_v1.jsonl');
  const [includeInteractiveSFT, setIncludeInteractiveSFT] = useState<boolean>(false);
  const [dpoFilename, setDpoFilename] = useState<string>('dpo_pairs_v1.jsonl');

  const [exportingSFT, setExportingSFT] = useState(false);
  const [exportingDPO, setExportingDPO] = useState(false);
  const [lastAuditResult, setLastAuditResult] = useState<ExportAudit | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [compData, auditData] = await Promise.all([
        api.getComparisons(),
        api.getExportAudits().catch(() => []),
      ]);
      setRows(compData);
      setAudits(auditData);
    } catch (err: any) {
      setError(err.message || '加载评测与导出数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleExportSFT = async () => {
    setExportingSFT(true);
    setError(null);
    try {
      const audit = await api.exportSFT({
        output_filename: sftFilename,
        include_interactive: includeInteractiveSFT,
      });
      setLastAuditResult(audit);
      fetchData();
    } catch (err: any) {
      setError(`SFT 导出失败: ${err.message}`);
    } finally {
      setExportingSFT(false);
    }
  };

  const handleExportDPO = async () => {
    setExportingDPO(true);
    setError(null);
    try {
      const audit = await api.exportDPO({
        output_filename: dpoFilename,
      });
      setLastAuditResult(audit);
      fetchData();
    } catch (err: any) {
      setError(`DPO 导出失败: ${err.message}`);
    } finally {
      setExportingDPO(false);
    }
  };

  const filteredRows = rows.filter((r) => {
    if (selectedTherapy !== 'all' && r.therapy !== selectedTherapy) return false;
    return true;
  });

  // 计算指标统计
  const validScores = filteredRows
    .map((r) => r.model_supervisor_score)
    .filter((s): s is number => s !== null && s !== undefined);
  const n = validScores.length;
  const avgScore = n > 0 ? validScores.reduce((a, b) => a + b, 0) / n : null;
  const variance =
    n > 1
      ? validScores.reduce((acc, v) => acc + Math.pow(v - (avgScore || 0), 2), 0) / (n - 1)
      : null;
  const std = variance !== null ? Math.sqrt(variance) : null;

  return (
    <div className="workbench-layout">
      {/* 左侧：筛选与科研导出操作 */}
      <div className="workbench-col-left">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sliders size={18} />
            <span>评测控制台</span>
          </h2>
          <button className="btn-secondary" style={{ padding: '4px 8px' }} onClick={fetchData} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div style={{ marginBottom: '20px' }}>
          <label style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'block', marginBottom: '6px' }}>流派过滤</label>
          <select
            className="input-base"
            value={selectedTherapy}
            onChange={(e) => setSelectedTherapy(e.target.value)}
          >
            <option value="all">全部流派</option>
            <option value="behavioral">行为治疗 (BT)</option>
            <option value="cbt">认知行为 (CBT)</option>
            <option value="humanistic_existential">人本存在 (HET)</option>
            <option value="psychodynamic">精神动力 (PDT)</option>
            <option value="postmodern">后现代叙事 (PMT)</option>
          </select>
        </div>

        {/* 导出区域 */}
        <div style={{ borderTop: '1px solid #334155', paddingTop: '16px', marginBottom: '20px' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Download size={16} color="#38bdf8" />
            <span>SFT 数据集导出</span>
          </h3>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '10px' }}>
            仅导出包含受控合法上下文、结构化规划、记忆证据与安全门控的正式轨迹。
          </div>
          <div style={{ marginBottom: '10px' }}>
            <label style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>输出文件名</label>
            <input
              type="text"
              className="input-base"
              value={sftFilename}
              onChange={(e) => setSftFilename(e.target.value)}
              placeholder="sft_output.jsonl"
              style={{ marginTop: '4px' }}
            />
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.75rem', color: '#cbd5e1', marginBottom: '14px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={includeInteractiveSFT}
              onChange={(e) => setIncludeInteractiveSFT(e.target.checked)}
            />
            <span>包含已完成的人工会谈 (默认排除)</span>
          </label>
          <button
            className="btn-primary"
            style={{ width: '100%', fontSize: '0.8rem' }}
            onClick={handleExportSFT}
            disabled={exportingSFT || observerMode}
          >
            {exportingSFT ? '正在导出并哈希留痕...' : '执行 SFT 合规导出'}
          </button>
        </div>

        <div style={{ borderTop: '1px solid #334155', paddingTop: '16px' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Download size={16} color="#c084fc" />
            <span>DPO 偏好对导出</span>
          </h3>
          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '10px' }}>
            严格限制为同一 RFT 批次、同一提示上下文内配对；排除未过安全门控与跨轨迹末句伪负例。
          </div>
          <div style={{ marginBottom: '12px' }}>
            <label style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>输出文件名</label>
            <input
              type="text"
              className="input-base"
              value={dpoFilename}
              onChange={(e) => setDpoFilename(e.target.value)}
              placeholder="dpo_pairs.jsonl"
              style={{ marginTop: '4px' }}
            />
          </div>
          <button
            className="btn-primary"
            style={{ width: '100%', fontSize: '0.8rem', background: '#9333ea' }}
            onClick={handleExportDPO}
            disabled={exportingDPO || observerMode}
          >
            {exportingDPO ? '正在提取偏好对...' : '执行 DPO 偏好对导出'}
          </button>
        </div>

        {/* 审计说明 */}
        <div style={{ marginTop: '24px', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '6px', padding: '12px', fontSize: '0.75rem', color: '#94a3b8' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#38bdf8', marginBottom: '6px', fontWeight: 600 }}>
            <ShieldCheck size={14} />
            <span>科研合规准则</span>
          </div>
          <ul style={{ paddingLeft: '16px', margin: 0, lineHeight: '1.4' }}>
            <li>同案例候选全部分配至同一划分 (Train/Val/Test)</li>
            <li>人工数据严格物理隔离，默认不入训练集</li>
            <li>缺少用量时不填零，保持真实未知</li>
          </ul>
        </div>
      </div>

      {/* 中间：多维评测对比大盘 */}
      <div className="workbench-col-center">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h1 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 4px 0' }}>多源实验评测对比大盘</h1>
            <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>
              模型评分、人工反馈与自动仿真分栏对比；样本量受限时如实注明不确定性。
            </p>
          </div>
          <div className="tag-pill tag-pill-info">
            已收录 {filteredRows.length} 条实验运行
          </div>
        </div>

        {error && (
          <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid #ef4444', color: '#fca5a5', padding: '10px 14px', borderRadius: '6px', marginBottom: '16px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* 统计卡片指标 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '8px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>实验运行总数</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '4px' }}>{filteredRows.length}</div>
            <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: '4px' }}>含各流派已完成与推进中运行</div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '8px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>督导评分均值</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '4px', color: '#38bdf8' }}>
              {avgScore !== null ? avgScore.toFixed(3) : '-'}
            </div>
            <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: '4px' }}>
              基于 {n} 个完成整体评估的轨迹
            </div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '8px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>评分标准差 / 不确定性</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 600, marginTop: '8px' }}>
              {std !== null ? `± ${std.toFixed(3)}` : n === 1 ? '无法估计方差 (n=1)' : '-'}
            </div>
            <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: '4px' }}>
              {n < 2 ? '缺少样本量无法断言显著性' : '无偏样本方差估算'}
            </div>
          </div>

          <div style={{ background: '#1e293b', padding: '12px', borderRadius: '8px', border: '1px solid #334155' }}>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>实验异常/失败率</div>
            <div style={{ fontSize: '1.4rem', fontWeight: 700, marginTop: '4px', color: '#f87171' }}>
              {filteredRows.length > 0
                ? `${(
                    (filteredRows.filter((r) => r.status === 'failed').length / filteredRows.length) *
                    100
                  ).toFixed(1)}%`
                : '0.0%'}
            </div>
            <div style={{ fontSize: '0.7rem', color: '#64748b', marginTop: '4px' }}>
              网络异常或安全门控阻断记录
            </div>
          </div>
        </div>

        {/* 核心对比表格 */}
        <div style={{ background: '#1e293b', borderRadius: '8px', border: '1px solid #334155', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
            <thead>
              <tr style={{ background: '#0f172a', borderBottom: '1px solid #334155', color: '#94a3b8', textAlign: 'left' }}>
                <th style={{ padding: '10px 12px' }}>运行编号 / 案例</th>
                <th style={{ padding: '10px 12px' }}>流派</th>
                <th style={{ padding: '10px 12px' }}>会谈数</th>
                <th style={{ padding: '10px 12px' }}>模型督导分</th>
                <th style={{ padding: '10px 12px' }}>人工反馈分</th>
                <th style={{ padding: '10px 12px' }}>自动仿真分</th>
                <th style={{ padding: '10px 12px' }}>延迟 / 成本</th>
                <th style={{ padding: '10px 12px' }}>状态</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ padding: '32px', textAlign: 'center', color: '#64748b' }}>
                    暂无实验对比记录
                  </td>
                </tr>
              ) : (
                filteredRows.map((r) => (
                  <tr key={r.run_id} style={{ borderBottom: '1px solid #334155' }}>
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{r.run_id}</div>
                      <div style={{ fontSize: '0.7rem', color: '#64748b' }}>案例: {r.case_id}</div>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span className="tag-pill tag-pill-therapy">{r.therapy}</span>
                    </td>
                    <td style={{ padding: '10px 12px' }}>{r.sessions_completed} 场</td>
                    <td style={{ padding: '10px 12px', fontWeight: 600, color: r.model_supervisor_score ? '#38bdf8' : '#64748b' }}>
                      {r.model_supervisor_score !== null ? r.model_supervisor_score.toFixed(3) : '-'}
                    </td>
                    <td style={{ padding: '10px 12px', color: '#64748b' }}>
                      {r.human_feedback_score !== null ? r.human_feedback_score.toFixed(3) : '待专家评定'}
                    </td>
                    <td style={{ padding: '10px 12px', color: r.auto_sim_score ? '#a78bfa' : '#64748b' }}>
                      {r.auto_sim_score !== null ? r.auto_sim_score.toFixed(3) : '-'}
                    </td>
                    <td style={{ padding: '10px 12px', fontSize: '0.75rem', color: '#94a3b8' }}>
                      <div>{r.latency_sec_avg ? `${r.latency_sec_avg.toFixed(1)}s` : '未知'}</div>
                      <div style={{ color: '#64748b' }}>{r.cost_estimate_cny ? `¥${r.cost_estimate_cny.toFixed(2)}` : '未知'}</div>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span className={`tag-pill tag-pill-${r.status === 'completed' ? 'success' : r.status === 'failed' ? 'danger' : 'warning'}`}>
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 右侧：导出审计与数据溯源 */}
      <div className="workbench-col-right">
        <h2 style={{ fontSize: '1.05rem', fontWeight: 600, margin: '0 0 16px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FileCheck size={18} />
          <span>导出审计与防泄漏留痕</span>
        </h2>

        {/* 最近一次导出结果提示 */}
        {lastAuditResult && (
          <div style={{ background: '#022c22', border: '1px solid #059669', borderRadius: '8px', padding: '12px', marginBottom: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#34d399', fontWeight: 600, fontSize: '0.85rem', marginBottom: '6px' }}>
              <CheckCircle2 size={16} />
              <span>导出已完成并登记</span>
            </div>
            <div style={{ fontSize: '0.75rem', color: '#cbd5e1' }}>
              <div>审计编号: {lastAuditResult.export_id}</div>
              <div>样本行数: {lastAuditResult.row_count} 行</div>
              <div>
                划分: 训练 {lastAuditResult.split_info.train || 0} / 验证 {lastAuditResult.split_info.val || 0} / 测试 {lastAuditResult.split_info.test || 0}
              </div>
              <div style={{ wordBreak: 'break-all', marginTop: '4px', fontFamily: 'monospace', fontSize: '0.7rem', color: '#94a3b8' }}>
                SHA256: {lastAuditResult.sha256}
              </div>
            </div>
          </div>
        )}

        <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: '12px' }}>
          历史导出任务台账 ({audits.length} 项)
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {audits.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: '#64748b', fontSize: '0.8rem' }}>
              暂无历史导出审计
            </div>
          ) : (
            audits.map((a) => (
              <div key={a.export_id} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', padding: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                  <span className={`tag-pill tag-pill-${a.export_type === 'sft' ? 'info' : 'warning'}`}>
                    {a.export_type.toUpperCase()}
                  </span>
                  <span style={{ fontSize: '0.7rem', color: '#64748b' }}>{a.created_at.slice(0, 16)}</span>
                </div>
                <div style={{ fontSize: '0.75rem', color: '#e2e8f0', fontWeight: 500, wordBreak: 'break-all', margin: '4px 0' }}>
                  {a.output_path.split(/[\\/]/).pop()}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>
                  有效样本: {a.row_count} 行 (训练 {a.split_info.train || 0} / 验证 {a.split_info.val || 0} / 测试 {a.split_info.test || 0})
                </div>
                <div style={{ fontSize: '0.65rem', color: '#64748b', fontFamily: 'monospace', wordBreak: 'break-all', marginTop: '4px' }}>
                  Hash: {a.sha256.slice(0, 20)}...
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
