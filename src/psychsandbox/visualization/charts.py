from __future__ import annotations

from html import escape

from ..domain import SessionRecord


STATE_SERIES = {
    "trust": ("信任", "#2563eb"),
    "distress": ("痛苦", "#dc2626"),
    "hope": ("希望", "#16a34a"),
    "resistance": ("抗拒", "#9333ea"),
}


def state_line_chart(sessions: list[SessionRecord]) -> str:
    """Render a dependency-free SVG for session boundary states."""

    if not sessions:
        return '<p class="muted">暂无状态数据</p>'
    width, height = 760, 280
    left, right, top, bottom = 48, 20, 24, 48
    plot_width = width - left - right
    plot_height = height - top - bottom
    states = [sessions[0].initial_state] + [item.final_state for item in sessions]
    labels = ["开始"] + [f"S{item.session_index}" for item in sessions]
    step = plot_width / max(1, len(states) - 1)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="来访者仿真状态趋势图">'
    ]
    for value in (0, 0.25, 0.5, 0.75, 1):
        y = top + (1 - value) * plot_height
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="#e5e7eb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" '
            f'class="axis">{value:.2g}</text>'
        )
    for index, label in enumerate(labels):
        x = left + index * step
        parts.append(
            f'<text x="{x:.1f}" y="{height-18}" text-anchor="middle" '
            f'class="axis">{escape(label)}</text>'
        )
    for field, (label, color) in STATE_SERIES.items():
        points = " ".join(
            f"{left + index * step:.1f},"
            f"{top + (1 - getattr(state, field)) * plot_height:.1f}"
            for index, state in enumerate(states)
        )
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for index, state in enumerate(states):
            x = left + index * step
            y = top + (1 - getattr(state, field)) * plot_height
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}">'
                f"<title>{escape(label)} {getattr(state, field):.3f}</title></circle>"
            )
    legend_x = left
    for label, color in STATE_SERIES.values():
        parts.append(
            f'<rect x="{legend_x}" y="2" width="12" height="12" rx="2" fill="{color}"/>'
            f'<text x="{legend_x+18}" y="13" class="legend">{escape(label)}</text>'
        )
        legend_x += 90
    parts.append("</svg>")
    return "".join(parts)
