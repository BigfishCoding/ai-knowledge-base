# ============== 构建层 ==============
FROM python:3.12-slim AS builder
WORKDIR /build
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# ============== 运行层 ==============
FROM python:3.12-slim
LABEL version="4.0"

WORKDIR /app
COPY --from=builder /install /usr/local

# 先 V3 继承（workflows / patterns），再 V4 新增（pipeline / distribution / bot）
# 顺序体现 "V4 = V3 + 分发 + Bot"
COPY workflows/ ./workflows/
COPY patterns/ ./patterns/
COPY pipeline/ ./pipeline/
COPY distribution/ ./distribution/
COPY bot/ ./bot/
COPY tests/ ./tests/

# 运行时数据目录（volume 会挂这里）
RUN mkdir -p /app/knowledge/articles /app/knowledge/raw /app/data

# 非 root 用户跑
RUN groupadd -r appuser && useradd -r -g appuser appuser && \
    chown -R appuser:appuser /app
USER appuser

# 健康检查 · 验证模块能 import（最低限度的"代码完整性"探针）
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import bot.knowledge_bot" || exit 1

CMD ["python", "-m", "bot.telegram_bot"]