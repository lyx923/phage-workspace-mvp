# scripts/monitor_runner.py
"""
公司项目 & 事件持续监控
支持：通用网页抓取 / 微信公众号合集 / 搜狗微信搜索关键词

注意：Neo4j 属性只支持基本类型及其数组，因此 monitor_sources
存储为 JSON 字符串数组。

新增：
- --today-only  只抓取当天发布的文章
- 内置 --schedule 每日定时调度（默认 23:30）

修复：
- 搜狗 /link 跳转页 href 里的 &amp; 未反转义
- _extract_sogou_real_url 只取一段 url += 导致拿不到完整微信链接
- 拿不到 mp.weixin.qq.com 时不再用相对路径去 fetch（避免 Invalid URL）
"""
import os
import sys
import re
import time
import json
import html
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


# ============================================================
# 当天判断辅助
# ============================================================

def parse_publish_time(pt: str):
    """把搜狗/微信的发布时间字符串解析成 date 对象，解析不出来返回 None"""
    if not pt:
        return None
    pt = pt.strip()
    today = datetime.now().date()

    if pt in ("刚刚", "刚才", "刚刚发布"):
        return today

    m = re.match(r"(\d+)\s*分钟前", pt)
    if m:
        return today

    m = re.match(r"(\d+)\s*小时前", pt)
    if m:
        return today

    if pt in ("昨天", "昨日"):
        return today - timedelta(days=1)

    m = re.match(r"(\d+)\s*天前", pt)
    if m:
        return today - timedelta(days=int(m.group(1)))

    # 2024-01-15 / 2024/01/15
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", pt)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            return None

    # 2024年01月15日
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", pt)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            return None

    # unix 秒字符串
    if pt.isdigit() and len(pt) >= 9:
        try:
            return datetime.fromtimestamp(int(pt)).date()
        except Exception:
            return None

    return None


def is_today(publish_time: str) -> bool:
    """
    判断是否为"当天"。
    - 能解析出日期 → 严格判断是否等于今天
    - 解析不出来（例如格式变了）→ 返回 True，靠 is_url_scraped 兜底去重
    """
    d = parse_publish_time(publish_time)
    if d is None:
        return True
    return d == datetime.now().date()


# ============================================================
# 监控源序列化辅助
# ============================================================

def build_sogou_url(org_name: str) -> str:
    """根据组织名称自动构造搜狗微信搜索 URL（与浏览器访问一致）"""
    params = {
        "type": "2",
        "s_from": "input",
        "query": org_name,
        "ie": "utf8",
        "_sug_": "n",
        "_sug_type_": "",
    }
    return "https://weixin.sogou.com/weixin?" + urlencode(params)


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
    """
    从搜狗的 /link?url=... 跳转页里还原真实的 mp.weixin.qq.com 地址。
    搜狗不是 302 跳转，而是返回一段 JS：url += 'xxx'; url += 'yyy'; ...
    必须把所有片段拼起来，且必须带 Referer: https://weixin.sogou.com/。
    """
    if not sogou_link:
        return ""

    # 1) 清理实体 + 补全 scheme
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

        # 情形 A：已经 302 到微信了
        if "mp.weixin.qq.com" in final_url:
            return final_url

        # 情形 B：拼接所有 url += '...' 片段
        parts = re.findall(r"url\s*\+=\s*['\"]([^'\"]+)['\"]", text)
        if parts:
            candidate = "".join(parts).replace("@", "")
            if "mp.weixin.qq.com" in candidate:
                return candidate
            if candidate.startswith("http"):
                return candidate

        # 情形 C：页面里直接有 mp.weixin.qq.com 的链接
        m = re.search(r"(https?://mp\.weixin\.qq\.com/s[^\s\"'<>\\]+)", text)
        if m:
            return html.unescape(m.group(1))

        # 情形 D：og:url
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
        r'<div\s+class="txt-box">(.*?)</div>\s*</div>\s*</div>',
        html_text, re.DOTALL
    )
    if not blocks:
        blocks = re.findall(
            r'<li[^>]*id="sogou_vr_11002601_box_\d+"[^>]*>(.*?)</li>',
            html_text, re.DOTALL
        )
    if not blocks:
        blocks = re.findall(
            r'(<h3>\s*<a[^>]+href="[^"]+"[^>]*>.*?</a>\s*</h3>.*?<p\s+class="txt-info".*?</p>)',
            html_text, re.DOTALL
        )

    for block in blocks:
        try:
            title_match = re.search(
                r'<h3>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>\s*</h3>',
                block, re.DOTALL
            )
            if not title_match:
                continue
            # ★ 关键修复：href 里可能有 &amp;，需要反转义
            sogou_link = html.unescape(title_match.group(1).strip())
            title = _clean_html(title_match.group(2))

            summary_match = re.search(
                r'<p\s+class="txt-info"[^>]*>(.*?)</p>', block, re.DOTALL
            )
            summary = _clean_html(summary_match.group(1)) if summary_match else ""

            account_match = re.search(
                r'<a[^>]+class="account"[^>]*>(.*?)</a>', block, re.DOTALL
            )
            account = _clean_html(account_match.group(1)) if account_match else ""

            time_match = re.search(
                r'<span\s+class="s2">(.*?)</span>', block, re.DOTALL
            )
            publish_time = _clean_html(time_match.group(1)) if time_match else ""

            articles.append({
                "title": title,
                "summary": summary,
                "account": account,
                "publish_time": publish_time,
                "sogou_link": sogou_link,
            })
        except Exception:
            continue

    return articles


