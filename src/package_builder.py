"""
src/package_builder.py Evidence Package 构建器
支持互作路径 + 黄金规则路径双路检索，LLM 和规则引擎均可使用。

"""
from typing import List, Dict, Optional, Any
import json
from openai import OpenAI
from src.data_loader import get_driver
from src.retriever import find_matching_phages, find_similar_cases
from config import Config


# ==================== 系统提示词（对齐规范 P2、P4） ====================
SYSTEM_PROMPT = """你是一个精准抗感染领域的循证助手。
你的职责是组织已有的检索结果，不是创造新知识。
你只使用下面提供的检索结果，不添加任何未在检索结果中出现的信息。
对于缺失的信息，标注"需人工进一步确认"。
不做治疗推荐。
输出严格的 JSON 格式。"""


# ==================== 初始化 DeepSeek 客户端 ====================
def _get_client() -> OpenAI:
    """获取 DeepSeek 客户端（使用 OpenAI 兼容 SDK）"""
    return OpenAI(
        api_key=Config.DS_API_KEY,
        base_url=Config.DS_BASE_URL
    )


# ==================== 黄金规则检索（公共函数） ====================
def _retrieve_golden_rules(species: str) -> Dict:
    """
    从 Neo4j 检索指定病原菌关联的黄金规则及其推荐的噬菌体。
    返回包含 rule_phages 和 matched_rules 的字典。
    """
    with get_driver() as driver:
        with driver.session() as session:
            rule_result = session.run("""
                MATCH (p:Pathogen {species: $species})
                OPTIONAL MATCH (p)-[:HAS_VALIDATED_RULE]->(r:KnowledgeRule)
                OPTIONAL MATCH (r)-[:RECOMMENDS_PHAGE]->(ph:Phage)
                RETURN COLLECT(DISTINCT ph.name) AS rule_phages,
                       COLLECT(DISTINCT {rule_id: r.rule_id, treatment: r.treatment, outcome: r.outcome}) AS rules
            """, species=species)
            rule_data = rule_result.single().data()
            return {
                "rule_phages": rule_data.get('rule_phages', []),
                "matched_rules": rule_data.get('rules', [])
            }


# ==================== 数据格式化函数 ====================
def _format_matching_phages(raw_phages: List[Dict]) -> List[Dict]:
    """将 retriever 返回的噬菌体字段映射为 Evidence Package 格式"""
    formatted = []
    for item in raw_phages:
        evidence_ref = item.get('evidence_ref')
        if isinstance(evidence_ref, str):
            evidence_ref = [x.strip() for x in evidence_ref.split(',') if x.strip()]
        elif evidence_ref is None:
            evidence_ref = []
        
        formatted.append({
            "phage_name": item.get('name'),
            "family": item.get('family'),
            "infection_result": item.get('infection_result'),
            "infection_probability": item.get('infection_probability'),
            "evidence_level": item.get('evidence_level'),
            "evidence_ref": evidence_ref,
            "notes": item.get('notes')
        })
    return formatted


def _format_similar_cases(raw_cases: List[Dict]) -> List[Dict]:
    """将 retriever 返回的病例字段映射为 Evidence Package 格式"""
    return [
        {
            "case_id": item.get('case_id'),
            "infection_type": item.get('infection_type'),
            "phage_treatment": item.get('phage_treatment'),
            "clinical_outcome": item.get('clinical_outcome'),
            "microbiological_outcome": item.get('microbiological_outcome')
        }
        for item in raw_cases
    ]


