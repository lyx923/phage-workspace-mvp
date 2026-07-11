import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

class Config:
    
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
    
    # 数据路径
    DATA_DIR = "data"
    CASES_CSV = f"{DATA_DIR}/cases.csv"
    PHAGE_CSV = f"{DATA_DIR}/phage_interactions.csv"

def get_driver():
    return GraphDatabase.driver(Config.NEO4J_URI, auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD))

config = Config()