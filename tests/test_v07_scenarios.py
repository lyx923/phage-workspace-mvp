# tests/test_v07_scenarios.py
"""
v0.7 验收测试场景 (自动化基础版)
运行方式: python tests/test_v07_scenarios.py
"""
import os
import sys

# 确保能导入项目根目录的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_driver


def test_t01_enzyme_gene():
    """T-01: 录入酶基因并验证批次关联"""
    with get_driver().session() as s:
        res = s.run("MATCH (e:EnzymeGene)-[:BELONGS_TO_BATCH]->(b:ExperimentBatch) RETURN count(e) AS c").single()
        assert res["c"] > 0, "未找到关联批次的酶基因"
    print("✅ T-01 酶基因及批次关联 通过")


def test_t02_engineered_phage():
    """T-02: 工程化噬菌体标记与血缘"""
    with get_driver().session() as s:
        res = s.run("MATCH (ep:Phage {is_engineered: true})-[:ENGINEERED_FROM]->(wt:Phage) RETURN count(ep) AS c").single()
        assert res["c"] > 0, "未找到工程化噬菌体血缘关系"
    print("✅ T-02 工程化噬菌体血缘 通过")


def test_t03_od_timeseries():
    """T-03: OD时序数据存在"""
    with get_driver().session() as s:
        res = s.run("MATCH (a:LysisAssay) WHERE a.od_timeseries IS NOT NULL AND a.od_timeseries <> '' RETURN count(a) AS c").single()
        assert res["c"] > 0, "未找到 OD 时序数据"
    print("✅ T-03 OD 时序数据 通过")


def test_t04_biofilm_assay():
    """T-04: 生物膜实验数据"""
    with get_driver().session() as s:
        res = s.run("MATCH (b:BiofilmAssay) RETURN count(b) AS c").single()
        assert res["c"] > 0, "未找到生物膜实验数据"
    print("✅ T-04 生物膜实验数据 通过")


def test_t13_evallog():
    """T-13: EvalLog 写入验证"""
    with get_driver().session() as s:
        res = s.run("MATCH (e:EvalLog) RETURN count(e) AS c").single()
        if res["c"] == 0:
            print("⚠️ T-13 EvalLog 暂无记录（请先去 AI 助手页面发起一次对话）")
        else:
            print(f"✅ T-13 EvalLog 有 {res['c']} 条记录")


if __name__ == "__main__":
    print("🚀 开始 v0.7 基础验收测试...")
    try:
        test_t01_enzyme_gene()
        test_t02_engineered_phage()
        test_t03_od_timeseries()
        test_t04_biofilm_assay()
        test_t13_evallog()
        print("\n🎉 验收项检查完毕！")
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
    except Exception as e:
        print(f"\n⚠️ 连接或执行异常: {e}")