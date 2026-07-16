"""每日 AI 知识库采集流水线入口脚本.

串行执行 collector → analyzer → organizer → reviewer，
支持失败告警通知和日志记录。

用法:
    python run_pipeline.py              # 执行完整 pipeline
    python run_pipeline.py --skip-review  # 跳过审计步骤
    python run_pipeline.py --step collector  # 只执行指定步骤
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 路径常量 ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
LOGS_DIR = PROJECT_ROOT / "logs"
RAW_DIR = KNOWLEDGE_DIR / "raw"
ARTICLES_DIR = KNOWLEDGE_DIR / "articles"
REPORTS_DIR = KNOWLEDGE_DIR / "reports"

# ── Pipeline 步骤定义 ───────────────────────────────────────────────────────
PIPELINE_STEPS = [
    {"name": "collector", "module": "agents.collector", "description": "采集 GitHub Trending / Hacker News"},
    {"name": "analyzer",  "module": "agents.analyzer",  "description": "LLM 分析去重摘要评分"},
    {"name": "organizer", "module": "agents.organizer", "description": "格式标准化生成日报"},
    {"name": "reviewer",  "module": "agents.reviewer",  "description": "独立审计质量检查"},
]

# ── 日志配置 ─────────────────────────────────────────────────────────────────
LOGS_DIR.mkdir(parents=True, exist_ok=True)

log_filename = LOGS_DIR / f"pipeline-{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("pipeline")


# ── 环境变量加载 ────────────────────────────────────────────────────────────
def load_env() -> None:
    """从 .env 文件加载环境变量（不覆盖已存在的变量）."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        logger.warning(".env 文件不存在，将使用系统环境变量")
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
        logger.info("已从 .env 加载环境变量")
    except ImportError:
        # fallback: 手动解析 .env
        logger.info("python-dotenv 未安装，手动解析 .env")
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


# ── 环境检查 ────────────────────────────────────────────────────────────────
def check_environment() -> bool:
    """检查必要的环境变量和目录是否就绪."""
    errors = []

    # 检查 LLM API Key
    if not os.environ.get("LLM_API_KEY"):
        errors.append("LLM_API_KEY 未设置，请在 .env 中配置")

    # 检查必要目录
    for d in [RAW_DIR, ARTICLES_DIR, REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    if errors:
        for e in errors:
            logger.error(e)
        return False

    logger.info("环境检查通过")
    return True


# ── 单步执行 ───────────────────────────────────────────────────────────────
def run_step(step: dict) -> bool:
    """执行单个 pipeline 步骤.

    Args:
        step: 步骤配置字典，包含 name, module, description.

    Returns:
        True 表示执行成功.
    """
    name = step["name"]
    start_time = time.time()

    logger.info(f"{'='*50}")
    logger.info(f"开始执行: {name} — {step['description']}")
    logger.info(f"{'='*50}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", step["module"]],
            capture_output=True,
            text=True,
            timeout=600,  # 单步超时 10 分钟
            cwd=str(PROJECT_ROOT),
        )

        elapsed = time.time() - start_time

        if result.stdout.strip():
            logger.info(f"[{name}] stdout:\n{result.stdout.strip()}")

        if result.returncode != 0:
            logger.error(f"[{name}] 失败 (exit code: {result.returncode}, 耗时: {elapsed:.1f}s)")
            if result.stderr.strip():
                logger.error(f"[{name}] stderr:\n{result.stderr.strip()}")
            return False

        logger.info(f"[{name}] 完成 (耗时: {elapsed:.1f}s)")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"[{name}] 超时 (>600s)")
        return False
    except Exception as e:
        logger.error(f"[{name}] 异常: {e}")
        return False


# ── 告警通知 ──────────────────────────────────────────────────────────────
def send_alert(failed_steps: list[str]) -> None:
    """Pipeline 失败时发送告警通知（Telegram + 飞书）.

    Args:
        failed_steps: 失败的步骤名称列表.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    message = f"AI Knowledge Base Pipeline 失败 ({today})\n失败步骤: {', '.join(failed_steps)}\n请检查日志: {log_filename}"

    # Telegram 告警
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try:
            import requests as req
            req.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=10,
            )
            logger.info("Telegram 告警已发送")
        except Exception as e:
            logger.error(f"Telegram 告警发送失败: {e}")
    else:
        logger.warning("未配置 Telegram 告警，跳过")

    # 飞书告警
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL")
    if webhook_url:
        try:
            import requests as req
            payload = {
                "msg_type": "text",
                "content": {"text": message},
            }
            req.post(webhook_url, json=payload, timeout=10)
            logger.info("飞书告警已发送")
        except Exception as e:
            logger.error(f"飞书告警发送失败: {e}")


# ── Pipeline 汇总 ──────────────────────────────────────────────────────────
def write_summary(results: dict[str, bool], total_time: float) -> Path:
    """写入本次执行的汇总 JSON.

    Args:
        results: 各步骤名称到成功/失败的映射.
        total_time: 总耗时秒数.

    Returns:
        汇总文件路径.
    """
    summary = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "total_time_seconds": round(total_time, 2),
        "steps": {name: {"status": "success" if ok else "failed"} for name, ok in results.items()},
        "overall": "success" if all(results.values()) else "failed",
    }

    summary_path = LOGS_DIR / f"summary-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"执行汇总已写入: {summary_path}")
    return summary_path


# ── 主函数 ─────────────────────────────────────────────────────────────────
def main() -> int:
    """执行完整或部分 pipeline.

    Returns:
        0 表示全部成功，1 表示有失败.
    """
    parser = argparse.ArgumentParser(description="AI Knowledge Base 每日采集 Pipeline")
    parser.add_argument("--skip-review", action="store_true", help="跳过 reviewer 审计步骤")
    parser.add_argument("--step", type=str, help="只执行指定步骤 (collector/analyzer/organizer/reviewer)")
    parser.add_argument("--dry-run", action="store_true", help="只检查环境，不执行")
    args = parser.parse_args()

    # 加载环境变量
    load_env()

    # 环境检查
    if not check_environment():
        return 1

    if args.dry_run:
        logger.info("Dry-run 模式，环境检查通过，退出")
        return 0

    # 确定要执行的步骤
    if args.step:
        steps = [s for s in PIPELINE_STEPS if s["name"] == args.step]
        if not steps:
            logger.error(f"未知步骤: {args.step}，可选: {[s['name'] for s in PIPELINE_STEPS]}")
            return 1
    else:
        steps = list(PIPELINE_STEPS)
        if args.skip_review:
            steps = [s for s in steps if s["name"] != "reviewer"]
            logger.info("已跳过 reviewer 步骤")

    # 执行 pipeline
    pipeline_start = time.time()
    results: dict[str, bool] = {}
    failed_steps: list[str] = []

    for step in steps:
        success = run_step(step)
        results[step["name"]] = success
        if not success:
            failed_steps.append(step["name"])
            logger.error(f"步骤 {step['name']} 失败，继续执行后续步骤...")
            # 不中断，让后续步骤也尝试执行（上游失败下游可能部分可用）

    total_time = time.time() - pipeline_start

    # 写入汇总
    write_summary(results, total_time)

    # 最终报告
    logger.info(f"{'='*50}")
    logger.info(f"Pipeline 执行完毕 (总耗时: {total_time:.1f}s)")
    logger.info(f"结果: {'全部成功' if not failed_steps else '失败: ' + ', '.join(failed_steps)}")
    logger.info(f"{'='*50}")

    # 失败告警
    if failed_steps:
        send_alert(failed_steps)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
