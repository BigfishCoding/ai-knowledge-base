"""分发模块：将知识条目格式化并推送到多渠道（ClawBot / 飞书）。

- ``formatter``: 纯函数，将知识条目渲染为 Markdown / ClawBot / 飞书卡片
- ``publisher``: （后续实现）负责网络推送，消费 formatter 的输出
"""
