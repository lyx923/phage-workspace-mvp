# scripts/monitor_runner.py
"""
公司项目 & 事件持续监控
支持：通用网页抓取 / 微信公众号合集 / 搜狗微信搜索关键词
"""
import os
import sys
import re
import time
import json
import html
import uuid
import hashlib
import argparse
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, parse_qs, urlencode, quote
from typing import Optional, List, Dict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import requests
from openai import OpenAI
from config import get_driver, Config
from src.ci.organization_service import create_organization
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event
from src.shared.source_artifact_service import create_source_artifact
from src.shared.monitor_cache import (
    get_cached, set_cached, mark_persisted, mark_persisted_by_url, cache_status,
)


# ============================================================
# 时间范围判断
# ============================================================

TIME_FILTER_DAYS = {"today": 1, "week": 7, "month": 30, "all": None}
VALID_TIME_FILTERS = tuple(TIME_FILTER_DAYS.keys())


def parse_publish_time(pt: str):
    """
    把搜狗/微信/通用页面里的发布时间字符串解析成 date 对象。
    无法可靠解析时返回 None。
    """
    if not pt:
        return None
    pt = str(pt).strip()
    if not pt:
        return None

    today = datetime.now().date()

    # --- ★ 搜狗列表页的 JS 时间戳：document.write(timeConvert('1788859380')) ---
    m = re.search(r"timeConvert\(\s*['\"]?(\d{9,13})['\"]?\s*\)", pt)
    if m:
        raw_ts = m.group(1)
        try:
            if len(raw_ts) == 13:           # 毫秒
                ts = int(raw_ts) / 1000
            else:                            # 10 位秒级
                ts = int(raw_ts)
            return datetime.fromtimestamp(ts).date()
        except Exception:
            return None

    # --- 裸数字时间戳（10 位秒 或 13 位毫秒） ---
    if re.fullmatch(r"\d{10}", pt):
        try:
            return datetime.fromtimestamp(int(pt)).date()
        except Exception:
            return None
    if re.fullmatch(r"\d{13}", pt):
        try:
            return datetime.fromtimestamp(int(pt) / 1000).date()
        except Exception:
            return None

    # --- 相对时间：刚刚 / 分钟前 / 小时前 ---
    if pt in ("刚刚", "刚才", "刚刚发布", "刚刚更新", "刚刚发表"):
        return today

    m = re.match(r"^(\d+)\s*分钟前", pt)
    if m:
        return today

    m = re.match(r"^(\d+)\s*小时前", pt)
    if m:
        return today

    # --- 相对时间：昨天 / 前天 ---
    if pt in ("昨天", "昨日"):
        return today - timedelta(days=1)
    if pt in ("前天",):
        return today - timedelta(days=2)

    # --- 相对时间：X天前 / X周前 / X月前 / X年前 ---
    m = re.match(r"^(\d+)\s*天前", pt)
    if m:
        return today - timedelta(days=int(m.group(1)))

    m = re.match(r"^(\d+)\s*周前", pt)
    if m:
        return today - timedelta(days=int(m.group(1)) * 7)

    m = re.match(r"^(\d+)\s*个?月前", pt)
    if m:
        n = int(m.group(1))
        y, mo = today.year, today.month - n
        while mo <= 0:
            mo += 12
            y -= 1
        try:
            return datetime(y, mo, min(today.day, 28)).date()
        except Exception:
            return None

    m = re.match(r"^(\d+)\s*年前", pt)
    if m:
        try:
            return datetime(today.year - int(m.group(1)), today.month,
                            min(today.day, 28)).date()
        except Exception:
            return None

    # --- ISO：2024-09-19T10:30:00 / 2024-09-19 10:30:00 ---
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[T\s]", pt)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)),
                            int(m.group(3))).date()
        except Exception:
            return None

    # --- 标准日期格式：2024-09-19 / 2024/9/19 / 2024.9.19 ---
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", pt)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)),
                            int(m.group(3))).date()
        except Exception:
            return None

    # --- 中文日期：2024年9月19日 ---
    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", pt)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)),
                            int(m.group(3))).date()
        except Exception:
            return None

    # --- 只有月日（没年份）：09月19日 / 9月19日 / 09-19 / 9/19 ---
    m = re.match(r"^(\d{1,2})\s*月\s*(\d{1,2})\s*日", pt)
    if not m:
        m = re.match(r"^(\d{1,2})[-/](\d{1,2})$", pt)
    if m:
        try:
            mo, day = int(m.group(1)), int(m.group(2))
            cand = datetime(today.year, mo, day).date()
            if cand > today:
                cand = datetime(today.year - 1, mo, day).date()
            return cand
        except Exception:
            return None

    return None


def is_in_time_range(publish_time: str, time_filter: str = "today") -> bool:
    if time_filter == "all":
        return True
    days_back = TIME_FILTER_DAYS.get(time_filter, 1)
    if days_back is None:
        return True
    d = parse_publish_time(publish_time)
    if d is None:
        print(f"        ⚠️  时间无法解析，默认过滤: {publish_time!r}")
        return False
    today = datetime.now().date()
    cutoff = today - timedelta(days=days_back - 1)
    return d >= cutoff


def is_today(publish_time: str) -> bool:
    return is_in_time_range(publish_time, "today")


# ============================================================
# 监控源序列化辅助
# ============================================================

def build_sogou_url(org_name: str) -> str:
    # ★ 与手动可用 URL 参数顺序保持一致：type, s_from, query, ie, _sug_, _sug_type_
    parts = [
        ("type", "2"),
        ("s_from", "input"),
        ("query", org_name),
        ("ie", "utf8"),
        ("_sug_", "n"),
        ("_sug_type_", ""),
    ]
    return "https://weixin.sogou.com/weixin?" + urlencode(parts)


def _source_to_json(src: dict) -> str:
    return json.dumps({
        "url": src.get("url", ""),
        "type": src.get("type", "mixed"),
        "label": src.get("label", ""),
    }, ensure_ascii=False)


