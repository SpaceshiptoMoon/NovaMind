"""解析产物跨层契约：figure region 形状与占位符协议的单一权威。

figure region 的基座键集、构造、规范化、占位符兜底读取在此唯一定义——
引擎各解析器经 :func:`make_figure_region` 构造，业务层（上传/快照/替换）
经同一模块读取，新增契约键在本模块登记，杜绝「跨层加字段漏透传」类
静默断裂（xlsx placeholder 透传事故 3145180b 的结构性根治）。

dict 是传输形态（region 随 metadata 进快照 JSON），类型收口在构造与
规范化两端而非传输过程。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# 无盐占位符形态：旧契约 region（无 placeholder 键）的兜底读取形态，
# 与其正文中实际插入的旧形态占位符同构——两种 key 各自命中各自的正文
UNSALTED_PLACEHOLDER_FMT = "__FIGURE_URL__{artifact_id}__"

# region 基座键与缺省值：跨格式统一的最小集，下游（上传链/呈现/前端）
# 写一种逻辑即可。值可调用（list/dict 构造器）表示逐 region 新建可变缺省。
# 各格式可在基座之上追加扩展键（pdf 的 has_image/caption_boxes/
# member_text_count 等），规范化只补基座、不裁扩展。
REGION_BASE_DEFAULTS: dict[str, Any] = {
    "artifact_id": "",
    "placeholder": "",
    "pages": list,
    "page_start": 0,
    "bbox": dict,
    "caption": "",
    "text": "",
    "member_texts": list,
    "member_bboxes": list,
    "image_blobs": list,
}


def unsalted_placeholder(artifact_id: str) -> str:
    """无盐占位符形态（旧契约兜底与读取端共用，勿用于新解析——新解析走加盐版）。"""
    return UNSALTED_PLACEHOLDER_FMT.format(artifact_id=artifact_id)


def make_figure_region(
    *,
    artifact_id: str,
    placeholder: str,
    caption: str = "",
    pages: Sequence[int] | None = None,
    page_start: int = 0,
    bbox: dict[str, Any] | None = None,
    text: str = "",
    member_texts: list[str] | None = None,
    member_bboxes: list[Any] | None = None,
    image_blobs: list[bytes] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """构造 figure region 契约 dict（基座十键恒齐，格式扩展键经 extra 透传）。

    Args:
        artifact_id: 图内唯一 artifact 标识（格式前缀 + 序号，如 docx_fig_0）。
        placeholder: 加盐占位符完整串（document_model.figure_placeholder 产物）。
        caption: 图题/来源描述，命中展示与 block caption 用。
        pages: 所属页码列表（PDF 版面 figure 用；嵌入图片类为空）。
        page_start: 起始页码（无页概念的嵌入图片为 0）。
        bbox: 版面坐标（页面相对比例框）；无坐标时空 dict。
        text: region 关联文本（OCR/VLM 描述等）。
        member_texts / member_bboxes: 复合 region（图表组）的成员明细。
        image_blobs: 图片字节流列表；上传完成后由业务层清除降内存。
        **extra: 格式扩展键（has_image / caption_boxes / region_index_on_page
            等），原样并入 region，出口规范化不裁剪。
    """
    region: dict[str, Any] = {
        "artifact_id": str(artifact_id),
        "placeholder": str(placeholder),
        "pages": list(pages or []),
        "page_start": int(page_start),
        "bbox": dict(bbox or {}),
        "caption": str(caption),
        "text": str(text),
        "member_texts": list(member_texts or []),
        "member_bboxes": list(member_bboxes or []),
        "image_blobs": list(image_blobs or []),
    }
    region.update(extra)
    return region


def normalize_figure_regions(regions: list[Any]) -> list[dict[str, Any]]:
    """逐 region 补齐基座键（就地修改返回），placeholder 缺失退无盐形态。

    出口规范化入口：不管解析器组装得全不全（ppt 历史上只出 4 键、旧快照
    region 无 placeholder），经此之后基座键恒在、形状一致。
    """
    normalized: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        for key, default in REGION_BASE_DEFAULTS.items():
            region.setdefault(key, default() if callable(default) else default)
        if not region.get("placeholder"):
            region["placeholder"] = unsalted_placeholder(str(region.get("artifact_id") or ""))
        normalized.append(region)
    return normalized


def region_placeholder_of(region: dict[str, Any]) -> str:
    """业务层兜底读取 region 的替换 key：placeholder 优先，缺失退无盐形态。

    上传替换 map 的 key 与剥除全集提取共用此读取——保证「读 region 侧」
    与「正文占位符侧」的兜底形态永远同构。
    """
    placeholder = str(region.get("placeholder") or "")
    if placeholder:
        return placeholder
    return unsalted_placeholder(str(region.get("artifact_id") or ""))
