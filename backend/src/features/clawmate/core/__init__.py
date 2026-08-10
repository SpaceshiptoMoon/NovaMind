"""clawmate 运行时核心：服务 + 工具 + 安全守卫的聚合目录。

刻意命名为 ``core/`` 而非项目约定 ``services/``：本目录混合承载业务服务
（``chat_service.py``）、命令/文件安全守卫（``command_safety.py`` /
``file_safety.py``）、运行时配置与环境（``config.py`` / ``environment.py``）、
上下文适配（``context_adapter.py``）、记忆存储（``memory_store.py``）以及
工具实现（``tools/``）。内容不止于 service，故不套用 ``services/`` 命名。
"""