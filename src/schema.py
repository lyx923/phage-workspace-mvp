# src/schema.py
from config import config, get_driver   # ← 导入 get_driver
from neo4j import GraphDatabase

def create_schema(driver):
    """执行 Cypher 语句，创建约束和索引"""
    with driver.session() as session:
        # 1. Pathogen 唯一约束
        session.run("CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE;")
        # 2. ClinicalCase 唯一约束
        session.run("CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:ClinicalCase) REQUIRE c.case_id IS UNIQUE;")
        # 3. Phage 唯一约束
        session.run("CREATE CONSTRAINT phage_id_unique IF NOT EXISTS FOR (p:Phage) REQUIRE p.phage_id IS UNIQUE;")
        # 4. PhageHostInteraction 唯一约束
        session.run("CREATE CONSTRAINT interaction_id_unique IF NOT EXISTS FOR (i:PhageHostInteraction) REQUIRE i.interaction_id IS UNIQUE;")
        print("✅ 数据库约束与索引创建完成")

if __name__ == "__main__":
    with get_driver() as driver:
        create_schema(driver)