"""缓存模块：RedisCache 客户端（redis_client）与 cache-aside 薄助手（helpers）。

本包不做 re-export：client_factory 懒 import redis_client 时会执行本文件，
在此处 import helpers 会把 client_factory 拉回来。使用方直接 import 子模块。
"""