def _source_from_any(raw) -> Optional[dict]:
    if isinstance(raw, dict):
        return {
            "url": raw.get("url", ""),
            "type": raw.get("type", "mixed"),
            "label": raw.get("label", ""),
        }
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.startswith("{"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    return {
                        "url": obj.get("url", ""),
                        "type": obj.get("type", "mixed"),
                        "label": obj.get("label", ""),
                    }
            except Exception:
                pass
        return {"url": s, "type": "mixed", "label": "通用"}
    return None


def _make_source_id(owner_id: Optional[str], url: str) -> str:
    key = f"{owner_id or '__global__'}|{url or ''}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:14]
    return f"src-{h}"


def _guess_label_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        q = parse_qs(p.query)
        kw = (q.get("query", [""])[0] or "").strip()
        if kw:
            return kw
        host = (p.netloc or "").replace("www.", "")
        tail = [seg for seg in (p.path or "").split("/") if seg]
        if tail:
            return f"{host}/{tail[-1]}" if host else tail[-1]
        return host
    except Exception:
        return ""


# ============================================================
# HTTP
# ============================================================

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return s


def fetch_html(session, url: str, timeout: int = 20) -> Optional[str]:
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        return r.text
    except Exception as e:
        print(f"    ❌ 抓取失败: {e}")
        return None


def html_to_text(raw_html: str) -> str:
    h = re.sub(r"<!--.*?-->", " ", raw_html, flags=re.DOTALL)
    h = re.sub(r"<script[^>]*>.*?</script>", " ", h, flags=re.DOTALL | re.IGNORECASE)
    h = re.sub(r"<style[^>]*>.*?</style>", " ", h, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", h)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
           .replace("&quot;", '"').replace("&#39;", "'")
           .replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", t).strip()


def extract_links(raw_html: str, base_url: str, same_host: bool = True) -> List[Dict]:
    links = []
    base_host = urlparse(base_url).netloc
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                         raw_html, flags=re.DOTALL | re.IGNORECASE):
        href, text_raw = m.groups()
        href = html.unescape(href).strip()
        text = re.sub(r"<[^>]+>", "", text_raw).strip()
        text = re.sub(r"\s+", " ", text)
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        full = urljoin(base_url, href)
        if same_host and urlparse(full).netloc != base_host:
            continue
        if any(x in full.lower() for x in ("/tag/", "/category/", "/author/", "/page/",
                                            "/privacy", "/terms", "/contact", "/login")):
            continue
        if len(text) < 8:
            continue
        links.append({"url": full, "title": text})
    seen = set()
    unique = []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            unique.append(l)
    return unique


# ============================================================
# LLM 抽取
# ============================================================

_SYS_PROMPT = """你是竞争情报抽取助手。请从给定网页文本中抽取结构化信息，输出严格的 JSON。

严禁编造：只抽取文本中明确出现的信息，无法确定的字段填空字符串或空数组。
输出必须是合法 JSON，不要任何 Markdown 代码块标记。
重要：控制输出规模，宁可少而精，避免超长输出导致被截断。"""

_USER_TMPL = """网页 URL：{url}
网页标题：{title}

网页正文：
{content}

请按以下 JSON 结构输出抽取结果：

{{
  "organizations": [
    {{"canonical_name": "", "organization_type": "biotech/pharma/academic/CRO/tech/food_safety/other",
      "aliases": [], "headquarters_country": "", "website": "", "description": ""}}
  ],
  "programs": [
    {{"canonical_name": "", "organization_name": "",
      "program_type": "therapeutic/diagnostic/platform/research/food_safety",
      "development_stage": "discovery/preclinical/phase_1/phase_1_2/phase_2/phase_2b/phase_3/commercial",
      "modality": "natural_phage/engineered_phage/cocktail/software",
      "target_pathogen_species": [],
      "program_status": "active/discontinued/paused",
      "intended_effects": [],
      "notes": "关于该项目的关键事实（可选）"}}
  ],
  "events": [
    {{"event_type": "regulatory_update/funding/acquisition/merger/partnership/clinical_trial_update/publication/patent_event/pipeline_update",
      "title": "（不超过 40 字）", "factual_summary": "（不超过 150 字）",
      "organization_name": "", "program_name": "",
      "event_date": "YYYY-MM-DD", "published_at": "YYYY-MM-DD",
      "source_url": "该事件的原始来源 URL（若正文中明确出现，否则填空字符串）"}}
  ]
}}

规则：
- event_type 必须从枚举中选一个最接近的
- 日期统一 YYYY-MM-DD；只有年月 → 当月 1 日；只有年 → 1 月 1 日
- organizations 至少包含 events 里出现的全部机构名称
- ★ source_url 只填正文里明确出现的原文链接，不要编造
- 若信息缺失返回空数组
- ★ 输出规模：organizations ≤ 8，programs ≤ 12，events ≤ 12
- 只输出 JSON"""


def _repair_json(s: str) -> Optional[dict]:
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    max_trim = min(1500, len(s) - 10)
    for trim in range(max_trim):
        cand = s if trim == 0 else s[:-trim]
        cand = cand.rstrip()
        while cand and cand[-1] in ",:":
            cand = cand[:-1].rstrip()
        in_str = False
        esc = False
        for ch in cand:
            if esc:
                esc = False; continue
            if ch == "\\":
                esc = True; continue
            if ch == '"':
                in_str = not in_str
        if in_str:
            cand += '"'
        ob = cand.count("[") - cand.count("]")
        oc = cand.count("{") - cand.count("}")
        if ob < 0 or oc < 0:
            continue
        cand = cand + ("]" * ob) + ("}" * oc)
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def extract_with_llm(url: str, title: str, content: str, max_chars: int = 6000) -> dict:
    client = OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)
    user_prompt = _USER_TMPL.format(url=url, title=title, content=content[:max_chars])
    resp = client.chat.completions.create(
        model=Config.DS_MODEL,
        messages=[
            {"role": "system", "content": _SYS_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8000,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = _repair_json(raw)
        if fixed is not None:
            fixed["_repaired"] = True
            return fixed
        return {"organizations": [], "programs": [], "events": [],
                "_parse_error": raw[-200:]}


# ============================================================
# 匹配
# ============================================================

def find_org_exact(driver, name: str, url: str = None):
    if not name and not url:
        return None
    name_norm = (name or "").strip().lower()
    with driver.session() as s:
        if name_norm:
            r = s.run("""
                MATCH (o:Organization)
                WHERE toLower(o.canonical_name) = $name
                   OR ANY(alias IN o.aliases WHERE toLower(alias) = $name)
                RETURN o.organization_id AS id LIMIT 1
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
                        WHERE o.website IS NOT NULL AND toLower(o.website) CONTAINS $host
                        RETURN o.organization_id AS id LIMIT 1
                    """, host=host).single()
                    if r:
                        return r["id"]
            except Exception:
                pass
    return None


def find_program_full(driver, name: str) -> Optional[dict]:
    if not name:
        return None
    with driver.session() as s:
        r = s.run("""
            MATCH (d:DevelopmentProgram)
            WHERE toLower(d.canonical_name) = toLower($name)
            RETURN d.program_id AS id, d.canonical_name AS name,
                   d.development_stage AS stage, d.program_status AS status,
                   d.modality AS modality, d.program_type AS program_type
            LIMIT 1
        """, name=name.strip()).single()
        return dict(r) if r else None


def is_url_scraped(driver, url: str) -> bool:
    if not url:
        return False
    url_norm = _normalize_url(url)
    with driver.session() as s:
        r = s.run("""
            MATCH (sa:SourceArtifact)
            WHERE sa.url = $url OR sa.url = $url_norm
            RETURN sa.source_id AS id LIMIT 1
        """, url=url, url_norm=url_norm).single()
        return r is not None


def _event_source_already_scraped(driver, event: dict) -> bool:
    if not event:
        return False
    src_url = (event.get("source_url") or event.get("url") or "").strip()
    if not src_url:
        return False
    return is_url_scraped(driver, src_url)


def _normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        q = parse_qs(p.query)
        drop = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                "utm_term", "fbclid", "gclid", "from"}
        keep = {k: v[0] for k, v in q.items() if k not in drop}
        return f"{p.scheme}://{p.netloc}{p.path}{'?' + urlencode(keep) if keep else ''}"
    except Exception:
        return url


def str_to_list(s) -> list:
    if not s:
        return []
    if isinstance(s, list):
        return [str(x).strip() for x in s if str(x).strip()]
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<.*?>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[\r\n\t]", "", text)
    return text.strip()


# ============================================================
# 搜狗微信搜索
# ============================================================

def _extract_sogou_real_url(sogou_link: str, session) -> str:
    if not sogou_link:
        return ""

    sogou_link = html.unescape(sogou_link).strip()
    if sogou_link.startswith("//"):
        sogou_link = "https:" + sogou_link
    elif sogou_link.startswith("/"):
        sogou_link = urljoin("https://weixin.sogou.com", sogou_link)

    if not sogou_link.startswith("http"):
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://weixin.sogou.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = session.get(sogou_link, headers=headers, timeout=15,
                           allow_redirects=True)
        final_url = resp.url
        text = resp.text

        if "mp.weixin.qq.com" in final_url:
            return final_url

        parts = re.findall(r"url\s*\+=\s*['\"]([^'\"]+)['\"]", text)
        if parts:
            candidate = "".join(parts).replace("@", "")
            if "mp.weixin.qq.com" in candidate:
                return candidate
            if candidate.startswith("http"):
                return candidate

        m = re.search(r"(https?://mp\.weixin\.qq\.com/s[^\s\"'<>\\]+)", text)
        if m:
            return html.unescape(m.group(1))

        m = re.search(
            r'<meta[^>]+property="og:url"[^>]+content="([^"]+)"',
            text, re.IGNORECASE
        )
        if m:
            return html.unescape(m.group(1))

        print(f"     ⚠️ 未能解析真实URL（页面片段）：{re.sub(chr(10), ' ', text)[:120]}")
    except Exception as e:
        print(f"     ⚠️ 请求搜狗跳转页失败: {e}")

    return ""


def _parse_sogou_articles(html_text: str, session) -> list:
    articles = []

    blocks = re.findall(
        r'<li[^>]*id="sogou_vr_11002601_box_\d+"[^>]*>(.*?)</li>',
        html_text, re.DOTALL
    )
    if not blocks:
        blocks = re.findall(
            r'<div\s+class="txt-box"[^>]*>(.*?)(?=<div\s+class="txt-box"|<div\s+class="footer|</ul>\s*</div>)',
            html_text, re.DOTALL
        )
    if not blocks:
        blocks = re.findall(
            r'(<h3>\s*<a[^>]+href="[^"]+"[^>]*>.*?</a>\s*</h3>.*?<p\s+class="txt-info".*?</p>)',
            html_text, re.DOTALL
        )
    if not blocks:
        blocks = re.findall(
            r'(<h3>[^<]*<a[^>]+href="[^"]+"[^>]*>.*?</a>[^<]*</h3>.*?<p[^>]*>.*?</p>)',
            html_text, re.DOTALL
        )

    print(f"     🔍 解析器切到 {len(blocks)} 个候选块")

    for idx, block in enumerate(blocks):
        try:
            tm = re.search(
                r'<h3>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>',
                block, re.DOTALL
            )
            if not tm:
                tm = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                               block, re.DOTALL)
                if not tm:
                    continue

            sogou_link = html.unescape(tm.group(1).strip())
            title = _clean_html(tm.group(2))
            if not title or not sogou_link:
                continue

            sm = re.search(r'<p\s+class="txt-info"[^>]*>(.*?)</p>',
                           block, re.DOTALL)
            summary = _clean_html(sm.group(1)) if sm else ""

            am = re.search(r'<a[^>]+class="account"[^>]*>(.*?)</a>',
                           block, re.DOTALL)
            account = _clean_html(am.group(1)) if am else ""

            publish_time = ""
            for tpat in [
                r'<span\s+class="s2"[^>]*>(.*?)</span>',
                r'<span\s+class="all-time-y2"[^>]*>(.*?)</span>',
                r'<span[^>]*class="[^"]*time[^"]*"[^>]*>(.*?)</span>',
                r'<span[^>]*class="s-p"[^>]*>.*?<span[^>]*>(.*?)</span>',
            ]:
                tmm = re.search(tpat, block, re.DOTALL)
                if tmm:
                    publish_time = _clean_html(tmm.group(1))
                    if publish_time:
                        break

            if not publish_time:
                tmm = re.search(r'(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})', block)
                if tmm:
                    publish_time = tmm.group(1)
                else:
                    tmm = re.search(
                        r'(\d+\s*(?:分钟|小时|天|周|个月|年)前|昨天|前天|刚刚)',
                        block
                    )
                    if tmm:
                        publish_time = tmm.group(1)
                if not publish_time:
                    tmm = re.search(r'\b(1[5-9]\d{8}|1[5-9]\d{11})\b', block)
                    if tmm:
                        publish_time = tmm.group(1)

            articles.append({
                "title": title,
                "summary": summary,
                "account": account,
                "publish_time": publish_time,
                "sogou_link": sogou_link,
            })
        except Exception as e:
            print(f"     ⚠️ 解析第 {idx} 块失败: {e}")
            continue

    return articles


