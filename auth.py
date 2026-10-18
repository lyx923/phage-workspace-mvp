# auth.py
"""
简单的用户认证模块（基于 Flask session）。
生产环境请替换为 Neo4j User 节点 / SSO / OAuth。
"""
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

# ── 演示用户库（首次导入生成密码哈希） ──────────────────
_USERS = {
    "admin": {
        "password_hash": generate_password_hash("admin123"),
        "name": "管理员",
        "role": "admin",
    },
    "analyst": {
        "password_hash": generate_password_hash("analyst123"),
        "name": "分析师",
        "role": "analyst",
    },
}


def verify_user(username: str, password: str):
    """校验用户名密码；成功返回 user dict，失败返回 None。"""
    if not username or not password:
        return None
    user = _USERS.get(username.strip().lower())
    if not user:
        return None
    if not check_password_hash(user["password_hash"], password):
        return None
    return {
        "username": username.strip().lower(),
        "name": user["name"],
        "role": user["role"],
    }


def current_user():
    return session.get("user")


def login_user(user: dict):
    session["user"] = user
    session.permanent = True


def logout_user():
    session.pop("user", None)


def is_authenticated() -> bool:
    return bool(session.get("user"))