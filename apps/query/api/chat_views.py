# -*- coding: utf-8 -*-
"""对话 API：会话 CRUD + SSE 流式问答。

权限口径（见存储/产品演进 RFC）：对话链路门禁押后——登录即可用，
不做 DatasetShare 校验；跨用户访问会话本身仍按 404 防枚举。
"""
import json

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError
from django.http import StreamingHttpResponse
from django.db import close_old_connections

from apps.datasets.models import Dataset
from apps.datasources.models import ExternalDataSource
from apps.query.models import Conversation, ChatMessage, TraceSpan
from apps.query.services.chat import ChatService


def _first_by_uuid(model, raw_id):
    """按 uuid 查单条；入参非 uuid 格式或不存在统一返回 None（body 参数没有
    URL converter 兜底，UUIDField 遇到格式非法会抛 ValidationError → 500）。"""
    try:
        return model.objects.filter(id=raw_id).first()
    except (ValidationError, ValueError, TypeError):
        return None


def _serialize_conversation(conv: Conversation) -> dict:
    return {
        'id': str(conv.id),
        'chat_mode': conv.chat_mode,
        'dataset_id': str(conv.dataset_id) if conv.dataset_id else None,
        'dataset_name': conv.dataset.name if conv.dataset else None,
        'source_id': str(conv.source_id) if conv.source_id else None,
        'source_name': conv.source.name if conv.source else None,
        'source_db_type': conv.source.db_type if conv.source else None,
        'title': conv.title,
        'skill': conv.skill,
        'created_at': conv.created_at.isoformat(),
        'updated_at': conv.updated_at.isoformat(),
    }


def _serialize_message(msg: ChatMessage) -> dict:
    return {
        'id': msg.id,
        'round_index': msg.round_index,
        'role': msg.role,
        'content': msg.content,
        'extra': msg.extra,
        'created_at': msg.created_at.isoformat(),
    }


def _get_own_conversation(request, conv_id) -> Conversation | None:
    """按 id 取当前用户的会话；不存在/他人会话统一 None（404 防枚举）。"""
    try:
        return Conversation.objects.select_related('dataset', 'source').get(
            id=conv_id, user=request.user)
    except Conversation.DoesNotExist:
        return None


class ChatSkillView(APIView):
    """技能清单（skills/ 目录扫描注册，插拔即生效）。"""

    def get(self, request):
        from apps.query.services.skills import list_skills
        return Response({'results': [
            {'name': s.name, 'description': s.description}
            for s in list_skills()
        ]})


class ChatConversationView(APIView):
    """会话列表 / 新建会话（chat_file 绑定数据集、chat_db 绑定外部源）。"""

    def get(self, request):
        convs = (
            Conversation.objects.filter(user=request.user)
            .select_related('dataset', 'source')
            .order_by('-updated_at')[:100]
        )
        return Response({'results': [_serialize_conversation(c) for c in convs]})

    def post(self, request):
        chat_mode = request.data.get('chat_mode')
        if chat_mode not in ('chat_file', 'chat_db'):
            return Response({'error': 'chat_mode 必须是 chat_file 或 chat_db'},
                            status=status.HTTP_400_BAD_REQUEST)

        # 技能可选：必须在注册表内（防注入任意 prompt 文本）
        skill = (request.data.get('skill') or '').strip()
        if skill:
            from apps.query.services.skills import get_skill
            if get_skill(skill) is None:
                return Response({'error': f'技能不存在: {skill}'},
                                status=status.HTTP_400_BAD_REQUEST)

        if chat_mode == 'chat_file':
            dataset = _first_by_uuid(Dataset, request.data.get('dataset_id'))
            if dataset is None:
                return Response({'error': '数据集不存在'},
                                status=status.HTTP_404_NOT_FOUND)
            if dataset.status != 'completed':
                return Response({'error': '数据集尚未处理完成'},
                                status=status.HTTP_400_BAD_REQUEST)
            conv = Conversation.objects.create(
                user=request.user, chat_mode=chat_mode, dataset=dataset, skill=skill)
        else:
            source = _first_by_uuid(ExternalDataSource,
                                    request.data.get('source_id'))
            if source is None:
                return Response({'error': '数据源不存在'},
                                status=status.HTTP_404_NOT_FOUND)
            conv = Conversation.objects.create(
                user=request.user, chat_mode=chat_mode, source=source, skill=skill)

        return Response(_serialize_conversation(conv), status=status.HTTP_201_CREATED)


class ChatConversationDetailView(APIView):
    """单个会话：GET 取会话+全部消息（回放），DELETE 删会话。"""

    def get(self, request, conv_id):
        conv = _get_own_conversation(request, conv_id)
        if conv is None:
            return Response({'error': '会话不存在'}, status=status.HTTP_404_NOT_FOUND)
        messages = conv.messages.order_by('round_index', 'id')
        return Response({
            'conversation': _serialize_conversation(conv),
            'messages': [_serialize_message(m) for m in messages],
        })

    def delete(self, request, conv_id):
        conv = _get_own_conversation(request, conv_id)
        if conv is None:
            return Response({'error': '会话不存在'}, status=status.HTTP_404_NOT_FOUND)
        conv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatTraceView(APIView):
    """回答过程追溯：按 assistant 消息 id 拉取该轮的 span 时间线。"""

    def get(self, request, message_id):
        msg = ChatMessage.objects.filter(
            id=message_id, conversation__user=request.user,
            role='assistant',
        ).first()
        if msg is None:
            return Response({'error': '消息不存在'}, status=status.HTTP_404_NOT_FOUND)
        trace_id = (msg.extra or {}).get('trace_id')
        if not trace_id:
            return Response({'trace_id': None, 'spans': []})
        spans = TraceSpan.objects.filter(trace_id=trace_id)
        return Response({
            'trace_id': trace_id,
            'spans': [
                {
                    'span_type': s.span_type, 'name': s.name,
                    'status': s.status, 'duration_ms': s.duration_ms,
                    'attributes': s.attributes,
                    'created_at': s.created_at.isoformat(),
                }
                for s in spans
            ],
        })


class ChatMessageStreamView(APIView):
    """SSE 流式问答。帧协议见 services/chat.py 模块注释，以 data: [DONE] 收尾。"""

    def post(self, request, conv_id):
        conv = _get_own_conversation(request, conv_id)
        if conv is None:
            return Response({'error': '会话不存在'}, status=status.HTTP_404_NOT_FOUND)
        question = (request.data.get('question') or '').strip()
        if not question:
            return Response({'error': '问题不能为空'},
                            status=status.HTTP_400_BAD_REQUEST)

        service = ChatService(conv)

        def event_stream():
            try:
                for frame in service.stream(question):
                    yield f'data: {json.dumps(frame, ensure_ascii=False)}\n\n'
            except Exception as e:  # 管线意外异常也要以帧协议收尾，前端不会挂起
                error = json.dumps(
                    {'type': 'error', 'message': f'服务内部错误: {e}'},
                    ensure_ascii=False)
                yield f'data: {error}\n\n'
            finally:
                yield 'data: [DONE]\n\n'
                # 流式响应里 ORM 连接生命周期跨请求，手动收尾防连接堆积
                close_old_connections()

        response = StreamingHttpResponse(event_stream(),
                                         content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # Nginx 不缓冲，逐帧直通
        return response
