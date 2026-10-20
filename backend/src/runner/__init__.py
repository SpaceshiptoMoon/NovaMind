"""伴生 runner：用户电脑上的哑执行器（P0 骨架）。

与云端的关系：runner 不 import 云端代码、不持智能——收 call →
安全校验（与云端同判据的独立实现）→ 本机执行 read/glob/grep → 回 result。
连接永远是 runner 主动出站（NAT 免穿透），断线指数退避重连。
"""
