"""Wiki slug 规范化（纯函数）。

中立模块：repository / services / api / agent 工具此前从
``wiki_ingest_service`` 懒 import ``normalize_slug``，导致
repository → services 回边成环（R1 无环门禁）；纯函数下沉到无依赖
中立位后，四方单向引用，环消除。
"""
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^\w一-鿿/-]+")


def normalize_slug(slug: str) -> str:
    """清洗模型产出的 slug：小写、剔除空白与危险字符、保留 CJK 与连字符。

    中文 slug 保守方案：保留原字符（不引 pypinyin），仅清洗空白与非法符号。
    """
    slug = (slug or "").strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = re.sub(r"-+/", "/", slug)   # 分隔符前不允许连字符
    slug = re.sub(r"/-+", "/", slug)   # 分隔符后不允许连字符
    return slug.strip("-/")


_WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_wiki_link_slugs(content: str, *, self_slug: str = "", valid_slugs: set[str] | None = None) -> list[str]:
    """从正文提取 ``[[slug|title]]`` 形式的有效链接 slug（去重、去自指、剔无效）。

    ``[[...]]`` 内文的解析规则与 wiki_linkify._extract_wiki_slug 一致
    （``slug|display`` 取 slug 部分）；slug 清洗走 normalize_slug。
    ``valid_slugs`` 缺省时不过滤（全部提取）。
    """
    links: list[str] = []
    for m in _WIKI_LINK_RE.finditer(content):
        inner = m.group(1)
        pipe = inner.find("|")
        if pipe >= 0:
            inner = inner[:pipe]
        slug = normalize_slug(inner.strip())
        if slug and slug != self_slug and slug not in links:
            if valid_slugs is None or slug in valid_slugs:
                links.append(slug)
    return links
