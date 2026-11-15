# config.py
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase
from redis import Redis
from redis.connection import ConnectionPool

load_dotenv()


class Config:
    # 应用基础信息
    APP_TITLE = "噬清森AI精准抗感染平台"
    APP_VERSION = "0.8.0-EXP"

    # Neo4j 配置
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

    # DeepSeek 配置（注意：变量名是 DS_*，不是 DEEPSEEK_*）
    DS_API_KEY = os.getenv("DS_API_KEY")
    DS_MODEL = os.getenv("DS_MODEL", "deepseek-chat")
    DS_TEMPERATURE = float(os.getenv("DS_TEMPERATURE", "0.3"))
    DS_MAX_TOKENS = int(os.getenv("DS_MAX_TOKENS", "4096"))
    DS_BASE_URL = os.getenv("DS_BASE_URL", "https://api.deepseek.com/v1")

    # Redis 配置（v0.8 修正：host 不再叫 REDIS_URL，端口与 README 的 6379 对齐）
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "localhost_lyx")
    REDIS_MAXIDLE = int(os.getenv("REDIS_MAXIDLE", "30"))
    REDIS_MINIDLE = int(os.getenv("REDIS_MINIDLE", "10"))
    REDIS_MAXTOTAL = int(os.getenv("REDIS_MAXTOTAL", "5000"))

    # 数据路径
    DATA_DIR = "data"
    CASES_CSV = f"{DATA_DIR}/cases.csv"
    PHAGE_CSV = f"{DATA_DIR}/phage_interactions.csv"

    # ============================================================
    # Schema 与迁移配置
    # ============================================================
    CURRENT_SCHEMA_VERSION = "0.8.0"
    # 生产建议: SCHEMA_AUTO_MIGRATE=false, 手动执行 python migrate.py up
    SCHEMA_AUTO_MIGRATE = os.getenv("SCHEMA_AUTO_MIGRATE", "false").lower() == "true"

    # ============================================================
    # 沙箱标志
    # ============================================================
    SANDBOX_MODE = os.getenv("SANDBOX_MODE", "true").lower() == "true"
    SANDBOX_MOCK_DATA = os.getenv("SANDBOX_MOCK_DATA", "true").lower() == "true"

    # ============================================================
    # Agent 验证开关（v0.8-Agent 批次）
    # ============================================================
    # 总开关：默认关闭。开启后 get_agent_runtime() 才会装配仓储和执行器。
    AGENT_VALIDATION_ENABLED = (
        os.getenv("AGENT_VALIDATION_ENABLED", "false").lower() == "true"
    )
    # 测试模型开关：仅当 SANDBOX_MODE 与 AGENT_VALIDATION_ENABLED 同时为 true
    # 且本开关为 true 时，才允许注册/调用 TEST-ELIGIBILITY-ECHO。
    AGENT_TEST_MODEL_ENABLED = (
        os.getenv("AGENT_TEST_MODEL_ENABLED", "false").lower() == "true"
    )
    # 失败步骤最大重试次数（第 6 批使用）。测试默认值，不是业务标准。
    AGENT_MAX_RETRIES = int(os.getenv("AGENT_MAX_RETRIES", "1"))

    # ============================================================
    # 文件存储预置（v0.8 仍预留，不实现）
    # ============================================================
    FILE_STORAGE_BACKEND = os.getenv("FILE_STORAGE_BACKEND", "local")
    FILE_STORAGE_PATH = os.getenv("FILE_STORAGE_PATH", "./uploads")
    # Enum: local / s3 / oss

    # 应用设置
    DEBUG_MODE = os.getenv("DEBUG", "false").lower() == "true"
    PORT = int(os.getenv("PORT", "8501"))
    HOST = os.getenv("HOST", "0.0.0.0")

# ============================================================
# 全局单例：Neo4j 驱动
# ============================================================
_driver = None


def get_driver():
    """获取 Neo4j 驱动（全局单例复用，避免并发打满连接池）"""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD)
        )
    return _driver


# ============================================================
# 全局单例：Redis 连接池
# ============================================================
_redis_pool = None


def get_redis_client() -> Redis:
    """获取 Redis 客户端（连接池复用）"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD,
            max_connections=Config.REDIS_MAXTOTAL,
        )
    return Redis(connection_pool=_redis_pool)


config = Config()