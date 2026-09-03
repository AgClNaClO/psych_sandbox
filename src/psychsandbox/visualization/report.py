from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from ..domain import (
    HolisticEvaluationReport,
    RolloutSelection,
    RunResult,
    ScaleScore,
    SessionRecord,
)
from .charts import state_line_chart


PROCESS_STEPS = (
    ("会谈准备", "读取允许记忆、阶段与目标"),
    ("咨询师 ReAct", "规划 → 查询技能 → 观察 → 选策略 → 回复"),
    ("双重安全门", "输入风险与输出边界检查"),
    ("来访者反应", "披露门控 → 反应 → 行为/抗拒 → 表达"),
    ("状态更新", "信任、痛苦、希望与抗拒"),
    ("会后闭环", "咨询师自评 → 未达目标再规划 → 规则督导与纵向趋势"),
)

ICON_BRAIN = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v1H6a3 3 0 0 0-3 3v2a3 3 0 0 0 1 2.17V15a3 3 0 0 0 3 3h1v1a3 3 0 0 0 6 0v-1h1'
    'a3 3 0 0 0 3-3v-1.83A3 3 0 0 0 19 11V9a3 3 0 0 0-3-3h-1V5a3 3 0 0 0-3-3z"/>'
    '<circle cx="9" cy="10" r="1.5"/><circle cx="15" cy="10" r="1.5"/>'
    '<path d="M9 14c.83.67 1.92 1 3 1s2.17-.33 3-1"/></svg>'
)
ICON_CHAT = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
)
ICON_USER = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
    '<circle cx="12" cy="7" r="4"/></svg>'
)
ICON_STETHOSCOPE = (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2"><path d="M4 8a6 6 0 0 1 12 0v6a3 3 0 0 0 6 0v-2"/>'
    '<path d="M22 12v2a4 4 0 0 1-8 0v-6"/><circle cx="6" cy="14" r="2"/>'
    '<line x1="6" y1="16" x2="6" y2="20"/><line x1="4" y1="20" x2="8" y2="20"/></svg>'
)


def generate_run_report(result: RunResult, output: Path) -> Path:
    """Create a self-contained HTML report for offline review and replay.

    Features:
    - Thinking process panel (counselor decision) separate from dialogue
    - Beautiful chat bubbles for conversation
    - Session-level thinking summary
    """

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    counselor_overall = result.holistic_report.counselor_overall if result.holistic_report else 0.0
    client_overall = result.holistic_report.client_overall if result.holistic_report else 0.0
    overall = (counselor_overall + client_overall) / 2
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
    holistic_html = _holistic_section(result.holistic_report)
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
    {_summary_card("会谈数", str(len(result.sessions)), "sessions", "📋")}
    {_summary_card("整体督导分", f"{overall:.2f}", "0–10", "📊")}
    {_summary_card("高风险事件", str(safety_events), "需人工复核", "⚠️")}
    {_summary_card("暴露泄漏", str(leaks), "越低越好", "🔒")}
  </section>
  {holistic_html}
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
    <h2>会谈明细</h2>
    {''.join(_session_section(item) for item in result.sessions)}
  </section>