def _collect_sogou_wechat(driver, session, source, owner_org_id, collected,
                          today_only: bool = False):
    """
    直接从存储的 URL 访问搜狗微信搜索（与浏览器行为一致）。
    today_only=True 时只保留发布时间为当天的文章。
    """
    base_url = source["url"].strip()
    if not base_url:
        collected["errors"].append("搜狗搜索 URL 为空")
        return collected

    parsed = urlparse(base_url)
    query_params = parse_qs(parsed.query)
    keyword = query_params.get("query", [""])[0]

    if not keyword:
        collected["errors"].append("搜狗搜索 URL 缺少 query 参数")
        return collected

    print(f"     🔑 关键词: {keyword}" + ("（仅当天）" if today_only else ""))

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

    max_pages = 3

    for page in range(1, max_pages + 1):
        if page == 1:
            req_url = base_url
        else:
            q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            q["page"] = str(page)
            req_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?" + urlencode(q)

        print(f"     📄 第 {page} 页: {req_url[:120]}")

        try:
            resp = session.get(req_url, headers=sogou_headers, timeout=20)
            html_text = resp.text

            print(f"     📊 返回长度 {len(html_text)}，"
                  f"含 txt-box: {'txt-box' in html_text}，"
                  f"含 sogou_vr: {'sogou_vr' in html_text}")

            if "验证" in html_text and "验证码" in html_text:
                print(f"     ⚠️ 第 {page} 页触发验证码")
                collected["errors"].append(
                    f"搜狗第 {page} 页触发验证码，请稍后重试或减少翻页"
                )
                break

            articles = _parse_sogou_articles(html_text, session)
            if not articles:
                print(f"     📭 第 {page} 页无结果（可能页面结构变了或没有更多）")
                if page == 1:
                    snippet = re.sub(r"\s+", " ", html_text)[:300]
                    collected["errors"].append(
                        f"搜狗第1页未解析到文章。页面片段: {snippet}"
                    )
                break

            print(f"     📋 第 {page} 页解析到 {len(articles)} 篇文章")

            page_has_today = False
            for art in articles:
                sogou_link = art.get("sogou_link", "")
                if not sogou_link:
                    continue

                # 仅当天过滤：在解析真实 URL 之前判断，省流量
                if today_only:
                    pt = art.get("publish_time", "")
                    if not is_today(pt):
                        print(f"        ⏭️  非当天，跳过: {art.get('title','')[:40]} ({pt})")
                        continue
                    page_has_today = True

                # ★ 关键修复：不再用相对路径 fallback
                real_url = _extract_sogou_real_url(sogou_link, session)
                if not real_url or "mp.weixin.qq.com" not in real_url:
                    print(f"        ⏭️  跳过（无法还原微信链接）: {art.get('title','')[:40]}")
                    collected["errors"].append(
                        f"无法还原微信链接: {art.get('title','')[:40]}"
                    )
                    continue

                if is_url_scraped(driver, real_url):
                    continue

                collected["articles_new"] += 1

                raw = fetch_html(session, real_url)
                if not raw:
                    continue

                text = html_to_text(raw)
                title = art.get("title", "")
                _collect_one_page(driver, real_url, title, text,
                                  owner_org_id, source, collected)
                time.sleep(3)

            # 若当天模式下，第 1 页已经全是非当天文章（搜狗按时间倒序），停止翻页
            if today_only and not page_has_today and page == 1:
                print(f"     ⏹️  第 1 页已无当天文章，停止翻页")
                break

            time.sleep(5)

        except Exception as e:
            collected["errors"].append(f"搜狗第 {page} 页异常: {e}")
            traceback.print_exc()
            break

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

