"""skill_parser name 校验回归测试。

P0 修复背景：``parse_skill_md``（上传链路实际调用方）原先不校验 name 格式，
与 ``validate_skill_md`` 不一致 —— ``BadName_1`` 之类大写/下划线 name 能入库，
且下划线 name 会加剧 ``skill__{id}_{name}`` 引用解析歧义。
"""
import pytest

from novamind.features.skill.services.skill_parser import parse_skill_md, validate_skill_md


def _skill_md(name: str) -> str:
    return f"---\nname: {name}\ndescription: 测试技能\n---\n\n正文内容"


@pytest.mark.unit
@pytest.mark.parametrize("bad_name", ["BadName", "bad_name", "1bad", "bad name", "-bad"])
def test_parse_skill_md_rejects_invalid_name(bad_name: str) -> None:
    """parse_skill_md 拒绝非 kebab-case name（与 validate_skill_md 同规则）"""
    with pytest.raises(ValueError, match="name 格式无效"):
        parse_skill_md(_skill_md(bad_name))


@pytest.mark.unit
@pytest.mark.parametrize("good_name", ["code-reviewer", "my-skill2", "a"])
def test_parse_skill_md_accepts_kebab_case(good_name: str) -> None:
    """kebab-case name 正常解析，字段透传不变"""
    parsed = parse_skill_md(_skill_md(good_name))
    assert parsed.name == good_name
    assert parsed.description == "测试技能"
    assert parsed.body_markdown == "正文内容"


@pytest.mark.unit
@pytest.mark.parametrize("bad_name", ["BadName", "bad_name", "1bad"])
def test_validate_skill_md_reports_invalid_name(bad_name: str) -> None:
    """validate_skill_md 保持原行为：name 格式错误进 errors"""
    result = validate_skill_md(_skill_md(bad_name))
    assert not result.valid
    assert any("name 格式无效" in e for e in result.errors)