def _merge_golden_rule_phages(
    formatted_phages: List[Dict],
    rule_data: Dict
) -> List[Dict]:
    """
    将黄金规则推荐的噬菌体合并到互作路径的噬菌体列表中。
    如果某噬菌体已在列表中，则将其 evidence_level 提升为 GOLDEN_RULE。
    """
    rule_phages = rule_data.get('rule_phages', [])
    matched_rules = rule_data.get('matched_rules', [])
    
    if not rule_phages:
        return formatted_phages
    
    # 构建噬菌体名称到索引的映射
    name_to_idx = {}
    for idx, p in enumerate(formatted_phages):
        name = p.get('phage_name')
        if name:
            name_to_idx[name] = idx
    
    # 处理黄金规则推荐的噬菌体
    golden_entries = []
    for phage_name in rule_phages:
        if not phage_name:
            continue
        
        if phage_name in name_to_idx:
            # 已存在于互作列表中，提升证据等级
            idx = name_to_idx[phage_name]
            formatted_phages[idx]['evidence_level'] = 'GOLDEN_RULE'
            # 追加规则信息到 notes
            existing_notes = formatted_phages[idx].get('notes') or ''
            if matched_rules:
                rule_info = f"黄金规则: {', '.join([r['rule_id'] for r in matched_rules])}"
                formatted_phages[idx]['notes'] = f"{existing_notes}；{rule_info}".strip('；')
        else:
            # 不在互作列表中，新增条目
            golden_entries.append({
                "phage_name": phage_name,
                "family": "黄金规则推荐",
                "infection_result": "Lytic (黄金规则)",
                "infection_probability": 1.0,
                "evidence_level": "GOLDEN_RULE",
                "evidence_ref": [f"Rule: {', '.join([r['rule_id'] for r in matched_rules])}"],
                "notes": f"由经过临床验证的黄金规则推荐。预期结局：{', '.join([r['outcome'] for r in matched_rules])}"
            })
    
    # 将黄金规则条目放在最前面
    return golden_entries + formatted_phages


# ==================== LLM 版本的 Evidence Package 构建器 ====================
def build_evidence_package(
    matching_phages: List[Dict],
    similar_cases: List[Dict],
    query_context: Dict[str, Any]
) -> Dict:
    """
    调用 DeepSeek API 组织检索结果，生成结构化的 Evidence Package。

    Args:
        matching_phages: 已格式化的噬菌体匹配列表（含 GOLDEN_RULE 标记）
        similar_cases: 已格式化的相似病例列表
        query_context: 查询上下文，包含 species, resistance, infection_type, matched_rules

    Returns:
        Dict: matching_evidence, clinical_evidence, explanation
    """
    # 提取黄金规则信息
    matched_rules = query_context.get('matched_rules', [])
    rules_text = json.dumps(matched_rules, ensure_ascii=False, indent=2) if matched_rules else "未匹配到黄金规则"

    user_prompt = f"""
查询上下文：
- 病原菌: {query_context.get('species', '未知')}
- 耐药机制: {query_context.get('resistance', '未知')}
- 感染类型: {query_context.get('infection_type', '未知')}

【黄金规则（经过临床验证的配型知识）】
{rules_text}

【匹配到的噬菌体（按证据等级排序，GOLDEN_RULE 为最高优先级）】
{json.dumps(matching_phages, ensure_ascii=False, indent=2)}

【相似历史病例】
{json.dumps(similar_cases, ensure_ascii=False, indent=2)}

请按以下 JSON 格式输出 Evidence Package：
{{
  "matching_evidence": [
    {{"phage_name": "", "family": "", "infection_result": "", "infection_probability": 0.0, "evidence_level": "", "evidence_ref": [], "notes": ""}}
  ],
  "clinical_evidence": [
    {{"case_id": "", "infection_type": "", "phage_treatment": "", "clinical_outcome": "", "microbiological_outcome": ""}}
  ],
  "explanation": ""
}}

【重要约束 - 必须严格遵守】
1. 如果存在 evidence_level 为 "GOLDEN_RULE" 的噬菌体，必须将其排在 matching_evidence 的第一位。
2. explanation 必须逐条引用证据，格式为："噬菌体名称（证据等级 Y，来源：Z）"。
3. ⚠️ 禁止使用"等"字概括未列出的噬菌体。所有匹配到的噬菌体都必须在 explanation 中单独列出。
4. 对于 GOLDEN_RULE 级别的噬菌体，必须引用其对应的规则 ID 和预期结局。
5. 对于 L3 级别的噬菌体，必须引用其对应的 CASE-XXX 来源。
6. 对于 L1/L2 级别的噬菌体，必须引用其对应的 PMID 或标注"体外验证"。
7. 只使用提供的数据，不添加任何未出现的信息。

【explanation 输出格式示例】
本次检索针对 [病原菌]（[耐药机制]）引起的 [感染类型]，共匹配到 N 个噬菌体：
- ΦK2-v3（黄金规则，来源：RULE_CRAB_KL2，预期结局：第14天微生物清除）—— 优先级最高，推荐使用。
- vB_AbaM_003（L3，来源：CASE-004，临床验证有效）—— 有单例临床验证支持。
- vB_AbaM_007（L3，来源：CASE-013，临床验证有效）—— 有单例临床验证支持。
- vB_AbaM_001（L2，来源：体外验证）—— 仅有体外活性数据，需进一步临床验证。
- vB_AbaM_008（L1，来源：PMID:56789012）—— 公开文献报道。
（按此格式列出所有噬菌体，禁止使用"等"字）
相似历史病例中，CASE-XXX 无噬菌体治疗记录，无法提供参考。
⚠️ explanation 中必须按以下格式逐条列出所有匹配到的噬菌体，不得使用"等"、"多个"等概括性词语：
格式：- 噬菌体名称（证据等级：X，来源：Y）
"""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=Config.DS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=Config.DS_TEMPERATURE,
            max_tokens=Config.DS_MAX_TOKENS,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "matching_evidence": [],
                "clinical_evidence": [],
                "explanation": f"解析失败，原始输出：\n{content}",
                "_raw_output": content,
                "_parse_error": True
            }
            
    except Exception as e:
        return {
            "matching_evidence": [],
            "clinical_evidence": [],
            "explanation": f"API 调用失败：{str(e)}",
            "_api_error": True
        }


