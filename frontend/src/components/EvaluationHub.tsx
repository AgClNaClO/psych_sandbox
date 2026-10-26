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
  BarChart3,
  Layers,
  Database,
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
  const failedCount = filteredRows.filter((r) => r.status === 'failed').length;
  const failureRate = filteredRows.length > 0 ? (failedCount / filteredRows.length) * 100 : 0;

  return (
    <div className="three-column-container">
      {/* 左栏：控制台与合规导出 */}
      <div className="column-left">
        <div className="column-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Sliders size={15} /> 评测控制与导出
          </span>
          <button
            className="btn btn-secondary"
            style={{ padding: '3px 8px', height: 26, fontSize: 11 }}
            onClick={fetchData}
            disabled={loading}
            title="刷新数据"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div className="column-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 流派过滤 */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-main)', display: 'block', marginBottom: 6 }}>
              流派对比筛选
            </label>
            <select
              style={{
                width: '100%',
                padding: '6px 10px',
                fontSize: 13,
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                background: '#fff',
                outline: 'none',
              }}
              value={selectedTherapy}
              onChange={(e) => setSelectedTherapy(e.target.value)}
            >
              <option value="all">全部流派 (BT, CBT, HET, PDT, PMT)</option>
              <option value="behavioral">行为治疗 (BT)</option>
              <option value="cbt">认知行为 (CBT)</option>
              <option value="humanistic_existential">人本存在 (HET)</option>
              <option value="psychodynamic">精神动力 (PDT)</option>
              <option value="postmodern">后现代叙事 (PMT)</option>
            </select>
          </div>

          {/* SFT 数据集导出卡片 */}
          <div style={{ background: '#fff', border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, fontWeight: 600, fontSize: 13, color: 'var(--primary)' }}>
              <Database size={15} />
              <span>SFT 训练集规范导出</span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, lineHeight: 1.4 }}>
              严格仅导出受控合法上下文、结构化规划、记忆证据与安全门控的正式轨迹。
            </p>
            <div style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                输出文件名 (.jsonl)
              </label>
              <input
                type="text"
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  fontSize: 12,
                  border: '1px solid var(--border-color)',
                  borderRadius: 4,
                  outline: 'none',
                }}
                value={sftFilename}
                onChange={(e) => setSftFilename(e.target.value)}
                placeholder="sft_output.jsonl"
              />
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-muted)', marginBottom: 10, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={includeInteractiveSFT}
                onChange={(e) => setIncludeInteractiveSFT(e.target.checked)}
              />
              <span>包含已完成的人工会谈 (默认排除隔离)</span>
            </label>
            <button
              className="btn btn-primary"
              style={{ width: '100%', fontSize: 12, height: 32 }}
              onClick={handleExportSFT}
              disabled={exportingSFT || observerMode}
            >
              <Download size={13} />
              {exportingSFT ? '正在导出并哈希留痕...' : '执行 SFT 合规导出'}
            </button>
          </div>

          {/* DPO 偏好对导出卡片 */}
          <div style={{ background: '#fff', border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, fontWeight: 600, fontSize: 13, color: '#7c3aed' }}>
              <Layers size={15} />
              <span>DPO 偏好对合规导出</span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, lineHeight: 1.4 }}>
              严格限制为同一 RFT 批次与相同提示上下文配对；杜绝跨轨迹末句伪负例。
            </p>
            <div style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 11, fontWeight: 500, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>
                输出文件名 (.jsonl)
              </label>
              <input
                type="text"
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  fontSize: 12,
                  border: '1px solid var(--border-color)',
                  borderRadius: 4,
                  outline: 'none',
                }}
                value={dpoFilename}
                onChange={(e) => setDpoFilename(e.target.value)}
                placeholder="dpo_pairs.jsonl"
              />
            </div>
            <button
              className="btn btn-primary"
              style={{ width: '100%', fontSize: 12, height: 32, background: '#7c3aed', borderColor: '#6d28d9' }}
              onClick={handleExportDPO}
              disabled={exportingDPO || observerMode}
            >
              <Download size={13} />
              {exportingDPO ? '正在配对验证...' : '执行 DPO 偏好对导出'}
            </button>
          </div>

          {/* 科研合规准则 */}
          <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: 10, fontSize: 11, color: '#0369a1' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 4 }}>
              <ShieldCheck size={14} />
              <span>科研防污染准则</span>
            </div>
            <ul style={{ paddingLeft: 16, margin: 0, lineHeight: 1.5 }}>
              <li>同案例全部候选分配至同一划分 (Train/Val/Test)</li>
              <li>人工数据物理隔离，默认严禁混入训练集</li>
              <li>缺少真实用量与评定标为未知，杜绝虚假填零</li>
            </ul>
          </div>
        </div>
      </div>

      {/* 中栏：多源实验评测对比大盘 */}
      <div className="column-center">
        <div className="column-header" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BarChart3 size={16} color="var(--primary)" />
            <span>多源实验评测对比大盘</span>
          </div>
          <span className="tag tag-info" style={{ fontSize: 11 }}>
            已收录 {filteredRows.length} 条实验运行
          </span>
        </div>

        <div className="column-body">
          {error && (
            <div style={{ background: '#fee2e2', border: '1px solid #f87171', color: '#b91c1c', padding: '8px 12px', borderRadius: 6, marginBottom: 12, fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <AlertCircle size={15} />
              <span>{error}</span>
            </div>
          )}

          {/* 4 张统计卡片 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            <div style={{ background: '#fff', padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border-color)', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>实验运行总数</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-main)', marginTop: 2 }}>{filteredRows.length}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>各流派仿真与交互运行</div>
            </div>

            <div style={{ background: '#fff', padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border-color)', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>整体督导评分均值</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--primary)', marginTop: 2 }}>
                {avgScore !== null ? avgScore.toFixed(3) : '-'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                基于 {n} 个完成整体评估的轨迹
              </div>
            </div>

            <div style={{ background: '#fff', padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border-color)', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>评分标准差 / 不确定性</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: '#0f766e', marginTop: 6 }}>
                {std !== null ? `± ${std.toFixed(3)}` : n === 1 ? '无法估计方差 (n=1)' : '-'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                {n < 2 ? '样本量受限时如实注明' : '无偏样本方差估算'}
              </div>
            </div>

            <div style={{ background: '#fff', padding: '12px 14px', borderRadius: 8, border: '1px solid var(--border-color)', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>实验异常 / 失败率</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: failureRate > 0 ? 'var(--danger)' : 'var(--success)', marginTop: 2 }}>
                {failureRate.toFixed(1)}%
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                网络异常或安全门控拦截
              </div>
            </div>
          </div>

          {/* 核心对比表格 */}
          <div style={{ background: '#fff', borderRadius: 8, border: '1px solid var(--border-color)', overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', textAlign: 'left' }}>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>运行编号 / 案例</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>流派</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>会谈数</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>模型督导分</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>人工反馈分</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>自动仿真分</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>延迟 / 成本</th>
                  <th style={{ padding: '10px 12px', fontWeight: 600 }}>运行状态</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                      暂无实验对比记录
                    </td>
                  </tr>
                ) : (
                  filteredRows.map((r) => (
                    <tr
                      key={r.run_id}
                      style={{ borderBottom: '1px solid var(--border-color)', transition: 'background-color 0.15s' }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#f8fafc')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                    >
                      <td style={{ padding: '10px 12px' }}>
                        <div style={{ fontWeight: 600, color: 'var(--text-main)', fontFamily: 'monospace' }}>{r.run_id}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>案例: {r.case_id}</div>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span className="tag tag-neutral">{r.therapy.toUpperCase()}</span>
                      </td>
                      <td style={{ padding: '10px 12px', fontWeight: 500 }}>{r.sessions_completed} 场</td>
                      <td style={{ padding: '10px 12px', fontWeight: 600, color: r.model_supervisor_score !== null ? 'var(--primary)' : 'var(--text-muted)' }}>
                        {r.model_supervisor_score !== null ? r.model_supervisor_score.toFixed(3) : '-'}
                      </td>
                      <td style={{ padding: '10px 12px', color: r.human_feedback_score !== null ? 'var(--success)' : 'var(--text-muted)' }}>
                        {r.human_feedback_score !== null ? r.human_feedback_score.toFixed(3) : '待专家评定'}
                      </td>
                      <td style={{ padding: '10px 12px', color: r.auto_sim_score !== null ? '#7c3aed' : 'var(--text-muted)' }}>
                        {r.auto_sim_score !== null ? r.auto_sim_score.toFixed(3) : '-'}
                      </td>
                      <td style={{ padding: '10px 12px', fontSize: 11, color: 'var(--text-muted)' }}>
                        <div>{r.latency_sec_avg ? `${r.latency_sec_avg.toFixed(1)}s` : '未知'}</div>
                        <div style={{ color: '#94a3b8' }}>{r.cost_estimate_cny ? `¥${r.cost_estimate_cny.toFixed(2)}` : '未知'}</div>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span
                          className={`tag tag-${
                            r.status === 'completed'
                              ? 'success'
                              : r.status === 'failed'
                              ? 'danger'
                              : 'warning'
                          }`}
                        >
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
      </div>

      {/* 右栏：导出审计与数据溯源 */}
      <div className="column-right">
        <div className="column-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <FileCheck size={15} color="var(--success)" /> 导出审计与溯源留痕
          </span>
          <span className="tag tag-neutral" style={{ fontSize: 11 }}>{audits.length} 项</span>
        </div>

        <div className="column-body">
          {/* 最近一次导出结果提示 */}
          {lastAuditResult && (
            <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: 12, marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#16a34a', fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
                <CheckCircle2 size={15} />
                <span>导出成功已登记留痕</span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-main)', display: 'flex', flexDirection: 'column', gap: 3 }}>
                <div>编号: <strong>{lastAuditResult.export_id}</strong></div>
                <div>行数: <strong>{lastAuditResult.row_count}</strong> 样本</div>
                <div>
                  划分: 训练 {lastAuditResult.split_info.train || 0} / 验证 {lastAuditResult.split_info.val || 0} / 测试 {lastAuditResult.split_info.test || 0}
                </div>
                <div style={{ wordBreak: 'break-all', marginTop: 4, fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)' }}>
                  SHA256: {lastAuditResult.sha256}
                </div>
              </div>
            </div>
          )}

          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10 }}>
            历史合规导出台账 ({audits.length})
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {audits.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 30, color: 'var(--text-muted)', fontSize: 12, background: 'var(--bg-subtle)', borderRadius: 6 }}>
                暂无历史导出审计记录
              </div>
            ) : (
              audits.map((a) => (
                <div
                  key={a.export_id}
                  style={{
                    background: '#fff',
                    border: '1px solid var(--border-color)',
                    borderRadius: 6,
                    padding: 10,
                    boxShadow: '0 1px 2px rgba(0,0,0,0.02)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span className={`tag tag-${a.export_type === 'sft' ? 'info' : 'warning'}`} style={{ fontSize: 10 }}>
                      {a.export_type.toUpperCase()}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{a.created_at.slice(0, 16)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-main)', fontWeight: 600, wordBreak: 'break-all', margin: '4px 0' }}>
                    {a.output_path.split(/[\\/]/).pop()}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    样本量: {a.row_count} 行 (训练 {a.split_info.train || 0} / 验证 {a.split_info.val || 0} / 测试 {a.split_info.test || 0})
                  </div>
                  <div style={{ fontSize: 10, color: '#94a3b8', fontFamily: 'monospace', wordBreak: 'break-all', marginTop: 4 }}>
                    Hash: {a.sha256.slice(0, 24)}...
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