</main>
</body>
</html>"""
    output.write_text(html, encoding="utf-8")
    return output


def _summary_card(label: str, value: str, note: str, icon: str) -> str:
    return (
        '<div class="summary-card">'
        f'<span class="card-icon">{icon}</span>'
        f"<span>{escape(label)}</span><strong>{escape(value)}</strong>"
        f"<small>{escape(note)}</small></div>"
    )


def _process_flow() -> str:
    parts = []
    for index, (title, description) in enumerate(PROCESS_STEPS, start=1):
        parts.append(
            '<div class="process-step">'
            f"<strong>{ICON_BRAIN}{index}. {escape(title)}</strong>"
            f"<span>{escape(description)}</span></div>"
        )
        if index < len(PROCESS_STEPS):
            parts.append('<div class="arrow">→</div>')
    return "".join(parts)


def _holistic_section(report: HolisticEvaluationReport | None) -> str:
    if not report:
        return ""
    return f"""
  <section class="panel">
    <h2>整体督导评估（PsychEval 多会话后评估）</h2>
    <p class="muted">Counselor-Level（临床胜任力）与 Client-Level（仿真保真度）评分，均为 0–10。</p>
    <div class="session-grid">
      <div>
        <h4>Counselor-Level（Counselor={report.counselor_overall:.2f}）</h4>
        {_scale_list(report.counselor_shared)}
        {_scale_list(report.counselor_specific)}
      </div>
      <div>
        <h4>Client-Level（Client={report.client_overall:.2f}）</h4>
        {_scale_list(report.client_shared)}
        {_scale_list(report.client_specific)}
      </div>
    </div>
  </section>"""


def _scale_list(scores: list[ScaleScore]) -> str:
    if not scores:
        return ""
    rows = "".join(
        f"<li><span>{escape(item.name)}</span><strong>{item.score:.2f}</strong>"
        f"<small>{'共享' if item.category == 'therapy_shared' else '流派专属'}</small></li>"
        for item in scores
    )
    return f'<ul class="scale-list">{rows}</ul>'


def _join_objectives(objectives: list[str]) -> str:
    """Join session objectives onto separate lines without doubled punctuation."""
    cleaned = [escape(obj).rstrip("。；;，,、 ") for obj in objectives]
    return "；".join(cleaned).replace("；", "<br>")


def _session_summary_text(session: SessionRecord) -> str:
    parts = []
    if session.clinical_summary and session.clinical_summary.session_summary_abstract:
        parts.append(
            "<details><summary>临床摘要（E.9）</summary>"
            f"<p>{escape(session.clinical_summary.session_summary_abstract)}</p></details>"
        )
    return "".join(parts)


def _session_section(session: SessionRecord) -> str:
    longitudinal = session.longitudinal_report
    trend = longitudinal.trend if longitudinal else "n/a"
    action = longitudinal.stage_action if longitudinal else "n/a"
    review = session.counselor_review
    review_status = (
        "暂无"
        if review is None
        else "目标已达到"
        if review.goals_achieved
        else "目标未完全达到"
    )
    review_items = []
    if review:
        review_items.extend(review.evidence)
        review_items.extend(review.improvement_areas)
        if review.revised_strategy:
            review_items.append(f"调整策略：{review.revised_strategy}")
    review_html = (
        "".join(f"<li>{escape(item)}</li>" for item in review_items)
        or "<li>暂无咨询师会后自评</li>"
    )
    summary_html = _session_summary_text(session)
    # Build thinking summary from turn records
    thinking_cards = _session_thinking_summary(session)

    return f"""
<article class="session">
  <div class="session-head">
    <div>
      <span class="badge">Session {session.session_index}</span>
      <h3>{escape(session.plan.stage.value)}</h3>
      <p>{_join_objectives(session.plan.objectives[:3])}</p>
    </div>
  </div>
  {summary_html}
  <div class="session-grid">
    <div>
      <h4>纵向判断</h4>
      <div class="trend"><span>趋势</span><strong>{escape(trend)}</strong></div>
      <div class="trend"><span>阶段动作</span><strong>{escape(action)}</strong></div>
      {_delta_table(session)}
    </div>
    <div>
      <h4>咨询师会后自评：{escape(review_status)}</h4>
      <ul>{review_html}</ul>
    </div>
  </div>
  {_rollout_selection(session.rollout_selection)}
  <details>
    <summary>{ICON_BRAIN} 咨询师可审计规划与决策（{len(session.turn_records)} turns）</summary>
    <p class="muted">以下展示模型或规则明确输出的决策摘要、执行步骤和交互信号，不是内部逐 token 思维链。</p>
    <div class="thinking-grid">{thinking_cards}</div>
  </details>
  <details open>
    <summary>{ICON_CHAT} 对话记录</summary>
    <div class="dialogue">{_dialogue(session)}</div>
  </details>
  <details>
    <summary>查看逐轮技术细节（{len(session.turn_records)} turns）</summary>
    {_turn_timeline(session)}
  </details>
