import json
from datetime import datetime

def safe_json_dumps(obj, indent=2):
    """安全的 JSON 序列化，处理 datetime 等类型"""
    def default_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, indent=indent, default=default_serializer)

def print_evidence_package(pkg: Dict):
    """在 Jupyter 中美化打印 Evidence Package"""
    from IPython.display import display, Markdown
    
    display(Markdown("## 🧬 Matching Evidence"))
    for item in pkg.get("matching_evidence", []):
        display(Markdown(f"- **{item.get('phage_name')}** (L{item.get('evidence_level')}): {item.get('infection_result')}, 概率 {item.get('infection_probability')}"))
    
    display(Markdown("## 📋 Clinical Evidence"))
    for item in pkg.get("clinical_evidence", []):
        display(Markdown(f"- **{item.get('case_id')}**: {item.get('phage_treatment')} → {item.get('clinical_outcome')}"))
    
    display(Markdown("## 💡 Explanation"))
    display(Markdown(pkg.get("explanation", "无解释")))