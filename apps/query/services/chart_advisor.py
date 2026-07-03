"""图表智能推荐服务：用 LLM 根据查询语义推荐最合适的图表类型。

参考 LIDA 的 Summary 模式（统计摘要而非全量数据进 prompt）+
Vanna 的三要素（question + sql + df 元数据）。

设计要点：
1. LLM 只输出"选型建议"（chartType + xField + yFields + reason），
   不输出完整 ECharts option——前者失败可降级到规则引擎，后者失败图表空白。
2. 异步调用：查询立即返回，前端拿到规则引擎默认图后，单独请求本服务。
3. 失败降级：LLM 超时/非法 JSON/字段不存在 → 返回 None，前端继续用规则引擎图。
"""
import json
import re
import logging
from string import Template

from django.conf import settings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# 支持的图表类型（与前端 chartSelector.ts 的 ChartType 对齐）
_VALID_CHART_TYPES = {'bar', 'line', 'pie', 'scatter', 'area', 'none'}

# LLM 客户端单例（复用 embedding.py 的惰性初始化范式）
_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0,  # 确定性输出，图表选型不需要创造性
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
        )
    return _llm


# ===== Prompt 模板（遵循项目 string.Template 模式）=====

CHART_SUGGEST_SYSTEM = Template("""你是一个数据可视化专家。根据用户问题、SQL 和查询结果统计摘要，推荐最合适的图表类型。

【选型规则】
- 排名/对比（"前N""最高""最受欢迎"）→ 柱状图（bar）
- 占比/构成（"分布""占比""各部分"）→ 饼图（pie，类别 ≤7 时）；类别多时降级柱状图
- 时间趋势（"随时间""每月""趋势"）→ 折线图（line）
- 相关性（"关系""相关""vs"）→ 散点图（scatter）
- 累积/进度 → 面积图（area）
- 明细数据（SQL 无 GROUP BY 且列多行多）→ none（不建议可视化）
- 单个数值（如"总共多少"）→ none（单个数字无需图表）

【判断要点】
- 看 SQL 语义：有 GROUP BY → 已聚合，直接画；有 ORDER BY DESC → 排名，优先柱状
- 看"用户问题"的措辞：分布/占比 → 饼图；趋势 → 折线；排名/对比 → 柱状
- 看 distinct 数量：>7 个类别不适合饼图（标签挤）；>20 个类别柱状图也要考虑横向

【业务说明】
$business_description

只输出 JSON，不要任何解释或 markdown 包裹。""")

CHART_SUGGEST_USER = Template("""【用户问题】$question

【生成的 SQL】
$sql

【结果列统计】
$column_stats

【行数】$row_count 行

请推荐图表，输出 JSON：
{"chartType": "bar|line|pie|scatter|area|none", "xField": "列名", "yFields": ["列名"], "reason": "推荐理由", "alternatives": ["备选类型"]}""")


def _escape_braces(text: str) -> str:
    """转义花括号，避免 ChatPromptTemplate 误解析 JSON（复用 nl2sql.py 同名逻辑）"""
    return text.replace('{', '{{').replace('}', '}}')


def _build_column_stats(columns: list, column_types: dict, data: list) -> str:
    """构建列统计摘要文本（借鉴 LIDA get_column_properties 思路）。

    不塞全量数据，只给 LLM 看每列的类型 + distinct 数 + 前 3 个样本值，
    让它判断列语义（维度 vs 度量）和可视化价值。
    """
    if not data:
        return '(无数据)'

    lines = []
    for col in columns:
        col_type = column_types.get(col, 'text')
        # 收集该列非空样本值（最多 3 个）
        samples = []
        for row in data:
            val = row.get(col)
            if val is not None and val != '':
                samples.append(str(val)[:40])  # 截断长值
                if len(samples) >= 3:
                    break
        distinct = len(set(str(row.get(col)) for row in data if row.get(col) is not None))
        sample_str = ', '.join(samples) if samples else '(全空)'
        lines.append(f'- {col} ({col_type}): {distinct} distinct, 样本: {sample_str}')

    return '\n'.join(lines)


