# auth.py
"""
基于 Neo4j 的用户认证模块。
首次运行时，如果数据库中不存在 User 节点，会自动初始化两个测试账号。

v0.7 扩展：
    - 引入 UserRole 枚举
    - 预置 PERMISSION_MATRIX 权限矩阵
    - 提供 check_permission / require_role 空壳，为 v1.0 鉴权做插槽
"""
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash
from config import get_driver
from enum import Enum


# ============================================================
# ★ v0.7 新增：角色枚举与权限矩阵
# ============================================================
class UserRole(str, Enum):
    RESEARCHER = "researcher"       # 实验数据录入/查询
    CLINICIAN = "clinician"         # 只读+证据包查看
    DATA_MANAGER = "data_manager"   # 数据导入/审计
    ADMIN = "admin"                 # 全部权限


# 权限矩阵 (v0.7 仅定义, v1.0 接入真实执行)
PERMISSION_MATRIX = {
    ("EnzymeGene", "create"): [UserRole.RESEARCHER, UserRole.ADMIN],
    ("EnzymeGene", "delete"): [UserRole.ADMIN],
    ("Phage", "create"): [UserRole.RESEARCHER, UserRole.ADMIN],
    ("Phage", "delete"): [UserRole.ADMIN],
    ("ExperimentBatch", "create"): [UserRole.RESEARCHER, UserRole.DATA_MANAGER, UserRole.ADMIN],
    ("BiofilmAssay", "create"): [UserRole.RESEARCHER, UserRole.ADMIN],
    ("AuditEvent", "read"): [UserRole.DATA_MANAGER, UserRole.ADMIN],
    ("SchemaVersion", "write"): [UserRole.ADMIN],
    ("Phage", "read"): list(UserRole),
    ("LysisAssay", "read"): list(UserRole),
    ("BiofilmAssay", "read"): list(UserRole),
}


def get_current_user() -> dict:
    """
    v0.7 沙箱：返回固定用户。
    v1.0：从 session/JWT 中解析真实用户。
    """
    return {
        "id": "sandbox_user",
        "name": "沙箱用户",
        "role": UserRole.ADMIN,
        "email": None
    }


def check_permission(resource: str, action: str, role: UserRole = None) -> bool:
    """
    v0.7: 始终返回 True.
    v1.0: 查询 PERMISSION_MATRIX 执行真实检查.
    """
    # TODO v1.0: 替换为真实权限检查
    # if role is None:
    #     role = UserRole(get_current_user().get("role", "admin"))
    # allowed_roles = PERMISSION_MATRIX.get((resource, action), [])
    # return role in allowed_roles
    return True


def require_role(role: UserRole):
    """
    装饰器预置 (v0.7 为空操作)。
    v1.0: 在 Dash callback 上使用, 未授权时返回 403 页面.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # TODO v1.0: 检查当前用户角色
            # current = UserRole(get_current_user().get("role", "admin"))
            # if current != role and current != UserRole.ADMIN:
            #     raise PermissionError(f"需要角色 {role} 权限")
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================
# 原有认证逻辑
# ============================================================
def _ensure_default_users():
    with get_driver().session() as s:
        cnt = s.run("MATCH (u:User) RETURN count(u) AS c").single()["c"]
        if cnt == 0:
            s.run("""
                CREATE (u1:User {
                    username: 'admin', 
                    password_hash: $p1, 
                    name: '管理员', 
                    role: 'admin'
                })
                CREATE (u2:User {
                    username: 'analyst', 
                    password_hash: $p2, 
                    name: '分析师', 
                    role: 'analyst'
                })
            """, p1=generate_password_hash("admin123"), p2=generate_password_hash("analyst123"))
            print("✅ 已初始化默认用户: admin/admin123, analyst/analyst123")


def verify_user(username: str, password: str):
    """从 Neo4j 校验用户名密码"""
    if not username or not password:
        return None

    _ensure_default_users()  # 确保表存在

    with get_driver().session() as s:
        row = s.run("""
            MATCH (u:User) WHERE toLower(u.username) = toLower($uname)
            RETURN u.username AS username, u.password_hash AS pwd, u.name AS name, u.role AS role
        """, uname=username.strip()).single()

        if not row:
            return None
        if not check_password_hash(row["pwd"], password):
            return None

        return {
            "username": row["username"],
            "name": row["name"],
            "role": row["role"]
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