"""智能推荐查询服务：根据数据集 schema 生成 4 条推荐问题。

解决用户冷启动焦虑——上传完数据集后面对空查询框不知道能问什么。
LLM 看 schema 摘要 + 业务说明，生成覆盖不同分析维度的 4 条推荐。

设计要点：
1. 4 条覆盖不同维度（分布/排名/趋势/对比），避免 4 个 COUNT
2. 只生成"问题文本"，不生成 SQL（SQL 由 NL2SQL 流水线处理）
3. 失败返回空列表，不阻塞数据集使用（推荐是锦上添花）
4. 结果缓存在 Dataset.suggested_questions，二次进入不重算
"""
import json
import re
import logging
from string import Template

from django.conf import settings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

# LLM 客户端单例（复用 embedding/chart_advisor 的惰性初始化范式）
_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=0.7,  # 推荐问题需要一点多样性，不像 SQL 生成要确定性
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
        )
    return _llm


QUESTION_SUGGEST_SYSTEM = Template("""你是一个数据分析专家。根据数据集的 schema 摘要和业务说明，生成 4 条用户可能想问的自然语言查询问题。

【生成规则】
1. 生成恰好 4 条问题，每条不超过 25 字
2. 4 条必须覆盖不同分析维度，避免都是计数：
   - 分布类：各 X 的数量占比（如"各部门人数占比"）
   - 排名类：最 X 的前 N 名（如"薪资最高的前 5 名"）
   - 趋势类：随时间变化的趋势（如"每月入职人数"，需有日期列）
   - 对比类：不同维度的指标对比（如"各部门平均年龄对比"）
3. 问题只基于 schema 里真实存在的列，不要编造列名
4. 问题用自然口语，不要出现 SQL 语法（用户用中文问，AI 转 SQL）

【业务说明】
$business_description

只输出 JSON，不要任何解释或 markdown 包裹。""")

QUESTION_SUGGEST_USER = Template("""【数据集名称】$dataset_name

【Schema 摘要】
$schema_summary

请生成 4 条推荐查询，输出 JSON：
{"questions": ["问题1", "问题2", "问题3", "问题4"]}""")


def _escape_braces(text: str) -> str:
    """转义花括号，避免 ChatPromptTemplate 误解析 JSON"""
    return text.replace('{', '{{').replace('}', '}}')


def _extract_questions(text: str) -> list[str]:
    """从 LLM 响应提取问题列表（防 markdown 包裹）。

    借鉴 chart_advisor._extract_json 的清洗思路。
    """
    # 1. 提取 ```json ... ``` 代码块
    code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_match:
        text = code_match.group(1)
    # 2. 尝试解析 JSON
    try:
        data = json.loads(text.strip())
        questions = data.get('questions', []) if isinstance(data, dict) else []
    except json.JSONDecodeError:
        # 3. 兜底：正则提取 "..." 字符串列表
        matches = re.findall(r'"([^"]+)"', text)
        questions = matches if matches else []
    # 清洗：去空白、去重、最多 4 条
    seen = set()
    result = []
    for q in questions:
        q = q.strip()
        if q and q not in seen and len(q) <= 50:
            seen.add(q)
            result.append(q)
        if len(result) >= 4:
            break
    return result


def generate_suggested_questions(
    dataset_name: str,
    schema_summary: str,
    business_description: str = '',
) -> list[str]:
    """用 LLM 生成 4 条推荐查询问题。

    Args:
        dataset_name: 数据集名称
        schema_summary: schema 发现摘要（列名 + 类型 + 样本，来自 get_schema_summary）
        business_description: 业务说明（可选，帮 LLM 理解字段语义）

    Returns:
        最多 4 条推荐问题字符串。失败返回空列表（调用方应容错）。
    """
    if not schema_summary or '尚未处理完成' in schema_summary:
        return []

    try:
        prompt = ChatPromptTemplate.from_messages([
            ('system', _escape_braces(QUESTION_SUGGEST_SYSTEM.safe_substitute(
                business_description=business_description or '无',
            ))),
            ('human', _escape_braces(QUESTION_SUGGEST_USER.safe_substitute(
                dataset_name=dataset_name[:50],  # 防超长数据集名
                schema_summary=schema_summary,
            ))),
        ])
        chain = prompt | _get_llm()
        response = chain.invoke({})
        return _extract_questions(response.content)
    except Exception as e:
        logger.warning('generate_suggested_questions 失败: %s', e)
        return []
