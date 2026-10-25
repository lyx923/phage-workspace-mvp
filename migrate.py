# migrate.py
from config import get_driver
import traceback

MIGRATIONS = [
    {
        "version": "2.0.0",
        "description": "v0.7-EXP 实验集成扩展",
        "up": [
            # 1. 创建索引
            "CREATE INDEX enzyme_id_idx IF NOT EXISTS FOR (e:EnzymeGene) ON (e.id)",
            "CREATE INDEX batch_id_idx IF NOT EXISTS FOR (b:ExperimentBatch) ON (b.id)",
            "CREATE INDEX biofilm_id_idx IF NOT EXISTS FOR (b:BiofilmAssay) ON (b.id)",
            "CREATE INDEX phage_engineered_idx IF NOT EXISTS FOR (p:Phage) ON (p.is_engineered)",
            # 2. 为现有 Phage 节点补全字段默认值
            """
            MATCH (p:Phage)
            WHERE p.is_engineered IS NULL
            SET p.is_engineered = false,
                p.engineering_status = null,
                p.regulatory_status = 'research_only'
            """,
            # 3. 写入版本记录
            """
            MERGE (s:SchemaVersion {version: '2.0.0'})
            SET s.applied_at = datetime(),
                s.description = 'v0.7-EXP 实验集成扩展',
                s.applied_by = 'migrate.py',
                s.reversible = true
            """
        ]
    }
]

def run_migration():
    driver = get_driver()
    print("🔄 开始执行 Schema v2.0.0 迁移...")
    with driver.session() as session:
        for m in MIGRATIONS:
            for cypher in m["up"]:
                try:
                    session.run(cypher)
                except Exception as e:
                    print(f"❌ 执行失败: {e}\nCypher: {cypher[:100]}...")
                    return
    print("✅ Schema v2.0.0 迁移完成！")

if __name__ == "__main__":
    run_migration() 