def _collect_sogou_wechat(driver, session, source, owner_org_id, collected,
                          time_filter: str = "today"):
    """
    ★ 核心修复：
      1. 不注入 tsn 参数（搜狗加了 tsn 会跳回首页）
      2. 参数顺序与手动可用 URL 一致
      3. 时间过滤完全依赖客户端 is_in_time_range()
      4. 不往项目里写任何 debug 文件
      5. ★ 智能翻页：本页 < 10 条 或 与上一页重复 → 停止
    """
    base_url = source["url"].strip()
    if not base_url:
        collected["errors"].append("搜狗搜索 URL 为空")
        return collected

    parsed = urlparse(base_url)
    keyword = (parse_qs(parsed.query).get("query", [""])[0] or "").strip()
    if not keyword:
        collected["errors"].append("搜狗搜索 URL 缺少 query 参数")
        return collected

    print(f"     🔑 关键词: {keyword}（时间范围：{time_filter}）")

    try:
        session.get("https://weixin.sogou.com", timeout=15)
        print(f"     ✅ 已获取搜狗初始Cookie")
    except Exception as e:
        collected["errors"].append(f"搜狗首页访问失败: {e}")
        return collected

    sogou_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://weixin.sogou.com/",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    max_pages = 6
    any_in_range = False
    seen_sogou_links = set()      # ★ 跨页去重：记录已经见过的 sogou_link

    for page in range(1, max_pages + 1):
        q = [
            ("type", "2"),
            ("s_from", "input"),
            ("query", keyword),
            ("ie", "utf8"),
            ("_sug_", "n"),
            ("_sug_type_", ""),
        ]
        if page > 1:
            q.append(("page", str(page)))

        req_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?" + urlencode(q)
        print(f"     📄 第 {page} 页: {req_url[:160]}")

        try:
            resp = session.get(req_url, headers=sogou_headers, timeout=20)

            resp.encoding = "utf-8"
            html_text = resp.text
            if "搜狗" not in html_text and "微信" not in html_text:
                resp.encoding = "gb18030"
                html_text = resp.text
            if "搜狗" not in html_text and "微信" not in html_text:
                resp.encoding = resp.apparent_encoding or "utf-8"
                html_text = resp.text

            print(f"     📊 HTTP {resp.status_code} 长度={len(html_text)} "
                  f"含txt-box={'txt-box' in html_text} "
                  f"含sogou_vr={'sogou_vr' in html_text} "
                  f"含news-list={'news-list' in html_text}")

            # 反爬检测
            for kw in ("请输入验证码", "访问过于频繁", "反爬虫", "请输入验证码后继续"):
                if kw in html_text:
                    print(f"     ⚠️ 第 {page} 页触发反爬：{kw}")
                    collected["errors"].append(
                        f"搜狗第 {page} 页触发反爬：{kw}"
                    )
                    return collected

            # 跳首页检测
            if ('id="vrResultContainer"' in html_text
                    and "news-list" not in html_text
                    and "txt-box" not in html_text):
                print(f"     ⚠️ 搜狗返回首页（关键词 '{keyword}' 可能无结果）")
                if page == 1:
                    collected["errors"].append(
                        f"搜狗返回首页（关键词 '{keyword}' 可能无结果）"
                    )
                break

            articles = _parse_sogou_articles(html_text, session)

            if not articles:
                print(f"     📭 第 {page} 页未解析到文章")
                if page == 1:
                    class_set = sorted(set(re.findall(r'class="([^"]+)"', html_text)))
                    print(f"     🔬 HTML 里的 class 种类（前 40）：{class_set[:40]}")
                    collected["errors"].append("搜狗第 1 页未解析到文章")
                break

            # ★ 计算本页"新文章"（去掉前面页已经见过的）
            new_articles = []
            for a in articles:
                link = a.get("sogou_link", "")
                if link and link not in seen_sogou_links:
                    new_articles.append(a)
                    seen_sogou_links.add(link)

            print(f"     📋 第 {page} 页解析到 {len(articles)} 篇文章"
                  f"（其中新文章 {len(new_articles)} 篇）")

            # ★ 如果整页内容都是重复的（page>1），说明搜狗在重复返回最后一页
            if page > 1 and not new_articles:
                print(f"     ⏹️  第 {page} 页全部为重复内容，停止翻页")
                break

            # 处理本页新文章
            for art in new_articles:
                sogou_link = art.get("sogou_link", "")
                if not sogou_link:
                    continue

                if time_filter != "all":
                    pt = art.get("publish_time", "")
                    if not is_in_time_range(pt, time_filter):
                        parsed_d = parse_publish_time(pt)
                        print(f"        ⏭️  超出时间范围，跳过: "
                              f"{art.get('title','')[:40]} | 原文时间={pt!r} | 解析={parsed_d}")
                        continue
                    any_in_range = True

                real_url = _extract_sogou_real_url(sogou_link, session)
                if not real_url or "mp.weixin.qq.com" not in real_url:
                    print(f"        ⏭️  跳过（无法还原微信链接）: {art.get('title','')[:40]}")
                    continue

                if is_url_scraped(driver, real_url):
                    print(f"        ♻️  URL 已入库，跳过: {art.get('title','')[:40]}")
                    continue

                collected["articles_new"] += 1

                raw = fetch_html(session, real_url)
                if not raw:
                    continue

                text = html_to_text(raw)
                title = art.get("title", "")
                pt = art.get("publish_time", "")
                _collect_one_page(driver, real_url, title, text,
                                  owner_org_id, source, collected,
                                  publish_time=pt)
                time.sleep(3)

            # ★ 关键：本页结果不足 10 条 → 搜狗已经到末页 → 停止翻页
            if len(articles) < 10:
                print(f"     ⏹️  第 {page} 页只有 {len(articles)} 条结果（<10），已到末页，停止翻页")
                break

            time.sleep(5)

        except Exception as e:
            collected["errors"].append(f"搜狗第 {page} 页异常: {e}")
            traceback.print_exc()
            break

    if time_filter != "all" and not any_in_range:
        print(f"     ℹ️  本次共翻若干页，未找到 {time_filter} 范围内的文章")

    return collected


