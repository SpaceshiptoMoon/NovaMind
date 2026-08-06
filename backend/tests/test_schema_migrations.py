"""SCHEMA_MIGRATIONS 注册表结构校验——防补列迁移漂移。

``core.database.schema_migrations.SCHEMA_MIGRATIONS`` 是 startup 期幂等补列的清单。
本测试锁定其结构契约：每条是 (表名, 列名, ALTER DDL) 三元组、DDL 形如
``ALTER TABLE <表名> ADD COLUMN ...``、无重复 (表,列)。新增迁移若违反格式会被
测试拦截，避免运行期 ALTER 语句写错表/列或重复补列。
"""
import re

import pytest

from novamind.core.database.schema_migrations import SCHEMA_MIGRATIONS

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