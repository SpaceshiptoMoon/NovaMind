"""本地工作区服务层：安全校验、执行器端口、工具实现。

两种部署形态共用同一套安全校验与工具定义：
- 云端形态：RunnerExecutor 经伴生 runner 的出站 WSS 转发执行
- 本地形态：InProcessExecutor 进程内直接执行

设计文档：docs/agent/local-workspace-runner-design.md
"""
