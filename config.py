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
    APP_VERSION = "0.7.0-EXP"

    # Neo4j 配置
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

    # DeepSeek 配置
    DS_API_KEY = os.getenv("DS_API_KEY")
    DS_MODEL = os.getenv("DS_MODEL", "deepseek-chat")
    DS_TEMPERATURE = float(os.getenv("DS_TEMPERATURE", "0.3"))
    DS_MAX_TOKENS = int(os.getenv("DS_MAX_TOKENS", "4096"))
    DS_BASE_URL = "https://api.deepseek.com/v1"

    # Redis 配置
    REDIS_MAXIDLE = int(os.getenv("REDIS_MAXIDLE", "30"))
    REDIS_MINIDLE = int(os.getenv("REDIS_MINIDLE", "10"))
    REDIS_MAXTOTAL = int(os.getenv("REDIS_MAXTOTAL", "5000"))
    REDIS_URL = os.getenv("REDIS_URL")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "7491"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
    REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "localhost_lyx")

    # 数据路径
    DATA_DIR = "data"
    CASES_CSV = f"{DATA_DIR}/cases.csv"
    PHAGE_CSV = f"{DATA_DIR}/phage_interactions.csv"


# ★ 优化：Neo4j 驱动全局单例
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


# Redis 连接池全局单例
_redis_pool = None

def get_redis_client() -> Redis:
    """获取 Redis 客户端（连接池复用）"""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = ConnectionPool(
            host=Config.REDIS_URL,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD,
            max_connections=Config.REDIS_MAXTOTAL,
        )
    return Redis(connection_pool=_redis_pool)


config = Config()