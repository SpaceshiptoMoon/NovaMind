"""回归测试：get_session_factory 首次调用不得自死锁。

缺陷（2026-09-07 独立诊断脚本实测踩坑）：修复前 get_session_factory 先拿
``_engine_lock``，再在 with 块内调 ``get_engine()``——后者内部对同一把
**非重入** threading.Lock 二次加锁，同线程自死锁。应用启动期 get_engine()
总是先被调用（引擎已建好走快路径），因此线上未暴露；任何未先建引擎的
独立调用（脚本/CLI）首次调用即永久挂起。

修复：get_engine() 移到锁外先行调用。本测试在干净子进程中以 sqlite 假配置
首次调用 get_session_factory()，用子进程超时判定死锁——挂起即失败。
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = BACKEND_DIR / "src"

# 子进程体：monkeypatch 假配置（mysql URL 仅创建引擎、惰性连接不真连库），
# 重置全局单例后首次调用 get_session_factory——修复前在此自死锁。
_CHILD_CODE = f"""
import sys
sys.path.insert(0, r"{SRC_DIR}")

import novamind.core.database.database as db


class _FakeDatabase:
    url = "mysql+aiomysql://user:pass@localhost:3306/pytest_no_connect"
    ssl = False
    pool_size = 5
    max_overflow = 10
    pool_timeout = 30
    pool_recycle = 3600
    pool_pre_ping = True


class _FakeConfig:
    database = _FakeDatabase()


db.get_config = lambda: _FakeConfig()
db._engine = None
db._session_factory = None

factory = db.get_session_factory()  # 修复前：同线程对 _engine_lock 二次加锁自死锁
assert factory is not None
print("SESSION_FACTORY_OK")
"""


def test_get_session_factory_first_call_does_not_deadlock():
    """干净子进程首次调用 get_session_factory 必须在超时内正常返回。"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_CODE],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError(
            "get_session_factory 首次调用疑似自死锁（子进程 30s 超时）——"
            "检查 get_engine() 是否被放回了 _engine_lock 的 with 块内"
        ) from None
    assert result.returncode == 0, f"子进程异常退出：{result.stderr[-500:]}"
    assert "SESSION_FACTORY_OK" in result.stdout