def process_source(driver, session, source: dict, owner_org_id: str,
                   dry_run: bool = False,
                   today_only: bool = False) -> dict:
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
                                     stats, dry_run, today_only=today_only)

    if stype == "wechat" or "mp.weixin.qq.com" in url:
        return _process_wechat(driver, session, source, owner_org_id, stats,
                               dry_run, today_only=today_only)

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
                          dry_run, today_only: bool = False):
    collected = _collect_sogou_wechat(driver, session, source, owner_org_id,
                                       {"orgs": [], "progs": [], "events": [],
                                        "errors": [], "articles_new": 0},
                                       today_only=today_only)

    if collected["orgs"] or collected["progs"] or collected["events"]:
        url = source.get("url", "")
        commit_extracted(driver, url,
                         collected["orgs"], collected["progs"], collected["events"],
                         stats, owner_org_id=owner_org_id, dry_run=dry_run)

    stats["errors"].extend(collected["errors"])
    return stats


def _process_article(driver, session, art_url: str, owner_org_id: str,
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
                      owner_org_id: str, stats: dict, dry_run: bool):
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


def _process_wechat(driver, session, source: dict, owner_org_id: str,
                    stats: dict, dry_run: bool,
                    today_only: bool = False) -> dict:
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
        # 仅当天过滤（合集里 create_time 是 unix 秒）
        if today_only:
            ct = a.get("create_time")
            if ct:
                try:
                    d = datetime.fromtimestamp(int(ct)).date()
                    if d != datetime.now().date():
                        print(f"        ⏭️  非当天，跳过: {a.get('title','')[:40]}")
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
             dry_run: bool = False, sleep_between: float = 3.0,
             today_only: bool = False):
    driver = get_driver()
    session = make_session()
    started = datetime.now()

    print(f"\n{'='*70}")
    print(f"🔍 公司监控 - {started.strftime('%Y-%m-%d %H:%M:%S')}"
          f"{'（仅当天）' if today_only else ''}")
    print(f"{'='*70}")

    orgs = get_monitored_orgs(driver, org_filter, type_filter)
    if not orgs:
        print("📭 没有配置监控源的组织。")
        print("   使用：python scripts/monitor_runner.py --add ORG_ID URL TYPE LABEL")
        return []

    print(f"📋 待监控组织: {len(orgs)}")

    all_stats = []
    for org in orgs:
        print(f"\n🏢 {org['name']} ({org['id']})")
        print(f"   监控源 {len(org['sources'])} 个 · 上次监控: {org.get('last_monitored') or '从未'}")

        for source in org["sources"]:
            try:
                stats = process_source(driver, session, source, org["id"],
                                       dry_run, today_only=today_only)
                all_stats.append(stats)
            except Exception as e:
                print(f"    ❌ 处理异常: {e}")
                traceback.print_exc()
            time.sleep(sleep_between)

        if not dry_run:
            with driver.session() as s:
                s.run("""
                    MATCH (o:Organization {organization_id: $oid})
                    SET o.last_monitored_at = datetime()
                """, oid=org["id"])

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
            label = org_name

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

        check = s.run("""
            MATCH (o:Organization {organization_id: $oid})
            RETURN o.monitor_sources AS sources
        """, oid=org_id).single()
        actual = check["sources"] if check else []
        if not actual:
            raise ValueError(f"写入后回读为空，可能写入失败（org_id={org_id}）")

        print(f"✅ 已为 {org_name} 添加监控源: [{stype}] {url}（当前共 {len(actual)} 个）")
        return f"已为 {org_name} 添加监控源，当前共 {len(actual)} 个"


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
        print(f"   剩余: {len(kept)} 个")
        return f"已移除 {removed} 条，剩余 {len(kept)} 个"


