"""图片结构化 caption 与保护性截断回归（2026-10 图片链路深度批次1）。

覆盖三处：
1. ``image_description`` 模板必须是固定分段结构（逐字段段名齐全）——
   分段是 BM25 逐字命中与向量语义命中的双通道根基。
2. ``_truncate_image_description`` 保护性截断语义：逐字段（图中文字/实体/
   图表数据）不可丢弃，超限先砍最长的非逐字段；旧格式（无分段）退化尾部硬切。
3. ``_image_caption_max_chars`` 配置化上限：YAML knowledge_base.parsing
   可覆盖，缺省 4000。
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.features.knowledge_space.prompts import templates as ks_templates
from novamind.features.knowledge_space.services import document_pipeline

pytestmark = pytest.mark.unit

_SILENT_LOGGER = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)


def _make_caption(
    subject: str = "这是主体描述内容" * 10,
    text_in_image: str = "图中文字：NovaMind X100 型号",
    chart: str = "无",
    entities: str = "实体：NovaMind、X100",
    visual: str = "蓝色调、扁平风格",
    scene: str = "截图",
) -> str:
    """构造一个符合模板分段结构的 caption。"""
    return (
        f"【主体描述】{subject}\n"
        f"【图中文字】{text_in_image}\n"
        f"【图表数据】{chart}\n"
        f"【实体】{entities}\n"
        f"【视觉特征】{visual}\n"
        f"【场景类型】{scene}"
    )


# ---------------------------------------------------------------------------
# 1. 模板结构门禁
# ---------------------------------------------------------------------------


def test_image_description_template_has_structured_sections():
    """模板必须含全部 6 个分段段名，且逐字段要求逐字保留。"""
    tpl = ks_templates.TEMPLATES["image_description"]
    for section in ("【主体描述】", "【图中文字】", "【图表数据】", "【实体】", "【视觉特征】", "【场景类型】"):
        assert section in tpl, f"image_description 模板缺分段段名 {section}"
    assert "逐字" in tpl, "模板必须要求图中文字/实体逐字保留（BM25 逐字通道根基）"


# ---------------------------------------------------------------------------
# 2. 保护性截断语义
# ---------------------------------------------------------------------------


def test_truncate_within_limit_returns_original():
    """限内文本原样返回（不触发任何裁剪）。"""
    caption = _make_caption()
    assert document_pipeline._truncate_image_description(caption, _SILENT_LOGGER) == caption


def test_truncate_drops_longest_flexible_section_keeps_literal():
    """超限时丢弃最长的非逐字段，逐字段（图中文字/实体/图表数据）必须保留。"""
    # 主体描述拉长到必超限，逐字段短小
    caption = _make_caption(subject="长" * 5000)
    result = document_pipeline._truncate_image_description(caption, _SILENT_LOGGER)
    assert len(result) <= document_pipeline._image_caption_max_chars()
    assert "【图中文字】" in result and "NovaMind X100" in result, (
        "逐字段【图中文字】被截断丢弃——BM25 逐字通道受损"
    )
    assert "【实体】" in result, "逐字段【实体】被截断丢弃"
    assert "【主体描述】" not in result, "超限时应整段丢弃最长的主体描述段"
    # 段落结构保持完整（不留半段）
    for section in ("【图中文字】", "【图表数据】", "【实体】", "【视觉特征】", "【场景类型】"):
        assert section in result, f"段落 {section} 结构不完整"


def test_truncate_no_sections_falls_back_to_hard_cut():
    """无分段结构（旧模板产物）退化为尾部硬切，不报错不丢前缀。"""
    text = "旧" * 6000
    result = document_pipeline._truncate_image_description(text, _SILENT_LOGGER)
    assert result == text[: document_pipeline._image_caption_max_chars()]


def test_split_sections_preserves_order_and_first_occurrence():
    """分段切分保序；重复段名只作为边界一次，二次段体并入前一个保留段。"""
    text = "【主体描述】A\n【图中文字】B\n【主体描述】重复段\n【实体】C"
    sections = document_pipeline._split_image_caption_sections(text)
    names = [n for n, _ in sections]
    assert names == ["【主体描述】", "【图中文字】", "【实体】"]
    by_name = dict(sections)
    assert "重复段" in by_name["【图中文字】"], "二次段体应并入前一个保留段（就近归属）"


# ---------------------------------------------------------------------------
# 3. 配置化上限
# ---------------------------------------------------------------------------


def test_caption_max_chars_default_4000(monkeypatch):
    """无 YAML 配置时默认 4000（旧值 2000 会把实体/图表段整段切掉）。"""
    import novamind.setting.yaml_config.loader as loader_mod

    class _EmptyCfg:
        knowledge_base = None

    monkeypatch.setattr(loader_mod, "get_config", lambda: _EmptyCfg())
    assert document_pipeline._image_caption_max_chars() == 4000


def test_caption_max_chars_yaml_override(monkeypatch):
    """YAML knowledge_base.parsing.image_caption_max_chars 可覆盖默认。"""
    import novamind.setting.yaml_config.loader as loader_mod

    parsing = SimpleNamespace(image_caption_max_chars=8000)

    class _Cfg:
        knowledge_base = SimpleNamespace(parsing=parsing)

    monkeypatch.setattr(loader_mod, "get_config", lambda: _Cfg())
    assert document_pipeline._image_caption_max_chars() == 8000
