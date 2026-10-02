"""
测试集解析器

支持 JSON 和 CSV 格式的测试集文件
"""
import csv
import io
import json

from novamind.features.evaluation.exceptions import InvalidTestSetError
from novamind.features.evaluation.schemas.evaluation_schema import TestCase, TestSet

# CSV 单元格里多段 contexts / expected_sources 的分隔符
CSV_LIST_SEPARATOR = "||"


def parse_test_set(file_content: bytes, filename: str) -> TestSet:
    """
    解析测试集文件

    Args:
        file_content: 文件内容（字节）
        filename: 文件名（用于判断格式）

    Returns:
        TestSet 对象

    Raises:
        InvalidTestSetError: 文件格式无效或内容不符合要求
    """
    ext = _get_extension(filename)

    if ext == ".json":
        return _parse_json(file_content)
    elif ext == ".csv":
        return _parse_csv(file_content)
    else:
        raise InvalidTestSetError(f"不支持的文件格式: {ext}，仅支持 .json 和 .csv")


def _get_extension(filename: str) -> str:
    """获取文件扩展名（含点号前缀）"""
    if not filename:
        raise InvalidTestSetError("文件名为空")
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _parse_json(file_content: bytes) -> TestSet:
    """解析 JSON 格式测试集"""
    try:
        data = json.loads(file_content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidTestSetError(f"JSON 解析失败: {e}")
    except UnicodeDecodeError:
        raise InvalidTestSetError("文件编码不是有效的 UTF-8")

    if not isinstance(data, dict):
        raise InvalidTestSetError("JSON 根元素必须是对象")

    test_cases_raw = data.get("test_cases")
    if not test_cases_raw or not isinstance(test_cases_raw, list):
        raise InvalidTestSetError("缺少 test_cases 字段或格式不正确（必须是非空数组）")

    cases = []
    for i, item in enumerate(test_cases_raw):
        if not isinstance(item, dict):
            raise InvalidTestSetError(f"第 {i + 1} 条测试用例必须是对象")
        question = item.get("question", "").strip()
        expected_answer = item.get("expected_answer", "").strip()
        if not question:
            raise InvalidTestSetError(f"第 {i + 1} 条测试用例缺少 question")
        if not expected_answer:
            raise InvalidTestSetError(f"第 {i + 1} 条测试用例缺少 expected_answer")
        cases.append(
            TestCase(
                question=question,
                expected_answer=expected_answer,
                contexts=_parse_str_list(item.get("contexts"), f"第 {i + 1} 条测试用例的 contexts"),
                expected_sources=_parse_str_list(
                    item.get("expected_sources"), f"第 {i + 1} 条测试用例的 expected_sources"
                ),
            )
        )

    return TestSet(
        name=data.get("name"),
        test_cases=cases,
    )


def _parse_str_list(raw: object, label: str) -> list[str]:
    """解析可选字符串列表字段（contexts / expected_sources）。

    缺省或 null 返回空表；提供时必须是字符串数组，空白项过滤；
    类型错误显式报错——静默忽略会让用户误以为字段已生效。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise InvalidTestSetError(f"{label} 必须是字符串数组")
    return [str(v).strip() for v in raw if str(v).strip()]


def _parse_csv(file_content: bytes) -> TestSet:
    """解析 CSV 格式测试集"""
    try:
        text = file_content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidTestSetError("文件编码不是有效的 UTF-8")

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames or "question" not in reader.fieldnames or "expected_answer" not in reader.fieldnames:
        raise InvalidTestSetError("CSV 文件必须包含 question 和 expected_answer 两列")

    cases = []
    for i, row in enumerate(reader):
        question = row.get("question", "").strip()
        expected_answer = row.get("expected_answer", "").strip()
        if not question:
            raise InvalidTestSetError(f"第 {i + 1} 行缺少 question")
        if not expected_answer:
            raise InvalidTestSetError(f"第 {i + 1} 行缺少 expected_answer")
        cases.append(
            TestCase(
                question=question,
                expected_answer=expected_answer,
                contexts=_split_csv_list(row.get("contexts")),
                expected_sources=_split_csv_list(row.get("expected_sources")),
            )
        )

    if not cases:
        raise InvalidTestSetError("CSV 文件没有数据行")

    return TestSet(test_cases=cases)


def _split_csv_list(raw: str | None) -> list[str]:
    """拆分 CSV 单元格的多值字段（|| 分隔），缺省列返回空表。"""
    if not raw:
        return []
    return [part.strip() for part in raw.split(CSV_LIST_SEPARATOR) if part.strip()]
