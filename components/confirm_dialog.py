# components/confirm_dialog.py
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc


def create_confirm_dialog():
    return dbc.Modal(
        id="modal-confirm",
        is_open=False,
        backdrop="static",
        keyboard=False,
        centered=True,
        children=[
            dbc.ModalHeader(
                html.Div([
                    html.I(className="bi bi-exclamation-triangle-fill me-2"),
                    html.Span(id="confirm-title", children="危险操作确认"),
                ], className="confirm-dialog-title"),
                close_button=False,
            ),
            dbc.ModalBody([
                html.P(id="confirm-desc", className="mb-3"),
                html.Div("此操作不可撤销。请在下方输入 DELETE 以确认：",
                         className="confirm-input-label"),
                dcc.Input(id="confirm-input-text", type="text",
                          placeholder="输入 DELETE", className="confirm-input",
                          debounce=False, autoComplete="off", value=""),
                html.Div(id="confirm-input-hint", className="mt-2"),
            ]),
            dbc.ModalFooter([
                html.Button("取消", id="btn-confirm-cancel",
                            className="btn-outline-custom", n_clicks=0),
                html.Button([html.I(className="bi bi-trash3 me-1"), "确认执行"],
                            id="btn-confirm-ok", className="btn-danger-custom",
                            n_clicks=0, disabled=True),
            ]),
        ],
    )


@callback(
    Output("modal-confirm", "is_open"),
    Output("confirm-title", "children"),
    Output("confirm-desc", "children"),
    Output("confirm-input-text", "value"),
    Input("store-confirm-payload", "data"),
    Input("btn-confirm-cancel", "n_clicks"),
    Input("btn-confirm-ok", "n_clicks"),
    State("modal-confirm", "is_open"),
    prevent_initial_call=True,
)
def cb_modal_open(payload, cancel_clicks, ok_clicks, is_open):
    from dash import ctx
    trigger = ctx.triggered_id
    if trigger == "store-confirm-payload" and payload:
        return (True,
                payload.get("title", "危险操作确认"),
                payload.get("desc", "此操作将永久删除数据。"),
                "")
    if trigger in ("btn-confirm-cancel", "btn-confirm-ok"):
        return False, no_update, no_update, ""
    return no_update, no_update, no_update, no_update


@callback(
    Output("btn-confirm-ok", "disabled"),
    Output("confirm-input-hint", "children"),
    Input("confirm-input-text", "value"),
)
def cb_validate_input(val):
    if val is None:
        return True, ""
    if val.strip().upper() == "DELETE":
        return False, ""
    return True, "" if not val else f"请输入 DELETE（已输入：{val}）"


@callback(
    Output("store-confirm-payload", "data", allow_duplicate=True),
    Input("btn-confirm-ok", "n_clicks"),
    prevent_initial_call=True,
)
def cb_confirm_ok(n):
    return None