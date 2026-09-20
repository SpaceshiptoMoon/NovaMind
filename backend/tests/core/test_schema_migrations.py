"""SCHEMA_MIGRATIONS / CONSTRAINT_MIGRATIONS 注册表结构校验——防启动期迁移漂移。

``core.database.schema_migrations`` 是 startup 期幂等迁移的清单。本测试锁定其
结构契约：

- SCHEMA_MIGRATIONS：每条是 (表名, 列名, ALTER DDL) 三元组、DDL 形如
  ``ALTER TABLE <表名> ADD COLUMN ...``、无重复 (表,列)。
- CONSTRAINT_MIGRATIONS：每条是 (表名, 旧索引, 新索引, ADD DDL) 四元组、DDL 形如
  ``ALTER TABLE <表名> ADD UNIQUE KEY|INDEX <新索引> ...``、无重复 (表,新索引)。

新增迁移若违反格式会被测试拦截，避免运行期 ALTER 语句写错表/列/索引。
"""
import re

import pytest
from novamind.core.database.schema_migrations import (
    CONSTRAINT_MIGRATIONS,
    SCHEMA_MIGRATIONS,
)

pytestmark = pytest.mark.unit


def test_entries_are_nonempty_three_tuples_of_str():
    assert len(SCHEMA_MIGRATIONS) > 0, "SCHEMA_MIGRATIONS 不应为空"
    for entry in SCHEMA_MIGRATIONS:
        assert isinstance(entry, tuple) and len(entry) == 3, f"条目非 3 元组: {entry!r}"
        table, column, ddl = entry
        assert all(isinstance(x, str) and x for x in (table, column, ddl)), f"条目含空/非字符串: {entry!r}"


def test_ddl_well_formed_add_column_matches_table():
    """DDL 必须形如 ALTER TABLE <表名> ADD COLUMN ...，且表名与条目首元素一致、列名出现在 DDL。"""
    pattern = re.compile(r"^ALTER TABLE `?(\w+)`? ADD COLUMN ", re.IGNORECASE)
    for table, column, ddl in SCHEMA_MIGRATIONS:
        m = pattern.match(ddl)
        assert m, f"DDL 不以 'ALTER TABLE <表> ADD COLUMN' 开头: {ddl!r}"
        assert m.group(1) == table, f"DDL 表名 {m.group(1)!r} 与条目表名 {table!r} 不一致"
        assert column in ddl, f"列名 {column!r} 未出现在 DDL: {ddl!r}"


def test_no_duplicate_table_column():
    """同一 (表,列) 不得出现两次，否则幂等补列清单冗余且暗示漂移。"""
    seen: set[tuple[str, str]] = set()
    for table, column, _ in SCHEMA_MIGRATIONS:
        key = (table, column)
        assert key not in seen, f"重复的 (表,列) 迁移条目: {key}"
        seen.add(key)


def test_constraint_entries_are_nonempty_four_tuples_of_str():
    assert len(CONSTRAINT_MIGRATIONS) > 0, "CONSTRAINT_MIGRATIONS 不应为空"
    for entry in CONSTRAINT_MIGRATIONS:
        assert isinstance(entry, tuple) and len(entry) == 4, f"条目非 4 元组: {entry!r}"
        assert all(isinstance(x, str) and x for x in entry), f"条目含空/非字符串: {entry!r}"


def test_constraint_ddl_well_formed_matches_table_and_index():
    """ADD DDL 必须形如 ALTER TABLE <表> ADD UNIQUE KEY|INDEX <新索引> ...，
    且表名/新索引名与条目一致；新旧索引名不得相同（否则幂等检测永不生效）。"""
    pattern = re.compile(
        r"^ALTER TABLE `?(\w+)`? ADD (?:UNIQUE KEY|INDEX) `?(\w+)`? ", re.IGNORECASE
    )
    for table, old_index, new_index, ddl in CONSTRAINT_MIGRATIONS:
        m = pattern.match(ddl)
        assert m, f"DDL 不匹配 'ALTER TABLE <表> ADD UNIQUE KEY|INDEX <索引>': {ddl!r}"
        assert m.group(1) == table, f"DDL 表名 {m.group(1)!r} 与条目表名 {table!r} 不一致"
        assert m.group(2) == new_index, f"DDL 索引名 {m.group(2)!r} 与条目新索引 {new_index!r} 不一致"
        assert old_index != new_index, (
            f"新旧索引名相同 ({old_index!r})：幂等检测基于新索引存在性，相同名会跳过 drop 导致迁移失效"
        )


def test_constraint_no_duplicate_table_index():
    """同一 (表,新索引) 不得出现两次。"""
    seen: set[tuple[str, str]] = set()
    for table, _, new_index, _ in CONSTRAINT_MIGRATIONS:
        key = (table, new_index)
        assert key not in seen, f"重复的 (表,新索引) 迁移条目: {key}"
        seen.add(key)