def list_sources():
    driver = get_driver()
    orgs = get_monitored_orgs(driver)
    if not orgs:
        print("📭 没有配置监控源的组织")
        return
    print(f"\n📋 共 {len(orgs)} 个组织配置了监控源:\n")
    for org in orgs:
        print(f"🏢 {org['name']}  ({org['id']})")
        print(f"   上次监控: {org.get('last_monitored') or '从未'}")
        for s_item in org["sources"]:
            print(f"   · [{s_item.get('type')}] {s_item.get('label')}")
            print(f"     {s_item.get('url')}")
        print()


# ============================================================
# 抓取到待审列表（不写库）
# ============================================================

def collect_for_review(org_filter: Optional[str] = None,
                       type_filter: Optional[str] = None,
                       sleep_between: float = 2.0,
                       today_only: bool = False) -> dict:
    driver = get_driver()
    session = make_session()
    started = datetime.now()

    print(f"\n{'='*70}")
    print(f"🔍 监控抓取（待审核）- {started.strftime('%Y-%m-%d %H:%M:%S')}"
          f"{'（仅当天）' if today_only else ''}")
    print(f"{'='*70}")

    orgs = get_monitored_orgs(driver, org_filter, type_filter)
    if not orgs:
        return {
            "orgs": [], "progs": [], "events": [],
            "stats": {"sources_scanned": 0, "articles_new": 0,
                      "timestamp": started.strftime("%Y-%m-%d %H:%M:%S")},
            "errors": ["没有配置监控源。请先在监控源配置中为组织添加 URL"],
        }

    all_orgs, all_progs, all_events, all_errors = [], [], [], []
    sources_scanned = 0
    articles_new = 0

    for org in orgs:
        print(f"\n🏢 {org['name']} ({org['id']})")
        for source in org["sources"]:
            try:
                r = _collect_one_source(driver, session, source, org["id"],
                                        today_only=today_only)
                all_orgs.extend(r["orgs"])
                all_progs.extend(r["progs"])
                all_events.extend(r["events"])
                all_errors.extend(r["errors"])
                sources_scanned += 1
                articles_new += r["articles_new"]
            except Exception as e:
                all_errors.append(f"{org['name']}: {e}")
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
            "today_only": today_only,
            "timestamp": started.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "errors": all_errors,
    }


def _collect_one_source(driver, session, source, owner_org_id,
                        today_only: bool = False):
    url = source.get("url", "").strip()
    stype = source.get("type", "mixed")
    label = source.get("label", stype)

    collected = {"orgs": [], "progs": [], "events": [], "errors": [], "articles_new": 0}

    if stype == "sogou_wechat" or "weixin.sogou.com" in url:
        return _collect_sogou_wechat(driver, session, source, owner_org_id,
                                     collected, today_only=today_only)

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
                    # 仅当天过滤
                    if today_only:
                        ct = a.get("create_time")
                        if ct:
                            try:
                                d = datetime.fromtimestamp(int(ct)).date()
                                if d != datetime.now().date():
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
                    _collect_one_page(driver, art_url, title, text,
                                      owner_org_id, source, collected)
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
                                      owner_org_id, source, collected)
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
                              owner_org_id, source, collected)
            time.sleep(2)
    else:
        _collect_one_page(driver, url, page_title, text,
                          owner_org_id, source, collected)

    return collected


