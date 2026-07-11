from typing import List, Dict
import json
import requests
from config import Config

SYSTEM_PROMPT = """你是一个精准抗感染领域的循证助手。
你的职责是组织已有的检索结果，不是创造新知识。
你只使用下面提供的检索结果，不添加任何未在检索结果中出现的信息。
对于缺失的信息，标注"需人工进一步确认"。
不做治疗推荐。
输出严格的 JSON 格式。"""

def build_evidence_package(
    matching_phages: List[Dict],
    similar_cases: List[Dict],
    query_context: Dict  # {species, resistance, infection_type, ...}
) -> Dict:
    """
    调用 DeepSeek API 组织 Evidence Package。
    返回 JSON 格式的 dict。
    """
    # 构造用户输入
    user_prompt = f"""
查询上下文：
- 病原菌: {query_context.get('species')}
- 耐药机制: {query_context.get('resistance')}
- 感染类型: {query_context.get('infection_type')}

匹配到的噬菌体（Matching Evidence）：
{json.dumps(matching_phages, ensure_ascii=False, indent=2)}

相似历史病例（Clinical Evidence）：
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
"""
    
    headers = {
        "Authorization": f"Bearer {Config.DS_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": Config.DS_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": Config.DS_TEMPERATURE,
        "max_tokens": Config.DS_MAX_TOKENS,
        "response_format": {"type": "json_object"}
    }
    
    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # fallback: 返回原始文本
        return {"raw_output": content, "parse_error": True}