def _extract_json(text: str) -> dict | None:
    """从 LLM 响应里提取 JSON（防 markdown 包裹 + 提取首个 JSON 对象）。

    借鉴 LIDA utils.clean_code_snippet 的正则思路 + 兜底解析。
    """
    # 1. 尝试提取 ```json ... ``` 或 ``` ... ``` 代码块
    code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_match:
        text = code_match.group(1)
    # 2. 尝试提取首个 {...} JSON 对象（LLM 可能在 JSON 前后加了解释文字）
    obj_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except json.JSONDecodeError:
            pass
    # 3. 直接尝试整体解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def _validate_suggestion(suggestion: dict, columns: list) -> dict | None:
    """校验 LLM 返回的选型建议：字段是否存在、类型是否合法。

    校验失败返回 None（调用方降级到规则引擎）。
    """
    chart_type = suggestion.get('chartType')
    if chart_type not in _VALID_CHART_TYPES:
        return None

    # none 类型无需校验轴字段
    if chart_type == 'none':
        return {
            'chartType': None,
            'xField': '',
            'yFields': [],
            'reason': suggestion.get('reason', 'LLM 判断不适合可视化'),
            'alternatives': [],
        }

    x_field = suggestion.get('xField', '')
    y_fields = suggestion.get('yFields', [])

    # 校验 xField 在列里（饼图/单数值场景 xField 可为空）
    if x_field and x_field not in columns:
        return None
    # 校验 yFields 都在列里
    valid_y = [y for y in y_fields if y in columns]
    if not valid_y:
        return None

    return {
        'chartType': chart_type,
        'xField': x_field,
        'yFields': valid_y,
        'reason': suggestion.get('reason', ''),
        'alternatives': [
            a for a in suggestion.get('alternatives', [])
            if a in _VALID_CHART_TYPES and a != chart_type
        ],
    }


def suggest_chart(
    question: str,
    sql: str,
    columns: list,
    column_types: dict,
    data: list,
    business_description: str = '',
) -> dict | None:
    """用 LLM 推荐图表选型。

    Args:
        question: 用户原始问题（NL2SQL 的输入）
        sql: 生成的 SQL（含 LIMIT，LLM 看 GROUP BY/ORDER BY 语义）
        columns: 结果列名列表
        column_types: 列类型映射 {col: 'number'|'text'|'date'|'boolean'}
        data: 结果行（list[dict]），只取统计摘要不塞全量
        business_description: 数据集业务说明（可选，帮助 LLM 理解字段语义）

    Returns:
        ChartSuggestion dict（与前端 chartSelector.ts 接口对齐）：
        {chartType, xField, yFields, reason, alternatives}
        chartType 为 null 表示不建议可视化。
        失败（LLM 超时/非法 JSON/校验不过）返回 None，调用方降级到规则引擎。
    """
    if not data:
        return None

    column_stats = _build_column_stats(columns, column_types, data)
    row_count = len(data)

    try:
        prompt = ChatPromptTemplate.from_messages([
            ('system', _escape_braces(CHART_SUGGEST_SYSTEM.safe_substitute(
                business_description=business_description or '无',
            ))),
            ('human', _escape_braces(CHART_SUGGEST_USER.safe_substitute(
                question=question,
                sql=sql,
                column_stats=column_stats,
                row_count=str(row_count),
            ))),
        ])
        chain = prompt | _get_llm()
        response = chain.invoke({})
        raw = response.content
    except Exception as e:
        logger.warning('chart_advisor LLM 调用失败，降级到规则引擎: %s', e)
        return None

    suggestion = _extract_json(raw)
    if suggestion is None:
        logger.warning('chart_advisor JSON 解析失败，原始响应: %s', raw[:300])
        return None

    return _validate_suggestion(suggestion, columns)