# ============================================================
# 变化检测
# ============================================================

STAGE_ORDER = {
    "discovery": 0, "preclinical": 1,
    "phase_1": 2, "phase_1_2": 3,
    "phase_2": 4, "phase_2b": 5, "phase_3": 6,
    "commercial": 7, "approved": 8,
    "discontinued": -1, "paused": -1,
}


def detect_program_changes(driver, url: str, org_id: str,
                            program_data: dict, stats: dict) -> int:
    pname = program_data.get("canonical_name", "").strip()
    if not pname:
        return 0
    existing = find_program_full(driver, pname)
    if not existing:
        return 0

    changes = []
    new_stage = program_data.get("development_stage", "").strip()
    old_stage = (existing.get("stage") or "").strip()
    if new_stage and old_stage and new_stage != old_stage:
        old_o = STAGE_ORDER.get(old_stage, -2)
        new_o = STAGE_ORDER.get(new_stage, -2)
        direction = "推进" if new_o > old_o else "回退" if new_o >= 0 else "变更"
        changes.append({
            "field": "development_stage",
            "summary": f"阶段{direction}: {old_stage} → {new_stage}",
        })

    new_status = program_data.get("program_status", "").strip()
    old_status = (existing.get("status") or "").strip()
    if new_status and old_status and new_status != old_status:
        changes.append({
            "field": "program_status",
            "summary": f"状态变化: {old_status} → {new_status}",
        })

    if not changes:
        return 0

    change_desc = "；".join(c["summary"] for c in changes)
    title = f"{pname} 项目更新：{change_desc}"
    if len(title) > 60:
        title = title[:57] + "..."

    factual_summary = f"项目 {pname} 监测到以下变化：" + "；".join(c["summary"] for c in changes)
    if len(factual_summary) > 300:
        factual_summary = factual_summary[:297] + "..."

    print(f"      🔄 检测到项目变化: {change_desc}")

    if stats.get("_dry_run"):
        return len(changes)

    try:
        src_id = create_source_artifact(
            driver, source_type="monitor_auto",
            title=title[:120],
            url=url, published_date=datetime.now().strftime("%Y-%m-%d"),
            credibility_tier="primary", actor_id="monitor_runner",
        )
        capture_intelligence_event(
            driver,
            event_type="pipeline_update",
            title=title,
            factual_summary=factual_summary,
            organization_id=org_id,
            program_id=existing["id"],
            event_date=datetime.now().strftime("%Y-%m-%d"),
            published_at=datetime.now().strftime("%Y-%m-%d"),
            source_ids=[src_id],
            actor_id="monitor_runner",
        )
        with driver.session() as s:
            s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                SET d.development_stage = COALESCE($stage, d.development_stage),
                    d.program_status = COALESCE($status, d.program_status),
                    d.last_updated_at = datetime()
            """, pid=existing["id"],
                 stage=program_data.get("development_stage") or None,
                 status=program_data.get("program_status") or None)
        stats["program_updated"] = stats.get("program_updated", 0) + 1
        stats["event_created"] = stats.get("event_created", 0) + 1
        return len(changes)
    except Exception as e:
        print(f"      ❌ 生成变更事件失败: {e}")
        stats.setdefault("errors", []).append(f"项目 {pname} 变更事件: {e}")
        return 0


# ============================================================
# 提交
# ============================================================

def commit_extracted(driver, source_url: str, orgs, progs, events,
                     stats: dict, owner_org_id: Optional[str] = None,
                     dry_run: bool = False) -> dict:
    for k in ("org_created", "org_reused", "prog_created", "prog_reused",
              "prog_changed", "program_updated", "event_created",
              "event_skipped", "event_failed"):
        stats.setdefault(k, 0)
    stats.setdefault("errors", [])

    org_id_map = {}

    for org in orgs:
        name = (org.get("canonical_name") or "").strip()
        if not name:
            continue
        existing = find_org_exact(driver, name, url=source_url)
        if existing:
            org_id_map[name] = existing
            stats["org_reused"] += 1
            continue
        if owner_org_id and len(orgs) == 1:
            org_id_map[name] = owner_org_id
            stats["org_reused"] += 1
            continue
        if dry_run:
            stats["org_created"] += 1
            continue
        try:
            oid = create_organization(
                driver, canonical_name=name,
                organization_type=org.get("organization_type") or "biotech",
                aliases=str_to_list(org.get("aliases", "")),
                headquarters_country=(org.get("headquarters_country") or "").strip() or None,
                website=(org.get("website") or "").strip() or None,
                description=(org.get("description") or "").strip() or None,
                actor_id="monitor_runner",
            )
            org_id_map[name] = oid
            stats["org_created"] += 1
        except Exception as e:
            stats["errors"].append(f"组织 '{name}': {e}")

    for evt in events:
        oname = (evt.get("organization_name") or "").strip()
        if oname and oname not in org_id_map:
            existing = find_org_exact(driver, oname, url=source_url)
            if existing:
                org_id_map[oname] = existing
            elif owner_org_id:
                org_id_map[oname] = owner_org_id
            elif not dry_run:
                try:
                    oid = create_organization(
                        driver, canonical_name=oname,
                        organization_type="biotech", aliases=[],
                        actor_id="monitor_runner",
                    )
                    org_id_map[oname] = oid
                    stats["org_created"] += 1
                except Exception as e:
                    stats["errors"].append(f"补建组织 '{oname}': {e}")

    for prog in progs:
        pname = (prog.get("canonical_name") or "").strip()
        oname = (prog.get("organization_name") or "").strip()
        if not pname:
            continue
        if owner_org_id:
            n_changes = detect_program_changes(driver, source_url, owner_org_id,
                                                prog, stats)
            if n_changes > 0:
                stats["prog_changed"] += 1
                continue
        oid = (org_id_map.get(oname)
               or (owner_org_id if owner_org_id else None)
               or find_org_exact(driver, oname, url=source_url))
        if not oid:
            if dry_run:
                stats["prog_created"] += 1
                continue
            stats["errors"].append(f"项目 '{pname}' 组织未找到")
            continue
        if find_program_full(driver, pname):
            stats["prog_reused"] += 1
            continue
        if dry_run:
            stats["prog_created"] += 1
            continue
        try:
            create_development_program(
                driver, organization_id=oid, canonical_name=pname,
                program_type=prog.get("program_type") or "therapeutic",
                development_stage=prog.get("development_stage") or "discovery",
                modality=(prog.get("modality") or "").strip() or None,
                target_pathogen_species=str_to_list(prog.get("target_pathogen_species", "")),
                actor_id="monitor_runner",
            )
            stats["prog_created"] += 1
        except Exception as e:
            stats["errors"].append(f"项目 '{pname}': {e}")

    for evt in events:
        oname = (evt.get("organization_name") or "").strip()
        oid = (org_id_map.get(oname)
               or (owner_org_id if owner_org_id else None)
               or find_org_exact(driver, oname, url=source_url))
        if not oid:
            stats["event_failed"] += 1
            stats["errors"].append(f"事件 '{evt.get('title','')}' 组织未找到")
            continue
        title = evt.get("title") or ""
        edate = evt.get("event_date") or ""
        if _event_exists(driver, oid, title, edate):
            stats["event_skipped"] += 1
            continue
        if dry_run:
            stats["event_created"] += 1
            continue
        pname = (evt.get("program_name") or "").strip()
        pid = None
        if pname:
            p = find_program_full(driver, pname)
            pid = p["id"] if p else None
        source_ids = []
        try:
            src_id = create_source_artifact(
                driver, source_type="monitor_auto",
                title=title[:120] or "auto",
                url=source_url,
                published_date=(evt.get("published_at") or edate or "unknown"),
                credibility_tier="secondary", actor_id="monitor_runner",
            )
            source_ids.append(src_id)
        except Exception:
            pass
        try:
            capture_intelligence_event(
                driver,
                event_type=evt.get("event_type") or "publication",
                title=title,
                factual_summary=evt.get("factual_summary") or "",
                organization_id=oid,
                program_id=pid,
                event_date=edate or None,
                published_at=evt.get("published_at") or None,
                source_ids=source_ids,
                actor_id="monitor_runner",
            )
            stats["event_created"] += 1
        except ValueError as e:
            if "重复" in str(e) or "已存在" in str(e):
                stats["event_skipped"] += 1
            else:
                stats["event_failed"] += 1
                stats["errors"].append(f"事件 '{title}': {e}")
        except Exception as e:
            stats["event_failed"] += 1
            stats["errors"].append(f"事件 '{title}': {e}")

    return stats


def _event_exists(driver, org_id: str, title: str, event_date: str) -> bool:
    if not org_id or not title:
        return False
    with driver.session() as s:
        r = s.run("""
            MATCH (e:IntelligenceEvent {organization_id: $oid})
            WHERE toLower(e.title) = toLower($title)
              AND COALESCE(e.event_date, '') = $date
            RETURN e.event_id AS id LIMIT 1
        """, oid=org_id, title=title, date=event_date or "").single()
        return r is not None


# ============================================================
# 处理单源
# ============================================================

def process_source(driver, session, source: dict, owner_org_id: Optional[str],
                   dry_run: bool = False,
                   time_filter: str = "today") -> dict:
    url = source.get("url", "").strip()
    stype = source.get("type", "mixed")
    label = source.get("label", stype)

    stats = {
        "source": url, "label": label, "type": stype,
        "org_created": 0, "org_reused": 0,
        "prog_created": 0, "prog_reused": 0, "prog_changed": 0,
        "program_updated": 0,
        "event_created": 0, "event_skipped": 0, "event_failed": 0,
        "errors": [], "_dry_run": dry_run,
    }

    print(f"  📡 [{label}] {url[:80]}")

    if stype == "sogou_wechat" or "weixin.sogou.com" in url:
        return _process_sogou_wechat(driver, session, source, owner_org_id,
                                     stats, dry_run, time_filter=time_filter)

    if stype == "wechat" or "mp.weixin.qq.com" in url:
        return _process_wechat(driver, session, source, owner_org_id, stats,
                               dry_run, time_filter=time_filter)

    raw = fetch_html(session, url)
    if not raw:
        stats["errors"].append("页面抓取失败")
        return stats

    text = html_to_text(raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.DOTALL | re.IGNORECASE)
    page_title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""

    links = extract_links(raw, url, same_host=True) if stype in ("news", "publications") else []

    candidate_links = []
    for l in links:
        if any(x in l["url"].lower() for x in ("/news/", "/press", "/blog/", "/article", "/insight")):
            candidate_links.append(l)

    if stype in ("news", "publications") and len(candidate_links) >= 2:
        print(f"     📋 列表页，发现 {len(candidate_links)} 个候选文章链接")
        for i, link in enumerate(candidate_links[:15], 1):
            art_url = link["url"]
            if is_url_scraped(driver, art_url):
                stats["event_skipped"] += 1
                continue
            print(f"     🆕 [{i}] {link['title'][:60]}")
            _process_article(driver, session, art_url, owner_org_id, stats, dry_run)
            time.sleep(2)
    else:
        _process_one_page(driver, url, page_title, text, owner_org_id, stats, dry_run)

    return stats


def _process_sogou_wechat(driver, session, source, owner_org_id, stats,
                          dry_run, time_filter: str = "today"):
    collected = _collect_sogou_wechat(driver, session, source, owner_org_id,
                                       {"orgs": [], "progs": [], "events": [],
                                        "errors": [], "articles_new": 0},
                                       time_filter=time_filter)

    if collected["orgs"] or collected["progs"] or collected["events"]:
        url = source.get("url", "")
        commit_extracted(driver, url,
                         collected["orgs"], collected["progs"], collected["events"],
                         stats, owner_org_id=owner_org_id, dry_run=dry_run)

    stats["errors"].extend(collected["errors"])
    return stats


def _process_article(driver, session, art_url: str, owner_org_id: Optional[str],
                     stats: dict, dry_run: bool):
    raw = fetch_html(session, art_url)
    if not raw:
        stats["errors"].append(f"抓取失败: {art_url}")
        return
    text = html_to_text(raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.DOTALL | re.IGNORECASE)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
    _process_one_page(driver, art_url, title, text, owner_org_id, stats, dry_run)


def _process_one_page(driver, url: str, title: str, text: str,
                      owner_org_id: Optional[str], stats: dict, dry_run: bool):
    try:
        result = extract_with_llm(url, title, text)
    except Exception as e:
        stats["errors"].append(f"LLM: {e}")
        return

    if result.get("_parse_error"):
        print(f"        ⚠️ JSON 解析失败")
    if result.get("_repaired"):
        print(f"        ℹ️ JSON 已自动修复")

    orgs = result.get("organizations", []) or []
    progs = result.get("programs", []) or []
    events = result.get("events", []) or []

    if not (orgs or progs or events):
        return

    if owner_org_id:
        with driver.session() as s:
            r = s.run("""
                MATCH (o:Organization {organization_id: $oid})
                RETURN o.canonical_name AS name
            """, oid=owner_org_id).single()
            default_name = r["name"] if r else None
        if default_name:
            for e in events:
                if not (e.get("organization_name") or "").strip():
                    e["organization_name"] = default_name
            for p in progs:
                if not (p.get("organization_name") or "").strip():
                    p["organization_name"] = default_name

    print(f"        → {len(orgs)}组织 / {len(progs)}项目 / {len(events)}事件")
    commit_extracted(driver, url, orgs, progs, events, stats,
                     owner_org_id=owner_org_id, dry_run=dry_run)


def _process_wechat(driver, session, source: dict, owner_org_id: Optional[str],
                    stats: dict, dry_run: bool,
                    time_filter: str = "today") -> dict:
    url = source["url"]
    if "/s?" in url or "/s/" in url:
        if is_url_scraped(driver, url):
            stats["event_skipped"] += 1
            return stats
        _process_article(driver, session, url, owner_org_id, stats, dry_run)
        return stats

    m = re.search(r"album_id=([^&]+)", url)
    biz_m = re.search(r"__biz=([^&]+)", url)
    if not m:
        stats["errors"].append("合集 URL 缺少 album_id")
        return stats
    album_id = m.group(1)
    biz = biz_m.group(1) if biz_m else ""

    api = (f"https://mp.weixin.qq.com/mp/appmsgalbum?action=getalbum&__biz={biz}"
           f"&album_id={album_id}&count=20&begin_msgid=&begin_itemidx=&is_reverse=1"
           f"&scene=173&subscene=159")
    try:
        r = session.get(api, timeout=20)
        data = r.json()
    except Exception as e:
        stats["errors"].append(f"合集接口: {e}")
        return stats

    articles = data.get("getalbum_resp", {}).get("article_list", []) or []
    print(f"     📋 合集找到 {len(articles)} 篇文章")

    new_count = 0
    for a in articles:
        if time_filter != "all":
            ct = a.get("create_time")
            if ct:
                try:
                    d = datetime.fromtimestamp(int(ct)).strftime("%Y-%m-%d")
                    if not is_in_time_range(d, time_filter):
                        print(f"        ⏭️  超出时间范围，跳过: {a.get('title','')[:40]}")
                        continue
                except Exception:
                    pass

        art_url = a.get("url") or (
            f"https://mp.weixin.qq.com/s?__biz={biz}&mid={a.get('msgid')}&idx={a.get('itemidx', 1)}"
        )
        if is_url_scraped(driver, art_url):
            stats["event_skipped"] += 1
            continue
        new_count += 1
        print(f"     🆕 [{new_count}] {a.get('title', '')[:60]}")
        _process_article(driver, session, art_url, owner_org_id, stats, dry_run)
        time.sleep(3)
        if new_count >= 10:
            break

    return stats


# ============================================================
# 监控源管理
# ============================================================

def _list_global_sources_raw(driver) -> List[dict]:
    with driver.session() as s:
        rs = s.run("""
            MATCH (g:GlobalMonitorSource)
            RETURN g.source_id AS source_id, g.url AS url,
                   g.type AS type, g.label AS label,
                   g.created_at AS created_at
            ORDER BY g.created_at DESC
        """)
        return [dict(r) for r in rs]


def get_all_monitor_sources(driver) -> List[dict]:
    result_list = []

    with driver.session() as s:
        rs = s.run("""
            MATCH (o:Organization)
            WHERE o.monitor_sources IS NOT NULL AND size(o.monitor_sources) > 0
            RETURN o.organization_id AS id, o.canonical_name AS name,
                   o.monitor_sources AS sources
        """)
        for r in rs:
            org_id = r["id"]
            org_name = r["name"]
            for raw in (r["sources"] or []):
                parsed = _source_from_any(raw)
                if not parsed or not parsed.get("url"):
                    continue
                label_txt = (parsed.get("label") or "").strip()
                if not label_txt or label_txt in ("通用", "全局源"):
                    label_txt = _guess_label_from_url(parsed["url"]) or org_name
                result_list.append({
                    "source_id": _make_source_id(org_id, parsed["url"]),
                    "owner_org_id": org_id,
                    "owner_name": org_name,
                    "url": parsed["url"],
                    "type": parsed.get("type", "mixed"),
                    "label": label_txt,
                })

    for g in _list_global_sources_raw(driver):
        url = (g.get("url") or "").strip()
        if not url:
            continue
        raw_label = (g.get("label") or "").strip()
        if not raw_label or raw_label == "全局源":
            raw_label = _guess_label_from_url(url) or "未命名"
        result_list.append({
            "source_id": _make_source_id(None, url),
            "owner_org_id": None,
            "owner_name": None,
            "url": url,
            "type": g.get("type") or "mixed",
            "label": raw_label,
        })

    return result_list


def add_global_source(url: str, stype: str = "sogou_wechat", label: str = ""):
    if stype not in VALID_TYPES:
        raise ValueError(f"未知 type: {stype}。可选: {sorted(VALID_TYPES)}")
    if not url or not url.strip():
        raise ValueError("URL 不能为空")
    url = url.strip()
    if not label or not label.strip():
        label = _guess_label_from_url(url) or "未命名"

    driver = get_driver()
    with driver.session() as s:
        r = s.run("""
            MATCH (g:GlobalMonitorSource {url: $url})
            RETURN g.source_id AS sid LIMIT 1
        """, url=url).single()
        if r:
            raise ValueError(f"该 URL 已存在，无需重复添加")

        sid = f"GSRC-{uuid.uuid4().hex[:12].upper()}"
        s.run("""
            CREATE (g:GlobalMonitorSource {
                source_id: $sid,
                url: $url,
                type: $type,
                label: $label,
                created_at: datetime()
            })
        """, sid=sid, url=url, type=stype, label=label)

    print(f"✅ 已添加监控源: [{stype}] {label} · {url}")
    return f"已添加监控源：{label}"


def remove_global_source(source_id: str):
    driver = get_driver()
    with driver.session() as s:
        r = s.run("""
            MATCH (g:GlobalMonitorSource {source_id: $sid})
            RETURN g.url AS url
        """, sid=source_id).single()
        if not r:
            raise ValueError(f"监控源 {source_id} 不存在")
        s.run("""
            MATCH (g:GlobalMonitorSource {source_id: $sid})
            DELETE g
        """, sid=source_id)
        return f"已删除: {r['url']}"


def get_global_source_node_id(driver, url: str) -> Optional[str]:
    if not url:
        return None
    with driver.session() as s:
        r = s.run("""
            MATCH (g:GlobalMonitorSource {url: $url})
            RETURN g.source_id AS sid LIMIT 1
        """, url=url).single()
        return r["sid"] if r else None


# ============================================================
# 主流程
# ============================================================

def get_monitored_orgs(driver, org_filter: Optional[str] = None,
                       type_filter: Optional[str] = None) -> List[dict]:
    with driver.session() as s:
        if org_filter:
            result = s.run("""
                MATCH (o:Organization {organization_id: $oid})
                WHERE o.monitor_sources IS NOT NULL AND size(o.monitor_sources) > 0
                RETURN o.organization_id AS id, o.canonical_name AS name,
                       o.monitor_sources AS sources, o.website AS website,
                       o.last_monitored_at AS last_monitored
            """, oid=org_filter)
        else:
            result = s.run("""
                MATCH (o:Organization)
                WHERE o.monitor_sources IS NOT NULL AND size(o.monitor_sources) > 0
                RETURN o.organization_id AS id, o.canonical_name AS name,
                       o.monitor_sources AS sources, o.website AS website,
                       o.last_monitored_at AS last_monitored
            """)
        orgs = [dict(r) for r in result]

    for o in orgs:
        srcs = []
        for raw in (o.get("sources") or []):
            parsed = _source_from_any(raw)
            if parsed:
                srcs.append(parsed)
        o["sources"] = srcs
        if type_filter:
            o["sources"] = [s for s in srcs if s.get("type") == type_filter]
    return [o for o in orgs if o["sources"]]


def run_once(org_filter: Optional[str] = None, type_filter: Optional[str] = None,
             source_id_filter: Optional[str] = None,
             dry_run: bool = False, sleep_between: float = 3.0,
             time_filter: str = "today"):
    driver = get_driver()
    session = make_session()
    started = datetime.now()

    print(f"\n{'='*70}")
    print(f"🔍 公司监控 - {started.strftime('%Y-%m-%d %H:%M:%S')}"
          f"（时间范围：{time_filter}）")
    print(f"{'='*70}")

    all_sources = get_all_monitor_sources(driver)
    if source_id_filter:
        all_sources = [s for s in all_sources if s["source_id"] == source_id_filter]
    if org_filter:
        all_sources = [s for s in all_sources if s["owner_org_id"] == org_filter]
    if type_filter:
        all_sources = [s for s in all_sources if s["type"] == type_filter]

    if not all_sources:
        print("📭 没有匹配的监控源。")
        return []

    print(f"📋 待监控源: {len(all_sources)}")

    all_stats = []
    for src in all_sources:
        print(f"\n📡 [{src['label']}] {src['url'][:80]}")

        try:
            stats = process_source(
                driver, session,
                {"url": src["url"], "type": src["type"], "label": src["label"]},
                src["owner_org_id"],
                dry_run, time_filter=time_filter,
            )
            all_stats.append(stats)
        except Exception as e:
            print(f"    ❌ 处理异常: {e}")
            traceback.print_exc()
        time.sleep(sleep_between)

        if not dry_run and src["owner_org_id"]:
            with driver.session() as s:
                s.run("""
                    MATCH (o:Organization {organization_id: $oid})
                    SET o.last_monitored_at = datetime()
                """, oid=src["owner_org_id"])

    total_events = sum(s.get("event_created", 0) for s in all_stats)
    total_prog_changed = sum(s.get("prog_changed", 0) for s in all_stats)
    total_prog_new = sum(s.get("prog_created", 0) for s in all_stats)
    total_skipped = sum(s.get("event_skipped", 0) for s in all_stats)
    total_errors = sum(len(s.get("errors", [])) for s in all_stats)
    elapsed = (datetime.now() - started).total_seconds()

    print(f"\n{'='*70}")
    print(f"✅ 完成")
    print(f"   新事件:       {total_events}")
    print(f"   新项目:       {total_prog_new}")
    print(f"   项目变化:     {total_prog_changed}")
    print(f"   跳过(已抓过): {total_skipped}")
    print(f"   错误:         {total_errors}")
    print(f"⏱️  耗时 {elapsed:.1f} 秒")
    print(f"{'='*70}\n")

    return all_stats


VALID_TYPES = {"news", "pipeline", "about", "wechat", "clinical_trials",
               "publications", "sec_filings", "twitter", "sogou_wechat", "mixed"}


def add_source(org_id: str, url: str = "", stype: str = "sogou_wechat", label: str = ""):
    if stype not in VALID_TYPES:
        raise ValueError(f"未知 type: {stype}。可选: {sorted(VALID_TYPES)}")

    driver = get_driver()
    with driver.session() as s:
        r = s.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.monitor_sources AS sources, o.canonical_name AS name
        """, oid=org_id).single()
        if not r:
            raise ValueError(f"组织 {org_id} 不存在，请检查 ID 是否正确")

        org_name = r["name"]

        if not url or not url.strip():
            url = build_sogou_url(org_name)

        if not label or not label.strip():
            label = _guess_label_from_url(url) or org_name

        src_json = _source_to_json({"url": url, "type": stype, "label": label})

        existing = r["sources"] or []
        existing_urls = []
        for raw in existing:
            parsed = _source_from_any(raw)
            if parsed:
                existing_urls.append(parsed.get("url", ""))
        if url in existing_urls:
            raise ValueError(f"该 URL 已存在于 {org_name}，无需重复添加")

        s.run("""
            MATCH (o:Organization {organization_id: $oid})
            SET o.monitor_sources = COALESCE(o.monitor_sources, []) + [$src]
        """, oid=org_id, src=src_json)

        print(f"✅ 已为 {org_name} 添加监控源: [{stype}] {url}")
        return f"已为 {org_name} 添加监控源"


