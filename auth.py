# auth.py
"""用户认证与基础权限检查。

变更说明（v0.8 批次）：
- check_permission 改为查库；
- 保留 admin 全权限与 agent 服务身份的特殊判断；
- 引入 DEFAULT_ROLE_GRANTS 兜底表，避免角色未配置权限时全部放行；
- 增加 clinician / data_manager 角色支持。
"""
from enum import Enum

from flask import has_request_context, session
from werkzeug.security import check_password_hash, generate_password_hash

from config import get_driver


class UserRole(str, Enum):
    RESEARCHER = "researcher"
    CLINICIAN = "clinician"
    ANALYST = "analyst"
    DATA_MANAGER = "data_manager"
    ADMIN = "admin"
    AGENT = "agent"


# 兜底权限表：仅在角色尚未通过「角色管理」页面配置权限时生效。
# 正式环境应通过 Role -[:HAS_PERMISSION]-> Permission 建立完整授权。
DEFAULT_ROLE_GRANTS = {
    "researcher": {
        "Phage:read", "HostStrain:read", "Pathogen:read",
        "LysisAssay:read", "BiofilmAssay:read", "EnzymeGene:read",
        "ExperimentBatch:read", "SourceArtifact:read", "Review:read",
        "AgentTask:create", "AgentTask:read", "AgentResult:read",
    },
    "clinician": {
        "Phage:read", "HostStrain:read", "Pathogen:read",
        "ClinicalCase:read", "LysisAssay:read",
        "AgentTask:create", "AgentTask:read", "AgentResult:read",
    },
    "analyst": {
        "Organization:read", "DevelopmentProgram:read",
        "IntelligenceEvent:read", "IntelligenceSignal:read",
        "EngineeringStrategy:read", "TechnologyAssessment:read",
        "SourceArtifact:read", "Review:read",
        "AgentTask:create", "AgentTask:read", "AgentResult:read",
    },
    "data_manager": {
        "Phage:read", "HostStrain:read", "Pathogen:read",
        "LysisAssay:read", "BiofilmAssay:read", "EnzymeGene:read",
        "ExperimentBatch:read", "Organization:read",
        "DevelopmentProgram:read", "IntelligenceEvent:read",
        "SourceArtifact:read", "Review:read", "AuditEvent:read",
        "AgentTask:create", "AgentTask:read", "AgentResult:read",
        "AgentPlan:approve", "AgentResult:approve",
    },
}


def get_current_user() -> dict:
    if has_request_context():
        user = session.get("user")
        if user:
            return {
                "id": user.get("username", "unknown"),
                "username": user.get("username", "unknown"),
                "name": user.get("name", "未知用户"),
                "role": user.get("role", "researcher"),
            }
    return {
        "id": "sandbox_user",
        "username": "sandbox_user",
        "name": "沙箱用户",
        "role": "researcher",
    }


def get_user_permissions(username: str) -> set:
    """查询用户通过角色获得的权限集合。

    admin 角色返回全权限标记。
    """
    if not username:
        return set()
    try:
        with get_driver().session() as s:
            res = s.run(
                "MATCH (u:User {username: $uname})-[:HAS_ROLE]->(r:Role) "
                "RETURN collect(r.role_key) AS roles",
                uname=username,
            ).single()
            if res and "admin" in res["roles"]:
                return {"system:admin:all"}

            res = s.run(
                "MATCH (u:User {username: $uname})"
                "-[:HAS_ROLE]->(:Role)-[:HAS_PERMISSION]->(p:Permission) "
                "RETURN collect(p.perm_key) AS perms",
                uname=username,
            ).single()
            if res and res["perms"]:
                return set(res["perms"])
            return set()
    except Exception:
        return set()


def check_permission(
    resource: str,
    action: str,
    user_context: dict = None,
) -> bool:
    """检查当前用户对指定资源/动作是否具有权限。

    判定顺序：
    1. admin：直接放行；
    2. agent 服务身份：白名单资源直接放行；
    3. 其他角色：查库 + 兜底表。
    """
    ctx = user_context or get_current_user()
    role = ctx.get("role", "researcher")

    # 1. admin 全权限
    if role == "admin":
        return True

    # 2. agent 服务身份
    if role == "agent" or ctx.get("username") == "agent":
        return resource in {"Phage", "IntelligenceEvent", "AgentTool"}

    # 3. 查库
    perm_key = f"{resource}:{action}"
    perms = get_user_permissions(ctx.get("username"))
    if "system:admin:all" in perms or perm_key in perms:
        return True

    # 4. 兜底表
    if perm_key in DEFAULT_ROLE_GRANTS.get(role, set()):
        return True

    return False


# ============================================================
# 用户 / 角色初始化
# ============================================================

def _ensure_default_users() -> None:
    with get_driver().session() as s:
        s.run(
            """
            MERGE (u1:User {username: 'admin'})
            ON CREATE SET u1.password_hash = $p1, u1.name = '系统管理员',
                          u1.role = 'admin', u1.status = 'active'

            MERGE (u2:User {username: 'analyst'})
            ON CREATE SET u2.password_hash = $p2, u2.name = '情报分析师',
                          u2.role = 'analyst', u2.status = 'active'

            MERGE (u3:User {username: 'agent'})
            ON CREATE SET u3.password_hash = $p3, u3.name = '受控Agent服务身份',
                          u3.role = 'agent', u3.status = 'active'
            """,
            p1=generate_password_hash("admin123"),
            p2=generate_password_hash("analyst123"),
            p3=generate_password_hash("agent123"),
        )

        s.run(
            """
            MERGE (r1:Role {role_key: 'admin'}) SET r1.name = '超级管理员'
            MERGE (r2:Role {role_key: 'researcher'}) SET r2.name = '科研人员'
            MERGE (r3:Role {role_key: 'analyst'}) SET r3.name = '情报分析师'
            MERGE (r4:Role {role_key: 'data_manager'}) SET r4.name = '数据管理员'
            MERGE (r5:Role {role_key: 'clinician'}) SET r5.name = '临床医生'
            MERGE (r6:Role {role_key: 'agent'}) SET r6.name = 'Agent执行器'
            """
        )

        s.run(
            """
            MATCH (u:User {username: 'admin'}), (r:Role {role_key: 'admin'})
            MERGE (u)-[:HAS_ROLE]->(r)
            MATCH (u:User {username: 'analyst'}), (r:Role {role_key: 'analyst'})
            MERGE (u)-[:HAS_ROLE]->(r)
            MATCH (u:User {username: 'agent'}), (r:Role {role_key: 'agent'})
            MERGE (u)-[:HAS_ROLE]->(r)
            """
        )


def verify_user(username: str, password: str):
    if not username or not password:
        return None
    _ensure_default_users()
    with get_driver().session() as s:
        row = s.run(
            """
            MATCH (u:User) WHERE toLower(u.username) = toLower($uname)
            RETURN u.username AS username, u.password_hash AS pwd,
                   u.name AS name, u.role AS role, u.status AS status
            """,
            uname=username.strip(),
        ).single()

        if not row or not row["pwd"] or not check_password_hash(row["pwd"], password):
            return None

        if row.get("status") != "active":
            raise ValueError("该账号已被停用，请联系管理员")

        return {
            "username": row["username"],
            "name": row["name"],
            "role": row["role"],
        }


def current_user():
    return session.get("user")


def login_user(user: dict) -> None:
    session["user"] = user
    session.permanent = True


def logout_user() -> None:
    session.pop("user", None)


def is_authenticated() -> bool:
    return bool(session.get("user"))