# ==================== 一站式入口（LLM 版本） ====================
def build_evidence_package_from_db(
    species: str,
    resistance: Optional[str] = None,
    infection_type: Optional[str] = None,
    phage_limit: int = 20,
    case_limit: int = 5
) -> Dict:
    """
    一站式入口：检索互作路径 + 黄金规则路径 → 合并 → 构建 Evidence Package。
    黄金规则推荐的噬菌体会被标记为 GOLDEN_RULE 并优先展示。
    """
    with get_driver() as driver:
        # 1. 从互作路径检索
        raw_phages = find_matching_phages(driver, species, resistance, limit=phage_limit)
        raw_cases = find_similar_cases(driver, species, infection_type, limit=case_limit)

    # 2. 格式化互作路径的噬菌体
    formatted_phages = _format_matching_phages(raw_phages)

    # 3. 检索黄金规则
    rule_data = _retrieve_golden_rules(species)

    # 4. 合并黄金规则推荐的噬菌体（提升优先级或新增）
    formatted_phages = _merge_golden_rule_phages(formatted_phages, rule_data)

    # 5. 格式化临床证据
    formatted_cases = _format_similar_cases(raw_cases)

    # 6. 构造上下文（包含黄金规则信息）
    query_context = {
        "species": species,
        "resistance": resistance or "未知",
        "infection_type": infection_type or "未知",
        "matched_rules": rule_data.get('matched_rules', [])
    }

    # 7. 调用 LLM
    return build_evidence_package(formatted_phages, formatted_cases, query_context)


# ==================== 验证函数 ====================
def verify_llm_effectiveness(case_id: str = "CASE-001") -> Dict:
    """
    验证 LLM 推荐效果 vs 真实临床方案
    """
    with get_driver() as driver:
        with driver.session() as session:
            result = session.run("""
                MATCH (c:ClinicalCase {case_id: $case_id})-[:INVOLVES_PATHOGEN]->(p:Pathogen)
                OPTIONAL MATCH (p)-[:HAS_VALIDATED_RULE]->(r:KnowledgeRule)
                RETURN c.case_id AS case_id,
                       c.infection_type AS infection_type,
                       c.phage_treatment AS actual_treatment,
                       c.microbiological_outcome AS actual_outcome,
                       p.species AS species,
                       p.resistance_mechanism AS resistance,
                       COLLECT(DISTINCT {rule_id: r.rule_id, treatment: r.treatment, outcome: r.outcome}) AS rules
            """, case_id=case_id)
            case_data = result.single().data()
    
    if not case_data:
        return {"error": f"病例 {case_id} 不存在"}
    
    # 构建 Evidence Package
    package = build_evidence_package_from_db(
        species=case_data['species'],
        resistance=case_data['resistance'],
        infection_type=case_data['infection_type']
    )
    
    # 对比真实方案
    actual_phages = ["cp-p-ec-23086", "cp-p-ec-23062"]
    lower = json.dumps(package, ensure_ascii=False).lower()
    found = [p for p in actual_phages if p in lower]
    
    package["_verification"] = {
        "case_id": case_id,
        "actual_treatment": case_data['actual_treatment'],
        "actual_outcome": case_data['actual_outcome'],
        "matched_phages": found,
        "coverage": "full" if set(found) == set(actual_phages) else "partial" if found else "none"
    }
    
    # 检查是否引用了规则
    if any(rule.get('rule_id') == 'RULE_ECOLI_O25' for rule in case_data.get('rules', [])):
        package["_verification"]["rule_cited"] = "O25" in lower or "48小时" in lower
    
    return package


