# test_env.py
import sys
from config import config
from neo4j import GraphDatabase
"""python -m tests.test_env"""
def test_neo4j():
    """测试 Neo4j 连接"""
    print("🔍 正在测试 Neo4j 连接...")
    try:
        driver = GraphDatabase.driver(
            config.NEO4J_URI, 
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD)
        )
        with driver.session() as session:
            result = session.run("RETURN 1 AS num")
            for record in result:
                if record["num"] == 1:
                    print("✅ Neo4j 连接成功！")
        driver.close()
        return True
    except Exception as e:
        print(f"❌ Neo4j 连接失败: {e}")
        return False

def test_deepseek():
    """测试 DeepSeek API 连通性（轻量级调用）"""
    print("🔍 正在测试 DeepSeek API...")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=config.DS_API_KEY,
            base_url=config.DS_BASE_URL,
        )
        # 调用 models 列表只是验证 Key 是否有效，不消耗 token
        models = client.models.list()
        print("✅ DeepSeek API Key 验证通过！")
        return True
    except Exception as e:
        print(f"❌ DeepSeek API 验证失败: {e}")
        return False

def test_files():
    """检查数据目录和文件是否存在（虽然还没放数据，但检查目录）"""
    import os
    print("🔍 正在检查数据目录...")
    if not os.path.exists(config.DATA_DIR):
        os.makedirs(config.DATA_DIR)
        print("📁 已创建 data/ 目录（请将 cases.csv 和 phage_interactions.csv 放入）")
    else:
        print("✅ data/ 目录已存在")
    return True

if __name__ == "__main__":
    print("🚀 开始进行环境验证...\n")
    
    all_passed = True
    if not test_neo4j():
        all_passed = False
    if not test_deepseek():
        all_passed = False
    test_files()  # 不阻断
    
    print("\n" + "="*40)
    if all_passed:
        print("🎉 环境验证全部通过！空项目已就绪，可以开始导入数据了。")
        sys.exit(0)
    else:
        print("⚠️ 存在环境错误，请检查 .env 配置或服务是否启动。")
        sys.exit(1)