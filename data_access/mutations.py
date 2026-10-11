# data_access/mutations.py
"""
Dash 前端写入层。
- 页面里禁止直接 CREATE
- 所有写入走 src/ 的服务函数
- 所有 ID 由后端生成
"""
from config import get_driver

from src.ci.organization_service import create_organization
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event
from src.engineering_intelligence.strategy_classifier import create_engineering_strategy
from src.decision_support.decision_record import create_decision_record
from src.shared.evidence_source import create_source_artifact
from src.shared.review import create_review


def add_event(*, event_type, title, factual_summary, organization_id,
              program_id=None, event_date=None, published_at=None,
              source_url=None, actor_id="dash_frontend"):
    src_ids = []
    if source_url:
        sid = create_source_artifact(
            get_driver(),
            source_type="url_scrape",
            title=title[:120],
            url=source_url,
            published_date=event_date or "unknown",
            credibility_tier="secondary",
            actor_id=actor_id,
        )
        src_ids.append(sid)
    return capture_intelligence_event(
        get_driver(),
        event_type=event_type, title=title,
        factual_summary=factual_summary,
        organization_id=organization_id,
        program_id=program_id,
        event_date=event_date, published_at=published_at,
        source_ids=src_ids, actor_id=actor_id,
    )


def add_program(*, organization_id, canonical_name,
                program_type="therapeutic",
                development_stage="discovery", modality=None,
                target_pathogen_species=None, actor_id="dash_frontend"):
    return create_development_program(
        get_driver(),
        organization_id=organization_id,
        canonical_name=canonical_name,
        program_type=program_type,
        development_stage=development_stage,
        modality=modality,
        target_pathogen_species=target_pathogen_species or [],
        actor_id=actor_id,
    )


def add_strategy(*, strategy_type, description="",
                 evidence_maturity="conceptual", actor_id="dash_frontend"):
    return create_engineering_strategy(
        get_driver(),
        strategy_type=strategy_type,
        description=description,
        evidence_maturity=evidence_maturity,
        actor_id=actor_id,
    )


def add_decision_record(*, brief_id, decision_type, decision_summary,
                        rationale, decision_owner, review_date=None,
                        actor_id="dash_frontend"):
    return create_decision_record(
        get_driver(),
        brief_id=brief_id,
        decision_type=decision_type,
        decision_summary=decision_summary,
        rationale=rationale,
        decision_owner=decision_owner,
        review_date=review_date,
        actor_id=actor_id,
    )


def approve_brief(*, brief_id, reviewer_id, comment=""):
    return create_review(
        get_driver(),
        review_type="intelligence_product_review",
        target_object_type="IntelligenceProduct",
        target_object_id=brief_id,
        reviewer_id=reviewer_id,
        decision="approved", comment=comment,
        update_target_status=True,
        actor_id="dash_frontend",
    )