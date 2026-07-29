from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from ..domain import RunResult, SessionRecord
from .charts import metric_bars, state_line_chart


PROCESS_STEPS = (
    ("会谈准备", "读取允许记忆、阶段与目标"),
    ("咨询师行动", "评估 → 选技能 → 定策略 → 回复"),
    ("双重安全门", "输入风险与输出边界检查"),
    ("来访者反应", "披露门控 → 反应 → 行为/抗拒 → 表达"),
    ("状态更新", "信任、痛苦、希望与抗拒"),
    ("督导与计划", "双侧评分 → 纵向趋势 → 下一计划"),
)


def generate_run_report(result: RunResult, output: Path) -> Path:
    """Create a self-contained HTML report for offline review and replay."""

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    scores = [
        item.supervisor_report.overall_score
        for item in result.sessions
        if item.supervisor_report
    ]
    mean_score = sum(scores) / len(scores) if scores else 0
    safety_events = sum(
        event.level.value in {"high", "imminent"}
        for session in result.sessions
        for event in session.risk_events
    )
    leaks = sum(
        bool(
            record.get("client_leakage", {}).get("exposed_to_counselor", False)
        )
        for session in result.sessions
        for record in session.turn_records
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>心理咨询沙盒运行报告 · {escape(result.run_id)}</title>
<style>{_styles()}</style>
</head>
<body>
<main>
  <header class="hero">
    <div>
      <p class="eyebrow">PHASE 1 · RESEARCH SANDBOX</p>
      <h1>心理咨询沙盒运行报告</h1>
      <p>{escape(result.case_id)} · {escape(result.therapy)} · seed {result.seed}</p>
    </div>
    <div class="disclaimer">仅用于教学与研究，不代表临床疗效</div>
  </header>
  <section class="summary-grid">
    {_summary_card("会谈数", str(len(result.sessions)), "sessions")}
    {_summary_card("平均督导分", f"{mean_score:.2f}", "/ 10")}
    {_summary_card("高风险事件", str(safety_events), "需人工复核")}
    {_summary_card("暴露泄漏", str(leaks), "越低越好")}
  </section>
  <section class="panel">
    <h2>运行过程</h2>
    <div class="process">{_process_flow()}</div>
  </section>
  <section class="panel">
    <h2>来访者状态趋势</h2>
    <p class="muted">以下均为 0–1 仿真变量，不是临床量表分数。</p>
    <div class="chart">{state_line_chart(result.sessions)}</div>
  </section>
  <section>
    <h2>会谈与督导明细</h2>
    {''.join(_session_section(item) for item in result.sessions)}
  </section>
</main>
</body>
</html>"""
    output.write_text(html, encoding="utf-8")
    return output


def _summary_card(label: str, value: str, note: str) -> str:
    return (
        '<div class="summary-card">'
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong>"
        f"<small>{escape(note)}</small></div>"
    )


def _process_flow() -> str:
    return "".join(
        (
            '<div class="process-step">'
            f"<strong>{index}. {escape(title)}</strong>"
            f"<span>{escape(description)}</span></div>"
        )
        + ('<div class="arrow">→</div>' if index < len(PROCESS_STEPS) else "")
        for index, (title, description) in enumerate(PROCESS_STEPS, start=1)
    )


def _session_section(session: SessionRecord) -> str:
    report = session.supervisor_report
    score = report.overall_score if report else 0
    longitudinal = session.longitudinal_report
    trend = longitudinal.trend if longitudinal else "n/a"
    action = longitudinal.stage_action if longitudinal else "n/a"
    feedback = (
        "".join(f"<li>{escape(item)}</li>" for item in report.feedback)
        if report and report.feedback
        else "<li>本次规则督导未生成低分修复项</li>"
    )
    return f"""
<article class="session">
  <div class="session-head">
    <div>
      <span class="badge">Session {session.session_index}</span>
      <h3>{escape(session.plan.stage.value)}</h3>
      <p>{escape('；'.join(session.plan.objectives[:3]))}</p>
    </div>
    <div class="score">{score:.2f}<small>/10</small></div>
  </div>
  <div class="session-grid">
    <div>
      <h4>督导指标</h4>
      {metric_bars(report.metrics if report else [])}
    </div>
    <div>
      <h4>纵向判断</h4>
      <div class="trend"><span>趋势</span><strong>{escape(trend)}</strong></div>
      <div class="trend"><span>阶段动作</span><strong>{escape(action)}</strong></div>
      {_delta_table(session)}
      <h4>反馈进入下一计划</h4>
      <ul>{feedback}</ul>
    </div>
  </div>
  <details>
    <summary>查看逐轮过程（{len(session.turn_records)} turns）</summary>
    {_turn_timeline(session)}
  </details>
  <details>
    <summary>查看对话</summary>
    <div class="dialogue">{_dialogue(session)}</div>
  </details>
</article>"""


def _delta_table(session: SessionRecord) -> str:
    report = session.longitudinal_report
    if not report:
        return '<p class="muted">暂无纵向数据</p>'
    labels = {
        "trust": "信任",
        "distress": "痛苦",
        "hope": "希望",
        "resistance": "抗拒",
        "valence": "效价",
        "arousal": "唤醒",
    }
    rows = "".join(
        f"<tr><td>{escape(labels.get(key, key))}</td>"
        f'<td class="{"positive" if value > 0 else "negative" if value < 0 else ""}">'
        f"{value:+.3f}</td></tr>"
        for key, value in report.state_deltas.items()
    )
    return f'<table class="delta"><tbody>{rows}</tbody></table>'


def _turn_timeline(session: SessionRecord) -> str:
    return '<div class="timeline">' + "".join(
        _turn_card(record) for record in session.turn_records
    ) + "</div>"


def _turn_card(record: dict[str, Any]) -> str:
    decision = record.get("decision", {})
    signal = record.get("client_turn_signal", {})
    disclosure = record.get("disclosure_decision", {})
    input_safety = record.get("input_safety", {})
    output_safety = record.get("output_safety", {})
    skills = decision.get("selected_atomic_skill_ids", [])
    state_before = record.get("state_before", {})
    state_after = record.get("state_after", {})
    trust_change = _number_delta(state_before, state_after, "trust")
    distress_change = _number_delta(state_before, state_after, "distress")
    return (
        '<div class="turn-card">'
        f'<div class="turn-index">Turn {escape(str(record.get("turn_index", "?")))}</div>'
        f"<p><b>目标/策略：</b>{escape(str(decision.get('strategy', '—')))}</p>"
        f"<p><b>技能：</b>{escape(', '.join(skills) or '无')}</p>"
        f"<p><b>来访者信号：</b>{escape(str(signal.get('reaction', '—')))} / "
        f"{escape(str(signal.get('behavior', '—')))}</p>"
        f"<p><b>披露：</b>retrieved {len(disclosure.get('retrieved', []))}，"
        f"blocked {len(disclosure.get('blocked', []))}</p>"
        f"<p><b>安全：</b>{escape(str(input_safety.get('level', '—')))} → "
        f"{escape(str(output_safety.get('level', '—')))}</p>"
        f"<p><b>状态变化：</b>信任 {trust_change}，痛苦 {distress_change}</p>"
        "</div>"
    )


def _number_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> str:
    try:
        return f"{float(after[key]) - float(before[key]):+.3f}"
    except (KeyError, TypeError, ValueError):
        return "—"


def _dialogue(session: SessionRecord) -> str:
    return "".join(
        '<div class="message '
        + escape(message.role)
        + '"><span>'
        + ("来访者" if message.role == "client" else "咨询师")
        + "</span><p>"
        + escape(message.content)
        + "</p></div>"
        for message in session.messages
        if message.role in {"client", "counselor"}
    )


def _styles() -> str:
    return """
:root{color-scheme:light;--ink:#172033;--muted:#64748b;--line:#dce3ed;
--panel:#fff;--bg:#f4f7fb;--blue:#3157d5;--green:#1b8f5a;--red:#c94343}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1180px;margin:auto;padding:32px 22px 72px}.hero{display:flex;
justify-content:space-between;align-items:flex-end;padding:30px;border-radius:20px;
background:linear-gradient(135deg,#172554,#3157d5);color:#fff}.hero h1{margin:4px 0;
font-size:32px}.hero p{margin:0}.eyebrow{letter-spacing:.12em;opacity:.8}
.disclaimer{padding:8px 12px;border:1px solid #ffffff55;border-radius:99px}
.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}
.summary-card,.panel,.session{background:var(--panel);border:1px solid var(--line);
border-radius:16px;box-shadow:0 7px 24px #1720330d}.summary-card{padding:18px}
.summary-card span,.summary-card small{display:block;color:var(--muted)}
.summary-card strong{display:block;font-size:28px;margin:4px 0}.panel{padding:22px;
margin:18px 0}h2{margin:28px 0 12px}h3,h4{margin:6px 0}.process{display:flex;
align-items:stretch;overflow:auto;padding:4px}.process-step{min-width:145px;flex:1;
padding:13px;background:#eef2ff;border-radius:10px}.process-step span{display:block;
color:var(--muted);font-size:12px}.arrow{align-self:center;padding:8px;color:var(--blue);
font-size:20px}.chart svg{width:100%;height:auto}.axis,.legend{font-size:11px;fill:#64748b}
.muted{color:var(--muted)}.session{padding:22px;margin:16px 0}.session-head{display:flex;
justify-content:space-between;gap:16px;border-bottom:1px solid var(--line);padding-bottom:14px}
.badge{display:inline-block;background:#e0e7ff;color:#3730a3;border-radius:99px;
padding:3px 9px;font-weight:700}.score{font-size:34px;font-weight:800;color:var(--blue)}
.score small{font-size:14px;color:var(--muted)}.session-grid{display:grid;
grid-template-columns:1.35fr 1fr;gap:28px;padding:18px 0}.metric{margin:10px 0}
.metric-label{display:flex;justify-content:space-between}.bar-track{height:8px;
background:#e8edf4;border-radius:99px;overflow:hidden}.bar{height:100%;background:var(--blue)}
.bar.good{background:var(--green)}.bar.warn{background:#d97706}.bar.bad{background:var(--red)}
.metric-reason{color:var(--muted);font-size:12px}.trend{display:flex;
justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--line)}
.delta{width:100%;border-collapse:collapse;margin:8px 0}.delta td{padding:5px;
border-bottom:1px solid var(--line)}.delta td:last-child{text-align:right;font-variant-numeric:tabular-nums}
.positive{color:var(--green)}.negative{color:var(--red)}details{border-top:1px solid var(--line);
padding:12px 0}summary{cursor:pointer;font-weight:700}.timeline{display:grid;
grid-template-columns:repeat(2,1fr);gap:10px;margin-top:12px}.turn-card{padding:12px;
border-left:4px solid var(--blue);background:#f8fafc;border-radius:8px}.turn-card p{margin:3px 0}
.turn-index{font-weight:800;color:var(--blue)}.dialogue{padding-top:10px}.message{max-width:82%;
padding:10px 13px;border-radius:12px;margin:8px 0}.message span{font-size:11px;
color:var(--muted)}.message p{margin:2px 0}.message.client{background:#f1f5f9}
.message.counselor{background:#e8efff;margin-left:auto}
@media(max-width:800px){.summary-grid{grid-template-columns:repeat(2,1fr)}
.session-grid,.timeline{grid-template-columns:1fr}.process{display:grid;gap:8px}
.arrow{display:none}.hero{display:block}.disclaimer{margin-top:12px;display:inline-block}}
"""
