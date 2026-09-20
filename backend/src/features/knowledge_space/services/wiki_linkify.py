"""Wiki 自动互链（linkify）——逐函数移植自 WeKnora wiki_linkify.go

纯文本替换（无 LLM）：扫描正文中其他页面标题/别名的提及，注入
``[[slug|matchText]]`` 交叉链接。

保护范围（禁区，不做注入）：
- 围栏代码块（``` / ~~~）
- 行内代码（匹配长度的反引号 run）
- 已有 ``[[slug|...]]`` wiki 链接（其 slug 记入 used，调用方跳过）
- 行内 markdown 链接 ``[text](url)`` 与图片 ``![alt](url)``
- 引用式链接 ``[text][label]`` 与引用定义 ``[label]: url``
- autolink ``<scheme://...>``

匹配规则：
- matchText 按**长度降序**处理，长名优先（"北京邮电大学" 优先于 "北京"）
- 每个 ref 只包**首个**安全命中
- ASCII 字母开/结尾的 matchText 要求词边界；CJK 视为边界
  （"北京" 可嵌入 "北京邮电大学" 命中，冲突由长名优先解决）
- 已链到该 slug 的 ref 跳过

索引语义：Go 版按字节偏移，Python 版按字符偏移——对 UTF-8 文本两者
在「同一字符边界切分」的意义上行为等价（ASCII 词边界判定用 ord<128）。
"""


class _Span:
    __slots__ = ("start", "end")

    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


def linkify_content(
    content: str,
    refs: list[tuple[str, str]],
    self_slug: str = "",
) -> tuple[str, bool]:
    """为 refs 中每个 (slug, match_text) 注入首个安全命中的 wiki 链接。

    Args:
        content: markdown 正文
        refs: (slug, match_text) 候选列表（title 与 aliases 已由调用方展开）
        self_slug: 当前页面 slug（自指跳过）

    Returns:
        (新正文, 是否有改动)
    """
    if not content or not refs:
        return content, False

    # matchText 长度（字符数）降序，稳定排序——长名优先于其子串
    sorted_refs = [
        r for r in refs
        if r[0] and r[1] and r[0] != self_slug
    ]
    sorted_refs.sort(key=lambda r: len(r[1]), reverse=True)

    forbidden, used = compute_forbidden_spans(content)
    changed = False

    for slug, match_text in sorted_refs:
        # 该 slug 已在正文任何位置被链接 → 跳过
        if slug in used:
            continue
        pos = _find_first_safe_match(content, match_text, forbidden)
        if pos < 0:
            continue
        replacement = f"[[{slug}|{match_text}]]"
        content = content[:pos] + replacement + content[pos + len(match_text):]
        # 平移/扩展禁区，防后续 ref 把链接嵌进新造的 [[...]] 里
        delta = len(replacement) - len(match_text)
        forbidden = _shift_spans_after(forbidden, pos, delta)
        forbidden.append(_Span(pos, pos + len(replacement)))
        _sort_spans(forbidden)
        used[slug] = True
        changed = True

    return content, changed


def _find_first_safe_match(haystack: str, needle: str, forbidden: list[_Span]) -> int:
    """首个「不在禁区内 + ASCII 词边界合法」的 needle 出现位置；无则 -1。"""
    if not needle:
        return -1
    needs_boundary = _has_ascii_letter_edge(needle)

    start = 0
    limit = len(haystack) - len(needle)
    while start <= limit:
        rel = haystack.find(needle, start)
        if rel < 0:
            return -1
        pos = rel
        end = pos + len(needle)

        if _span_contains(forbidden, pos, end):
            start = pos + 1
            continue
        if needs_boundary and not _has_word_boundary(haystack, pos, end):
            start = pos + 1
            continue
        return pos
    return -1


def _has_ascii_letter_edge(s: str) -> bool:
    """needle 首尾为 ASCII 字母/数字时才需要词边界检查（纯 CJK/标点无需）。"""
    if not s:
        return False
    return _is_ascii_word_rune(s[0]) or _is_ascii_word_rune(s[-1])


def _is_ascii_word_rune(ch: str) -> bool:
    if ord(ch) > 127:
        return False
    return ch == "_" or ch.isdigit() or ch.isalpha()