# ==================== 规则引擎（无 LLM） ====================
def rule_based_evidence_package(
    species: str,
    resistance: Optional[str] = None,
    infection_type: Optional[str] = None,
    phage_limit: int = 20,
    case_limit: int = 5
) -> Dict:
    """
    纯规则引擎：同时检索互作路径和黄金规则路径。
    黄金规则推荐的噬菌体优先级最高。
    """
    with get_driver() as driver:
        # 1. 从互作路径检索
        raw_phages = find_matching_phages(driver, species, resistance, limit=phage_limit)
        raw_cases = find_similar_cases(driver, species, infection_type, limit=case_limit)

        # 2. 格式化互作路径的噬菌体
        matching_evidence = []
        for item in raw_phages:
            ref = item.get('evidence_ref')
            if isinstance(ref, str):
                ref = [x.strip() for x in ref.split(',') if x.strip()]
            elif ref is None:
                ref = []
            
            matching_evidence.append({
                "phage_name": item.get('name'),
                "family": item.get('family'),
                "infection_result": item.get('infection_result'),
                "infection_probability": item.get('infection_probability'),
                "evidence_level": item.get('evidence_level'),
                "evidence_ref": ref,
                "notes": item.get('notes')
            })

        # 3. 检索并合并黄金规则
        rule_data = _retrieve_golden_rules(species)
        matching_evidence = _merge_golden_rule_phages(matching_evidence, rule_data)

        # 4. 排序：GOLDEN_RULE > L3 > L2 > L1
        def sort_key(e):
            level = e.get('evidence_level', 'L5')
            prob = e.get('infection_probability', 0) or 0
            if level == 'GOLDEN_RULE':
                return (0, 1.0)
            level_order = {'L3': 1, 'L2': 2, 'L1': 3, 'L4': 4, 'L5': 5}
            return (level_order.get(level, 5), -prob)
        
        matching_evidence.sort(key=sort_key)

        # 5. 格式化临床证据
        clinical_evidence = [
            {
                "case_id": item.get('case_id'),
                "infection_type": item.get('infection_type'),
                "phage_treatment": item.get('phage_treatment'),
                "clinical_outcome": item.get('clinical_outcome'),
                "microbiological_outcome": item.get('microbiological_outcome')
            }
            for item in raw_cases
        ]

        # 6. 生成解释
        total = len(matching_evidence)
        clinical_cnt = len(clinical_evidence)
        
        golden_phages = [e['phage_name'] for e in matching_evidence if e.get('evidence_level') == 'GOLDEN_RULE']
        validated_phages = [e['phage_name'] for e in matching_evidence if e.get('evidence_level') == 'L3']
        
        if golden_phages:
            explanation = (
                f"针对 {species}（{resistance or '未知耐药'}）引起的 {infection_type or '未知感染'}，"
                f"共检索到 {total} 个匹配噬菌体。其中 {', '.join(golden_phages)} 由经过临床验证的黄金规则推荐，优先级最高。"
            )
        elif validated_phages:
            explanation = (
                f"针对 {species}（{resistance or '未知耐药'}）引起的 {infection_type or '未知感染'}，"
                f"共检索到 {total} 个匹配噬菌体。其中 {', '.join(validated_phages[:3])} 有临床病例验证，优先推荐。"
            )
        else:
            explanation = f"检索到 {total} 个匹配噬菌体和 {clinical_cnt} 个相似病例，无临床验证噬菌体，建议人工复核。"

        return {
            "matching_evidence": matching_evidence,
            "clinical_evidence": clinical_evidence,
            "explanation": explanation,
            "_engine_type": "rule_based",
            "_golden_rules_applied": golden_phages
        }