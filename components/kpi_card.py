# components/kpi_card.py
"""KPI 卡片组件 —— 支持趋势方向、图标、颜色主题。"""
from dash import html

_THEMES = {
    "blue":   ("var(--c-primary)",   "var(--c-primary-light)"),
    "green":  ("var(--c-secondary)", "var(--c-secondary-light)"),
    "amber":  ("var(--c-warning)",   "var(--c-warning-light)"),
    "red":    ("var(--c-danger)",    "var(--c-danger-light)"),
}


def kpi_card(label, value, icon, change_text="", change_dir="neutral",
             theme="blue", card_id=None):
    """
    参数：
        label       卡片标题
        value       主数值
        icon        Bootstrap Icons class，如 "bi bi-virus"
        change_text 变化描述文字（可选）
        change_dir  "up" / "down" / "neutral"
        theme       blue / green / amber / red
        card_id     可选；如果传了，会给容器加 id，并给数字部分加 "{card_id}-value"
    """
    color, bg = _THEMES.get(theme, _THEMES["blue"])

    # 容器属性：只有 card_id 存在时才加 id
    wrap_kwargs = {}
    if card_id:
        wrap_kwargs["id"] = card_id

    # 数字部分属性：同样只在有 card_id 时加 id
    value_kwargs = {"className": "kpi-value"}
    if card_id:
        value_kwargs["id"] = f"{card_id}-value"

    change_cls = {"up": "kpi-change up", "down": "kpi-change down"}.get(
        change_dir, "kpi-change")

    children = [
        html.Div(className="kpi-icon", children=html.I(className=icon)),
        html.Div(label, className="kpi-label"),
        html.Div(str(value), **value_kwargs),
    ]
    if change_text:
        children.append(html.Div(change_text, className=change_cls))

    return html.Div(
        className="kpi-card",
        style={"--kpi-color": color, "--kpi-bg": bg},
        children=children,
        **wrap_kwargs,
    )