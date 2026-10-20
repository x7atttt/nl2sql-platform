"""文本向量化服务：把问题文本转 1024 维向量，用于 few-shot 语义检索。

按 DashScope 原生协议直调（POST {EMBEDDING_API_BASE}，body 用
input.texts / parameters.dimension 结构），不走 langchain 的
OpenAIEmbeddings——后者要求 OpenAI 兼容端点，而当前中转只开放原生路径。
不引入新依赖（urllib 零依赖）。

维度固定 1024：与 QueryHistory.question_embedding 的 VectorField(1024)
及 HNSW 索引对齐；Qwen text-embedding-v3/v4 的 dimension 参数均支持 1024。
"""
import json
import logging
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

_EMBEDDING_DIMENSIONS = 1024
_EMBEDDING_TIMEOUT = 20


def embed_question(text: str) -> list[float] | None:
    """把问题文本转成 1024 维向量。

    Returns:
        向量列表；接口异常时返回 None（调用方应跳过 embedding 写入，
        不阻塞主查询流程——few-shot 退化为时间倒序或无案例）
    """
    if not text or not text.strip():
        return None
    body = json.dumps({
        'model': settings.EMBEDDING_MODEL,
        'input': {'texts': [text.strip()]},
        # 检索两侧都是"问题"（查询词对查询词），text_type 统一 query 保持同空间
        'parameters': {'text_type': 'query', 'dimension': _EMBEDDING_DIMENSIONS},
    }).encode()
    req = urllib.request.Request(
        settings.EMBEDDING_API_BASE.rstrip('/'),
        data=body,
        headers={
            'Authorization': f'Bearer {settings.EMBEDDING_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        resp = urllib.request.urlopen(req, timeout=_EMBEDDING_TIMEOUT)
        data = json.loads(resp.read().decode())
        vector = data['output']['embeddings'][0]['embedding']
        if len(vector) != _EMBEDDING_DIMENSIONS:
            logger.warning('embed_question 维度异常 %d（预期 %d），丢弃',
                           len(vector), _EMBEDDING_DIMENSIONS)
            return None
        return vector
    except Exception as e:
        # embedding 失败不阻塞查询（最坏情况是这条记录不参与语义检索）
        logger.warning('embed_question 失败，跳过向量写入: %s', e)
        return None
