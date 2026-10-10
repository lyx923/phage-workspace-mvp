# src/shared/deepseek_client.py
"""
DeepSeek 客户端封装。

职责：
    - get_deepseek_client：获取 OpenAI 兼容客户端
    - repair_json：尝试修复 LLM 返回的不完整 JSON
    - chat_json：调用 DeepSeek 并返回 JSON

设计：
    - repair_json 使用启发式方法：去 markdown 标记、逐字符截断、补全括号、补全字符串引号
"""
import json
import re
from typing import Optional, Dict

from openai import OpenAI
from config import Config


def get_deepseek_client() -> OpenAI:
    """获取 DeepSeek 客户端（OpenAI 兼容 SDK）。"""
    return OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)


def repair_json(s: str) -> Optional[dict]:
    """
    尝试修复 LLM 返回的不完整 JSON。

    策略：
        1. 去掉 markdown 代码块标记
        2. 直接尝试解析
        3. 循环截断尾部字符，同时处理未闭合字符串、补齐括号
        4. 全部失败返回 None

    Args:
        s: 原始字符串

    Returns:
        Optional[dict]: 修复后的 dict，或 None
    """
    if not s or not s.strip():
        return None
    s = s.strip()
    # 去掉 markdown 代码块
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)

    # 直接尝试
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # 逐字符截断尝试修复
    max_trim = min(2000, len(s) - 10)
    for trim in range(max_trim):
        cand = s if trim == 0 else s[:-trim]
        cand = cand.rstrip()
        # 去掉尾部孤立的逗号 / 冒号
        while cand and cand[-1] in ",:":
            cand = cand[:-1].rstrip()

        # 检测是否有未闭合的字符串
        in_str = False
        esc = False
        for ch in cand:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
        if in_str:
            cand += '"'

        # 补齐括号
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


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 8000,
) -> Dict:
    """
    调用 DeepSeek 并以 JSON 形式返回。

    - 使用 response_format={"type": "json_object"} 强制 JSON 输出
    - 解析失败时尝试 repair_json
    - 全部失败返回 {"_parse_error": ...}

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        model: 模型名（默认 Config.DS_MODEL）
        temperature: 温度（默认 0.1）
        max_tokens: 最大 token 数

    Returns:
        Dict: 解析后的 JSON 或错误信息
    """
    client = get_deepseek_client()
    resp = client.chat.completions.create(
        model=model or Config.DS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = repair_json(raw)
        if fixed is not None:
            fixed["_repaired"] = True
            return fixed
        return {"_parse_error": raw[-500:] if raw else ""}