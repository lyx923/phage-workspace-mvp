# pages/login.py
import time
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, clientside_callback
from flask import session

from auth import verify_user, login_user

dash.register_page(__name__, path="/login", name="登录")

layout = html.Div(
    className="login-page",
    children=[
        dcc.Store(id="store-login-status", data=None),
        html.Div(className="login-bg-shapes", children=[
            html.Div(className="login-shape login-shape-1"),
            html.Div(className="login-shape login-shape-2"),
            html.Div(className="login-shape login-shape-3"),
        ]),
        html.Div(className="login-card", children=[
            html.Div(className="login-header", children=[
                html.Div("AI", className="login-logo"),
                html.H2("AI 精准抗感染平台", className="login-title"),
            ]),
            html.Div(className="login-body", children=[
                html.Div(className="login-field", children=[
                    html.Label("用户名", className="login-label"),
                    dcc.Input(
                        id="login-username", type="text", value="admin",
                        placeholder="请输入用户名",
                        className="login-input",
                        autoComplete="username",
                    ),
                ]),
                html.Div(className="login-field", children=[
                    html.Label("密码", className="login-label"),
                    dcc.Input(
                        id="login-password", type="password", value="admin",
                        placeholder="请输入密码",
                        className="login-input",
                        autoComplete="current-password",
                    ),
                ]),
                html.Button(
                    [html.I(className="bi bi-box-arrow-in-right me-2"), "登 录"],
                    id="btn-login", className="login-submit", n_clicks=0,
                ),
                html.Div(id="login-feedback", className="login-feedback"),
            ]),
        ]),
    ],
)

@callback(
    Output("store-login-status", "data"),
    Output("login-feedback", "children"),
    Input("btn-login", "n_clicks"),
    State("login-username", "value"),
    State("login-password", "value"),
    prevent_initial_call=True,
)
def cb_login(n_clicks, username, password):
    if not n_clicks:
        return no_update, no_update
    if not username or not password:
        return no_update, html.Div("请输入用户名和密码", className="login-error")
    
    user = verify_user(username, password)
    if not user:
        return no_update, html.Div("用户名或密码错误", className="login-error")
    
    login_user(user)
    # 返回 success 信号，交给前端 JS 进行跳转
    return "success", html.Div(
        [html.I(className="bi bi-check-circle-fill me-2"), "登录成功，正在进入系统…"],
        className="login-success",
    )

# ★ 使用前端回调硬核跳转
clientside_callback(
    """
    function(status) {
        if (status === "success") {
            window.location.href = "/";
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("store-login-status", "id"),
    Input("store-login-status", "data"),
    prevent_initial_call=True,
)

@callback(
    Output("btn-login", "n_clicks"),
    Input("login-password", "n_submit"),
    State("btn-login", "n_clicks"),
    prevent_initial_call=True,
)
def cb_enter_submit(n_submit, current_clicks):
    if n_submit:
        return (current_clicks or 0) + 1
    return no_update