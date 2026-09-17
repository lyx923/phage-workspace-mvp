# pages/ci.py
import streamlit as st
import pandas as pd
import json
import re
import pathlib
import requests
from urllib.parse import urlparse, quote, urlencode
from typing import Optional
from openai import OpenAI
from config import get_driver, Config
from src.shared.audit_service import write_audit_event

# CI 相关导入
from src.ci.organization_service import create_organization
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event
from src.shared.source_artifact_service import create_source_artifact
from src.ci.competitor_profile import build_competitor_profile, list_organizations
from src.ci.competitor_brief import generate_competitor_brief
from src.shared.review import create_review
from src.decision_support.decision_record import create_decision_record
from src.ci.use_event_service import record_intelligence_use
from src.engineering_intelligence.strategy_classifier import create_engineering_strategy
from src.engineering_intelligence.construct_service import create_engineered_construct, link_program_to_construct
from src.engineering_intelligence.claim_extractor import (
    create_technical_claim, create_technical_result)
from src.engineering_intelligence.technology_assessment import (
    create_technology_assessment)
from src.ci.competitor_assessment import create_competitor_assessment


@st.cache_resource
def get_db():
    return get_driver()

driver = get_db()


# ============================================================
# 情报抓取辅助函数
# ============================================================

def _fetch_url_content(url: str, timeout: int = 20) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or r.encoding
    html = r.text

    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    html = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)

    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&quot;", '"').replace("&#39;", "'")
                .replace("&lt;", "<").replace("&gt;", ">"))
    text = re.sub(r"\s+", " ", text).strip()

    return {"title": title, "text": text, "url": url}


_EXTRACT_SYSTEM_PROMPT = """你是竞争情报抽取助手。请从给定网页文本中抽取结构化信息，输出严格的 JSON。

严禁编造：只抽取文本中明确出现的信息，无法确定的字段填空字符串或空数组。
输出必须是合法 JSON，不要任何 Markdown 代码块标记。
重要：控制输出规模，宁可少而精，避免超长输出导致被截断。"""

_EXTRACT_USER_TEMPLATE = """网页 URL：{url}
网页标题：{title}

网页正文：
{content}

请按以下 JSON 结构输出抽取结果：

{{
  "organizations": [
    {{
      "canonical_name": "公司/机构/院校名称",
      "organization_type": "biotech/pharma/academic/CRO/tech/food_safety/other",
      "aliases": ["常见别名/缩写"],
      "headquarters_country": "总部国家",
      "website": "官网 URL",
      "description": "一句话描述该机构"
    }}
  ],
  "programs": [
    {{
      "canonical_name": "研发项目/产品管线名称",
      "organization_name": "所属机构名称（需与上面 organizations 保持一致）",
      "program_type": "therapeutic/diagnostic/platform/research/food_safety",
      "development_stage": "discovery/preclinical/phase_1/phase_1_2/phase_2/phase_2b/phase_3/commercial",
      "modality": "natural_phage/engineered_phage/cocktail/software",
      "target_pathogen_species": ["靶向病原菌物种（如 Klebsiella pneumoniae）"]
    }}
  ],
  "events": [
    {{
      "event_type": "regulatory_update/funding/acquisition/merger/partnership/clinical_trial_update/publication/patent_event/pipeline_update",
      "title": "事件标题（简洁，不超过 40 字）",
      "factual_summary": "事实摘要（不超过 150 字），只陈述原文事实，不加推断",
      "organization_name": "所属机构名称",
      "program_name": "关联项目（若无填空字符串）",
      "event_date": "YYYY-MM-DD",
      "published_at": "YYYY-MM-DD",
      "source_url": "该事件的原始来源 URL（若原文中明确给出，否则填空字符串）"
    }}
  ]
}}

规则：
- event_type 必须从枚举中选一个最接近的
- 日期统一为 YYYY-MM-DD；只有年月就用当月 1 日；只有年就用 1 月 1 日
- organizations 至少包含 events 里出现的全部机构名称
- ★ source_url 只填正文里明确出现的原文链接，不要编造
- 若无信息，返回空数组
- ★ 输出规模上限：organizations ≤ 8，programs ≤ 8，events ≤ 12（超出则优先保留最相关）
- ★ 每条字段尽量简短，不要复制原文长段落
- 只输出 JSON，不要任何解释文字
"""