def _has_word_boundary(s: str, pos: int, end: int) -> bool:
    """命中前后紧邻字符不是 ASCII 词字符才算安全边界。

    非 ASCII（CJK）视为边界："北京" 嵌在 "北京邮电大学" 中仍命中，
    该冲突由长名优先排序另行消解。
    """
    if pos > 0 and _is_ascii_word_rune(s[pos - 1]):
        return False
    if end < len(s) and _is_ascii_word_rune(s[end]):
        return False
    return True


def _span_contains(spans: list[_Span], pos: int, end: int) -> bool:
    return any(pos < sp.end and end > sp.start for sp in spans)


def _shift_spans_after(spans: list[_Span], pivot: int, delta: int) -> list[_Span]:
    if delta == 0:
        return spans
    for sp in spans:
        if sp.start >= pivot:
            sp.start += delta
            sp.end += delta
    return spans


def _sort_spans(spans: list[_Span]) -> None:
    spans.sort(key=lambda sp: (sp.start, sp.end))


def compute_forbidden_spans(s: str) -> tuple[list[_Span], dict[str, bool]]:
    """返回 s 的禁区列表 + 已引用 wiki slug 集合（used）。

    覆盖：围栏代码块、行内代码、既有 wiki 链接（记 used）、行内 markdown
    链接/图片、引用式链接、引用定义行、autolink。
    """
    spans: list[_Span] = []
    used: dict[str, bool] = {}
    n = len(s)

    # Pass 1: 引用定义行（[label]: url ...）——必须先记录，
    # 否则主扫描会把 [label] 当悬挂的裸括号
    spans.extend(_scan_reference_definitions(s))

    i = 0
    while i < n:
        if _is_fence_start(s, i):
            fence_len, fence_ch = _fence_run(s, i)
            end = _find_fence_end(s, i + fence_len, fence_ch, fence_len)
            spans.append(_Span(i, end))
            i = end
            continue

        c = s[i]
        if c == "`":
            # 行内代码：数反引号 run，找等长闭合 run
            run = 1
            while i + run < n and s[i + run] == "`":
                run += 1
            close_idx = _find_inline_code_close(s, i + run, run)
            if close_idx < 0:
                i += run
                continue
            spans.append(_Span(i, close_idx + run))
            i = close_idx + run
        elif c == "[":
            # [[slug...]] wiki 链接——slug 记入 used
            if i + 1 < n and s[i + 1] == "[":
                close = s.find("]]", i + 2)
                if close >= 0:
                    end = close + 2
                    inner = s[i + 2:close]
                    slug = _extract_wiki_slug(inner)
                    if slug:
                        used[slug] = True
                    spans.append(_Span(i, end))
                    i = end
                    continue
            end = _match_markdown_link(s, i)
            if end is not None:
                spans.append(_Span(i, end))
                i = end
                continue
            end = _match_reference_style_link(s, i)
            if end is not None:
                spans.append(_Span(i, end))
                i = end
                continue
            i += 1
        elif c == "!":
            # ![alt](url) 图片
            if i + 1 < n and s[i + 1] == "[":
                end = _match_markdown_link(s, i + 1)
                if end is not None:
                    spans.append(_Span(i, end))
                    i = end
                    continue
                end = _match_reference_style_link(s, i + 1)
                if end is not None:
                    spans.append(_Span(i, end))
                    i = end
                    continue
            i += 1
        elif c == "<":
            end = _match_autolink(s, i)
            if end is not None:
                spans.append(_Span(i, end))
                i = end
                continue
            i += 1
        else:
            i += 1

    _sort_spans(spans)
    return spans, used


def _extract_wiki_slug(inner: str) -> str:
    """[[...]] 内文 → slug 部分（"slug|display" 取 slug）。空串=不像真 slug。"""
    pipe = inner.find("|")
    if pipe >= 0:
        inner = inner[:pipe]
    return inner.strip()


def _match_reference_style_link(s: str, i: int) -> int | None:
    """``[text][label]`` → 闭括号后偏移；不匹配返回 None。"""
    if i >= len(s) or s[i] != "[":
        return None
    text_end = _find_closing_bracket(s, i)
    if text_end is None:
        return None
    if text_end + 1 >= len(s) or s[text_end + 1] != "[":
        return None
    label_end = _find_closing_bracket(s, text_end + 1)
    if label_end is None:
        return None
    return label_end + 1


