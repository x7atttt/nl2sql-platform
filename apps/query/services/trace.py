# -*- coding: utf-8 -*-
"""轻量 trace 埋点：record_span 落库 + span 上下文管理器计时。

用法（ChatService / 物化 / 技能等关键步骤）：
    with span(trace_id, 'llm', '生成SQL', model='deepseek-v4') as s:
        ...
        s.attrs['prompt_chars'] = len(prompt)   # 过程中补充属性
    # 离开 with 自动计时落库；块内抛异常记 error 后原样上抛
"""
import logging
import time
import uuid
from contextlib import contextmanager

from apps.query.models import TraceSpan

logger = logging.getLogger(__name__)


def new_trace_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def span(trace_id: str, span_type: str, name: str, **attrs):
    """计时 + 落库的步骤上下文。attributes 只放摘要（无完整 prompt/密钥）。"""

    class _Handle:
        pass

    handle = _Handle()
    handle.attrs = dict(attrs)
    start = time.time()
    status = 'ok'
    error = None
    try:
        yield handle
    except Exception as e:
        status = 'error'
        error = str(e)[:500]
        raise
    finally:
        duration_ms = int((time.time() - start) * 1000)
        if not trace_id:  # 无 trace 上下文（如独立调用服务层）不落库
            return
        attributes = {k: v for k, v in handle.attrs.items() if v is not None}
        if error:
            attributes['error'] = error
        try:
            TraceSpan.objects.create(
                trace_id=trace_id, span_type=span_type, name=name,
                status=status, duration_ms=duration_ms,
                attributes=attributes or None,
            )
        except Exception:
            # trace 落库失败不影响主流程（可观测性是旁路能力）
            logger.warning('trace span 落库失败: %s %s', span_type, name, exc_info=True)
