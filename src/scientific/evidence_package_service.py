"""
src/scientific/evidence_package_service.py Evidence Package 构建器
支持互作路径 + 黄金规则路径双路检索，LLM 和规则引擎均可使用。

"""
from typing import List, Dict, Optional, Any
import json
from openai import OpenAI
from src.scientific.import_service import get_driver
from src.scientific.retriever_service import find_matching_phages, find_similar_cases
from config import Config
import uuid


# ==================== 系统提示词（对齐规范 P2、P4 及文案约束） ====================
SYSTEM_PROMPT = """你是一个精准抗感染领域的循证助手。
你的职责是组织已有的检索结果，不是创造新知识。
你只使用下面提供的检索结果，不添加任何未在检索结果中出现的信息。
对于缺失的信息，标注"需人工进一步确认"。
不做治疗推荐。
严禁把候选项写成治疗建议。
严禁把规则命中直接写成临床有效。
严禁自动决定证据等级。
严禁自动生成 approved Review。
严禁使用"推荐使用"、"优先治疗"、"应采用"等表达。
应使用"在当前检索结果中证据排序较高"、"存在以下候选证据"、"需领域专家进一步审核"等表述。
输出严格的 JSON 格式。"""


# ==================== 初始化 DeepSeek 客户端 ====================
def _get_client() -> OpenAI:
    """获取 DeepSeek 客户端（使用 OpenAI 兼容 SDK）"""
    return OpenAI(
        api_key=Config.DS_API_KEY,
        base_url=Config.DS_BASE_URL
    )