def _find_closing_bracket(s: str, i: int) -> int | None:
    """i 处 ``[`` 的配对 ``]`` 偏移；支持 ``\\[`` 转义；跨行放弃。"""
    if i >= len(s) or s[i] != "[":
        return None
    depth = 1
    j = i + 1
    while j < len(s):
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return j
        elif ch == "\n":
            return None
        j += 1
    return None


def _scan_reference_definitions(s: str) -> list[_Span]:
    """``[label]: url ...`` 定义行整行禁区（含行尾换行）。

    首个非空格字符为 ``[`` 即候选（缩进 ≤3 空格，对齐 CommonMark）。
    """
    out: list[_Span] = []
    line_start = 0
    while line_start < len(s):
        nl = s.find("\n", line_start)
        line_end = len(s) if nl < 0 else nl + 1

        indent = 0
        while indent < 3 and line_start + indent < line_end and s[line_start + indent] == " ":
            indent += 1
        start = line_start + indent

        if start < line_end and s[start] == "[":
            label_end = _find_closing_bracket(s, start)
            if label_end is not None and label_end + 1 < line_end and s[label_end + 1] == ":":
                out.append(_Span(line_start, line_end))

        line_start = line_end
    return out


def _is_fence_start(s: str, i: int) -> bool:
    """i 在行首且以 ``` 或 ~~~（≥3 个）开头。"""
    if i > 0 and s[i - 1] != "\n":
        return False
    if i + 2 >= len(s):
        return False
    c = s[i]
    if c != "`" and c != "~":
        return False
    return s[i + 1] == c and s[i + 2] == c


def _fence_run(s: str, i: int) -> tuple[int, str]:
    c = s[i]
    j = i
    while j < len(s) and s[j] == c:
        j += 1
    return j - i, c


def _find_fence_end(s: str, start: int, ch: str, min_len: int) -> int:
    """闭合围栏之后的偏移；找不到闭合到文末。"""
    nl = s.find("\n", start)
    if nl < 0:
        return len(s)
    pos = nl + 1
    while pos < len(s):
        if s[pos] == ch:
            run_len, _ = _fence_run(s, pos)
            if run_len >= min_len:
                # 闭合须在行首（已越过换行）；跳到行尾
                end_line = s.find("\n", pos)
                if end_line < 0:
                    return len(s)
                return end_line + 1
        nl = s.find("\n", pos)
        if nl < 0:
            return len(s)
        pos = nl + 1
    return len(s)


def _find_inline_code_close(s: str, start: int, run_len: int) -> int:
    """等长反引号闭合 run 的起点；无则 -1。

    CommonMark 里行内码可跨单换行；遇双换行（段落断）放弃防失控。
    """
    i = start
    while i < len(s):
        if i + 1 < len(s) and s[i] == "\n" and s[i + 1] == "\n":
            return -1
        if s[i] == "`":
            j = i
            while j < len(s) and s[j] == "`":
                j += 1
            if j - i == run_len:
                return i
            i = j
            continue
        i += 1
    return -1


def _match_markdown_link(s: str, i: int) -> int | None:
    """``[text](url)`` → 闭括号后偏移；不匹配 None。"""
    if i >= len(s) or s[i] != "[":
        return None
    depth = 1
    j = i + 1
    while j < len(s) and depth > 0:
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "\n":
            return None  # 链接文本不跨行，放弃防失控
        if depth == 0:
            break
        j += 1
    if j >= len(s) or s[j] != "]":
        return None
    if j + 1 >= len(s) or s[j + 1] != "(":
        return None
    k = j + 2
    paren_depth = 1
    while k < len(s) and paren_depth > 0:
        ch = s[k]
        if ch == "\\":
            k += 2
            continue
        if ch == "(":
            paren_depth += 1
        elif ch == ")":
            paren_depth -= 1
            if paren_depth == 0:
                return k + 1
        elif ch == "\n":
            return None
        k += 1
    return None


def _match_autolink(s: str, i: int) -> int | None:
    """``<scheme://...>`` / ``<mailto:...>`` → 闭合后偏移；不匹配 None。"""
    if i >= len(s) or s[i] != "<":
        return None
    close = s.find(">", i + 1)
    if close < 0:
        return None
    inner = s[i + 1:close]
    if not inner or any(c in inner for c in " \t\n"):
        return None
    if "://" not in inner and not inner.startswith("mailto:"):
        return None
    return close + 1
