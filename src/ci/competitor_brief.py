# src/ci/competitor_brief.py
from typing import Dict, Optional
from neo4j import Driver
from datetime import datetime
from src.ci.competitor_profile import build_competitor_profile
from src.ci.organization_service import detect_material_changes

def generate_competitor_brief(
    driver: Driver,
    organization_id: str,
    days_back: int = 90,
    include_all_programs: bool = True
) -> Dict:
    """
    PRD 16.1: 生成竞争者情报简报（Competitor Intelligence Brief）
    整合档案、变化检测和评估，输出结构化 JSON
    """
    # 1. 获取档案
    profile = build_competitor_profile(driver, organization_id)
    if "error" in profile:
        return profile
    
    # 2. 获取变化检测
    changes = detect_material_changes(driver, organization_id, days_back=days_back)
    
    # 3. 生成简报
    brief = {
        "brief_type": "competitor",
        "as_of_date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "organization": {
            "id": profile["organization"]["id"],
            "name": profile["organization"]["name"],
            "type": profile["organization"]["org_type"],
            "country": profile["organization"]["country"],
            "website": profile["organization"]["website"],
            "description": profile["organization"]["description"],
            "status": profile["organization"]["status"],
            "public_or_private": profile["organization"]["public_private"]
        },
        "active_programs": [],
        "recent_events": [],
        "competitive_assessment": {
            "opportunities": [],
            "threats": [],
            "uncertainties": []
        },
        "changes_summary": {
            "new_events": changes.get("total_new_events", 0),
            "new_programs": changes.get("total_new_programs", 0),
            "status_changes": changes.get("total_status_changes", 0),
            "high_impact_events": changes.get("total_high_impact_events", 0)
        },
        "data_gaps": profile.get("data_gaps", []),
        "recommended_next_steps": [],
        "citations": [],
        "review_status": "pending"
    }
    
    # 4. 填充项目信息（带病原体）
    for prog in profile.get("active_programs", []):
        pathogens = [p["species"] for p in prog.get("target_pathogens", []) if p.get("species")]
        brief["active_programs"].append({
            "name": prog["name"],
            "stage": prog.get("stage", "unknown"),
            "status": prog.get("status", "active"),
            "modality": prog.get("modality", "unknown"),
            "target_pathogens": pathogens,
            "program_type": prog.get("program_type", "unknown")
        })
    
    # 5. 填充事件信息
    for evt in profile.get("recent_events", [])[:10]:  # 最多10条
        brief["recent_events"].append({
            "date": evt.get("event_date"),
            "type": evt.get("event_type"),
            "title": evt.get("title"),
            "summary": evt.get("summary"),
            "confidence": evt.get("confidence", "medium"),
            "materiality": evt.get("materiality", "medium"),
            "affected_program": evt.get("affected_program")
        })
    
    # 6. 生成竞争评估（基于事件和项目）
    if changes.get("total_high_impact_events", 0) > 0:
        brief["competitive_assessment"]["threats"].append(
            f"近期有 {changes['total_high_impact_events']} 个高影响事件，需关注其战略影响"
        )
    
    if len(profile.get("active_programs", [])) == 0:
        brief["competitive_assessment"]["opportunities"].append(
            "该组织无公开研发管线，可能为非竞争性或早期阶段"
        )
    elif len(profile.get("active_programs", [])) <= 2:
        brief["competitive_assessment"]["uncertainties"].append(
            "管线较窄，产品或技术集中度较高，可能对特定靶点依赖性强"
        )
    
    if not profile.get("target_pathogens"):
        brief["data_gaps"].append("未明确该组织靶向的病原体谱")
    
    # 7. 推荐下一步
    if changes.get("has_material_change", False):
        brief["recommended_next_steps"].append("建议跟进近期重大事件，评估对内部战略的影响")
    if profile.get("data_gaps"):
        brief["recommended_next_steps"].append("补充数据缺口，完善竞争对手档案")
    
    return brief


def generate_technology_brief(
    driver: Driver,
    strategy_id: Optional[str] = None,
    construct_id: Optional[str] = None
) -> Dict:
    """
    PRD 16.2: 生成技术简报（Technology Brief）
    整合工程策略、构建体、主张和结果
    """
    # TODO: 下一阶段实现
    return {"message": "Technology Brief - 待实现"}