def _repair_json(s: str) -> Optional[dict]:
    if not s or not s.strip():
        return None
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    max_trim = min(1500, len(s) - 10)
    for trim in range(0, max_trim):
        candidate = s if trim == 0 else s[:-trim]
        candidate = candidate.rstrip()
        while candidate and candidate[-1] in ",:":
            candidate = candidate[:-1].rstrip()
        in_string = False
        escaped = False
        for ch in candidate:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
        if in_string:
            candidate += '"'
        open_brackets = candidate.count("[") - candidate.count("]")
        open_braces = candidate.count("{") - candidate.count("}")
        if open_brackets < 0 or open_braces < 0:
            continue
        candidate = candidate + ("]" * open_brackets) + ("}" * open_braces)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _extract_with_llm(url: str, title: str, content: str, max_chars: int = 5000) -> dict:
    client = OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)
    content_slice = content[:max_chars]
    user_prompt = _EXTRACT_USER_TEMPLATE.format(
        url=url, title=title, content=content_slice
    )
    resp = client.chat.completions.create(
        model=Config.DS_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e1:
        repaired = _repair_json(raw)
        if repaired is not None:
            repaired["_repaired"] = True
            return repaired
        return {
            "organizations": [],
            "programs": [],
            "events": [],
            "_parse_error": str(e1),
            "_raw_snippet": raw[-500:] if raw else "",
        }


def _find_org_exact(name: str, url: str = None):
    if not name and not url:
        return None
    name_norm = (name or "").strip().lower()
    with driver.session() as s:
        if name_norm:
            r = s.run("""
                MATCH (o:Organization)
                WHERE toLower(o.canonical_name) = $name
                   OR ANY(alias IN o.aliases WHERE toLower(alias) = $name)
                RETURN o.organization_id AS id
                LIMIT 1
            """, name=name_norm).single()
            if r:
                return r["id"]
        if url:
            try:
                host = urlparse(url).netloc.lower()
                host = host[4:] if host.startswith("www.") else host
                if host:
                    r = s.run("""
                        MATCH (o:Organization)
                        WHERE o.website IS NOT NULL
                          AND toLower(o.website) CONTAINS $host
                        RETURN o.organization_id AS id
                        LIMIT 1
                    """, host=host).single()
                    if r:
                        return r["id"]
            except Exception:
                pass
    return None


def _find_program_exact(name: str):
    if not name:
        return None
    with driver.session() as s:
        r = s.run("""
            MATCH (d:DevelopmentProgram)
            WHERE toLower(d.canonical_name) = toLower($name)
            RETURN d.program_id AS id
            LIMIT 1
        """, name=name.strip()).single()
        return r["id"] if r else None


def _check_org_status(name: str, url: str = None) -> tuple:
    if not name and not url:
        return ("empty", "")
    oid = _find_org_exact(name, url=url)
    if not oid:
        return ("new", "")
    with driver.session() as s:
        r = s.run("""
            MATCH (o:Organization {organization_id: $id})
            RETURN o.canonical_name AS n
        """, id=oid).single()
        return ("existing", (r["n"] if r else name))


def _check_program_status(name: str) -> tuple:
    if not name:
        return ("empty", "")
    pid = _find_program_exact(name)
    if not pid:
        return ("new", "")
    with driver.session() as s:
        r = s.run("""
            MATCH (d:DevelopmentProgram {program_id: $id})
            RETURN d.canonical_name AS n
        """, id=pid).single()
        return ("existing", (r["n"] if r else name))


def _check_event_status(org_name: str, title: str, event_date: str, url: str = None) -> tuple:
    if not org_name or not title:
        return ("empty", "")
    oid = _find_org_exact(org_name, url=url)
    if not oid:
        return ("org_missing", "")
    with driver.session() as s:
        r = s.run("""
            MATCH (e:IntelligenceEvent {organization_id: $oid})
            WHERE toLower(e.title) = toLower($title)
              AND COALESCE(e.event_date, '') = $date
            RETURN e.event_id AS id
            LIMIT 1
        """, oid=oid, title=title, date=event_date or "").single()
        if r:
            return ("existing", r["id"])
    return ("new", "")


def _status_emoji(status: str) -> str:
    return {
        "new": "🆕 新增",
        "existing": "♻️ 已存在",
        "org_missing": "⚠️ 组织缺失",
        "empty": "—",
    }.get(status, status)


def _norm_list_to_str(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x)
    return str(v) if v else ""


def _str_to_list(s: str) -> list:
    if not s:
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _commit_scraped_data(url: str, orgs, progs, events) -> dict:
    stats = {
        "org_created": 0, "org_reused": 0,
        "prog_created": 0, "prog_reused": 0,
        "event_created": 0, "event_skipped": 0, "event_failed": 0,
        "errors": [],
    }
    org_id_map = {}

    for org in orgs:
        name = (org.get("canonical_name") or "").strip()
        if not name:
            continue
        existing = _find_org_exact(name, url=url)
        if existing:
            org_id_map[name] = existing
            stats["org_reused"] += 1
            continue
        try:
            oid = create_organization(
                driver,
                canonical_name=name,
                organization_type=org.get("organization_type") or "biotech",
                aliases=_str_to_list(org.get("aliases", "")),
                headquarters_country=(org.get("headquarters_country") or "").strip() or None,
                website=(org.get("website") or "").strip() or None,
                description=(org.get("description") or "").strip() or None,
                actor_id="url_scraper",
            )
            org_id_map[name] = oid
            stats["org_created"] += 1
        except Exception as e:
            stats["errors"].append(f"组织 '{name}' 创建失败：{e}")

    for evt in events:
        oname = (evt.get("organization_name") or "").strip()
        if oname and oname not in org_id_map:
            existing = _find_org_exact(oname, url=url)
            if existing:
                org_id_map[oname] = existing
            else:
                try:
                    oid = create_organization(
                        driver, canonical_name=oname,
                        organization_type="biotech", aliases=[],
                        actor_id="url_scraper",
                    )
                    org_id_map[oname] = oid
                    stats["org_created"] += 1
                except Exception as e:
                    stats["errors"].append(f"自动补建组织 '{oname}' 失败：{e}")

    for prog in progs:
        pname = (prog.get("canonical_name") or "").strip()
        oname = (prog.get("organization_name") or "").strip()
        if not pname or not oname:
            continue
        oid = org_id_map.get(oname) or _find_org_exact(oname, url=url)
        if not oid:
            stats["errors"].append(f"项目 '{pname}' 所属组织 '{oname}' 未找到")
            continue
        if _find_program_exact(pname):
            stats["prog_reused"] += 1
            continue
        try:
            create_development_program(
                driver,
                organization_id=oid,
                canonical_name=pname,
                program_type=prog.get("program_type") or "therapeutic",
                development_stage=prog.get("development_stage") or "discovery",
                modality=(prog.get("modality") or "").strip() or None,
                target_pathogen_species=_str_to_list(prog.get("target_pathogen_species", "")),
                actor_id="url_scraper",
            )
            stats["prog_created"] += 1
        except Exception as e:
            stats["errors"].append(f"项目 '{pname}' 创建失败：{e}")

    for evt in events:
        oname = (evt.get("organization_name") or "").strip()
        if not oname:
            continue
        oid = org_id_map.get(oname) or _find_org_exact(oname, url=url)
        if not oid:
            stats["event_failed"] += 1
            stats["errors"].append(f"事件 '{evt.get('title','')}' 所属组织 '{oname}' 未找到")
            continue

        pname = (evt.get("program_name") or "").strip()
        pid = _find_program_exact(pname) if pname else None

        source_ids = []
        try:
            src_id = create_source_artifact(
                driver, source_type="url_scrape",
                title=(evt.get("title") or "URL 抓取")[:120],
                url=url,
                published_date=(evt.get("published_at") or evt.get("event_date") or "unknown"),
                credibility_tier="secondary", actor_id="url_scraper",
            )
            source_ids.append(src_id)
        except Exception:
            pass

        try:
            capture_intelligence_event(
                driver,
                event_type=evt.get("event_type") or "publication",
                title=evt.get("title") or "",
                factual_summary=evt.get("factual_summary") or "",
                organization_id=oid,
                program_id=pid,
                event_date=evt.get("event_date") or None,
                published_at=evt.get("published_at") or None,
                source_ids=source_ids,
                actor_id="url_scraper",
            )
            stats["event_created"] += 1
        except ValueError as e:
            if "重复" in str(e) or "已存在" in str(e):
                stats["event_skipped"] += 1
            else:
                stats["event_failed"] += 1
                stats["errors"].append(f"事件 '{evt.get('title','')}'：{e}")
        except Exception as e:
            stats["event_failed"] += 1
            stats["errors"].append(f"事件 '{evt.get('title','')}' 写入失败：{e}")

    return stats


# ============================================================
# 监控中心辅助函数
# ============================================================

_PENDING_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "monitor_pending.json"


def _save_pending(data):
    try:
        _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            if _PENDING_FILE.exists():
                _PENDING_FILE.unlink()
        else:
            with open(_PENDING_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def _load_pending():
    try:
        if _PENDING_FILE.exists():
            with open(_PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _build_review_df(items, kind):
    rows = []
    for it in items:
        if kind == "org":
            rows.append({
                "选择": True,
                "名称": it.get("canonical_name", ""),
                "类型": it.get("organization_type", "biotech"),
                "别名": _norm_list_to_str(it.get("aliases", [])),
                "国家": it.get("headquarters_country", ""),
                "官网": it.get("website", ""),
                "描述": it.get("description", ""),
                "_source": it.get("_source_label", ""),
            })
        elif kind == "prog":
            rows.append({
                "选择": True,
                "项目名称": it.get("canonical_name", ""),
                "所属组织": it.get("organization_name", ""),
                "类型": it.get("program_type", "therapeutic"),
                "阶段": it.get("development_stage", "discovery"),
                "模态": it.get("modality", ""),
                "靶向病原": _norm_list_to_str(it.get("target_pathogen_species", [])),
                "_source": it.get("_source_label", ""),
            })
        elif kind == "evt":
            src_url = it.get("_source_url") or it.get("source_url") or ""
            rows.append({
                "选择": True,
                "事件类型": it.get("event_type", "publication"),
                "标题": it.get("title", ""),
                "事实摘要": it.get("factual_summary", ""),
                "所属组织": it.get("organization_name", ""),
                "关联项目": it.get("program_name", ""),
                "事件日期": it.get("event_date", ""),
                "发布日期": it.get("published_at", ""),
                "_source": it.get("_source_label", ""),
                "source_url": src_url,
            })
    return pd.DataFrame(rows)


def _org_col_config():
    return {
        "选择": st.column_config.CheckboxColumn("✓", width="small"),
        "名称": st.column_config.TextColumn("名称", required=True, width="medium"),
        "类型": st.column_config.SelectboxColumn(
            "类型", width="small",
            options=["biotech", "pharma", "academic", "CRO", "tech", "food_safety", "other"]
        ),
        "别名": st.column_config.TextColumn("别名", width="small"),
        "国家": st.column_config.TextColumn("国家", width="small"),
        "官网": st.column_config.TextColumn("官网", width="medium"),
        "描述": st.column_config.TextColumn("描述", width="large"),
        "_source": st.column_config.TextColumn("来源", width="small", disabled=True),
    }


def _prog_col_config():
    return {
        "选择": st.column_config.CheckboxColumn("✓", width="small"),
        "项目名称": st.column_config.TextColumn("项目名称", required=True, width="medium"),
        "所属组织": st.column_config.TextColumn("所属组织", required=True, width="medium"),
        "类型": st.column_config.SelectboxColumn(
            "类型", width="small",
            options=["therapeutic", "diagnostic", "platform", "research", "food_safety"]
        ),
        "阶段": st.column_config.SelectboxColumn(
            "阶段", width="small",
            options=["discovery", "preclinical", "phase_1", "phase_1_2",
                     "phase_2", "phase_2b", "phase_3", "commercial"]
        ),
        "模态": st.column_config.TextColumn("模态", width="small"),
        "靶向病原": st.column_config.TextColumn("靶向病原", width="medium"),
        "_source": st.column_config.TextColumn("来源", width="small", disabled=True),
    }


def _evt_col_config():
    return {
        "选择": st.column_config.CheckboxColumn("✓", width="small"),
        "事件类型": st.column_config.SelectboxColumn(
            "类型", required=True, width="small",
            options=["regulatory_update", "funding", "acquisition", "merger",
                     "partnership", "clinical_trial_update", "publication",
                     "patent_event", "pipeline_update"]
        ),
        "标题": st.column_config.TextColumn("标题", required=True, width="large"),
        "事实摘要": st.column_config.TextColumn("摘要", width="large"),
        "所属组织": st.column_config.TextColumn("所属组织", required=True, width="medium"),
        "关联项目": st.column_config.TextColumn("关联项目", width="medium"),
        "事件日期": st.column_config.TextColumn("事件日期", width="small"),
        "发布日期": st.column_config.TextColumn("发布日期", width="small"),
        "_source": st.column_config.TextColumn("来源", width="small", disabled=True),
        "source_url": st.column_config.LinkColumn(
            "source_url", width="medium", display_text="打开来源"
        ),
    }


def _df_to_records(df, original_list, kind):
    if df is None or len(df) == 0:
        return []

    def _key(it, k):
        if k in ("org", "prog"):
            return it.get("canonical_name", "")
        if k == "evt":
            return (it.get("organization_name", ""), it.get("title", ""))
        return ""

    meta_map = {}
    for it in original_list:
        meta_map[_key(it, kind)] = {
            "_source_url": it.get("_source_url", ""),
            "_source_label": it.get("_source_label", ""),
            "_owner_org_id": it.get("_owner_org_id", ""),
        }

    records = []
    for _, row in df.iterrows():
        rec = row.to_dict()
        selected = bool(rec.pop("选择", False))

        if kind == "org":
            k = rec.get("名称", "")
        elif kind == "prog":
            k = rec.get("项目名称", "")
        else:
            k = (rec.get("所属组织", ""), rec.get("标题", ""))

        meta = meta_map.get(k, {})

        if kind == "org":
            out = {
                "canonical_name": rec.get("名称", ""),
                "organization_type": rec.get("类型", "biotech"),
                "aliases": rec.get("别名", ""),
                "headquarters_country": rec.get("国家", ""),
                "website": rec.get("官网", ""),
                "description": rec.get("描述", ""),
                "_selected": selected,
                **meta,
            }
        elif kind == "prog":
            out = {
                "canonical_name": rec.get("项目名称", ""),
                "organization_name": rec.get("所属组织", ""),
                "program_type": rec.get("类型", "therapeutic"),
                "development_stage": rec.get("阶段", "discovery"),
                "modality": rec.get("模态", ""),
                "target_pathogen_species": rec.get("靶向病原", ""),
                "_selected": selected,
                **meta,
            }
        else:
            out = {
                "event_type": rec.get("事件类型", "publication"),
                "title": rec.get("标题", ""),
                "factual_summary": rec.get("事实摘要", ""),
                "organization_name": rec.get("所属组织", ""),
                "program_name": rec.get("关联项目", ""),
                "event_date": rec.get("事件日期", ""),
                "published_at": rec.get("发布日期", ""),
                "source_url": rec.get("source_url", ""),
                "_selected": selected,
                **meta,
            }
        records.append(out)
    return records


def _strip_internal(rec, kind):
    return {k: v for k, v in rec.items()
            if k not in ("_selected", "_source_url", "_source_label", "_owner_org_id")}


def _apply_reviewed(driver, sel_orgs, sel_progs, sel_events, prior_errors):
    source_url = ""
    for r in (sel_orgs + sel_progs + sel_events):
        if r.get("_source_url"):
            source_url = r["_source_url"]
            break

    stats = _commit_scraped_data(
        url=source_url,
        orgs=sel_orgs,
        progs=sel_progs,
        events=sel_events,
    )
    if prior_errors:
        stats.setdefault("errors", []).extend(prior_errors)
    return stats


# ============================================================
# 主函数
# ============================================================
def ci_mode(driver):
    st.markdown("""
    <style>
    .ci-main-title { font-size: 1.8rem; font-weight: 700; color: #0f172a; margin-bottom: 0.2rem; }
    .ci-subtitle { color: #64748b; margin-bottom: 1.5rem; }
    .ci-step-header { font-size: 1.2rem; font-weight: 600; color: #1e293b; display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
    .ci-step-number { display: inline-flex; align-items: center; justify-content: center; background: #0068c9; color: white; border-radius: 50%; width: 28px; height: 28px; font-size: 0.9rem; font-weight: 700; flex-shrink: 0; }
    .ci-badge { background: #eef2ff; color: #1e40af; border-radius: 20px; padding: 0.15rem 0.75rem; font-size: 0.75rem; font-weight: 500; }
    .ci-metric-box { background: #f8fafc; border-radius: 8px; padding: 0.8rem 1rem; text-align: center; border: 1px solid #e9edf2; }
    .ci-metric-box .number { font-size: 1.6rem; font-weight: 700; color: #0f172a; line-height: 1.2; }
    .ci-metric-box .label { font-size: 0.8rem; color: #64748b; margin-top: 0.15rem; }
    </style>
    """, unsafe_allow_html=True)

    if "ci_step" not in st.session_state:
        st.session_state.ci_step = 0
    if "ci_context" not in st.session_state:
        st.session_state.ci_context = {
            "org_ids": {}, "program_ids": {}, "source_ids": {}, "event_ids": {},
            "strategy_ids": {}, "construct_ids": {}, "claim_ids": {}, "result_ids": {},
            "brief_ids": [], "decision_ids": [], "use_event_ids": [],
            "current_org_id": None, "current_program_id": None, "current_brief_id": None,
            "technology_assessment_id": None, "temp_events": [],
            "created_objects": {"organization": None, "program": None, "sources": [], "events": []}
        }
    if "ci_step_status" not in st.session_state:
        st.session_state.ci_step_status = {f"step{i+1}_done": False for i in range(6)}
    if "ci_step6_results" not in st.session_state:
        st.session_state["ci_step6_results"] = None
    if "scrape_result" not in st.session_state:
        st.session_state.scrape_result = None
    if "scrape_raw" not in st.session_state:
        st.session_state.scrape_raw = None
    if "scrape_url" not in st.session_state:
        st.session_state.scrape_url = ""

    ci_tab0, ci_tab1, ci_tab2, ci_tab3, ci_tab4 = st.tabs([
        "📊 决策链图", "📋 情报流程", "🔍 情报查询", "📡 情报抓取", "🎯 监控中心"
    ])

    # ========== Tab0: 决策链图 ==========
    with ci_tab0:
        st.markdown("### 🧭 情报与决策 Ontology 链路")
        st.caption("下图展示了从情报源到组织决策的完整数据链路，包括市场情报与工程情报的融合。")
        mermaid_html = """
        <div class="mermaid">
        graph LR
            A[情报源<br>SourceArtifact] -->|HAS_SOURCE| B[情报事件<br>IntelligenceEvent]
            B -->|AFFECTS| C[开发项目<br>DevelopmentProgram]
            C -->|TARGETS_PATHOGEN| D[病原体<br>Pathogen]
            B -->|AFFECTS| E[组织<br>Organization]
            E -->|COVERS| F[简报<br>IntelligenceProduct]
            F -->|REVIEWS| G[审核<br>Review]
            G -->|BASED_ON| H[决策记录<br>DecisionRecord]
            H -->|CONSUMES| I[情报使用事件<br>IntelligenceUseEvent]
            C -.->|USES_CONSTRUCT| J[工程化构建体<br>EngineeredPhageConstruct]
            J -->|IMPLEMENTS| K[工程策略<br>EngineeringStrategy]
            J -.->|CLAIMS_ABOUT| L[技术主张<br>TechnicalClaim]
            J -.->|RESULT_FOR| M[技术结果<br>TechnicalResult]
            style A fill:#dbeafe,stroke:#2563eb
            style B fill:#fef3c7,stroke:#d97706
            style C fill:#e0e7ff,stroke:#4338ca
            style D fill:#fce7f3,stroke:#db2777
            style E fill:#d1fae5,stroke:#059669
            style F fill:#f3e8ff,stroke:#7c3aed
            style G fill:#fecaca,stroke:#dc2626
            style H fill:#c7d2fe,stroke:#4f46e5
            style I fill:#fef08a,stroke:#ca8a04
            style J fill:#d9f99d,stroke:#65a30d
            style K fill:#fde047,stroke:#ca8a04
            style L fill:#fca5a5,stroke:#dc2626
            style M fill:#93c5fd,stroke:#2563eb
        </div>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
            (function() {
                function initMermaid() {
                    if (typeof mermaid !== 'undefined') {
                        mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
                        mermaid.run();
                    } else { setTimeout(initMermaid, 300); }
                }
                if (document.readyState === 'complete') { initMermaid(); }
                else { window.addEventListener('load', initMermaid); }
            })();
        </script>
        """
        st.iframe(mermaid_html, height=330)
        st.caption("💡 实线表示主要链路，虚线表示可选关联（工程情报分支）。")

    # ========== Tab1: 情报流程 ==========
    with ci_tab1:
        step_names = ["创建组织/项目/事件", "工程策略与构建体", "技术主张与结果", "生成简报并审核", "情报消费", "归因验证"]
        step_status = [st.session_state.ci_step_status[f"step{i+1}_done"] for i in range(6)]
        cols = st.columns(len(step_names))
        for i, (name, done) in enumerate(zip(step_names, step_status)):
            with cols[i]:
                color = "#22c55e" if done else "#94a3b8"
                st.markdown(f"""
                <div style="text-align:center; padding:0.5rem; background: {'#dcfce7' if done else '#f1f5f9'}; border-radius:8px; border:1px solid {color};">
                    <div style="font-size:0.75rem; font-weight:600; color:{color};">步骤 {i+1}</div>
                    <div style="font-size:0.7rem; color:#475569;">{name}</div>
                    <div style="font-size:0.65rem; color:{color};">{'✅ 已完成' if done else '⏳ 待执行'}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        step = st.session_state.ci_step

        def go_to_step(n):
            st.session_state.ci_step = n
            st.rerun()

        if step == 0:
            with st.container(border=True):
                st.markdown("#### 🏢 步骤 1：创建组织、项目与情报事件")
                if st.session_state.ci_step_status.get("step1_done", False):
                    st.success("✅ 步骤1已完成，已创建以下对象：")
                    obj = st.session_state.ci_context.get("created_objects", {})
                    st.write(f"**组织**: {obj.get('organization', 'N/A')}")
                    st.write(f"**项目**: {obj.get('program', 'N/A')}")
                    if obj.get('sources'):
                        st.write(f"**来源**: {', '.join(obj['sources'])}")
                    if obj.get('events'):
                        st.write("**已创建的情报事件**:")
                        for evt in obj['events']:
                            st.write(f"  - {evt}")
                    st.markdown("---")
                    st.markdown("#### ➕ 添加更多情报事件")
                    with st.form("ci_step1_append_form"):
                        evt_type = st.selectbox("事件类型", ["regulatory_update", "funding", "acquisition", "partnership", "clinical_trial_update", "patent_event", "pipeline_update"])
                        evt_title = st.text_input("事件标题", value="New event")
                        evt_summary = st.text_area("事件摘要", value="详细描述...")
                        evt_date = st.date_input("事件日期", value=pd.to_datetime("2026-01-01"))
                        submitted_append = st.form_submit_button("➕ 添加此事件", width="stretch")
                    if submitted_append:
                        try:
                            with st.spinner("正在添加事件..."):
                                org_id = st.session_state.ci_context.get("current_org_id")
                                prog_id = st.session_state.ci_context.get("current_program_id")
                                if not org_id or not prog_id:
                                    st.error("缺少组织或项目ID，请重新执行步骤1")
                                else:
                                    src = create_source_artifact(driver, source_type="user_input", title=f"手动添加: {evt_title}", url="", published_date=evt_date.strftime("%Y-%m-%d"), credibility_tier="secondary", actor_id="test_user")
                                    evt_id = capture_intelligence_event(driver, event_type=evt_type, title=evt_title, factual_summary=evt_summary, organization_id=org_id, program_id=prog_id, event_date=evt_date.strftime("%Y-%m-%d"), published_at=evt_date.strftime("%Y-%m-%d"), source_ids=[src], actor_id="test_user")
                                    st.session_state.ci_context["created_objects"]["events"].append(f"{evt_id} ({evt_type})")
                                    st.success(f"✅ 事件 {evt_id} 已添加")
                                    st.rerun()
                        except Exception as e:
                            st.error(f"添加事件失败: {e}")
                    if st.button("➡️ 进入步骤 2（工程策略）", key="step1_continue"):
                        st.session_state.ci_step = 1
                        st.rerun()
                else:
                    existing = list_organizations(driver)
                    org_options = [""] + [f"{o['name']} ({o['id']})" for o in existing]
                    quick_org = st.selectbox("选择已有组织或（留空则新建）", options=org_options, key="ci_step1_quick_org")
                    selected_org_id = None
                    if quick_org and quick_org.strip():
                        parts = quick_org.split("(")
                        if len(parts) > 1:
                            selected_org_id = parts[1].rstrip(")")
                    prog_options_existing = []
                    if selected_org_id:
                        with driver.session() as session:
                            progs = session.run("""
                                MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
                                RETURN d.program_id AS id, d.canonical_name AS name
                                ORDER BY d.canonical_name
                            """, oid=selected_org_id)
                            prog_options_existing = [f"{r['name']} ({r['id']})" for r in progs]
                    quick_prog_options = [""] + prog_options_existing
                    quick_prog = st.selectbox("选择已有项目或（留空则新建）", options=quick_prog_options, key="ci_step1_quick_prog")
                    st.caption("💡 选择已有组织后，下方会自动列出该组织的项目供选择；若都不选，则按下方名称新建。")

                    with st.form("ci_step1_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            org_name = st.text_input("组织名称（新建时填写）", value="Proteon Pharmaceuticals")
                            org_type = st.selectbox("组织类型", ["biotech", "pharma", "academic", "CRO", "tech"])
                        with col2:
                            prog_name = st.text_input("项目名称（新建时填写）", value="BAFASAL")
                            prog_stage = st.selectbox("研发阶段", ["discovery", "preclinical", "phase_1", "phase_2", "phase_3", "commercial"])
                        st.markdown("---")
                        st.markdown("#### 📝 添加情报事件（可选，可多次添加）")
                        evt_type = st.selectbox("事件类型", ["regulatory_update", "funding", "acquisition", "partnership", "clinical_trial_update", "patent_event", "pipeline_update"], key="evt_type")
                        evt_title = st.text_input("事件标题", value="New event", key="evt_title")
                        evt_summary = st.text_area("事件摘要", value="详细描述...", key="evt_summary")
                        evt_date = st.date_input("事件日期", value=pd.to_datetime("2026-01-01"), key="evt_date")
                        add_clicked = st.form_submit_button("➕ 添加事件到列表", width="content")

                    if add_clicked:
                        temp_event = {"type": evt_type, "title": evt_title, "summary": evt_summary, "date": evt_date.strftime("%Y-%m-%d")}
                        st.session_state.ci_context["temp_events"].append(temp_event)
                        st.success(f"已添加事件: {evt_title}")
                        st.rerun()

                    if st.session_state.ci_context.get("temp_events"):
                        st.write("**已暂存的事件（待提交）:**")
                        for i, evt in enumerate(st.session_state.ci_context["temp_events"]):
                            st.write(f"  {i+1}. [{evt['type']}] {evt['title']} ({evt['date']})")
                    st.caption("💡 情报事件为可选，您可以直接提交而不添加任何事件。")

                    if st.button("🚀 提交并完成步骤1", width="stretch", type="primary"):
                        try:
                            with st.spinner("正在创建组织、项目及事件..."):
                                if quick_org and quick_org.strip():
                                    parts = quick_org.split("(")
                                    org_id = parts[1].rstrip(")") if len(parts) > 1 else None
                                else:
                                    org_id = None
                                if not org_id:
                                    with driver.session() as session:
                                        existing_org = session.run("MATCH (o:Organization {canonical_name: $name}) RETURN o.organization_id AS id", name=org_name).single()
                                        if existing_org:
                                            org_id = existing_org["id"]
                                            st.warning(f"组织 '{org_name}' 已存在，将复用该组织 (ID: {org_id})")
                                        else:
                                            org_id = create_organization(driver, canonical_name=org_name, organization_type=org_type, aliases=[org_name[:8]], headquarters_country="Poland", website=f"https://www.{org_name.lower().replace(' ','')}.com", description=f"{org_name} 是一家专注于噬菌体技术的生物技术公司。", actor_id="test_user")
                                            st.session_state.ci_context["org_ids"][org_name] = org_id
                                st.session_state.ci_context["current_org_id"] = org_id
                                with driver.session() as session:
                                    org_display = session.run("MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS name", oid=org_id).single()["name"]
                                prog_id = None
                                prog_display_name = None
                                if quick_prog and quick_prog.strip():
                                    parts = quick_prog.split("(")
                                    if len(parts) > 1:
                                        prog_id = parts[1].rstrip(")")
                                        prog_display_name = parts[0].strip()
                                if not prog_id:
                                    with driver.session() as session:
                                        existing_prog = session.run("""
                                            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram {canonical_name: $pname})
                                            RETURN d.program_id AS id
                                            """, pname=prog_name, oid=org_id).single()
                                        if existing_prog:
                                            prog_id = existing_prog["id"]
                                            prog_display_name = prog_name
                                            st.warning(f"项目 '{prog_name}' 已存在，将复用该项目 (ID: {prog_id})")
                                        else:
                                            prog_id = create_development_program(driver, organization_id=org_id, canonical_name=prog_name, program_type="therapeutic", development_stage=prog_stage, modality="cocktail", target_pathogen_species=["Salmonella enterica"], actor_id="test_user")
                                            prog_display_name = prog_name
                                st.session_state.ci_context["program_ids"][prog_display_name] = prog_id
                                st.session_state.ci_context["current_program_id"] = prog_id
                                created_events = []
                                created_sources = []
                                for evt in st.session_state.ci_context["temp_events"]:
                                    src = create_source_artifact(driver, source_type="user_input", title=f"手动添加: {evt['title']}", url="", published_date=evt['date'], credibility_tier="secondary", actor_id="test_user")
                                    created_sources.append(src)
                                    evt_id = capture_intelligence_event(driver, event_type=evt['type'], title=evt['title'], factual_summary=evt['summary'], organization_id=org_id, program_id=prog_id, event_date=evt['date'], published_at=evt['date'], source_ids=[src], actor_id="test_user")
                                    created_events.append(f"{evt_id} ({evt['type']})")
                                st.session_state.ci_context["created_objects"] = {
                                    "organization": f"{org_display} (ID: {org_id})",
                                    "program": f"{prog_display_name} (ID: {prog_id})",
                                    "sources": created_sources,
                                    "events": created_events
                                }
                                st.session_state.ci_context["temp_events"] = []
                                st.session_state.ci_step_status["step1_done"] = True
                                st.success(f"✅ 步骤1完成！已创建 {len(created_events)} 个事件。")
                                st.session_state.ci_step = 1
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ 执行失败：{e}")

        elif step == 1:
            with st.container(border=True):
                st.markdown("#### 🧬 步骤 2：创建工程策略与构建体")
                with st.form("ci_step2_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        strategy_type = st.selectbox("策略类型", ["host_range_expansion", "lysis_enhancement", "tail_fiber_engineering", "receptor_binding_engineering", "biofilm_disruption", "payload_delivery"])
                    with col2:
                        construct_name = st.text_input("构建体名称", value="vB_Kpn_HRE_001")
                    submitted = st.form_submit_button("🚀 执行步骤 2", width="stretch", type="primary")
                if submitted:
                    try:
                        with st.spinner("正在创建..."):
                            strategy_id = create_engineering_strategy(driver, strategy_type=strategy_type, description=f"{strategy_type} 策略描述", evidence_maturity="in_vitro", actor_id="test_user")
                            st.session_state.ci_context["strategy_ids"][strategy_type] = strategy_id
                            program_id = st.session_state.ci_context.get("current_program_id")
                            if not program_id:
                                st.error("未找到当前项目，请先执行步骤 1")
                                st.stop()
                            construct_id = create_engineered_construct(driver, public_name=construct_name, construct_code=construct_name.upper().replace("V","ENG"), parent_phage_name="PKP001", intended_effects=[f"{strategy_type} 效果"], target_pathogen_ids=["PATH-003"], strategy_ids=[strategy_id], construct_status="in_vitro_tested", first_public_date="2025-06-15", actor_id="test_user")
                            st.session_state.ci_context["construct_ids"][construct_name] = construct_id
                            link_program_to_construct(driver, program_id, construct_id, actor_id="test_user")
                            tech_assess_id = create_technology_assessment(driver, subject_type="construct", subject_id=construct_id, evidence_maturity="in_vitro", technical_relevance="high", translational_potential="medium", manufacturability_risk="medium", safety_uncertainty="low", ip_relevance="medium", internal_capability_gap="low", assessment_summary="该构建体展示了宿主范围扩展潜力，但可制造性和转化风险尚需进一步验证。", actor_id="test_user")
                            st.session_state.ci_context["technology_assessment_id"] = tech_assess_id
                            st.session_state.ci_step_status["step2_done"] = True
                            st.success("✅ 步骤 2 完成！已自动创建技术评估。")
                            go_to_step(2)
                    except Exception as e:
                        st.error(f"❌ 执行失败：{e}")

        elif step == 2:
            with st.container(border=True):
                st.markdown("#### 📝 步骤 3：创建技术主张与结果")
                with st.form("ci_step3_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        claim_type = st.selectbox("主张类型", ["host_range", "efficacy", "safety", "manufacturability", "mechanism"])
                        claim_text = st.text_area("主张文本", value="", height=80)
                    with col2:
                        result_type = st.selectbox("结果类型", ["host_range", "lysis", "biofilm", "safety", "in_vivo", "computational"])
                        metric_value = st.number_input("结果值", value=0.85, step=0.05)
                    submitted = st.form_submit_button("🚀 执行步骤 3", width="stretch", type="primary")
                if submitted:
                    try:
                        with st.spinner("正在创建..."):
                            construct_id = list(st.session_state.ci_context["construct_ids"].values())[0] if st.session_state.ci_context["construct_ids"] else None
                            if not construct_id:
                                st.error("请先执行步骤 2 创建构建体")
                                st.stop()
                            claim_id = create_technical_claim(driver, claim_type=claim_type, claim_text=claim_text, exact_quote=claim_text[:50], claimant_type="publication", evidence_context="in_vitro", construct_id=construct_id, actor_id="test_user")
                            st.session_state.ci_context["claim_ids"]["claim1"] = claim_id
                            result_id = create_technical_result(driver, result_type=result_type, study_context="in_vitro", outcome_direction="positive", metric_name=result_type, metric_value=float(metric_value), metric_unit="%", comparator="亲本噬菌体", sample_size=12, limitation_summary="需进一步验证", construct_id=construct_id, actor_id="test_user")
                            st.session_state.ci_context["result_ids"]["result1"] = result_id
                            st.session_state.ci_step_status["step3_done"] = True
                            st.success("✅ 步骤 3 完成！")
                            go_to_step(3)
                    except Exception as e:
                        st.error(f"❌ 执行失败：{e}")

        elif step == 3:
            with st.container(border=True):
                st.markdown("#### 📄 步骤 4：生成竞争简报并完成审核")
                if "brief_id" in st.session_state.ci_context and st.session_state.ci_context["brief_id"]:
                    st.info(f"当前简报 ID: {st.session_state.ci_context['brief_id']}，状态: {'已审核' if st.session_state.ci_step_status['step4_done'] else '待审核'}")
                else:
                    org_list = list_organizations(driver)
                    org_options = [f"{o['name']} ({o['id']})" for o in org_list]
                    if not org_options:
                        st.warning("⚠️ 暂无组织，请先执行步骤 1")
                    else:
                        current_org_id = st.session_state.ci_context.get("current_org_id")
                        default_index = 0
                        if current_org_id:
                            for idx, opt in enumerate(org_options):
                                if current_org_id in opt:
                                    default_index = idx
                                    break
                        selected_org = st.selectbox("选择要分析的组织", options=org_options, index=default_index)
                        parts = selected_org.split("(")
                        org_id = parts[1].rstrip(")") if len(parts)>1 else None
                        if org_id:
                            with st.expander("🧬 该组织的工程化噬菌体情报", expanded=True):
                                with driver.session() as session:
                                    engineering_data = session.run("""
                                        MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(p:DevelopmentProgram)
                                        OPTIONAL MATCH (c:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(p)
                                        OPTIONAL MATCH (p)-[:USES_CONSTRUCT]->(c2:EngineeredPhageConstruct)
                                        WITH p, COLLECT(DISTINCT c) + COLLECT(DISTINCT c2) AS constructs
                                        UNWIND (CASE WHEN size(constructs) = 0 THEN [null] ELSE constructs END) AS c
                                        OPTIONAL MATCH (c)-[:IMPLEMENTS]->(s:EngineeringStrategy)
                                        OPTIONAL MATCH (c)-[:CLAIMS_ABOUT]-(cl:TechnicalClaim)
                                        OPTIONAL MATCH (c)-[:RESULT_FOR]-(r:TechnicalResult)
                                        RETURN p.canonical_name AS program,
                                            collect(DISTINCT s.strategy_type) AS strategies,
                                            collect(DISTINCT c.public_name) AS constructs,
                                            collect(DISTINCT cl.claim_type) AS claims,
                                            collect(DISTINCT r.result_type) AS results
                                    """, oid=org_id)
                                    rows = list(engineering_data)
                                    if rows:
                                        for row in rows:
                                            st.write(f"**项目**: {row['program']}")
                                            st.write(f"  策略: {row['strategies'] if row['strategies'] else '无'}")
                                            st.write(f"  构建体: {row['constructs'] if row['constructs'] else '无'}")
                                            st.write(f"  技术主张: {row['claims'] if row['claims'] else '无'}")
                                            st.write(f"  实验结果: {row['results'] if row['results'] else '无'}")
                                    else:
                                        st.info("该组织暂无工程化噬菌体对象。")
                            with st.form("ci_step4_form"):
                                days_back = st.number_input("回溯天数", min_value=30, max_value=730, value=365)
                                submitted = st.form_submit_button("📄 生成简报", width="stretch", type="primary")
                            if submitted:
                                try:
                                    with st.spinner("生成简报中..."):
                                        brief = generate_competitor_brief(driver, org_id, days_back=days_back, persist=True)
                                        brief_id = brief.get("brief_id")
                                        if brief_id:
                                            st.session_state.ci_context["brief_id"] = brief_id
                                            st.session_state.ci_context["current_brief_id"] = brief_id
                                            st.session_state.ci_step_status["step4_done"] = False
                                            st.success(f"✅ 简报已生成，ID: {brief_id}")
                                            st.rerun()
                                except Exception as e:
                                    st.error(f"生成失败：{e}")
                if "brief_id" in st.session_state.ci_context and st.session_state.ci_context["brief_id"]:
                    brief_id = st.session_state.ci_context["brief_id"]
                    if not st.session_state.ci_step_status["step4_done"]:
                        with st.form("ci_step4_review_form"):
                            st.subheader("📌 创建评估（内部判断）")
                            col1, col2 = st.columns(2)
                            with col1:
                                assess_type = st.selectbox("竞争评估类型", ["threat", "opportunity", "capability", "uncertainty"])
                                impact_level = st.selectbox("影响程度", ["high", "medium", "low"])
                                confidence = st.selectbox("置信度", ["high", "medium", "low"])
                            with col2:
                                tech_relevance = st.selectbox("技术相关性", ["high", "medium", "low"])
                                evidence_maturity = st.selectbox("证据成熟度", ["conceptual", "in_vitro", "in_vivo", "clinical"])
                                translational_potential = st.selectbox("转化潜力", ["high", "medium", "low", "unknown"])
                            assessment_summary = st.text_area("评估摘要", value="该竞争对手在工程化噬菌体领域布局积极，但转化证据尚不充分。")
                            assumptions = st.text_input("假设条件（逗号分隔）", value="产品商业化顺利, 专利壁垒较低")
                            unknowns = st.text_input("未知项（逗号分隔）", value="市场接受度, 监管路径")
                            decision_choice = st.selectbox("审核决策", ["approved", "rejected"], index=0)
                            submitted_review = st.form_submit_button("✅ 提交审核（创建评估+决策）", width="stretch", type="primary")
                        if submitted_review:
                            try:
                                with st.spinner("审核中..."):
                                    org_id = st.session_state.ci_context.get("current_org_id")
                                    with driver.session() as session:
                                        result = session.run("MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS name", oid=org_id).single()
                                        org_name = result["name"] if result else "Unknown"
                                    assess_id = create_competitor_assessment(driver, assessment_type=assess_type, subject_type="organization", subject_id=org_id, impact_area="market", impact_level=impact_level, assessment_summary=assessment_summary, confidence=confidence, analyst_id="analyst_zhang", time_horizon="short", assumptions=assumptions.split(",") if assumptions else [], unknowns=unknowns.split(",") if unknowns else [], actor_id="system")
                                    construct_id = list(st.session_state.ci_context.get("construct_ids", {}).values())[0] if st.session_state.ci_context.get("construct_ids") else None
                                    if construct_id:
                                        tech_assess_id = create_technology_assessment(driver, subject_type="construct", subject_id=construct_id, evidence_maturity=evidence_maturity, technical_relevance=tech_relevance, translational_potential=translational_potential, manufacturability_risk="medium", safety_uncertainty="low", ip_relevance="medium", internal_capability_gap="low", assessment_summary=f"技术评估: {assessment_summary[:50]}...", actor_id="system")
                                    review_brief_id = create_review(driver, review_type="intelligence_product_review", target_object_type="IntelligenceProduct", target_object_id=brief_id, reviewer_id="expert_wang", decision=decision_choice, comment=f"简报审核 {decision_choice}", update_target_status=True, actor_id="system")
                                    review_assess_id = create_review(driver, review_type="intelligence_product_review", target_object_type="CompetitorAssessment", target_object_id=assess_id, reviewer_id="expert_wang", decision=decision_choice, comment=f"评估审核 {decision_choice}", update_target_status=True, actor_id="system")
                                    dec_id = create_decision_record(driver, brief_id=brief_id, decision_type="monitor", decision_summary=f"将 {org_name} 列入年度重点监控名单", rationale=f"审核决策: {decision_choice}", decision_owner="VP_Strategy", review_date="2027-01-01", actor_id="system")
                                    st.session_state.ci_context["decision_ids"].append(dec_id)
                                    st.session_state.ci_step_status["step4_done"] = True
                                    st.success("✅ 审核完成！")
                                    go_to_step(4)
                            except Exception as e:
                                st.error(f"审核失败：{e}")
                    else:
                        st.success("🎉 本步骤已完成审核，可继续下一步。")
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            if st.button("➡️ 进入步骤 5（情报消费）", key="go_to_step5"):
                                go_to_step(4)
                        with col2:
                            if st.button("🔄 重新生成简报（重置）"):
                                st.session_state.ci_context.pop("brief_id", None)
                                st.session_state.ci_step_status["step4_done"] = False
                                st.session_state["ci_step6_results"] = None
                                st.rerun()

        elif step == 4:
            with st.container(border=True):
                st.markdown("#### 📊 步骤 5：记录情报消费事件")
                with driver.session() as session:
                    briefs = session.run("""
                        MATCH (b:IntelligenceProduct)
                        RETURN b.brief_id AS brief_id, b.title AS title
                        ORDER BY b.created_at DESC LIMIT 10
                    """)
                    brief_options = [f"{r['title']} ({r['brief_id']})" for r in briefs]
                if not brief_options:
                    st.warning("⚠️ 暂无简报，请先执行步骤 4")
                else:
                    selected = st.selectbox("选择要消费的简报", options=brief_options)
                    brief_id = selected.split("(")[-1].rstrip(")")
                    with st.form("ci_step5_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            consumer_type = st.selectbox("消费方类型", ["IPD", "RD", "BD", "Strategy", "Clinical", "Management"])
                        with col2:
                            use_purpose = st.selectbox("使用目的", ["go_no_go_decision", "roadmap_planning", "competitor_monitoring", "portfolio_review", "due_diligence", "strategic_planning"])
                        submitted = st.form_submit_button("📌 记录消费", width="stretch", type="primary")
                    if submitted:
                        try:
                            with st.spinner("记录中..."):
                                dec_id = st.session_state.ci_context["decision_ids"][-1] if st.session_state.ci_context["decision_ids"] else None
                                use_id = record_intelligence_use(driver, product_id=brief_id, consumer_type=consumer_type, consumer_id=f"{consumer_type.lower()}_team", use_purpose=use_purpose, context_note=f"{consumer_type} 团队使用简报进行 {use_purpose}", referenced_decision_id=dec_id, actor_id="test_user")
                                st.session_state.ci_context["use_event_ids"].append(use_id)
                                st.session_state.ci_step_status["step5_done"] = True
                                st.success(f"✅ 消费事件记录成功，ID: {use_id}")
                                go_to_step(5)
                        except Exception as e:
                            st.error(f"记录失败：{e}")

        elif step == 5:
            with st.container(border=True):
                st.markdown("#### 🔗 步骤 6：验证归因链")
                if st.button("🔍 执行归因验证", width="stretch", type="primary"):
                    try:
                        with st.spinner("验证中..."):
                            query = """
                            MATCH (brief:IntelligenceProduct)-[:COVERS]->(org:Organization)
                            MATCH (review:Review)-[:REVIEWS]->(brief)
                            WHERE review.decision = 'approved'
                            MATCH (dec:DecisionRecord)-[:BASED_ON]->(brief)
                            MATCH (use:IntelligenceUseEvent)-[:CONSUMES]->(brief)
                            OPTIONAL MATCH (src:SourceArtifact)<-[:HAS_SOURCE]-(evt:IntelligenceEvent)-[:AFFECTS]->(prog:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen)
                            WHERE evt.organization_id = org.organization_id
                            OPTIONAL MATCH (prog)-[:USES_CONSTRUCT|ASSOCIATED_WITH]-(con:EngineeredPhageConstruct)
                            OPTIONAL MATCH (con)-[:IMPLEMENTS]->(strat:EngineeringStrategy)
                            OPTIONAL MATCH (con)<-[:CLAIMS_ABOUT]-(claim:TechnicalClaim)
                            OPTIONAL MATCH (con)<-[:RESULT_FOR]-(res:TechnicalResult)
                            WITH org,
                                COLLECT(DISTINCT brief) AS briefs,
                                COLLECT(DISTINCT review) AS reviews,
                                COLLECT(DISTINCT dec) AS decs,
                                COLLECT(DISTINCT use) AS uses,
                                COLLECT(DISTINCT src.title) AS evidence_sources,
                                COLLECT(DISTINCT src.credibility_tier) AS credibility_tiers,
                                COLLECT(DISTINCT evt.title) AS events,
                                COLLECT(DISTINCT p.species) AS pathogens,
                                COLLECT(DISTINCT strat.strategy_type) AS strategies,
                                COLLECT(DISTINCT con.public_name) AS constructs,
                                COLLECT(DISTINCT claim.claim_type) AS claim_types,
                                COLLECT(DISTINCT res.result_type) AS result_types
                            RETURN org.canonical_name AS competitor,
                                org.organization_id AS org_id,
                                [b IN briefs | b.brief_id] AS brief_ids,
                                [r IN reviews | r.decision] AS review_decisions,
                                [d IN decs | d.decision_type] AS decision_types,
                                [u IN uses | u.consumer_type] AS consumers,
                                [u IN uses | u.use_purpose] AS purposes,
                                evidence_sources, credibility_tiers, events, pathogens,
                                strategies, constructs, claim_types, result_types
                            """
                            with driver.session() as session:
                                results = list(session.run(query))
                            st.session_state["ci_step6_results"] = [dict(r) for r in results]
                            st.session_state.ci_step_status["step6_done"] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"验证失败：{e}")
                results = st.session_state.get("ci_step6_results")
                if results is not None:
                    if not results:
                        st.warning("未找到完整归因链路。请确保至少有一个组织已完成简报审核并记录消费。")
                    else:
                        st.success(f"✅ 找到 {len(results)} 个组织具备完整归因链路")
                        rows = []
                        for row in results:
                            rows.append({
                                "组织": row['competitor'], "组织ID": row['org_id'],
                                "简报ID": ', '.join(row['brief_ids']) if row['brief_ids'] else '',
                                "审核决策": ', '.join(row['review_decisions']) if row['review_decisions'] else '',
                                "决策类型": ', '.join(row['decision_types']) if row['decision_types'] else '',
                                "消费方": ', '.join(row['consumers']) if row['consumers'] else '',
                                "用途": ', '.join(row['purposes']) if row['purposes'] else '',
                                "证据来源数": len(row['evidence_sources']) if row['evidence_sources'] else 0,
                                "事件数": len(row['events']) if row['events'] else 0,
                                "靶向病原": ', '.join(row['pathogens']) if row['pathogens'] else '',
                                "策略": ', '.join(row['strategies']) if row['strategies'] else '',
                                "构建体": ', '.join(row['constructs']) if row['constructs'] else '',
                                "主张": ', '.join(row['claim_types']) if row['claim_types'] else '',
                                "结果": ', '.join(row['result_types']) if row['result_types'] else '',
                            })
                        df = pd.DataFrame(rows)
                        st.dataframe(df, width="stretch", hide_index=True)
                        st.markdown("---")
                        st.markdown("#### 📌 查看单个组织完整详情")
                        org_names = [row['competitor'] for row in results]
                        selected_org = st.selectbox("选择组织", org_names, key="ci_step6_org_select")
                        if selected_org:
                            for row in results:
                                if row['competitor'] == selected_org:
                                    st.json({
                                        "组织": row['competitor'], "简报ID列表": row['brief_ids'],
                                        "审核决策列表": row['review_decisions'], "决策类型列表": row['decision_types'],
                                        "消费方列表": row['consumers'], "用途列表": row['purposes'],
                                        "证据来源": row['evidence_sources'], "可信度等级": row['credibility_tiers'],
                                        "情报事件": row['events'], "靶向病原": row['pathogens'],
                                        "工程策略": row['strategies'], "构建体": row['constructs'],
                                        "技术主张": row['claim_types'], "实验结果": row['result_types']
                                    }, expanded=True)
                                    break
        with st.expander("📊 当前上下文状态"):
            st.json({
                "current_org_id": st.session_state.ci_context.get("current_org_id"),
                "current_program_id": st.session_state.ci_context.get("current_program_id"),
                "current_brief_id": st.session_state.ci_context.get("current_brief_id"),
                "decision_count": len(st.session_state.ci_context.get("decision_ids", [])),
                "use_event_count": len(st.session_state.ci_context.get("use_event_ids", [])),
                "technology_assessment_id": st.session_state.ci_context.get("technology_assessment_id"),
            })

    # ========== Tab2: 情报查询 ==========
    with ci_tab2:
        st.markdown("### 🔍 智能语义检索")
        st.caption("输入名称、缩写或关联关键词，系统将自动匹配已有本体实体，未匹配时可触发全网情报检索")
        search_query = st.text_input("搜索本体实体", placeholder="例如: APT, BiomX, BX211, Salmonella, Klebsiella...", key="ci_search_input", value="")
        col_search_btn, _ = st.columns([1, 5])
        with col_search_btn:
            st.button("🔍 搜索", key="ci_search_btn", width="stretch")
        if search_query:
            query = search_query.strip()
            if len(query) >= 2:
                with st.spinner("搜索本体中..."):
                    with driver.session() as session:
                        results = {"Organization": [], "DevelopmentProgram": [], "IntelligenceEvent": [], "Pathogen": []}
                        org_result = session.run("""
                            MATCH (o:Organization)
                            WHERE o.canonical_name CONTAINS toLower($q)
                               OR ANY(alias IN o.aliases WHERE alias CONTAINS toLower($q))
                            RETURN o.organization_id AS id, o.canonical_name AS name,
                                   o.organization_type AS type, o.headquarters_country AS country
                            LIMIT 10
                        """, q=query)
                        results["Organization"] = [dict(r) for r in org_result]
                        prog_result = session.run("""
                            MATCH (d:DevelopmentProgram)
                            WHERE d.canonical_name CONTAINS toLower($q)
                               OR ANY(alias IN d.aliases WHERE alias CONTAINS toLower($q))
                            RETURN d.program_id AS id, d.canonical_name AS name,
                                   d.development_stage AS stage, d.program_type AS type
                            LIMIT 10
                        """, q=query)
                        results["DevelopmentProgram"] = [dict(r) for r in prog_result]
                        event_result = session.run("""
                            MATCH (e:IntelligenceEvent)
                            WHERE e.title CONTAINS toLower($q) OR e.event_type CONTAINS toLower($q)
                            RETURN e.event_id AS id, e.title AS name, e.event_type AS type, e.event_date AS date
                            ORDER BY e.event_date DESC LIMIT 10
                        """, q=query)
                        results["IntelligenceEvent"] = [dict(r) for r in event_result]
                        path_result = session.run("""
                            MATCH (p:Pathogen)
                            WHERE p.species CONTAINS toLower($q)
                               OR ANY(alias IN p.aliases WHERE alias CONTAINS toLower($q))
                            RETURN p.pathogen_id AS id, p.species AS name, p.pathogen_type AS type
                            LIMIT 10
                        """, q=query)
                        results["Pathogen"] = [dict(r) for r in path_result]
                    total_matches = sum(len(v) for v in results.values())
                    if total_matches > 0:
                        st.success(f"✅ 在 Ontology 中找到 {total_matches} 个匹配实体")
                        for label, items in results.items():
                            if items:
                                with st.expander(f"📌 {label} ({len(items)})", expanded=True):
                                    for item in items:
                                        if label == "Organization":
                                            st.write(f"**{item['name']}** ({item.get('type','')}) - {item.get('country','')}  `{item['id']}`")
                                        elif label == "DevelopmentProgram":
                                            st.write(f"**{item['name']}** ({item.get('stage','')}) - {item.get('type','')}  `{item['id']}`")
                                        elif label == "IntelligenceEvent":
                                            st.write(f"**{item['name']}** ({item.get('type','')}) - {item.get('date','')}  `{item['id']}`")
                                        elif label == "Pathogen":
                                            st.write(f"**{item['name']}** ({item.get('type','')})  `{item['id']}`")
                    else:
                        st.warning(f"⚠️ 未在 Ontology 中找到与「{query}」匹配的实体")
            else:
                st.info("请输入至少 2 个字符开始搜索")
        st.markdown("---")
        st.markdown("#### 组织列表（按事件数排序）")
        try:
            orgs = list_organizations(driver)
            if not orgs:
                st.info("暂无组织数据，请先执行步骤1创建组织。")
            else:
                org_with_events = []
                for org in orgs:
                    org_id = org["id"]
                    with driver.session() as session:
                        event_count = session.run("MATCH (e:IntelligenceEvent {organization_id: $oid}) RETURN count(e) AS cnt", oid=org_id).single()["cnt"]
                    org_with_events.append({**org, "event_count": event_count})
                org_sorted = sorted(org_with_events, key=lambda x: x["event_count"], reverse=True)[:10]
                cols = st.columns(2)
                for idx, org in enumerate(org_sorted):
                    with cols[idx % 2]:
                        org_id = org["id"]; name = org["name"]; org_type = org["type"]
                        country = org.get("country", "未知")
                        profile = build_competitor_profile(driver, org_id)
                        if "error" in profile:
                            detail = "无法加载详情"
                        else:
                            progs = profile.get('active_programs', [])
                            detail = f"项目数: {len(progs)} | 事件数: {len(profile.get('recent_events', []))} | 数据截止: {profile.get('as_of_date', 'N/A')}"
                        st.markdown(f"""
                        <div style="background:white; border-radius:10px; padding:1rem 1.2rem; border:1px solid #e9edf2; margin-bottom:0.8rem; box-shadow:0 1px 4px rgba(0,0,0,0.02);">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-weight:600; font-size:1.05rem;">{name}</span>
                                <span style="background:#eef2ff; padding:0.1rem 0.6rem; border-radius:12px; font-size:0.7rem; color:#1e40af;">{org_type}</span>
                            </div>
                            <div style="font-size:0.85rem; color:#64748b; margin-top:0.2rem;">{country}</div>
                            <div style="font-size:0.8rem; margin-top:0.4rem;">{detail}</div>
                        </div>
                        """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"加载组织列表失败: {e}")
        st.markdown("---")
        st.markdown("#### 最新情报事件")
        try:
            with driver.session() as session:
                events = session.run("""
                    MATCH (e:IntelligenceEvent)
                    RETURN e.event_id AS 事件ID, e.title AS 标题, e.event_type AS 类型,
                           e.event_date AS 日期, e.review_status AS 审核状态
                    ORDER BY e.event_date DESC LIMIT 10
                """)
                event_records = [dict(r) for r in events]
                if event_records:
                    st.dataframe(pd.DataFrame(event_records), width="stretch", hide_index=True)
                else:
                    st.info("暂无事件记录。")
        except Exception as e:
            st.error(f"加载事件失败: {e}")
        st.markdown("#### 最新情报简报")
        try:
            with driver.session() as session:
                briefs = session.run("""
                    MATCH (b:IntelligenceProduct)
                    RETURN b.brief_id AS 简报ID, b.title AS 标题, b.brief_type AS 类型,
                           b.as_of_date AS 截止日期, b.review_status AS 审核状态
                    ORDER BY b.created_at DESC LIMIT 10
                """)
                brief_records = [dict(r) for r in briefs]
                if brief_records:
                    st.dataframe(pd.DataFrame(brief_records), width="stretch", hide_index=True)
                else:
                    st.info("暂无简报记录。")
        except Exception as e:
            st.error(f"加载简报失败: {e}")

    # ========== Tab3: 情报抓取 ==========
    with ci_tab3:
        st.markdown("### 📡 从 URL 抓取情报")
        st.caption(
            "输入网页地址，系统自动抓取并识别其中的**公司 / 项目 / 事件**。"
            "每行都会标注「🆕 新增 / ♻️ 已存在」，确认后写入图谱。"
        )
        st.markdown("---")
        col_u1, col_u2 = st.columns([4, 1])
        with col_u1:
            url_input = st.text_input(
                "网页地址",
                value=st.session_state.scrape_url,
                placeholder="例如：https://www.biomx.com/news/biomx-acquires-apt",
                key="scrape_url_field",
            )
        with col_u2:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            btn_extract = st.button("🔍 抓取并分析", type="primary", width="stretch", key="scrape_extract_btn")

        if btn_extract:
            if not url_input.strip():
                st.warning("请输入 URL")
            else:
                st.session_state.scrape_url = url_input.strip()
                with st.spinner("🌐 正在抓取网页..."):
                    try:
                        fetched = _fetch_url_content(url_input.strip())
                        st.session_state.scrape_raw = fetched
                    except Exception as e:
                        st.error(f"抓取失败：{e}")
                        st.session_state.scrape_raw = None
                        st.session_state.scrape_result = None
                if st.session_state.scrape_raw:
                    with st.spinner("🤖 正在用 LLM 抽取结构化信息..."):
                        try:
                            result = _extract_with_llm(
                                url=url_input.strip(),
                                title=st.session_state.scrape_raw.get("title", ""),
                                content=st.session_state.scrape_raw.get("text", ""),
                            )
                            st.session_state.scrape_result = result
                        except Exception as e:
                            st.error(f"LLM 抽取失败：{e}")
                            st.session_state.scrape_result = None

        if st.session_state.scrape_result:
            result = st.session_state.scrape_result
            raw = st.session_state.scrape_raw or {}
            scrape_url = st.session_state.scrape_url

            if result.get("_parse_error"):
                st.warning(
                    f"⚠️ JSON 解析失败：{result['_parse_error']}\n\n"
                    "可能原因：LLM 输出过长被截断。可尝试：\n"
                    "1. 刷新重试（偶发）\n"
                    "2. 换用信息量更少的页面\n"
                    "3. 如果是超长周报，只截取感兴趣的部分单独抓取"
                )
                with st.expander("查看被截断的原文片段（末尾 500 字）"):
                    st.code(result.get("_raw_snippet", ""))
                if not (result.get("organizations") or result.get("programs") or result.get("events")):
                    st.info("未抽取到任何结构化数据。")
                    st.session_state.scrape_result = None
                    st.stop()

            if result.get("_repaired"):
                st.info("ℹ️ 本次 LLM 输出被截断，已自动修复保留了完整部分。")

            orgs_raw = result.get("organizations", []) or []
            progs_raw = result.get("programs", []) or []
            events_raw = result.get("events", []) or []

            org_status = {}
            for o in orgs_raw:
                nm = o.get("canonical_name", "")
                if nm and nm not in org_status:
                    org_status[nm] = _check_org_status(nm, url=scrape_url)

            prog_status = {}
            for p in progs_raw:
                nm = p.get("canonical_name", "")
                if nm and nm not in prog_status:
                    prog_status[nm] = _check_program_status(nm)

            evt_status = {}
            for e in events_raw:
                key = (e.get("organization_name", ""), e.get("title", ""), e.get("event_date", ""))
                if key not in evt_status:
                    evt_status[key] = _check_event_status(
                        e.get("organization_name", ""), e.get("title", ""),
                        e.get("event_date", ""), url=scrape_url,
                    )

            n_org_new  = sum(1 for s, _ in org_status.values() if s == "new")
            n_org_ex   = sum(1 for s, _ in org_status.values() if s == "existing")
            n_prog_new = sum(1 for s, _ in prog_status.values() if s == "new")
            n_prog_ex  = sum(1 for s, _ in prog_status.values() if s == "existing")
            n_evt_new  = sum(1 for s, _ in evt_status.values() if s == "new")
            n_evt_ex   = sum(1 for s, _ in evt_status.values() if s == "existing")

            st.success(
                f"✅ 抽取完成：识别到 **{len(orgs_raw)}** 个组织、"
                f"**{len(progs_raw)}** 个项目、**{len(events_raw)}** 个事件"
            )

            s1, s2, s3 = st.columns(3)
            with s1:
                st.markdown(f"""
                <div class="ci-metric-box">
                    <div class="number">🆕 {n_org_new} · ♻️ {n_org_ex}</div>
                    <div class="label">组织：新增 / 已存在</div>
                </div>
                """, unsafe_allow_html=True)
            with s2:
                st.markdown(f"""
                <div class="ci-metric-box">
                    <div class="number">🆕 {n_prog_new} · ♻️ {n_prog_ex}</div>
                    <div class="label">项目：新增 / 已存在</div>
                </div>
                """, unsafe_allow_html=True)
            with s3:
                st.markdown(f"""
                <div class="ci-metric-box">
                    <div class="number">🆕 {n_evt_new} · ♻️ {n_evt_ex}</div>
                    <div class="label">事件：新增 / 已存在</div>
                </div>
                """, unsafe_allow_html=True)

            with st.expander("📄 查看抓取到的网页原文（前 3000 字）", expanded=False):
                st.caption(f"标题：{raw.get('title', '（无）')}")
                st.text((raw.get("text") or "")[:3000] + "...")

            st.markdown("---")
            st.markdown("#### 🏢 组织（可编辑）")
            if orgs_raw:
                org_rows = []
                for o in orgs_raw:
                    nm = o.get("canonical_name", "")
                    status, matched = org_status.get(nm, ("empty", ""))
                    label = _status_emoji(status)
                    if status == "existing" and matched and matched.lower() != nm.lower():
                        label = f"♻️ 已存在 → {matched}"
                    org_rows.append({
                        "状态": label,
                        "canonical_name": nm,
                        "organization_type": o.get("organization_type", "biotech"),
                        "aliases": _norm_list_to_str(o.get("aliases", [])),
                        "headquarters_country": o.get("headquarters_country", ""),
                        "website": o.get("website", ""),
                        "description": o.get("description", ""),
                    })
                org_df = pd.DataFrame(org_rows)
                edited_orgs = st.data_editor(
                    org_df,
                    column_config={
                        "状态": st.column_config.TextColumn("状态", width="small", disabled=True),
                        "canonical_name": st.column_config.TextColumn("名称", required=True, width="medium"),
                        "organization_type": st.column_config.SelectboxColumn("类型", width="small", options=["biotech", "pharma", "academic", "CRO", "tech", "food_safety", "other"]),
                        "aliases": st.column_config.TextColumn("别名（逗号分隔）", width="small"),
                        "headquarters_country": st.column_config.TextColumn("国家", width="small"),
                        "website": st.column_config.TextColumn("官网", width="medium"),
                        "description": st.column_config.TextColumn("描述", width="large"),
                    },
                    num_rows="dynamic", width="stretch", key="scrape_org_editor",
                )
            else:
                st.caption("未识别到组织")
                edited_orgs = pd.DataFrame(columns=["状态", "canonical_name", "organization_type", "aliases", "headquarters_country", "website", "description"])

            st.markdown("#### 📦 项目 / 管线（可编辑）")
            if progs_raw:
                prog_rows = []
                for p in progs_raw:
                    nm = p.get("canonical_name", "")
                    status, matched = prog_status.get(nm, ("empty", ""))
                    label = _status_emoji(status)
                    if status == "existing" and matched and matched.lower() != nm.lower():
                        label = f"♻️ 已存在 → {matched}"
                    prog_rows.append({
                        "状态": label,
                        "canonical_name": nm,
                        "organization_name": p.get("organization_name", ""),
                        "program_type": p.get("program_type", "therapeutic"),
                        "development_stage": p.get("development_stage", "discovery"),
                        "modality": p.get("modality", ""),
                        "target_pathogen_species": _norm_list_to_str(p.get("target_pathogen_species", [])),
                    })
                prog_df = pd.DataFrame(prog_rows)
                edited_progs = st.data_editor(
                    prog_df,
                    column_config={
                        "状态": st.column_config.TextColumn("状态", width="small", disabled=True),
                        "canonical_name": st.column_config.TextColumn("项目名称", required=True, width="medium"),
                        "organization_name": st.column_config.TextColumn("所属组织", required=True, width="medium"),
                        "program_type": st.column_config.SelectboxColumn("类型", width="small", options=["therapeutic", "diagnostic", "platform", "research", "food_safety"]),
                        "development_stage": st.column_config.SelectboxColumn("阶段", width="small", options=["discovery", "preclinical", "phase_1", "phase_1_2", "phase_2", "phase_2b", "phase_3", "commercial"]),
                        "modality": st.column_config.TextColumn("模态", width="small"),
                        "target_pathogen_species": st.column_config.TextColumn("靶向病原（逗号分隔）", width="medium"),
                    },
                    num_rows="dynamic", width="stretch", key="scrape_prog_editor",
                )
            else:
                st.caption("未识别到项目")
                edited_progs = pd.DataFrame(columns=["状态", "canonical_name", "organization_name", "program_type", "development_stage", "modality", "target_pathogen_species"])

            st.markdown("#### 📰 事件（可编辑）")
            if events_raw:
                evt_rows = []
                for e in events_raw:
                    key = (e.get("organization_name", ""), e.get("title", ""), e.get("event_date", ""))
                    status, _ = evt_status.get(key, ("empty", ""))
                    evt_rows.append({
                        "状态": _status_emoji(status),
                        "event_type": e.get("event_type", "publication"),
                        "title": e.get("title", ""),
                        "factual_summary": e.get("factual_summary", ""),
                        "organization_name": e.get("organization_name", ""),
                        "program_name": e.get("program_name", ""),
                        "event_date": e.get("event_date", ""),
                        "published_at": e.get("published_at", e.get("event_date", "")),
                    })
                evt_df = pd.DataFrame(evt_rows)
                edited_events = st.data_editor(
                    evt_df,
                    column_config={
                        "状态": st.column_config.TextColumn("状态", width="small", disabled=True),
                        "event_type": st.column_config.SelectboxColumn("事件类型", required=True, width="small", options=["regulatory_update", "funding", "acquisition", "merger", "partnership", "clinical_trial_update", "publication", "patent_event", "pipeline_update"]),
                        "title": st.column_config.TextColumn("标题", required=True, width="large"),
                        "factual_summary": st.column_config.TextColumn("事实摘要", width="large"),
                        "organization_name": st.column_config.TextColumn("所属组织", required=True, width="medium"),
                        "program_name": st.column_config.TextColumn("关联项目（可选）", width="medium"),
                        "event_date": st.column_config.TextColumn("事件日期 (YYYY-MM-DD)", width="small"),
                        "published_at": st.column_config.TextColumn("发布日期", width="small"),
                    },
                    num_rows="dynamic", width="stretch", key="scrape_evt_editor",
                )
            else:
                st.caption("未识别到事件")
                edited_events = pd.DataFrame(columns=["状态", "event_type", "title", "factual_summary", "organization_name", "program_name", "event_date", "published_at"])

            st.markdown("---")
            col_confirm, col_reset = st.columns([3, 1])
            with col_confirm:
                btn_commit = st.button("✅ 确认写入图谱", type="primary", width="stretch", key="scrape_commit_btn")
            with col_reset:
                btn_reset = st.button("🗑️ 清除结果", width="stretch", key="scrape_reset_btn")

            if btn_reset:
                st.session_state.scrape_result = None
                st.session_state.scrape_raw = None
                st.rerun()

            if btn_commit:
                org_records = edited_orgs.drop(columns=["状态"], errors="ignore").fillna("").to_dict("records")
                prog_records = edited_progs.drop(columns=["状态"], errors="ignore").fillna("").to_dict("records")
                evt_records = edited_events.drop(columns=["状态"], errors="ignore").fillna("").to_dict("records")

                if not evt_records and not org_records:
                    st.warning("没有需要写入的内容")
                else:
                    with st.spinner("正在写入图谱..."):
                        stats = _commit_scraped_data(
                            url=st.session_state.scrape_url,
                            orgs=org_records,
                            progs=prog_records,
                            events=evt_records,
                        )
                    parts = []
                    for k, label in [
                        ("org_created", "新建企业"), ("org_reused", "复用企业"),
                        ("prog_created", "新建项目"), ("prog_reused", "复用项目"),
                        ("event_created", "新建事件"), ("event_skipped", "跳过重复"),
                        ("event_failed", "失败"),
                    ]:
                        if stats.get(k):
                            parts.append(f"{label} {stats[k]}")
                    st.success("✅ 写入完成：" + (" · ".join(parts) if parts else "无变更"))
                    if stats.get("errors"):
                        with st.expander(f"⚠️ {len(stats['errors'])} 条错误"):
                            for err in stats["errors"][:30]:
                                st.write(f"- {err}")
                    st.session_state.scrape_result = None
                    st.session_state.scrape_raw = None
        else:
            st.info(
                "💡 使用步骤：\n"
                "1. 粘贴网页地址（新闻稿、行业周报、公司博客等）\n"
                "2. 点击「🔍 抓取并分析」\n"
                "3. 检查识别出的公司 / 项目 / 事件 —— **每行都有状态列**：\n"
                "   · 🆕 新增 = 数据库中不存在\n"
                "   · ♻️ 已存在 = 数据库已有（自动复用）\n"
                "   · ♻️ 已存在 → XXX = 通过别名 / 域名匹配到了 XXX\n"
                "4. 点击「✅ 确认写入图谱」"
            )

    # ========== Tab4: 监控中心 ==========
    with ci_tab4:
        st.markdown("### 🎯 监控中心")
        st.caption(
            "抓取所有已配置监控源，LLM 抽取后逐条审核，勾选保留的写入图谱。"
            "**已解析过的事件会自动隐藏，避免重复展示。**"
        )

        # ---------- 顶部提示（rerun 后依然可见）----------
        flash = st.session_state.pop("_monitor_flash", None)
        if flash:
            kind, text = flash
            if kind == "success":
                st.success(f"✅ {text}")
            elif kind == "error":
                st.error(f"❌ {text}")
            elif kind == "info":
                st.info(f"ℹ️ {text}")

        # ---------- 监控源配置面板 ----------
        with st.expander("⚙️ 监控源配置", expanded=False):
            st.caption("为组织添加监控源。选择组织后会自动生成搜狗微信搜索 URL，也可以手动改成官网新闻页等。")

            org_list_for_config = list_organizations(driver)
            if not org_list_for_config:
                st.warning("暂无组织，请先到「📋 情报流程」步骤1创建组织")
            else:
                org_options = [f"{o['name']} ({o['id']})" for o in org_list_for_config]
                selected_org_for_src = st.selectbox(
                    "选择组织", options=org_options, key="monitor_src_org_select"
                )

                if selected_org_for_src and "(" in selected_org_for_src:
                    org_name_for_src = selected_org_for_src.rsplit(" (", 1)[0]
                    org_id_for_src = selected_org_for_src.rsplit("(", 1)[-1].rstrip(")")
                else:
                    org_name_for_src = ""
                    org_id_for_src = None

                last_org_key = "_monitor_last_org_for_src"
                if st.session_state.get(last_org_key) != org_id_for_src:
                    default_url = (
                        "https://weixin.sogou.com/weixin?" + urlencode({
                            "type": "2",
                            "s_from": "input",
                            "query": org_name_for_src,
                            "ie": "utf8",
                            "_sug_": "n",
                            "_sug_type_": "",
                        })
                        if org_name_for_src else ""
                    )
                    st.session_state["monitor_src_url_input"] = default_url
                    st.session_state[last_org_key] = org_id_for_src

                with st.form("monitor_add_source_form"):
                    col_s1, col_s2 = st.columns([4, 1])
                    with col_s1:
                        src_url = st.text_input(
                            "监控源 URL",
                            key="monitor_src_url_input",
                            placeholder="选择组织后自动填充搜狗微信搜索 URL，也可手动修改",
                        )
                    with col_s2:
                        src_type = st.selectbox(
                            "类型",
                            options=["sogou_wechat", "wechat", "news", "publications", "mixed"],
                            key="monitor_src_type_select",
                            index=0,
                        )
                    src_label = st.text_input("标签（可选）", value="", key="monitor_src_label_input")
                    submitted_src = st.form_submit_button("➕ 添加监控源", width="stretch", type="primary")

                if submitted_src:
                    if not org_id_for_src:
                        st.session_state["_monitor_flash"] = ("error", "请选择组织")
                        st.rerun()
                    else:
                        try:
                            from scripts.monitor_runner import add_source
                            msg = add_source(org_id_for_src, src_url, src_type, src_label)
                            st.session_state["_monitor_flash"] = ("success", msg)
                            st.rerun()
                        except Exception as e:
                            st.session_state["_monitor_flash"] = ("error", f"添加失败：{e}")
                            st.rerun()

                with driver.session() as session:
                    result = session.run("""
                        MATCH (o:Organization {organization_id: $oid})
                        RETURN o.monitor_sources AS sources, o.canonical_name AS name
                    """, oid=org_id_for_src).single()
                    if not result:
                        st.error(
                            f"⚠️ 组织 ID `{org_id_for_src}` 在数据库中不存在，"
                            f"请检查 `list_organizations` 返回的 id 字段"
                        )
                        existing_sources = []
                    else:
                        existing_sources = result["sources"] or []
                        st.caption(f"当前组织：**{result['name']}** （id=`{org_id_for_src}`）")

                def _parse_src(raw):
                    if isinstance(raw, dict):
                        return raw
                    if isinstance(raw, str):
                        s_ = raw.strip()
                        if s_.startswith("{"):
                            try:
                                return json.loads(s_)
                            except Exception:
                                return None
                        return {"url": s_, "type": "mixed", "label": "通用"}
                    return None

                if existing_sources:
                    st.markdown(f"**已配置的监控源（共 {len(existing_sources)} 条）：**")
                    for idx, raw in enumerate(existing_sources):
                        src = _parse_src(raw)
                        if not src:
                            st.warning(f"⚠️ 无法解析第 {idx+1} 条监控源：{raw}")
                            continue
                        cols = st.columns([4, 1, 1])
                        with cols[0]:
                            st.code(src.get("url", ""), language=None)
                        with cols[1]:
                            st.caption(f"类型: {src.get('type', '')}")
                        with cols[2]:
                            if st.button("🗑️", key=f"del_src_{idx}"):
                                try:
                                    from scripts.monitor_runner import remove_source
                                    msg = remove_source(org_id_for_src, src.get("url", ""))
                                    st.session_state["_monitor_flash"] = ("success", msg)
                                    st.rerun()
                                except Exception as e:
                                    st.session_state["_monitor_flash"] = ("error", f"删除失败：{e}")
                                    st.rerun()
                else:
                    st.caption("该组织暂无监控源")

                with st.expander("🔍 调试：查看数据库原始 monitor_sources 值", expanded=False):
                    st.write("原始值（JSON）:")
                    st.json(existing_sources)

        # ---------- 抓取按钮 ----------
        col_run0, col_run1, col_run2, col_run3 = st.columns([1, 1, 1, 3])
        with col_run0:
            today_only = st.checkbox(
                "仅抓当天",
                value=True,
                key="monitor_today_only",
                help="只抓取发布日期是今天的文章（定时任务推荐勾选）"
            )
        with col_run1:
            btn_collect = st.button("🔍 立即抓取", type="primary",
                                    width="stretch", key="monitor_collect_btn")
        with col_run2:
            btn_clear = st.button("🗑️ 清空待审", width="stretch",
                                  key="monitor_clear_btn")

        if btn_clear:
            st.session_state.pop("monitor_pending", None)
            _save_pending(None)
            st.rerun()

        if btn_collect:
            try:
                from scripts.monitor_runner import collect_for_review
            except Exception as e:
                st.error(f"❌ 无法加载 monitor_runner: {e}")
            else:
                with st.spinner("🌐 抓取中（首次可能较慢，请稍候）..."):
                    try:
                        # ★ 改动点 2：传入 today_only
                        result = collect_for_review(today_only=today_only)
                        st.session_state["monitor_pending"] = result
                        _save_pending(result)
                        st.success(
                            f"✅ 抓取完成："
                            f"{result['stats'].get('orgs', 0)} 组织 / "
                            f"{result['stats'].get('progs', 0)} 项目 / "
                            f"{result['stats'].get('events', 0)} 事件"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"抓取失败：{e}")
                        import traceback as _tb
                        with st.expander("查看详细错误"):
                            st.code(_tb.format_exc())

        # ---------- 从磁盘恢复 ----------
        if "monitor_pending" not in st.session_state:
            loaded = _load_pending()
            if loaded:
                st.session_state["monitor_pending"] = loaded

        pending = st.session_state.get("monitor_pending")

        if not pending:
            st.info(
                "📭 **暂无待审数据**\n\n"
                "1. 先到上方「⚙️ 监控源配置」为组织添加监控源（选择组织后 URL 会自动填充）\n"
                "2. 回到这里点【🔍 立即抓取】\n"
                "3. 抓取结果会分组织/项目/事件三类展示，勾选后点【✅ 应用选中项】"
            )
        else:
            stats = pending.get("stats", {})
            st.markdown("---")
            # ★ 改动点 3：显示模式（仅当天 / 全部）
            st.caption(
                f"📅 抓取时间：{stats.get('timestamp', '—')}  ·  "
                f"模式：{'仅当天' if stats.get('today_only') else '全部'}  ·  "
                f"扫描源 {stats.get('sources_scanned', 0)} 个  ·  "
                f"新文章 {stats.get('articles_new', 0)} 篇"
            )

            if pending.get("errors"):
                with st.expander(f"⚠️ {len(pending['errors'])} 条抓取错误"):
                    for e in pending["errors"][:30]:
                        st.write(f"- {e}")

            # 过滤：隐藏 source_url 已解析过的事件
            try:
                from scripts.monitor_runner import is_url_scraped as _is_url_scraped
            except Exception:
                _is_url_scraped = None

            org_list_all = pending.get("orgs", [])
            prog_list_all = pending.get("progs", [])
            evt_list_all = pending.get("events", [])

            evt_list_filtered = []
            skipped_scraped = 0
            for e in evt_list_all:
                src_url = (e.get("_source_url") or e.get("source_url") or "").strip()
                if _is_url_scraped and src_url and _is_url_scraped(driver, src_url):
                    skipped_scraped += 1
                    continue
                evt_list_filtered.append(e)

            if skipped_scraped:
                st.info(f"ℹ️ 已自动隐藏 **{skipped_scraped}** 条 source_url 已解析过的事件。")

            search_kw = st.text_input(
                "🔎 按 canonical_name 搜索（组织 / 项目），或按标题/组织搜索事件",
                value="",
                key="monitor_search_kw",
                placeholder="例如: APT、BiomX、BX211、Salmonella...",
            ).strip().lower()

            org_list = org_list_all
            prog_list = prog_list_all
            evt_list = evt_list_filtered

            if search_kw:
                org_list = [
                    o for o in org_list
                    if search_kw in (o.get("canonical_name") or "").lower()
                ]
                prog_list = [
                    p for p in prog_list
                    if search_kw in (p.get("canonical_name") or "").lower()
                ]
                evt_list = [
                    e for e in evt_list
                    if search_kw in (e.get("title") or "").lower()
                    or search_kw in (e.get("organization_name") or "").lower()
                ]
                st.caption(
                    f"🔎 关键词 `{search_kw}` — "
                    f"命中 {len(org_list)} 组织 / {len(prog_list)} 项目 / {len(evt_list)} 事件"
                )

            st.markdown("---")

            # 组织
            st.markdown(f"#### 🏢 组织 ({len(org_list)} 条)")
            if not org_list:
                st.caption("无")
                edited_orgs = []
            else:
                df_org = _build_review_df(org_list, "org")
                edited_orgs_df = st.data_editor(
                    df_org,
                    column_config=_org_col_config(),
                    num_rows="dynamic",
                    width="stretch",
                    key="monitor_org_editor",
                )
                edited_orgs = _df_to_records(edited_orgs_df, org_list, "org")

            # 项目
            st.markdown(f"#### 📦 项目 / 管线 ({len(prog_list)} 条)")
            if not prog_list:
                st.caption("无")
                edited_progs = []
            else:
                df_prog = _build_review_df(prog_list, "prog")
                edited_progs_df = st.data_editor(
                    df_prog,
                    column_config=_prog_col_config(),
                    num_rows="dynamic",
                    width="stretch",
                    key="monitor_prog_editor",
                )
                edited_progs = _df_to_records(edited_progs_df, prog_list, "prog")

            # 事件
            st.markdown(f"#### 📰 事件 ({len(evt_list)} 条)")
            if not evt_list:
                st.caption("无")
                edited_events = []
            else:
                df_evt = _build_review_df(evt_list, "evt")
                edited_events_df = st.data_editor(
                    df_evt,
                    column_config=_evt_col_config(),
                    num_rows="dynamic",
                    width="stretch",
                    key="monitor_evt_editor",
                )
                edited_events = _df_to_records(edited_events_df, evt_list, "evt")

            st.markdown("---")
            col_a1, col_a2 = st.columns([3, 1])
            with col_a1:
                btn_apply = st.button(
                    "✅ 应用选中项（写入图谱）",
                    type="primary", width="stretch", key="monitor_apply_btn",
                )
            with col_a2:
                n_sel = (
                    sum(1 for r in edited_orgs if r.get("_selected")) +
                    sum(1 for r in edited_progs if r.get("_selected")) +
                    sum(1 for r in edited_events if r.get("_selected"))
                )
                st.metric("已勾选", n_sel)

            if btn_apply:
                sel_orgs = [r for r in edited_orgs if r.get("_selected")]
                sel_progs = [r for r in edited_progs if r.get("_selected")]
                sel_events = [r for r in edited_events if r.get("_selected")]

                if not (sel_orgs or sel_progs or sel_events):
                    st.warning("请先勾选至少一条记录")
                else:
                    sel_orgs = [_strip_internal(r, "org") for r in sel_orgs]
                    sel_progs = [_strip_internal(r, "prog") for r in sel_progs]
                    sel_events = [_strip_internal(r, "evt") for r in sel_events]

                    with st.spinner("正在写入图谱..."):
                        stats_apply = _apply_reviewed(
                            driver, sel_orgs, sel_progs, sel_events,
                            pending.get("errors", []),
                        )

                    st.success(
                        f"✅ 写入完成："
                        f"新建企业 {stats_apply['org_created']} · "
                        f"复用 {stats_apply['org_reused']} · "
                        f"新建项目 {stats_apply['prog_created']} · "
                        f"新建事件 {stats_apply['event_created']} · "
                        f"跳过重复 {stats_apply['event_skipped']}"
                    )
                    if stats_apply.get("errors"):
                        with st.expander(f"⚠️ {len(stats_apply['errors'])} 条错误"):
                            for e in stats_apply["errors"][:30]:
                                st.write(f"- {e}")

                    applied_org_names = {r.get("canonical_name") for r in sel_orgs}
                    applied_prog_names = {r.get("canonical_name") for r in sel_progs}
                    applied_evt_keys = {
                        (r.get("organization_name"), r.get("title"), r.get("event_date"))
                        for r in sel_events
                    }
                    pending["orgs"] = [
                        o for o in pending.get("orgs", [])
                        if o.get("canonical_name") not in applied_org_names
                    ]
                    pending["progs"] = [
                        p for p in pending.get("progs", [])
                        if p.get("canonical_name") not in applied_prog_names
                    ]
                    pending["events"] = [
                        e for e in pending.get("events", [])
                        if (e.get("organization_name"), e.get("title"),
                            e.get("event_date")) not in applied_evt_keys
                    ]

                    st.session_state["monitor_pending"] = pending
                    _save_pending(pending)

                    st.info(
                        f"剩余待审：{len(pending['orgs'])} 组织 / "
                        f"{len(pending['progs'])} 项目 / "
                        f"{len(pending['events'])} 事件"
                    )
                    st.rerun()


ci_mode(driver)