"""文本向量化服务：调智谱 embedding-3 接口把文本转 2048 维向量。

复用现有 OPENAI_API_KEY / OPENAI_API_BASE（智谱 OpenAI 兼容协议），
不引入新依赖（langchain-openai 已装，OpenAIEmbeddings 直接可用）。

用于 few-shot 语义检索：把查询问题向量化后存 QueryHistory.question_embedding，
检索时按余弦距离找语义最相关的历史成功查询作为 few-shot 案例。
"""
import logging
from django.conf import settings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)

# 模型名（智谱 embedding-3）
# 用 1024 维而非默认 2048：HNSW 索引限制 ≤2000 维，且 1024 对几百条 few-shot 检索精度足够
_EMBEDDING_MODEL = 'embedding-3'
_EMBEDDING_DIMENSIONS = 1024

# 单例惰性初始化，避免每次调用都新建客户端
_embedder: OpenAIEmbeddings | None = None


def _get_embedder() -> OpenAIEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = OpenAIEmbeddings(
            model=_EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_API_BASE,
            # embedding-3 支持自定义维度（langchain-openai 的 dimensions 是顶层参数）
            dimensions=_EMBEDDING_DIMENSIONS,
        )
    return _embedder


def embed_question(text: str) -> list[float] | None:
    """把问题文本转成 2048 维向量。

    Returns:
        向量列表；接口异常时返回 None（调用方应跳过 embedding 写入，
        不阻塞主查询流程——few-shot 退化为时间倒序或无案例）
    """
    if not text or not text.strip():
        return None
    try:
        return _get_embedder().embed_query(text)
    except Exception as e:
        # embedding 失败不阻塞查询（最坏情况是这条记录不参与语义检索）
        logger.warning('embed_question 失败，跳过向量写入: %s', e)
        return None
