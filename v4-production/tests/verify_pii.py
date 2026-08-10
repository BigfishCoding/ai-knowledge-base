"""验证 Security · PII 掩码（实操任务 4.3）。

两步验证：
1. 直接调用 ``filter_output`` 掩码手机号 / 邮箱 / IP；
2. 走真实 :func:`organize_node`，确认出口过滤已接入生产路径
   （summary / key_points 中的 PII 在写盘前被掩码）。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.security import filter_output
from workflows import nodes
from workflows.state import new_state

SAMPLE = "联系作者 13812345678 或 author@example.com 获取完整代码 · IP 192.168.1.1"


def _verify_filter() -> None:
    """直接验证 filter_output 掩码手机号 / 邮箱 / IP。"""
    filtered, detections = filter_output(SAMPLE, mask=True)
    print(f"原文：{SAMPLE}")
    print(f"掩码：{filtered}")
    print(f"检出：{detections}")
    assert "[PHONE_CN_MASKED]" in filtered
    assert "[EMAIL_MASKED]" in filtered
    assert "[IP_ADDRESS_MASKED]" in filtered
    assert len(detections) == 3, detections
    print("[OK] filter_output 掩码手机号 / 邮箱 / IP")


def _verify_organize_wiring() -> None:
    """构造带 PII 的分析结果，验证 organize_node 出口掩码生效。"""
    st = new_state()
    st["plan"] = {"relevance_threshold": 0.5}
    st["sources"] = [
        {
            "source_id": "a",
            "title": "标题",
            "url": "u1",
            "source_type": "gh",
            "collected_at": "x",
            "popularity": 1.0,
            "summary": "s",
        }
    ]
    st["analyses"] = [
        {
            "source_id": "a",
            "summary": SAMPLE,
            "key_points": ["电话 13812345678", "正常要点"],
            "score": 0.8,
            "tags": ["llm"],
        }
    ]
    result = nodes.organize_node(st)
    article = result["articles"][0]
    assert "[EMAIL_MASKED]" in article["summary"], article["summary"]
    assert "[PHONE_CN_MASKED]" in article["key_points"][0], article["key_points"]
    assert article["key_points"][1] == "正常要点"
    print(f"[OK] organize_node 出口 PII 掩码已生效: {article['summary']}")
    print(f"    key_points: {article['key_points']}")


if __name__ == "__main__":
    _verify_filter()
    _verify_organize_wiring()
    print("\n4.3 PII 掩码验证通过")
