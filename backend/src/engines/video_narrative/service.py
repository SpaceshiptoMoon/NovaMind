"""视频叙事合成引擎：把逐帧/逐块的碎片画面描述合成为章节化连贯叙事文档。

Map-Reduce 两层：分批生成章节摘要（Map，保留时间范围），再汇总成全片结构化
文档（Reduce：梗概/章节时间轴/角色清单/场景物件清单）。直收 LLM 客户端，
零 features/ORM/setting 依赖——块来源、落库、触发时机均归业务编排。
"""
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class NarrativeSynthesisError(Exception):
    """叙事合成失败（LLM 不可用/输出不可解析）。"""


@dataclass
class NarrativeBlock:
    """一个时间窗口的画面描述（来自视频解析的碎片块）。

    chunk_index 为业务侧原始块索引（检索回链用；无则留 None）。
    """

    start_time: float
    end_time: float | None
    text: str
    chunk_index: int | None = None


@dataclass
class NarrativeChapter:
    """合成产物中的一个章节：时间范围 + 标题 + 连贯摘要 + 覆盖的块索引。"""

    title: str
    start_time: float
    end_time: float | None
    summary: str
    chunk_indices: list[int] = field(default_factory=list)


@dataclass
class NarrativeDocument:
    """全片叙事文档：梗概 + 章节列表。"""

    overview: str
    chapters: list[NarrativeChapter] = field(default_factory=list)

    def to_markdown(self, title: str = "") -> str:
        """渲染为 markdown 全文（梗概 + 章节时间轴表 + 各章正文）。"""
        parts: list[str] = []
        if title:
            parts.append(f"# {title}\n")
        parts.append("## 全片梗概\n\n" + self.overview.strip() + "\n")
        parts.append("## 章节时间轴\n")
        for ch in self.chapters:
            t0 = _fmt_ts(ch.start_time)
            t1 = _fmt_ts(ch.end_time) if ch.end_time is not None else "末尾"
            parts.append(f"- **{t0} – {t1}** {ch.title}\n")
        parts.append("\n## 章节详情\n")
        for ch in self.chapters:
            t0 = _fmt_ts(ch.start_time)
            t1 = _fmt_ts(ch.end_time) if ch.end_time is not None else "末尾"
            parts.append(f"\n### {t0} – {t1} {ch.title}\n\n{ch.summary.strip()}\n")
        return "\n".join(parts)


def _fmt_ts(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class VideoNarrativeSynthesizer:
    """Map-Reduce 叙事合成器：碎片块描述 → 章节化连贯文档。

    直收 LLM 客户端（``generate_text(prompt=..., max_tokens=...)``）；
    块来源与产物落库由业务编排层负责。
    """

    def __init__(self, llm_client, batch_size: int = 12, logger=None):
        self.llm_client = llm_client
        self.batch_size = max(1, batch_size)
        self.logger = logger or logging.getLogger(__name__)

    async def synthesize(self, blocks: list[NarrativeBlock]) -> NarrativeDocument:
        """合成叙事文档。

        Args:
            blocks: 按时间升序排列的画面描述块。

        Returns:
            NarrativeDocument：梗概与章节列表（章节带 chunk_indices 供检索回链）。

        Raises:
            NarrativeSynthesisError: 块列表为空或全部批次合成失败。
        """
        blocks = [b for b in blocks if (b.text or "").strip()]
        if not blocks:
            raise NarrativeSynthesisError("块列表为空，无可合成内容")

        batches = [blocks[i:i + self.batch_size]
                   for i in range(0, len(blocks), self.batch_size)]
        chapters: list[NarrativeChapter] = []
        for bi, batch in enumerate(batches):
            try:
                ch = await self._map_batch(bi, batch)
                if ch is not None:
                    chapters.append(ch)
            except Exception as exc:  # 单批失败不中断整体（降级跳过该时间窗）
                self.logger.warning(
                    "叙事合成 Map 批失败，跳过该时间窗",
                    extra={"batch_index": bi, "error": str(exc)},
                )
        if not chapters:
            raise NarrativeSynthesisError("全部批次合成失败")

        overview = await self._reduce_overview(chapters)
        chapters.sort(key=lambda c: c.start_time)
        return NarrativeDocument(overview=overview, chapters=chapters)

    async def _map_batch(self, batch_index: int, batch: list[NarrativeBlock]) -> NarrativeChapter | None:
        """Map：一个时间窗批次的碎片描述 → 一个章节。"""
        t0 = batch[0].start_time
        t1 = batch[-1].end_time
        indices = [b.chunk_index for b in batch if b.chunk_index is not None]
        joined = "\n\n".join(
            f"[{b.start_time}-{b.end_time if b.end_time is not None else '?'}秒] {b.text.strip()}"
            for b in batch
        )
        prompt = (
            f"以下是一个视频第 {t0} 秒到第 {t1 if t1 is not None else '?'} 秒的逐帧画面描述"
            f"（按时间顺序，可能含重复或相近画面）。\n"
            f"请连贯化为一个章节摘要，用 JSON 输出（不要多余文字）：\n"
            f'{{"title": "章节标题，12字以内", "summary": "连贯叙述这段时间的内容、'
            f'出现的人物/场景/物件，250字以内"}}\n\n{joined}'
        )
        resp = await self.llm_client.generate_text(
            prompt=prompt, max_tokens=8192, temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = _parse_json_object(resp)
        title = str(data.get("title") or f"第{batch_index + 1}部分").strip()[:30]
        summary = str(data.get("summary") or "").strip()
        if not summary:
            return None
        return NarrativeChapter(
            title=title, start_time=t0, end_time=t1,
            summary=summary, chunk_indices=indices,
        )

    async def _reduce_overview(self, chapters: list[NarrativeChapter]) -> str:
        """Reduce：全部章节摘要 → 全片梗概（200 字以内连贯叙事）。"""
        seg = "\n\n".join(
            f"## 章节（{c.start_time}-{c.end_time if c.end_time is not None else '?'}秒）{c.title}\n{c.summary}"
            for c in chapters
        )
        prompt = (
            "以下是一个视频各章节的摘要（按时间顺序）。\n"
            "请合成一份全片梗概：一段连贯的叙事文字，概括整体内容与关键转折，"
            "不要分点、不要标题，250 字以内，用中文。\n\n" + seg
        )
        resp = await self.llm_client.generate_text(
            prompt=prompt, max_tokens=8192, temperature=0.3,
        )
        text = (resp or "").strip()
        if not text:
            raise NarrativeSynthesisError("全片梗概生成失败（LLM 空响应）")
        return text


def _parse_json_object(resp: str | None) -> dict:
    """解析 LLM 返回的 JSON 对象（容忍 ```json 围栏与前后杂文）。"""
    if not resp:
        return {}
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