def remove_source(org_id: str, url: str):
    driver = get_driver()
    with driver.session() as s:
        r = s.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.monitor_sources AS sources, o.canonical_name AS name
        """, oid=org_id).single()
        if not r:
            raise ValueError(f"组织 {org_id} 不存在")

        existing = r["sources"] or []
        kept = []
        removed = 0
        for raw in existing:
            parsed = _source_from_any(raw)
            if parsed and parsed.get("url") == url:
                removed += 1
                continue
            kept.append(raw)

        s.run("""
            MATCH (o:Organization {organization_id: $oid})
            SET o.monitor_sources = $kept
        """, oid=org_id, kept=kept)

        print(f"✅ 已从 {r['name']} 移除 {removed} 条: {url}")
        return f"已移除 {removed} 条，剩余 {len(kept)} 个"


def list_sources():
    driver = get_driver()
    srcs = get_all_monitor_sources(driver)
    if not srcs:
        print("📭 没有配置监控源")
        return
    print(f"\n📋 共 {len(srcs)} 个监控源:\n")
    for s_item in srcs:
        print(f"📡 [{s_item['type']}] {s_item['label']}")
        print(f"   URL:       {s_item['url']}")
        print(f"   source_id: {s_item['source_id']}")
        print()


# ============================================================
# 抓取到待审列表（不写库）
# ============================================================

def collect_for_review(org_filter: Optional[str] = None,
                       type_filter: Optional[str] = None,
                       source_id_filter: Optional[str] = None,
                       sleep_between: float = 2.0,
                       time_filter: str = "today") -> dict:
    driver = get_driver()
    session = make_session()
    started = datetime.now()

    print(f"\n{'='*70}")
    print(f"🔍 监控抓取（待审核）- {started.strftime('%Y-%m-%d %H:%M:%S')}"
          f"（时间范围：{time_filter}）")
    print(f"{'='*70}")

    all_sources = get_all_monitor_sources(driver)
    if source_id_filter:
        all_sources = [s for s in all_sources if s["source_id"] == source_id_filter]
    if org_filter:
        all_sources = [s for s in all_sources if s["owner_org_id"] == org_filter]
    if type_filter:
        all_sources = [s for s in all_sources if s["type"] == type_filter]

    if not all_sources:
        return {
            "orgs": [], "progs": [], "events": [],
            "stats": {"sources_scanned": 0, "articles_new": 0,
                      "time_filter": time_filter,
                      "timestamp": started.strftime("%Y-%m-%d %H:%M:%S")},
            "errors": ["没有匹配的监控源。请先在监控源配置中添加 URL"],
        }

    all_orgs, all_progs, all_events, all_errors = [], [], [], []
    sources_scanned = 0
    articles_new = 0

    for src in all_sources:
        print(f"\n📡 [{src['label']}] {src['url'][:80]}")

        try:
            r = _collect_one_source(
                driver, session,
                {"url": src["url"], "type": src["type"], "label": src["label"]},
                src["owner_org_id"],
                time_filter=time_filter,
            )
            all_orgs.extend(r["orgs"])
            all_progs.extend(r["progs"])
            all_events.extend(r["events"])
            all_errors.extend(r["errors"])
            sources_scanned += 1
            articles_new += r["articles_new"]
        except Exception as e:
            all_errors.append(f"{src['label']}: {e}")
            traceback.print_exc()
        time.sleep(sleep_between)

    print(f"\n✅ 抓取完成：{len(all_orgs)} 组织 / {len(all_progs)} 项目 / {len(all_events)} 事件")

    return {
        "orgs": all_orgs,
        "progs": all_progs,
        "events": all_events,
        "stats": {
            "sources_scanned": sources_scanned,
            "articles_new": articles_new,
            "orgs": len(all_orgs),
            "progs": len(all_progs),
            "events": len(all_events),
            "time_filter": time_filter,
            "timestamp": started.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "errors": all_errors,
    }


def _collect_one_source(driver, session, source, owner_org_id: Optional[str],
                        time_filter: str = "today"):
    url = source.get("url", "").strip()
    stype = source.get("type", "mixed")

    collected = {"orgs": [], "progs": [], "events": [], "errors": [], "articles_new": 0}

    if stype == "sogou_wechat" or "weixin.sogou.com" in url:
        return _collect_sogou_wechat(driver, session, source, owner_org_id,
                                     collected, time_filter=time_filter)

    if stype == "wechat" or "mp.weixin.qq.com" in url:
        m = re.search(r"album_id=([^&]+)", url)
        biz_m = re.search(r"__biz=([^&]+)", url)
        if m:
            album_id = m.group(1)
            biz = biz_m.group(1) if biz_m else ""
            api = (f"https://mp.weixin.qq.com/mp/appmsgalbum?action=getalbum&__biz={biz}"
                   f"&album_id={album_id}&count=20&begin_msgid=&begin_itemidx=&is_reverse=1"
                   f"&scene=173&subscene=159")
            try:
                r = session.get(api, timeout=20)
                data = r.json()
                articles = data.get("getalbum_resp", {}).get("article_list", []) or []
                for a in articles:
                    if time_filter != "all":
                        ct = a.get("create_time")
                        if ct:
                            try:
                                d = datetime.fromtimestamp(int(ct)).strftime("%Y-%m-%d")
                                if not is_in_time_range(d, time_filter):
                                    continue
                            except Exception:
                                pass
                    art_url = a.get("url") or (
                        f"https://mp.weixin.qq.com/s?__biz={biz}&mid={a.get('msgid')}&idx={a.get('itemidx', 1)}"
                    )
                    if is_url_scraped(driver, art_url):
                        continue
                    collected["articles_new"] += 1
                    raw = fetch_html(session, art_url)
                    if not raw:
                        continue
                    title = a.get("title", "")
                    text = html_to_text(raw)
                    pt_str = ""
                    ct = a.get("create_time")
                    if ct:
                        try:
                            pt_str = datetime.fromtimestamp(int(ct)).strftime("%Y-%m-%d")
                        except Exception:
                            pt_str = ""
                    _collect_one_page(driver, art_url, title, text,
                                      owner_org_id, source, collected,
                                      publish_time=pt_str)
                    time.sleep(3)
                    if collected["articles_new"] >= 10:
                        break
            except Exception as e:
                collected["errors"].append(f"微信合集: {e}")
        else:
            if not is_url_scraped(driver, url):
                raw = fetch_html(session, url)
                if raw:
                    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw,
                                        flags=re.DOTALL | re.IGNORECASE)
                    title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
                    text = html_to_text(raw)
                    collected["articles_new"] += 1
                    _collect_one_page(driver, url, title, text,
                                      owner_org_id, source, collected,
                                      publish_time=datetime.now().strftime("%Y-%m-%d"))
        return collected

    raw = fetch_html(session, url)
    if not raw:
        collected["errors"].append(f"{url}: 抓取失败")
        return collected

    text = html_to_text(raw)
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.DOTALL | re.IGNORECASE)
    page_title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""

    links = extract_links(raw, url, same_host=True) if stype in ("news", "publications") else []
    candidate_links = [l for l in links if any(
        x in l["url"].lower() for x in ("/news/", "/press", "/blog/", "/article", "/insight")
    )]

    if stype in ("news", "publications") and len(candidate_links) >= 2:
        for link in candidate_links[:15]:
            art_url = link["url"]
            if is_url_scraped(driver, art_url):
                continue
            collected["articles_new"] += 1
            raw2 = fetch_html(session, art_url)
            if not raw2:
                continue
            text2 = html_to_text(raw2)
            tm2 = re.search(r"<title[^>]*>(.*?)</title>", raw2,
                            flags=re.DOTALL | re.IGNORECASE)
            title2 = re.sub(r"\s+", " ", tm2.group(1)).strip() if tm2 else ""
            _collect_one_page(driver, art_url, title2, text2,
                              owner_org_id, source, collected,
                              publish_time=datetime.now().strftime("%Y-%m-%d"))
            time.sleep(2)
    else:
        _collect_one_page(driver, url, page_title, text,
                          owner_org_id, source, collected,
                          publish_time=datetime.now().strftime("%Y-%m-%d"))

    return collected


def _collect_one_page(driver, url, title, text, owner_org_id: Optional[str],
                      source, collected, publish_time: str = ""):
    creator = source.get("label") or source.get("type") or "monitor"
    ptime = (publish_time or "").strip() or datetime.now().strftime("%Y-%m-%d")

    url_in_db = is_url_scraped(driver, url)
    cached = get_cached(title, ptime, creator)

    if cached and cached.get("parsed"):
        result = cached["parsed"]
        print(f"        💾 命中缓存: {title[:40]}")
    elif url_in_db:
        print(f"        ⏭️  已解析过（URL 已在库，无缓存），跳过: {url[:80]}")
        return
    else:
        try:
            result = extract_with_llm(url, title, text)
        except Exception as e:
            collected["errors"].append(f"LLM {url[:60]}: {e}")
            return
        set_cached(
            title=title,
            publish_time=ptime,
            parsed=result,
            creator=creator,
            source_url=url,
        )
        print(f"        🆕 新解析并缓存: {title[:40]}")

    orgs = result.get("organizations", []) or []
    progs = result.get("programs", []) or []
    events = result.get("events", []) or []

    for o in orgs:
        nm = (o.get("canonical_name") or "").strip()
        oid = find_org_exact(driver, nm) if nm else None
        o["_already_in_db"] = bool(oid)
        o["_existing_id"] = oid or ""

    for p in progs:
        nm = (p.get("canonical_name") or "").strip()
        existing = find_program_full(driver, nm) if nm else None
        p["_already_in_db"] = bool(existing)
        p["_existing_id"] = (existing["id"] if existing else "") or ""

    for e in events:
        oname = (e.get("organization_name") or "").strip()
        etitle = (e.get("title") or "").strip()
        edate = (e.get("event_date") or "").strip()
        oid = find_org_exact(driver, oname) if oname else None
        if oid and etitle and _event_exists(driver, oid, etitle, edate):
            e["_already_in_db"] = True
        else:
            e["_already_in_db"] = False

    filtered_events = []
    skipped_events = 0
    for e in events:
        if _event_source_already_scraped(driver, e):
            skipped_events += 1
            continue
        filtered_events.append(e)
    if skipped_events:
        print(f"        ⏭️  跳过 {skipped_events} 条已解析 source_url 的事件")
    events = filtered_events

    owner_name = None
    if owner_org_id:
        with driver.session() as s:
            r = s.run("MATCH (o:Organization {organization_id: $oid}) "
                      "RETURN o.canonical_name AS name", oid=owner_org_id).single()
            owner_name = r["name"] if r else None

    for e in events:
        if not (e.get("organization_name") or "").strip() and owner_name:
            e["organization_name"] = owner_name
        e["_source_url"] = url
        e["_source_label"] = source.get("label", source.get("type", ""))
        e["_owner_org_id"] = owner_org_id
        e["_publish_time"] = ptime
        e["_creator"] = creator

    for p in progs:
        if not (p.get("organization_name") or "").strip() and owner_name:
            p["organization_name"] = owner_name
        p["_source_url"] = url
        p["_source_label"] = source.get("label", source.get("type", ""))
        p["_owner_org_id"] = owner_org_id
        p["_publish_time"] = ptime
        p["_creator"] = creator

    for o in orgs:
        o["_source_url"] = url
        o["_source_label"] = source.get("label", source.get("type", ""))
        o["_owner_org_id"] = owner_org_id
        o["_publish_time"] = ptime
        o["_creator"] = creator

    collected["orgs"].extend(orgs)
    collected["progs"].extend(progs)
    collected["events"].extend(events)


# ============================================================
# 内置调度器
# ============================================================

def _seconds_until_next_run(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_schedule(hour: int = 23, minute: int = 30,
                 time_filter: str = "week",
                 org_filter: Optional[str] = None,
                 type_filter: Optional[str] = None):
    print(f"🕒 调度器已启动 — 每天 {hour:02d}:{minute:02d} 抓取"
          f"（时间范围：{time_filter}）")
    print("   Ctrl+C 退出\n")

    while True:
        wait = _seconds_until_next_run(hour, minute)
        next_run = datetime.now() + timedelta(seconds=wait)
        print(f"   下次执行: {next_run:%Y-%m-%d %H:%M:%S}"
              f"（等待 {wait/3600:.2f} 小时）")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            print("\n👋 调度器已退出")
            return

        print(f"\n{'='*60}")
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 开始每日抓取...")
        try:
            result = collect_for_review(org_filter=org_filter,
                                        type_filter=type_filter,
                                        time_filter=time_filter)
            s = result.get("stats", {})
            print(f"完成：组织 {s.get('orgs',0)} / 项目 {s.get('progs',0)} / "
                  f"事件 {s.get('events',0)} / 新文章 {s.get('articles_new',0)}")
            if result.get("errors"):
                print(f"⚠️  错误 {len(result['errors'])} 条")
                for e in result["errors"][:10]:
                    print(f"   - {e}")
        except Exception as e:
            print(f"❌ 抓取失败: {e}")
            traceback.print_exc()
        print(f"{'='*60}\n")


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="公司项目 & 事件持续监控")
    parser.add_argument("--org", help="只监控指定 organization_id（历史组织源）")
    parser.add_argument("--type", help=f"只处理指定 type，可选: {sorted(VALID_TYPES)}")
    parser.add_argument("--source-id", help="只抓取指定 source_id（来自 list）")
    parser.add_argument("--dry-run", action="store_true", help="只抽取不写入")
    parser.add_argument("--list", action="store_true", help="列出所有配置")
    parser.add_argument("--collect", action="store_true",
                        help="只抓取待审数据（不写库）")
    parser.add_argument("--time", choices=list(VALID_TIME_FILTERS),
                        default="today",
                        help="时间范围：today / week / month / all（默认 today）")
    parser.add_argument("--schedule", action="store_true",
                        help="启动常驻调度器（默认每天 23:30 抓一周）")
    parser.add_argument("--schedule-hour", type=int, default=23,
                        help="调度小时（默认 23）")
    parser.add_argument("--schedule-minute", type=int, default=30,
                        help="调度分钟（默认 30）")
    parser.add_argument("--schedule-time", choices=list(VALID_TIME_FILTERS),
                        default="week",
                        help="调度时的时间范围（默认 week）")
    parser.add_argument("--add-global", nargs="+",
                        metavar="URL_TYPE_LABEL",
                        help="添加监控源：--add-global URL [TYPE] [LABEL]")
    parser.add_argument("--remove-global", metavar="URL",
                        help="移除监控源（按 URL）")
    args = parser.parse_args()

    if args.list:
        list_sources()
    elif args.schedule:
        run_schedule(
            hour=args.schedule_hour,
            minute=args.schedule_minute,
            time_filter=args.schedule_time,
            org_filter=args.org,
            type_filter=args.type,
        )
    elif args.collect:
        r = collect_for_review(org_filter=args.org, type_filter=args.type,
                               source_id_filter=args.source_id,
                               time_filter=args.time)
        print(json.dumps(r["stats"], ensure_ascii=False, indent=2))
    elif args.add_global:
        url = args.add_global[0] if len(args.add_global) > 0 else ""
        stype = args.add_global[1] if len(args.add_global) > 1 else "sogou_wechat"
        label = args.add_global[2] if len(args.add_global) > 2 else ""
        add_global_source(url, stype, label)
    elif args.remove_global:
        url = args.remove_global
        sid = get_global_source_node_id(get_driver(), url)
        if not sid:
            print(f"❌ 未找到: {url}")
            sys.exit(1)
        remove_global_source(sid)
    else:
        run_once(org_filter=args.org, type_filter=args.type,
                 source_id_filter=args.source_id,
                 dry_run=args.dry_run, time_filter=args.time)