</article>"""


def _rollout_selection(selection: RolloutSelection | None) -> str:
    if selection is None:
        return ""
    rows, details = [], []
    for item in selection.candidates:
        reward = item.reward
        score = f"{reward.total:.3f}" if reward else "—"
        if reward:
            client_signals = [s for s in reward.signals if s.side == "client"]
            if client_signals:
                client_z = sum(s.standardized for s in client_signals) / len(client_signals)
                delta = f"{client_z:+.3f}"
            else:
                delta = "无基线"
        else:
            delta = "—"
        rows.append(
            f"<tr><td>{item.index}</td><td>{escape(item.status)}</td><td>{score}</td>"
            f"<td>{delta}</td><td>{escape(item.reason)}</td></tr>"
        )
        assessment = item.assessment
        evidence = []
        if assessment:
            for name in type(assessment).model_fields:
                dimension = getattr(assessment, name)
                if not hasattr(dimension, "score"):
                    continue
                quotes = "；".join(f"消息 {e.message_index}: {e.quote}" for e in dimension.evidence)
                evidence.append(
                    f"<li><b>{escape(name)}: {dimension.score:.2f}</b> "
                    f"{escape(dimension.reason)}<br>{escape(quotes)}</li>"
                )
        # Only relative artifact paths generated by the runner become links.
        path = item.artifact_path
        safe_path = path.startswith("rollouts/") and ".." not in path.split("/") and ":" not in path and "\\" not in path
        link = f'<a href="{escape(path, quote=True)}">完整候选记录 JSON</a>' if safe_path else "候选路径不可链接"
        details.append(
            f"<details><summary>候选 {item.index}：评分依据与记录</summary>"
            f"<p>{link}</p><ul>{''.join(evidence)}</ul></details>"
        )
    return (
        '<details open><summary>整场会谈候选与 RFT 选优</summary>'
        f'<p>批次 {escape(selection.batch_id)}；胜出候选：{selection.winner_index or "无"}。'
        f'{escape(selection.reason)}</p>'
        '<p class="muted">评分是研究用候选比较信号，不是临床疗效。只提交胜出会谈；未选中分支不进入记忆。'
        '首次无来访者变化基线时仅计咨询师分。</p>'
        '<table><thead><tr><th>候选</th><th>状态</th><th>总分</th><th>来访者变化</th><th>原因</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>{"".join(details)}</details>'
    )


def _session_thinking_summary(session: SessionRecord) -> str:
    """Render explicit decision summaries; never provider-internal reasoning."""
    cards = []
    for record in session.turn_records:
        decision = record.get("decision", {})
        planning = record.get("planning", {})
        observation = record.get("observation", {})
        turn = record.get("turn_index", "?")
        assessment = decision.get("assessment", "")
        strategy = decision.get("strategy", "")
        state_obs = decision.get("state_observation", "")
        skills = decision.get("selected_atomic_skill_ids", [])
        risk = decision.get("risk_level", "low")
        progress = decision.get("goal_progress", 0)
        reasoning = planning.get("reasoning_summary", "")
        current_goal = planning.get("current_goal", "")
        action_input = planning.get("action_input", "")
        action_name = planning.get("action", "—")
        plan_steps = planning.get("plan_steps", [])
        observation_status = observation.get("status", "—")
        observed_count = len(observation.get("atomic_skills", []))

        risk_class = ""
        risk_label = ""
        if risk == "high":
            risk_class = "risk-high"
            risk_label = "🔴 高风险"
        elif risk == "medium":
            risk_class = "risk-medium"
            risk_label = "🟡 中风险"
        elif risk == "imminent":
            risk_class = "risk-imminent"
            risk_label = "🚨 紧急"
        else:
            risk_class = "risk-low"
            risk_label = "🟢 低风险"

        cards.append(
            '<div class="thinking-card">'
            f'<div class="thinking-header">'
            f'<span class="thinking-badge">Turn {escape(str(turn))}</span>'
            f'<span class="risk-tag {risk_class}">{risk_label}</span>'
            f'<span class="progress-tag">目标进度 {progress:.0%}</span>'
            f'</div>'
            f'<div class="thinking-body">'
            f'<div class="thinking-item">'
            f'<strong>🧭 决策摘要 / Planning</strong>'
            f'<p>{escape(reasoning)}</p>'
            f'<p><b>本轮目标：</b>{escape(current_goal)}</p>'
            f'<p>{escape(" → ".join(plan_steps))}</p>'
            f'</div>'
            f'<div class="thinking-item">'
            f'<strong>⚙️ Action / Observation</strong>'
            f'<p>{escape(str(action_name))} → {escape(str(observation_status))} '
            f'({observed_count} skills)</p>'
            f'<p>{escape(action_input)}</p>'
            f'</div>'
            f'<div class="thinking-item">'
            f'<strong>📋 评估</strong>'
            f'<p>{escape(assessment)}</p>'
            f'</div>'
            f'<div class="thinking-item">'
            f'<strong>🔍 状态观察</strong>'
            f'<p>{escape(state_obs)}</p>'
            f'</div>'
            f'<div class="thinking-item">'
            f'<strong>🎯 策略</strong>'
            f'<p>{escape(strategy)}</p>'
            f'</div>'
            + (
                f'<div class="thinking-item skills">'
                f'<strong>🛠 使用技能</strong>'
                f'<div class="skill-tags">'
                + "".join(
                    f'<span class="skill-tag">{escape(s)}</span>'
                    for s in skills
                )
                + "</div></div>"
                if skills
                else ""
            )
            + _skill_query_audit(record)
            + _client_decision_summary(record)
            + "</div></div>"
        )
    return "".join(cards) if cards else '<p class="muted">暂无决策摘要</p>'


def _client_decision_summary(record: dict[str, Any]) -> str:
    signal = record.get("client_turn_signal") or {}
    if not signal:
        return ""
    labels = (
        ("reaction", "反应"), ("intensity", "强度"),
        ("behavior", "行为"), ("resistance_pattern", "阻抗形式"),
        ("trust_change", "信任变化"),
    )
    details = "；".join(
        f"{label}：{signal[key]}" for key, label in labels if signal.get(key)
    )
    return (
        '<div class="thinking-item">'
        '<strong>来访者模拟决策摘要</strong>'
        f'<p>{escape(str(signal.get("rationale", "")))}</p>'
        f'<p>{escape(details)}</p>'
        '</div>'
    )


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
    planning = record.get("planning", {})
    observation = record.get("observation", {})
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
        f"<p><b>规划动作：</b>{escape(str(planning.get('action', '—')))}</p>"
        f"<p><b>观察结果：</b>{escape(str(observation.get('status', '—')))}，"
        f"{len(observation.get('atomic_skills', []))} 个技能</p>"
        f"<p><b>目标/策略：</b>{escape(str(decision.get('strategy', '—')))}</p>"
        f"<p><b>技能：</b>{escape(', '.join(skills) or '无')}</p>"
        f"<p><b>来访者信号：</b>{escape(str(signal.get('reaction', '—')))} / "
        f"{escape(str(signal.get('behavior', '—')))}</p>"
        f"<p><b>披露：</b>retrieved {len(disclosure.get('retrieved', []))}，"
        f"blocked {len(disclosure.get('blocked', []))}</p>"
        f"<p><b>安全：</b>{escape(str(input_safety.get('level', '—')))} → "
        f"{escape(str(output_safety.get('level', '—')))}</p>"
        f"<p><b>状态变化：</b>信任 {trust_change}，痛苦 {distress_change}</p>"
        + "</div>"
    )


def _skill_query_audit(record: dict[str, Any]) -> str:
    """Show each saved attempt's explicit plan, including rejected queries."""
    attempts = record.get("skill_queries", [])
    if not attempts:
        return ""
    parts = [f"<details><summary>技能查询记录（{len(attempts)} 次）</summary>"]
    for attempt in attempts:
        planning = attempt.get("planning") or {}
        before = attempt.get("candidate_skill_ids", [])
        returned = attempt.get("returned_skill_ids", [])
        method = "向量筛选" if attempt.get("vector_filtered") else "完整展开"
        parts.append(
            f"<p><b>第 {escape(str(attempt.get('attempt', '?')))} 次：</b>"
            f"{len(before)} → {len(returned)} 项，{method}；"
            f"{escape(str(attempt.get('assessment', '—')))}</p>"
        )
        for key, label in (
            ("reasoning_summary", "规划摘要"),
            ("current_goal", "本次目标"),
            ("action", "执行动作"),
            ("action_input", "查询意图"),
        ):
            if planning.get(key):
                parts.append(f"<p><b>{label}：</b>{escape(str(planning[key]))}</p>")
        if planning.get("plan_steps"):
            parts.append(
                "<p><b>执行计划：</b>"
                + escape(" → ".join(planning["plan_steps"]))
                + "</p>"
            )
        if attempt.get("rejection_reason"):
            parts.append(f"<p><b>拒绝原因：</b>{escape(attempt['rejection_reason'])}</p>")
        for warning in attempt.get("selection_warnings", []):
            parts.append(f"<p><b>校验：</b>{escape(warning)}</p>")
        for evidence in planning.get("selection_evidence", []):
            parts.append(
                f"<p><b>元技能依据 {escape(evidence['skill_id'])}：</b>"
                f"“{escape(evidence['evidence_quote'])}” — {escape(evidence['reason'])}</p>"
            )
        parts.append(f"<p><b>返回候选：</b>{escape('、'.join(returned) or '无')}</p>")
    for evidence in record.get("decision", {}).get("skill_evidence", []):
        parts.append(
            f"<p><b>原子技能依据 {escape(evidence['skill_id'])}：</b>"
            f"“{escape(evidence['evidence_quote'])}” — {escape(evidence['reason'])}</p>"
        )
    parts.append("</details>")
    return "".join(parts)


