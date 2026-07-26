"""
配型效果验证工具
支持 L1-L5 五级证据等级
"""
from typing import List, Dict, Optional
import pandas as pd
from config import get_driver
from src.package_builder import build_evidence_package_from_db

# 证据等级排序映射（L5 最高）
EVIDENCE_ORDER = {'L5': 1, 'L4': 2, 'L3': 3, 'L2': 4, 'L1': 5, 'GOLDEN_RULE': 0}


def query_phages_for_host(
    host_strain: str,
    limit: int = 10,
    evidence_level: Optional[str] = None
) -> List[Dict]:
    """
    查询某个宿主菌株能匹配哪些噬菌体
    使用 split 精确提取菌株名称
    """
    host_strain = host_strain.strip() 
    with get_driver() as driver:
        with driver.session() as session:
            level_filter = ""
            if evidence_level:
                level_filter = f"AND phi.evidence_level = '{evidence_level}'"

            result = session.run(f"""
                MATCH (phi:PhageHostInteraction)
                WHERE trim(split(phi.notes, ': ')[1]) = $host_strain
                  {level_filter}
                MATCH (ph:Phage)-[:HAS_INTERACTION]->(phi)
                RETURN ph.name AS phage_name,
                       ph.phage_id AS phage_id,
                       phi.evidence_level AS evidence_level,
                       phi.evidence_ref AS evidence_ref
                ORDER BY 
                    CASE phi.evidence_level
                        WHEN 'L5' THEN 1
                        WHEN 'L4' THEN 2
                        WHEN 'L3' THEN 3
                        WHEN 'L2' THEN 4
                        WHEN 'L1' THEN 5
                        ELSE 6
                    END,
                    ph.name
                LIMIT $limit
            """, host_strain=host_strain, limit=limit)
            return [dict(record) for record in result]


def query_hosts_for_phage(
    phage_name: str,
    limit: int = 10,
    evidence_level: Optional[str] = None
) -> List[Dict]:
    with get_driver() as driver:
        with driver.session() as session:
            level_filter = ""
            if evidence_level:
                level_filter = f"AND phi.evidence_level = '{evidence_level}'"

            result = session.run(f"""
                MATCH (phi:PhageHostInteraction)
                WHERE phi.phage_id = $phage_name OR phi.phage_id = 'PHAGE-' + $phage_name
                  {level_filter}
                RETURN split(phi.notes, ': ')[1] AS host_strain,
                       phi.evidence_level AS evidence_level
                ORDER BY 
                    CASE phi.evidence_level
                        WHEN 'L5' THEN 1
                        WHEN 'L4' THEN 2
                        WHEN 'L3' THEN 3
                        WHEN 'L2' THEN 4
                        WHEN 'L1' THEN 5
                        ELSE 6
                    END
                LIMIT $limit
            """, phage_name=phage_name, limit=limit)
            return [dict(record) for record in result]


def get_phage_recommendation(
    species: str,
    host_strain: Optional[str] = None,
    resistance: Optional[str] = None,
    infection_type: str = "Pneumonia",
    verbose: bool = True
) -> Dict:
    if host_strain:
        phages = query_phages_for_host(host_strain, limit=20)
        if verbose:
            print(f"🔬 {host_strain} 匹配到 {len(phages)} 个噬菌体：")
            for p in phages[:5]:
                print(f"   {p['phage_name']} (L{p['evidence_level']}) 来源: {p['evidence_ref']}")
            if len(phages) > 5:
                print(f"   ... 还有 {len(phages)-5} 个")
        return {
            "type": "host_level",
            "host_strain": host_strain,
            "phages": phages,
            "count": len(phages)
        }

    result = build_evidence_package_from_db(
        species=species,
        resistance=resistance,
        infection_type=infection_type
    )
    if verbose:
        print(f"📦 Evidence Package 生成完成")
        print(f"   - 匹配噬菌体: {len(result.get('matching_evidence', []))} 个")
        print(f"   - 临床证据: {len(result.get('clinical_evidence', []))} 条")
        print(f"   - 解释: {result.get('explanation', '')[:100]}...")
    return result


def query_l3_evidence(host_strain: Optional[str] = None) -> List[Dict]:
    with get_driver() as driver:
        with driver.session() as session:
            strain_filter = ""
            if host_strain:
                strain_filter = f"AND split(phi.notes, ': ')[1] = '{host_strain}'"

            result = session.run(f"""
                MATCH (phi:PhageHostInteraction)
                WHERE phi.evidence_level IN ['L3', 'L4', 'L5']
                  {strain_filter}
                MATCH (ph:Phage)-[:HAS_INTERACTION]->(phi)
                RETURN ph.name AS phage_name,
                       ph.phage_id AS phage_id,
                       phi.evidence_level AS evidence_level,
                       phi.evidence_ref AS evidence_ref,
                       split(phi.notes, ': ')[1] AS host_strain
                ORDER BY 
                    CASE phi.evidence_level
                        WHEN 'L5' THEN 1
                        WHEN 'L4' THEN 2
                        WHEN 'L3' THEN 3
                        ELSE 4
                    END,
                    ph.name
            """)
            return [dict(record) for record in result]