def _collect_one_page(driver, url, title, text, owner_org_id, source, collected):
    if is_url_scraped(driver, url):
        print(f"        ⏭️  已解析过，跳过: {url[:80]}")
        return

    try:
        result = extract_with_llm(url, title, text)
    except Exception as e:
        collected["errors"].append(f"LLM {url[:60]}: {e}")
        return

    orgs = result.get("organizations", []) or []
    progs = result.get("programs", []) or []
    events = result.get("events", []) or []

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

    for p in progs:
        if not (p.get("organization_name") or "").strip() and owner_name:
            p["organization_name"] = owner_name
        p["_source_url"] = url
        p["_source_label"] = source.get("label", source.get("type", ""))
        p["_owner_org_id"] = owner_org_id

    for o in orgs:
        o["_source_url"] = url
        o["_source_label"] = source.get("label", source.get("type", ""))
        o["_owner_org_id"] = owner_org_id

    collected["orgs"].extend(orgs)
    collected["progs"].extend(progs)
    collected["events"].extend(events)


# ============================================================
# 内置调度器（每天固定时间跑一次）
# ============================================================

def _seconds_until_next_run(hour: int, minute: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_schedule(hour: int = 23, minute: int = 30,
                 today_only: bool = True,
                 org_filter: Optional[str] = None,
                 type_filter: Optional[str] = None):
    """
    常驻调度：每天 hour:minute 自动抓取一次。
    Ctrl+C 退出。
    """
    print(f"🕒 调度器已启动 — 每天 {hour:02d}:{minute:02d} 抓取"
          f"{'当天' if today_only else '全部'}文章")
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
                                        today_only=today_only)
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
    parser.add_argument("--org", help="只监控指定 organization_id")
    parser.add_argument("--type", help=f"只处理指定 type，可选: {sorted(VALID_TYPES)}")
    parser.add_argument("--dry-run", action="store_true", help="只抽取不写入")
    parser.add_argument("--list", action="store_true", help="列出所有配置")
    parser.add_argument("--collect", action="store_true",
                        help="只抓取待审数据（不写库）")
    parser.add_argument("--today-only", action="store_true",
                        help="仅抓取当天发布的文章")
    parser.add_argument("--schedule", action="store_true",
                        help="启动常驻调度器（默认每天 23:30 抓当天）")
    parser.add_argument("--schedule-hour", type=int, default=23,
                        help="调度小时（默认 23）")
    parser.add_argument("--schedule-minute", type=int, default=30,
                        help="调度分钟（默认 30）")
    parser.add_argument("--schedule-all", action="store_true",
                        help="调度时不限制当天（默认仅当天）")
    # nargs="+" 不能配 metavar 元组，用字符串
    parser.add_argument("--add", nargs="+", metavar="ORG_ID_URL_TYPE_LABEL",
                        help="添加监控源：--add ORG_ID [URL] [TYPE] [LABEL]")
    parser.add_argument("--remove", nargs=2, metavar=("ORG_ID", "URL"),
                        help="移除监控源")
    args = parser.parse_args()

    if args.list:
        list_sources()
    elif args.schedule:
        run_schedule(
            hour=args.schedule_hour,
            minute=args.schedule_minute,
            today_only=not args.schedule_all,
            org_filter=args.org,
            type_filter=args.type,
        )
    elif args.collect:
        r = collect_for_review(org_filter=args.org, type_filter=args.type,
                               today_only=args.today_only)
        print(json.dumps(r["stats"], ensure_ascii=False, indent=2))
    elif args.add:
        if len(args.add) < 1:
            print("用法: --add ORG_ID [URL] [TYPE] [LABEL]")
            sys.exit(1)
        org_id = args.add[0]
        url = args.add[1] if len(args.add) > 1 else ""
        stype = args.add[2] if len(args.add) > 2 else "sogou_wechat"
        label = args.add[3] if len(args.add) > 3 else ""
        add_source(org_id, url, stype, label)
    elif args.remove:
        remove_source(args.remove[0], args.remove[1])
    else:
        run_once(org_filter=args.org, type_filter=args.type,
                 dry_run=args.dry_run, today_only=args.today_only)