"""LangGraph 工作流共享状态定义。

以 :class:`KBState` 为中心的**报告式通信**模型：各 Agent（采集/分析/整理/审核）
之间不直接传递原始数据，而是交换**结构化摘要**——只含下游决策所需的
关键字段，控制跨 Agent 的消息体积与上下文成本。

用法:
    from workflows.state import KBState, CostTracker, new_state

    state: KBState = new_state()
    state["sources"] = [...]  # 各节点按字段读写
"""

from typing import TypedDict

# ── 常量 ──────────────────────────────────────────────────────────────────

MAX_ITERATIONS = 3
"""审核循环最大迭代次数：超过则视为未通过并结束流水线。"""

# ── 报告式摘要类型 ────────────────────────────────────────────────────────


class SourceEntry(TypedDict):
    """采集阶段产出的原始数据摘要（报告式：只保留下游必需字段）。

    Attributes:
        source_id: 来源条目唯一标识，格式 ``{source_type}-{date}-{seq}``。
        title: 标题。
        url: 原始链接。
        source_type: 来源类型 ``github_trending`` / ``hacker_news``。
        collected_at: 采集时间（ISO 8601）。
        popularity: 热度数值（stars / points）。
        summary: 一句话内容概述（可选，采集阶段不强制）。
    """

    source_id: str
    title: str
    url: str
    source_type: str
    collected_at: str
    popularity: float
    summary: str


class AnalysisEntry(TypedDict):
    """分析阶段产出：LLM 对单条 source 的结构化结论。

    Attributes:
        source_id: 对应的来源条目 ID，用于关联回 Sources。
        summary: AI 生成的摘要（<=200 字）。
        key_points: 关键要点列表（2-5 条）。
        score: 技术价值评分（1-10）。
        tags: 标签列表（2-5 个）。
    """

    source_id: str
    summary: str
    key_points: list[str]
    score: float
    tags: list[str]


class ArticleEntry(TypedDict):
    """整理阶段产出：格式化、去重后的最终知识条目。

    Attributes:
        id: 唯一标识，沿用 ``source_id`` 格式。
        title: 条目标题。
        source_url: 原始来源链接。
        source_type: 来源类型。
        summary: AI 摘要。
        key_points: 关键要点列表。
        tags: 标签列表。
        status: 状态（draft / review / published / archived）。
    """

    id: str
    title: str
    source_url: str
    source_type: str
    summary: str
    key_points: list[str]
    tags: list[str]
    status: str


class CostTracker(TypedDict):
    """Token 用量追踪（每次 LLM 调用后累加）。

    Attributes:
        llm_calls: 累计调用次数。
        prompt_tokens: 累计输入 token 数。
        completion_tokens: 累计输出 token 数。
        total_tokens: 累计总 token 数。
    """

    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# ── 共享状态 ──────────────────────────────────────────────────────────────


class KBState(TypedDict):
    """LangGraph 工作流全程共享的状态结构。

    字段均为结构化摘要而非原始数据（报告式通信原则），
    节点间以最小必要信息传递，降低上下文占用。
    """

    # 采集结果：SourceEntry 列表，每项是去冗余后的来源摘要
    sources: list[SourceEntry]

    # 分析结果：AnalysisEntry 列表，与 sources 通过 source_id 关联
    analyses: list[AnalysisEntry]

    # 知识条目：ArticleEntry 列表，经格式化与去重后的最终产物
    articles: list[ArticleEntry]

    # 审核反馈：Supervisor 对 articles 的具体改进意见（供重新分析迭代）
    review_feedback: str

    # 审核结论：True 表示达标可通过，False 表示需重做
    review_passed: bool

    # 审核循环计数：从 0 递增，达到 MAX_ITERATIONS 即强制结束
    iteration: int

    # Token 追踪：CostTracker 结构，跨节点累计 LLM 用量
    cost_tracker: CostTracker


# ── 工厂函数 ──────────────────────────────────────────────────────────────


def new_state() -> KBState:
    """构造一份初始化的 KBState。

    为所有字段提供安全的默认值，避免各节点重复判空。

    Returns:
        全字段初始化的状态字典。
    """
    return KBState(
        sources=[],
        analyses=[],
        articles=[],
        review_feedback="",
        review_passed=False,
        iteration=0,
        cost_tracker=CostTracker(
            llm_calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        ),
    )