# ==================== 黄金规则检索（公共函数） ====================
def _retrieve_golden_rules(species: str, strain_type: Optional[str] = None) -> Dict:
    """
    从 Neo4j 检索指定病原菌关联的黄金规则及其推荐的噬菌体。
    规则只有在全部必填条件（species + strain_type）满足时才能应用。
    如果查询中缺少 strain_type，返回提示信息，不应用规则。
    """
    with get_driver() as driver:
        with driver.session() as session:
            # 如果缺少 strain_type，返回提示，不应用规则
            if not strain_type:
                return {
                    "rule_phages": [],
                    "matched_rules": [],
                    "missing_condition": "strain_type",
                    "message": "规则存在，但当前上下文缺少适用条件（strain_type）"
                }
            
            # 使用 ScientificKnowledgeRule 标签，并要求 strain_type 匹配且规则状态为 active
            rule_result = session.run("""
                MATCH (p:Pathogen {species: $species})
                OPTIONAL MATCH (p)-[:HAS_VALIDATED_RULE]->(r:ScientificKnowledgeRule)
                WHERE r.strain_type = $strain_type
                  AND r.status = 'active'
                OPTIONAL MATCH (r)-[:RECOMMENDS_PHAGE]->(ph:Phage)
                RETURN COLLECT(DISTINCT ph.name) AS rule_phages,
                       COLLECT(DISTINCT {
                           rule_id: r.rule_id, 
                           treatment: r.treatment, 
                           outcome: r.outcome,
                           required_attributes: r.required_attributes,
                           applicability: r.applicability
                       }) AS rules
            """, species=species, strain_type=strain_type)
            rule_data = rule_result.single().data()
            return {
                "rule_phages": rule_data.get('rule_phages', []),
                "matched_rules": rule_data.get('rules', []),
                "missing_condition": None,
                "message": None
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
    如果规则因缺少条件而未匹配，则添加提示信息。
    """
    # 检查是否因缺少条件而未应用规则
    if rule_data.get('missing_condition'):
        return formatted_phages + [{
            "phage_name": f"⚠️ 规则存在，但缺少适用条件（{rule_data.get('missing_condition')}）",
            "family": "提示",
            "infection_result": "需人工确认",
            "infection_probability": 0,
            "source_type": "info",
            "priority": "low",
            "evidence_ref": [],
            "notes": f"当前查询缺少 {rule_data.get('missing_condition')} 等必填条件，黄金规则暂未应用。请补充条件后重新检索。"
        }]
    
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
            # 已存在于互作列表中，提升为 validated_rule
            idx = name_to_idx[phage_name]
            formatted_phages[idx]['source_type'] = 'validated_rule'
            formatted_phages[idx]['priority'] = 'high'
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
                "source_type": "validated_rule",
                "priority": "high",
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

【匹配到的噬菌体（按证据排序，validated_rule 优先，其后按 L1-L5 排序）】
{json.dumps(matching_phages, ensure_ascii=False, indent=2)}

【相似历史病例】
{json.dumps(similar_cases, ensure_ascii=False, indent=2)}

请按以下 JSON 格式输出 Evidence Package：
{{
  "matching_evidence": [
    {{"phage_name": "", "family": "", "infection_result": "", "infection_probability": 0.0, "evidence_level": "", "evidence_ref": [], "notes": "", "source_type": "", "priority": ""}}
  ],
  "clinical_evidence": [
    {{"case_id": "", "infection_type": "", "phage_treatment": "", "clinical_outcome": "", "microbiological_outcome": ""}}
  ],
  "explanation": ""
}}

【重要约束 - 必须严格遵守】
1. 如果存在 source_type 为 "validated_rule" 的噬菌体，必须将其排在 matching_evidence 的第一位。
2. explanation 必须逐条引用证据，格式为："噬菌体名称（证据等级 Y，来源：Z）"。
3. 禁止使用"等"字概括未列出的噬菌体。所有匹配到的噬菌体都必须在 explanation 中单独列出。
4. 对于 validated_rule 级别的噬菌体，必须引用其对应的规则 ID 和预期结局。
5. 对于 L3 级别的噬菌体，必须引用其对应的 CASE-XXX 来源。
6. 对于 L1/L2 级别的噬菌体，必须引用其对应的 PMID 或标注"体外验证"。
7. 只使用提供的数据，不添加任何未出现的信息。
8. 严禁使用"推荐使用"、"优先治疗"、"应采用"等表述，应使用"在当前检索结果中证据排序较高"、"存在以下候选证据"、"需领域专家进一步审核"。
9. 严禁把候选项写成治疗建议。
10. 严禁把规则命中直接写成临床有效。黄金规则只是候选证据之一，不代表临床有效性。
11. 严禁自动决定证据等级。证据等级应保留原始值，不得自行推断升级。
12. 严禁自动生成 approved Review。生成的 Evidence Package 仅作为草稿（draft）。

【explanation 输出格式示例】
本次检索针对 [病原菌]（[耐药机制]）引起的 [感染类型]，共匹配到 N 个噬菌体：
- ΦK2-v3（黄金规则，来源：RULE_CRAB_KL2，预期结局：第14天微生物清除）—— 在当前检索结果中证据排序较高。
- vB_AbaM_003（L3，来源：CASE-004，临床验证有效）—— 存在单例临床验证支持。
- vB_AbaM_001（L2，来源：体外验证）—— 仅有体外活性数据，需领域专家进一步审核。
（按此格式列出所有噬菌体，禁止使用"等"字）
相似历史病例中，CASE-XXX 无噬菌体治疗记录，无法提供参考。
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
    strain_type: Optional[str] = None,
    resistance: Optional[str] = None,
    infection_type: Optional[str] = None,
    phage_limit: int = 20,
    case_limit: int = 5
) -> Dict:
    """
    一站式入口：检索互作路径 + 黄金规则路径 → 合并 → 构建 Evidence Package。
    """
    with get_driver() as driver:
        raw_phages = find_matching_phages(driver, species, resistance, limit=phage_limit)
        raw_cases = find_similar_cases(driver, species, infection_type, limit=case_limit)

    formatted_phages = _format_matching_phages(raw_phages)

    # 检索黄金规则
    rule_data = _retrieve_golden_rules(species, strain_type)

    # 合并黄金规则推荐的噬菌体
    formatted_phages = _merge_golden_rule_phages(formatted_phages, rule_data)

    formatted_cases = _format_similar_cases(raw_cases)

    query_context = {
        "species": species,
        "strain_type": strain_type,
        "resistance": resistance or "未知",
        "infection_type": infection_type or "未知",
        "matched_rules": rule_data.get('matched_rules', [])
    }
    
    package_dict = build_evidence_package(formatted_phages, formatted_cases, query_context)

    # 持久化
    package_id = persist_evidence_package(package_dict, query_context)
    package_dict["_package_id"] = package_id

    return package_dict


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
    
    package = build_evidence_package_from_db(
        species=case_data['species'],
        resistance=case_data['resistance'],
        infection_type=case_data['infection_type']
    )
    
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
    
    if any(rule.get('rule_id') == 'RULE_ECOLI_O25' for rule in case_data.get('rules', [])):
        package["_verification"]["rule_cited"] = "O25" in lower or "48小时" in lower
    
    return package


# ==================== 规则引擎（无 LLM） ====================
def rule_based_evidence_package(
    species: str,
    strain_type: Optional[str] = None,
    resistance: Optional[str] = None,
    infection_type: Optional[str] = None,
    phage_limit: int = 20,
    case_limit: int = 5
) -> Dict:
    """
    纯规则引擎：同时检索互作路径和黄金规则路径。
    """
    with get_driver() as driver:
        raw_phages = find_matching_phages(driver, species, resistance, limit=phage_limit)
        raw_cases = find_similar_cases(driver, species, infection_type, limit=case_limit)

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

        # 检索并合并黄金规则
        rule_data = _retrieve_golden_rules(species, strain_type)
        matching_evidence = _merge_golden_rule_phages(matching_evidence, rule_data)

        # 排序：priority='high' 优先，然后按 evidence_level（L1-L5 数字越小越高）
        def sort_key(e):
            priority = e.get('priority', 'normal')
            level = e.get('evidence_level', 'L5')
            prob = e.get('infection_probability', 0) or 0
            if priority == 'high':
                return (0, 0, 1.0)  # 第一优先级
            level_order = {'L5': 1, 'L4': 2, 'L3': 3, 'L2': 4, 'L1': 5}
            return (1, level_order.get(level, 5), -prob)
        
        matching_evidence.sort(key=sort_key)

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

        total = len(matching_evidence)
        clinical_cnt = len(clinical_evidence)
        
        golden_phages = [e['phage_name'] for e in matching_evidence if e.get('priority') == 'high']
        validated_phages = [e['phage_name'] for e in matching_evidence if e.get('evidence_level') == 'L3']
        
        if golden_phages:
            explanation = (
                f"针对 {species}（{resistance or '未知耐药'}）引起的 {infection_type or '未知感染'}，"
                f"共检索到 {total} 个匹配噬菌体。其中 {', '.join(golden_phages)} 由经过临床验证的黄金规则推荐，证据排序较高。"
            )
        elif validated_phages:
            explanation = (
                f"针对 {species}（{resistance or '未知耐药'}）引起的 {infection_type or '未知感染'}，"
                f"共检索到 {total} 个匹配噬菌体。其中 {', '.join(validated_phages[:3])} 有临床病例验证，需领域专家进一步审核。"
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


# ==================== 持久化 Evidence Package ====================
def persist_evidence_package(package_dict: Dict, query_context: Dict) -> str:
    """
    将 Evidence Package 持久化为 ScientificEvidencePackage 节点，并建立所有必要关系。
    符合 PRD 5.4 节要求：
    - 字段完整（package_type, query_context, generated_by, model_used, prompt_version, 
      updated_at, review_status, schema_version）
    - 建立关系：USES_ASSAY, REFERENCES_CASE, CITES_SOURCE, INCLUDES_CANDIDATE
    - status 默认为 draft（DeepSeek 只生成 draft）
    """
    package_id = f"EP-{uuid.uuid4().hex[:8].upper()}"
    
    with get_driver() as driver:
        with driver.session() as session:
            # 1. 创建 ScientificEvidencePackage 节点（完整字段）
            session.run("""
                CREATE (p:ScientificEvidencePackage {
                    package_id: $package_id,
                    package_type: 'evidence_summary',
                    query_context: $query_context,
                    status: 'draft',
                    generated_by: $generated_by,
                    model_used: $model_used,
                    prompt_version: $prompt_version,
                    created_at: datetime(),
                    updated_at: datetime(),
                    review_status: 'pending',
                    summary: $summary,
                    limitations: $limitations,
                    schema_version: '1.0.0'
                })
            """,
            package_id=package_id,
            query_context=json.dumps(query_context, ensure_ascii=False, default=str),
            generated_by=query_context.get('generated_by', 'system'),
            model_used=query_context.get('model_used', 'deepseek-v3'),
            prompt_version=query_context.get('prompt_version', 'v1.0'),
            summary=package_dict.get('explanation', ''),
            limitations='需人工进一步确认')

            # 2. 建立 INCLUDES_CANDIDATE → Phage 关系
            for item in package_dict.get('matching_evidence', []):
                phage_name = item.get('phage_name')
                if phage_name:
                    session.run("""
                        MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
                        MATCH (ph:Phage {name: $phage_name})
                        CREATE (pkg)-[:INCLUDES_CANDIDATE]->(ph)
                    """, package_id=package_id, phage_name=phage_name)

            # 3. 建立 USES_ASSAY → LysisAssay 关系
            # 从 matching_evidence 中提取 assay_id（如果有）
            for item in package_dict.get('matching_evidence', []):
                assay_id = item.get('assay_id')
                if assay_id:
                    session.run("""
                        MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
                        MATCH (a:LysisAssay {assay_id: $assay_id})
                        CREATE (pkg)-[:USES_ASSAY]->(a)
                    """, package_id=package_id, assay_id=assay_id)

            # 4. 建立 REFERENCES_CASE → ClinicalCase 关系
            for case in package_dict.get('clinical_evidence', []):
                case_id = case.get('case_id')
                if case_id:
                    session.run("""
                        MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
                        MATCH (c:ClinicalCase {case_id: $case_id})
                        CREATE (pkg)-[:REFERENCES_CASE]->(c)
                    """, package_id=package_id, case_id=case_id)

            # 5. 建立 CITES_SOURCE → SourceArtifact 关系
            # 从 matching_evidence 的 evidence_ref 中提取来源
            source_refs = set()
            for item in package_dict.get('matching_evidence', []):
                for ref in item.get('evidence_ref', []):
                    if ref and str(ref).strip():
                        source_refs.add(ref.strip())
            
            for ref in source_refs:
                # 尝试匹配 SourceArtifact（通过 title 或 source_id 模糊匹配）
                session.run("""
                    MATCH (pkg:ScientificEvidencePackage {package_id: $package_id})
                    MATCH (s:SourceArtifact)
                    WHERE s.title CONTAINS $ref OR s.source_id CONTAINS $ref
                    CREATE (pkg)-[:CITES_SOURCE]->(s)
                """, package_id=package_id, ref=ref)

    return package_id