def _number_delta(before: dict[str, Any], after: dict[str, Any], key: str) -> str:
    try:
        return f"{float(after[key]) - float(before[key]):+.3f}"
    except (KeyError, TypeError, ValueError):
        return "—"


def _dialogue(session: SessionRecord) -> str:
    """Render conversation with styled chat bubbles, counselor vs client."""
    parts = []
    for message in session.messages:
        if message.role not in {"client", "counselor"}:
            continue
        is_client = message.role == "client"
        role_label = "来访者" if is_client else "咨询师"
        avatar = ICON_USER if is_client else ICON_STETHOSCOPE
        css_class = "msg-client" if is_client else "msg-counselor"
        parts.append(
            f'<div class="{css_class}">'
            f'<div class="msg-avatar">{avatar}</div>'
            f'<div class="msg-bubble">'
            f'<div class="msg-role">{escape(role_label)}</div>'
            f'<div class="msg-text">{escape(message.content)}</div>'
            f"</div></div>"
        )
    return "".join(parts)


def _styles() -> str:
    return """
:root{color-scheme:light;--ink:#172033;--muted:#64748b;--line:#dce3ed;
--panel:#fff;--bg:#f4f7fb;--blue:#3157d5;--green:#1b8f5a;--red:#c94343;
--amber:#d97706;--purple:#7c3aed;--pink:#db2777;--cyan:#0891b2;
--surface2:#f1f5f9;--surface3:#e8efff;--shadow:0 7px 24px #1720330d;--radius:16px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
main{max-width:1280px;margin:auto;padding:32px 22px 72px}

/* ---- Hero ---- */
.hero{display:flex;justify-content:space-between;align-items:flex-end;padding:30px 36px;
border-radius:20px;background:linear-gradient(135deg,#0f172a,#1e3a8a,#3157d5);
color:#fff;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-50%;right:-20%;width:400px;height:400px;
background:radial-gradient(circle,rgba(255,255,255,.08) 0%,transparent 70%);border-radius:50%}
.hero::after{content:'';position:absolute;bottom:-30%;left:-10%;width:300px;height:300px;
background:radial-gradient(circle,rgba(255,255,255,.06) 0%,transparent 70%);border-radius:50%}
.hero h1{margin:4px 0;font-size:32px;position:relative;z-index:1}
.hero p{margin:0;position:relative;z-index:1}
.eyebrow{letter-spacing:.12em;opacity:.8;font-size:12px;text-transform:uppercase}
.disclaimer{padding:8px 16px;border:1px solid #ffffff55;border-radius:99px;
backdrop-filter:blur(4px);position:relative;z-index:1}

/* ---- Summary ---- */
.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:20px 0}
.summary-card,.panel,.session{background:var(--panel);border:1px solid var(--line);
border-radius:var(--radius);box-shadow:var(--shadow);transition:transform .2s,box-shadow .2s}
.summary-card:hover{transform:translateY(-2px);box-shadow:0 12px 40px #17203315}
.summary-card{padding:20px;position:relative;overflow:hidden}
.summary-card::after{content:'';position:absolute;top:0;left:0;width:4px;height:100%;
background:var(--blue);border-radius:4px 0 0 4px}
.summary-card .card-icon{font-size:28px;display:block;margin-bottom:4px}
.summary-card span,.summary-card small{display:block;color:var(--muted)}
.summary-card strong{display:block;font-size:30px;margin:4px 0;font-weight:800}

/* ---- Panel ---- */
.panel{padding:24px;margin:20px 0}
h2{margin:32px 0 14px}h3,h4{margin:6px 0}

/* ---- Process Flow ---- */
.process{display:flex;align-items:stretch;overflow:auto;padding:4px;gap:0}
.process-step{min-width:155px;flex:1;padding:16px;background:linear-gradient(135deg,#eef2ff,#e0e7ff);
border-radius:12px;border:1px solid #c7d2fe;transition:transform .2s}
.process-step:hover{transform:translateY(-2px)}
.process-step strong{display:flex;align-items:center;gap:6px;font-size:13px;color:#3730a3}
.process-step strong svg{flex-shrink:0;color:#6366f1}
.process-step span{display:block;color:var(--muted);font-size:12px;margin-top:4px}
.arrow{align-self:center;padding:0 10px;color:var(--blue);font-size:24px;font-weight:300}
.chart svg{width:100%;height:auto}.axis,.legend{font-size:11px;fill:#64748b}
.muted{color:var(--muted)}

/* ---- Session ---- */
.session{padding:24px;margin:20px 0}
.session-head{display:flex;justify-content:space-between;gap:16px;
border-bottom:1px solid var(--line);padding-bottom:16px}
.badge{display:inline-block;background:linear-gradient(135deg,#e0e7ff,#c7d2fe);
color:#3730a3;border-radius:99px;padding:4px 12px;font-weight:700;font-size:13px}
.score{font-size:38px;font-weight:800;color:var(--blue)}
.score small{font-size:14px;color:var(--muted)}
.session-grid{display:grid;grid-template-columns:1.35fr 1fr;gap:28px;padding:18px 0}

/* ---- Metrics ---- */
.metric{margin:12px 0}
.metric-label{display:flex;justify-content:space-between;margin-bottom:4px}
.metric-label strong{font-variant-numeric:tabular-nums}
.bar-track{height:10px;background:#e8edf4;border-radius:99px;overflow:hidden}
.bar{height:100%;background:var(--blue);border-radius:99px;transition:width .6s ease}
.bar.good{background:linear-gradient(90deg,#16a34a,#22c55e)}
.bar.warn{background:linear-gradient(90deg,#d97706,#f59e0b)}
.bar.bad{background:linear-gradient(90deg,#c94343,#ef4444)}
.metric-reason{color:var(--muted);font-size:12px;margin-top:4px}

/* ---- Trends ---- */
.trend{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--line)}
.delta{width:100%;border-collapse:collapse;margin:8px 0}
.delta td{padding:6px;border-bottom:1px solid var(--line)}
  .delta td:last-child{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
  .scale-list{list-style:none;padding:0;margin:0}
  .scale-list li{display:flex;justify-content:space-between;align-items:center;gap:8px;
  padding:8px 0;border-bottom:1px solid var(--line)}
  .scale-list li span{font-weight:600}
  .scale-list li strong{color:var(--blue);font-variant-numeric:tabular-nums}
  .scale-list li small{color:var(--muted);font-size:11px}
.positive{color:var(--green)}.negative{color:var(--red)}

/* ---- Details (collapsible) ---- */
details{border-top:1px solid var(--line);padding:14px 0}
details summary{cursor:pointer;font-weight:700;font-size:15px;display:flex;align-items:center;gap:8px;
padding:4px 0;user-select:none;transition:color .2s}
details summary:hover{color:var(--blue)}
details summary svg{flex-shrink:0}

/* ---- Thinking Process Grid ---- */
.thinking-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px;
margin-top:14px}
.thinking-card{background:linear-gradient(135deg,#faf5ff,#ede9fe);border:1px solid #ddd6fe;
border-radius:14px;overflow:hidden;transition:transform .2s,box-shadow .2s}
.thinking-card:hover{transform:translateY(-2px);box-shadow:0 8px 30px #7c3aed15}
.thinking-header{display:flex;align-items:center;gap:8px;padding:10px 14px;
background:linear-gradient(90deg,#ede9fe,#ddd6fe);border-bottom:1px solid #c4b5fd}
.thinking-badge{font-weight:800;font-size:13px;color:#5b21b6}
.risk-tag{font-size:11px;padding:2px 8px;border-radius:99px;font-weight:600}
.risk-low{background:#dcfce7;color:#166534}
.risk-medium{background:#fef9c3;color:#854d0e}
.risk-high{background:#fee2e2;color:#991b1b}
.risk-imminent{background:#fecaca;color:#7f1d1d;animation:pulse 1.5s infinite}
.progress-tag{font-size:11px;padding:2px 8px;background:#e0f2fe;color:#0c4a6e;
border-radius:99px;font-weight:600;margin-left:auto}
.thinking-body{padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.thinking-item strong{display:block;font-size:12px;color:var(--muted);margin-bottom:2px}
.thinking-item p{margin:0;font-size:13px;line-height:1.5}
.thinking-item.skills .skill-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}
.skill-tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;
background:#dbeafe;color:#1e40af;font-weight:600}

/* ---- Dialogue ---- */
.dialogue{padding:16px 0;display:flex;flex-direction:column;gap:16px}
.msg-client,.msg-counselor{display:flex;gap:10px;align-items:flex-start;max-width:88%}
.msg-counselor{align-self:flex-end;flex-direction:row-reverse}
.msg-avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;
justify-content:center;flex-shrink:0}
.msg-client .msg-avatar{background:linear-gradient(135deg,#e0e7ff,#c7d2fe);color:#3730a3}
.msg-counselor .msg-avatar{background:linear-gradient(135deg,#dcfce7,#bbf7d0);color:#166534}
.msg-bubble{padding:12px 16px;border-radius:18px;position:relative}
.msg-client .msg-bubble{background:#f1f5f9;border-bottom-left-radius:6px}
.msg-counselor .msg-bubble{background:#e8efff;border-bottom-right-radius:6px;text-align:right}
.msg-role{font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:600}
.msg-text{font-size:14px;line-height:1.6;white-space:pre-wrap;word-break:break-word}

/* ---- Turn Timeline ---- */
.timeline{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:12px}
.turn-card{padding:12px;border-left:4px solid var(--blue);background:#f8fafc;border-radius:8px}
.turn-card p{margin:3px 0;font-size:13px}
.turn-index{font-weight:800;color:var(--blue)}

/* ---- Animations ---- */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.6}}

/* ---- Responsive ---- */
@media(max-width:900px){
  .summary-grid{grid-template-columns:repeat(2,1fr)}
  .session-grid,.timeline,.thinking-grid{grid-template-columns:1fr}
  .process{display:grid;gap:8px}.arrow{display:none}
  .hero{display:block}.disclaimer{margin-top:12px;display:inline-block}
  .msg-client,.msg-counselor{max-width:96%}
}
@media(max-width:600px){
  .summary-grid{grid-template-columns:1fr}
  main{padding:16px 10px 48px}
  .hero{padding:20px 22px}
  .hero h1{font-size:24px}
}
"""
