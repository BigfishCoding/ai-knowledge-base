"""每日知识简报推送入口脚本。

从 :mod:`distribution.formatter` 加载当日知识条目，过滤低质量文章后，
调用 :func:`distribution.publisher.publish_daily_digest` 并发推送到所有
已配置渠道，并输出推送结果汇总（成功/失败渠道数）。

用法::

    python daily_digest.py                        # 今日，默认 knowledge/articles
    python daily_digest.py --date 2026-04-11      # 指定日期
    python daily_digest.py --threshold 0.8        # 提高低质量过滤阈值
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根目录注入 sys.path，保证 distribution 包可导入
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from distribution import formatter, publisher  # noqa: E402

logger = logging.getLogger(__name__)

# 低质量过滤阈值默认取 formatter 的中分线（0.6），低于视为低质量
DEFAULT_SCORE_THRESHOLD = formatter.MEDIUM_SCORE_THRESHOLD

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表；None 时使用 ``sys.argv[1:]``。

    Returns:
        解析后的参数命名空间。
    """
    parser = argparse.ArgumentParser(description="每日知识简报推送入口")
    parser.add_argument(
        "--knowledge-dir",
        default=formatter.DEFAULT_KNOWLEDGE_DIR,
        help="知识条目目录，默认 %(default)s",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="日期（YYYY-MM-DD）；缺省使用今天 UTC",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=formatter.DEFAULT_TOP_N,
        help="按相关性降序取前 N 条，默认 %(default)s",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SCORE_THRESHOLD,
        help="低质量过滤阈值（0-1），低于该值视为低质量，默认 %(default)s",
    )
    return parser.parse_args(argv)


def _report(results: list[publisher.PublishResult]) -> int:
    """输出推送结果汇总并计算退出码。

    Args:
        results: 各渠道的发布结果列表。

    Returns:
        存在失败渠道或没有任何渠道时返回 1；全部成功返回 0。
    """
    success = [result for result in results if result.success]
    failed = [result for result in results if not result.success]

    for result in failed:
        logger.error("[%s] 推送失败: %s", result.channel, result.error)

    if not results:
        logger.warning("没有任何已配置的分发渠道，跳过推送")
        return 1

    logger.info(
        "推送汇总：成功 %d 个渠道，失败 %d 个渠道",
        len(success),
        len(failed),
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """推送当日简报到所有已配置渠道。

    流程：加载当日文章 → 过滤低质量 → 无高质量则跳过 → 并发发布 → 汇总。

    Args:
        argv: 命令行参数列表；None 时使用 ``sys.argv[1:]``。

    Returns:
        跳过推送或全部成功返回 0；存在失败渠道返回 1。
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    args = _parse_args(argv)

    target = Path(args.knowledge_dir)
    date = args.date or datetime.now(timezone.utc).strftime(formatter.DATE_FORMAT)

    articles = formatter._load_articles(target, date)
    high_quality = [
        article
        for article in articles
        if formatter._score(article) >= args.threshold
    ]
    logger.info(
        "日期 %s 共 %d 篇文章，高质量（≥%.2f）%d 篇",
        date,
        len(articles),
        args.threshold,
        len(high_quality),
    )

    if not high_quality:
        logger.warning("无高质量文章，跳过推送")
        return 0

    results = asyncio.run(
        publisher.publish_daily_digest(
            knowledge_dir=target,
            date=date,
            top_n=args.top_n,
            score_threshold=args.threshold,
        )
    )
    return _report(results)


if __name__ == "__main__":
    raise SystemExit(main())