def batch_validate_hosts(
    host_strains: List[str],
    limit: int = 20,
    show_details: bool = False
) -> pd.DataFrame:
    results = []
    for host in host_strains:
        phages = query_phages_for_host(host, limit=limit)

        level_counts = {}
        l3_phages = []
        for p in phages:
            level = p['evidence_level'] or '未知'
            level_counts[level] = level_counts.get(level, 0) + 1
            if level in ['L3', 'L4', 'L5']:
                l3_phages.append(p['phage_name'])

        results.append({
            "菌株": host,
            "总匹配": len(phages),
            **{f"L{lv}": level_counts.get(f"L{lv}", 0) for lv in range(1, 6)},
            "其他": level_counts.get('未知', 0),
            "高等级噬菌体(L3+)": ", ".join(l3_phages[:3]) + ("..." if len(l3_phages) > 3 else "")
        })

        if show_details:
            print(f"\n🔬 {host}: {len(phages)} 个噬菌体")
            for p in phages[:5]:
                print(f"   {p['phage_name']} (L{p['evidence_level']})")

    return pd.DataFrame(results)


def validate_without_sequencing(host_strain: str) -> Dict:
    phages = query_phages_for_host(host_strain, limit=20)

    has_high_evidence = any(p['evidence_level'] in ['L3', 'L4', 'L5'] for p in phages)
    l2_phages = [p for p in phages if p['evidence_level'] == 'L2']

    return {
        "host_strain": host_strain,
        "total_phages": len(phages),
        "has_high_level_evidence": has_high_evidence,
        "l2_phages_count": len(l2_phages),
        "l2_phages": [p['phage_name'] for p in l2_phages[:5]],
        "conclusion": f"✅ 不依赖测序数据，仅凭菌株编号即可推荐 {len(phages)} 个候选噬菌体"
                      + (f"（其中 {len(l2_phages)} 个来自裂解谱证据）" if l2_phages else ""),
        "recommendation": "可在缺乏测序数据时作为配型参考"
    }


# ==================== 基于裂解谱聚类的伪型别推荐（不持久化，Python 动态计算） ====================
# ==================== 基于裂解谱聚类的伪型别推荐（Python 动态计算，不持久化到图） ====================
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from typing import Dict, List, Optional
import pandas as pd


def cluster_strains_from_csv(csv_path: str, n_clusters: int = 8, random_state: int = 42):
    """
    从裂解谱 CSV 读取数据，对菌株进行聚类，返回菌株到簇标签的映射 dict。
    """
    df = pd.read_csv(csv_path, encoding="utf-8")
    host_cols = df.columns[1:-1]  # 所有菌株列
    matrix = df[host_cols].T.values.astype(int)  # 菌株数 × 噬菌体数
    scaler = StandardScaler()
    matrix_scaled = scaler.fit_transform(matrix)
    kmeans = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    labels = kmeans.fit_predict(matrix_scaled)
    strain_to_cluster = {strain: int(label) for strain, label in zip(host_cols, labels)}
    return strain_to_cluster, matrix_scaled, kmeans


def query_phages_by_pseudo_type_from_mapping(
    strain_to_cluster: Dict[str, int],
    pseudo_type_label: int,  # 簇标签，从 0 开始
    min_host_count: int = 2,
    limit: int = 20
) -> List[Dict]:
    """
    基于聚类映射，查询某个伪型别（簇）中，至少覆盖 min_host_count 个菌株的噬菌体。
    直接从数据库中查询，不依赖图中的伪型别节点。
    """
    # 获取该簇的所有菌株
    strains_in_group = [strain for strain, label in strain_to_cluster.items() if label == pseudo_type_label]
    if not strains_in_group:
        return []
    
    print(f"🔍 查询簇 {pseudo_type_label+1}，包含 {len(strains_in_group)} 个菌株")
    
    with get_driver() as driver:
        with driver.session() as session:
            # 使用 UNWIND 和 REDUCE 计算每个互作记录覆盖的菌株数
            result = session.run("""
                MATCH (phi:PhageHostInteraction)<-[:HAS_INTERACTION]-(ph:Phage)
                WITH ph, phi, $strains AS strains
                WITH ph, phi, 
                     REDUCE(s = 0, strain IN strains | 
                         s + CASE WHEN phi.notes CONTAINS strain THEN 1 ELSE 0 END
                     ) AS host_count
                WHERE host_count >= $min_host_count
                RETURN ph.name AS phage_name,
                       ph.phage_id AS phage_id,
                       phi.evidence_level AS evidence_level,
                       phi.evidence_ref AS evidence_ref,
                       host_count
                ORDER BY host_count DESC,
                         CASE phi.evidence_level
                             WHEN 'L5' THEN 1
                             WHEN 'L4' THEN 2
                             WHEN 'L3' THEN 3
                             WHEN 'L2' THEN 4
                             WHEN 'L1' THEN 5
                             ELSE 6
                         END
                LIMIT $limit
            """, strains=strains_in_group, min_host_count=min_host_count, limit=limit)
            return [dict(record) for record in result]