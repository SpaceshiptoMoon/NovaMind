"""知识运营（KB-OPS）feature：事件账本与运营信号。

当前批次 O1 范围：KbEvent 事件账本 + EventRecorder 写入端口 + 会话内改写检测。
查询侧信号（问答量/零命中/低分/点踩）由 qa 的 extra + knowledge_space 看板承担，
本 feature 只记没有归宿的事件（用户行为信号、归因结果、跨会话信号），不重复建设。
"""
