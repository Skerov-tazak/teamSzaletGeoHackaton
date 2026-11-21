"""
Chat endpoints, exactly as agreed in docs/interfaces.md -> Chat (built in the assistant app,
see INTERFACE_PROPOSALS.md #8). No authentication, no CSRF (single-farm demo).

    POST /api/chat/                       {conversation_id|null, message, field_id|null} -> {conversation_id, message}
    GET  /api/chat/conversations/         [{id, title, updated_at}]
    GET  /api/chat/conversations/{id}/    {id, title, messages: [...]}
"""
from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Conversation, Message


def message_json(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "text": m.text,
        "citations": m.citations if m.role == Message.Role.ASSISTANT else [],
        "focus_field_id": m.focus_field_id,
        "updated_field_ids": (m.meta or {}).get("updated_field_ids", []),
        "chart": (m.meta or {}).get("chart"),                    # Vega-Lite spec or null (docs/interfaces.md -> Chat)
        "pending_action": (m.meta or {}).get("pending_action"),  # {"type": "confirm_observation", "draft": {...}} or null
        "created_at": m.created_at.isoformat().replace("+00:00", "Z"),
    }


class ChatIn(serializers.Serializer):
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    message = serializers.CharField(max_length=4000, trim_whitespace=True)
    field_id = serializers.IntegerField(required=False, allow_null=True)


MessageOut = inline_serializer("ChatMessage", fields={
    "id": serializers.IntegerField(), "role": serializers.CharField(), "text": serializers.CharField(),
    "citations": serializers.ListField(child=serializers.DictField()),
    "focus_field_id": serializers.IntegerField(allow_null=True),
    "updated_field_ids": serializers.ListField(child=serializers.IntegerField()),
    "chart": serializers.DictField(allow_null=True),
    "pending_action": serializers.DictField(allow_null=True),
    "created_at": serializers.DateTimeField()})


class OpenAPIView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]


class ChatView(OpenAPIView):
    """Send a message; returns the assistant's answer (saved, with citations)."""

    @extend_schema(request=ChatIn, responses=inline_serializer("ChatReply", fields={
        "conversation_id": serializers.IntegerField(), "message": MessageOut}))
    def post(self, request):
        from core.models import Field

        from .answer import answer

        data = ChatIn(data=request.data)
        data.is_valid(raise_exception=True)
        d = data.validated_data
        field = None
        if d.get("field_id") is not None:
            field = Field.objects.filter(pk=d["field_id"]).first()
            if field is None:
                return Response({"detail": f"field {d['field_id']} not found"}, status=status.HTTP_400_BAD_REQUEST)
        if d.get("conversation_id") is not None:
            conv = Conversation.objects.filter(pk=d["conversation_id"]).first()
            if conv is None:
                return Response({"detail": f"conversation {d['conversation_id']} not found"},
                                status=status.HTTP_404_NOT_FOUND)
        else:
            conv = Conversation.objects.create(title=Conversation.title_from(d["message"]))
        Message.objects.create(conversation=conv, role=Message.Role.USER, text=d["message"], field=field)

        reply = answer(conv, d["message"], field)

        meta = dict(reply.meta) | {"updated_field_ids": reply.updated_field_ids}
        msg = Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, text=reply.text,
                                     citations=reply.citations, focus_field_id=reply.focus_field_id, meta=meta)
        return Response({"conversation_id": conv.id, "message": message_json(msg)})


class ConversationListView(OpenAPIView):
    @extend_schema(responses=inline_serializer("ConversationItem", many=True, fields={
        "id": serializers.IntegerField(), "title": serializers.CharField(), "updated_at": serializers.DateTimeField()}))
    def get(self, request):
        return Response([{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat().replace("+00:00", "Z")}
                         for c in Conversation.objects.all()[:200]])


class ConversationDetailView(OpenAPIView):
    @extend_schema(responses=inline_serializer("ConversationDetail", fields={
        "id": serializers.IntegerField(), "title": serializers.CharField(),
        "messages": serializers.ListField(child=serializers.DictField())}))
    def get(self, request, pk: int):
        conv = Conversation.objects.filter(pk=pk).first()
        if conv is None:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"id": conv.id, "title": conv.title,
                         "messages": [message_json(m) for m in conv.messages.all()]})
