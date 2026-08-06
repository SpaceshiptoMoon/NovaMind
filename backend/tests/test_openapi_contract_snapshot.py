"""openapi 契约快照测试——锁定 API 表面，任何路径/组件/参数变更需显式更新 baseline。

5 同名 Pydantic 重命名（commit 4e0d687）后 openapi 跨运行字节确定（零 ``_1``/``_2``
碰撞后缀），具备可靠快照条件。本测试把 ``create_app().openapi()`` 全量与
``tests/fixtures/openapi_baseline.json`` 逐键比对，任何 feature 改动意外改契约会被
立刻拦住。

合法契约变更（新增端点、改响应模型等）需同步更新 baseline（用 ``newline=''`` 保 LF）：
    PYTHONPATH=src .venv/Scripts/python.exe -c "
    import json; from novamind.core.middleware.app_factory import create_app
    json.dump(create_app().openapi(), open('tests/fixtures/openapi_baseline.json','w',encoding='utf-8',newline=''), ensure_ascii=False, indent=2, sort_keys=True)"
"""
import json
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).resolve().parent / "fixtures" / "openapi_baseline.json"

pytestmark = pytest.mark.unit


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _current_openapi() -> dict:
    from novamind.core.middleware.app_factory import create_app

    return create_app().openapi()


def test_openapi_matches_baseline():
    """全量 openapi 必须与 baseline 逐键一致，否则即契约变更。"""
    baseline = _load_baseline()
    current = _current_openapi()

    if baseline == current:
        return

    # 差异定位：顶层键 + paths + components.schemas
    base_keys = set(baseline) | set(current)
    top_diff = {k: {"baseline": type(baseline.get(k)).__name__, "current": type(current.get(k)).__name__} for k in base_keys if baseline.get(k) != current.get(k)}

    b_paths = set(baseline.get("paths", {}).keys())
    c_paths = set(current.get("paths", {}).keys())
    path_diff = {
        "only_in_baseline": sorted(b_paths - c_paths),
        "only_in_current": sorted(c_paths - b_paths),
    }

    b_schemas = set(baseline.get("components", {}).get("schemas", {}).keys())
    c_schemas = set(current.get("components", {}).get("schemas", {}).keys())
    schema_diff = {
        "only_in_baseline": sorted(b_schemas - c_schemas),
        "only_in_current": sorted(c_schemas - b_schemas),
    }

    pytest.fail(
        "openapi 与 baseline 不一致——契约已变更。\n"
        f"  顶层键差异: {top_diff}\n"
        f"  paths 差异: {path_diff}\n"
        f"  schemas 差异: {schema_diff}\n"
        "若为合法变更，请重新生成 baseline（见本文件 docstring 顶部命令）。"
    )


def test_openapi_baseline_is_deterministic_across_runs():
    """连续两次生成 openapi 必须逐键一致——防 5 同名 Pydantic 类回归。"""
    a = _current_openapi()
    b = _current_openapi()
    assert a == b, "openapi 跨运行非确定——疑似同名 Pydantic 响应类重新引入碰撞"