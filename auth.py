# auth.py
"""
基于 Neo4j 的用户认证模块。
首次运行时，如果数据库中不存在 User 节点，会自动初始化两个测试账号。
"""
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash
from config import get_driver

# 初始化默认账号
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
    
    _ensure_default_users() # 确保表存在
    
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