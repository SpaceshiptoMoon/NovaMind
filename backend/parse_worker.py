"""解析管道独立 worker 进程（backend=stream 时的消费端）。

与 main.py（API 进程）对称的进程入口——backend=stream 时由 supervisor/
脚本拉起，消费 nm:parse:tasks 流；默认 backend=arq 时本进程不需要启动。

启动初始化链复制 API 必需子集（config → 加密 → ClientFactory → prompt
注册）；消费循环/认领门控/reaper/延迟搬运在 parse_stream_consumer 中。
任务表 schema 由 API 进程负责创建（compose 下 API 先于 worker 就绪）。
"""
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from novamind.shared.logging import get_logger, setup_structured_logging


async def main() -> None:
    from novamind.setting.yaml_config import get_config

    config = get_config()
    setup_structured_logging()
    logger = get_logger("parse_worker")

    if config.task_queue.backend != "stream":
        logger.warning(
            "task_queue.backend 不是 stream，parse_worker 无事可做，退出",
            backend=config.task_queue.backend,
        )
        return

    # ---- 初始化链（API 必需子集） ----
    from novamind.core.security.encryption import configure_encryption_key

    configure_encryption_key(config.security.encryption_key)

    from novamind.shared.storage.client_factory import ClientFactory

    ClientFactory.configure(config)

    from novamind.core.middleware.prompt_registration import (
        register_all_prompt_templates,
    )

    register_all_prompt_templates()

    # ---- 消费循环 + reaper + 延迟搬运 ----
    from novamind.features.knowledge_space.tasks.parse_stream_consumer import (
        run_delayed_dispatcher,
        run_parse_consumer,
        run_reaper,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(run_parse_consumer(stop_event)),
        asyncio.create_task(run_reaper(stop_event)),
        asyncio.create_task(run_delayed_dispatcher(stop_event)),
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("parse_worker 退出")


if __name__ == "__main__":
    asyncio.run(main())
