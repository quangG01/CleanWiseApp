from rest_framework import serializers

from apps.ai_engine.models import ChatbotMessage, ChatbotSession
from .models import ChatbotRun, HelpArticle


class ConversationCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False, allow_blank=True, default='')


class ConversationUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=ChatbotSession.Status.choices, required=False)


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatbotSession
        fields = ['id', 'title', 'status', 'created_at', 'updated_at']
        read_only_fields = fields


class MessageInputSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000, trim_whitespace=True)
    client_message_id = serializers.UUIDField()


class MessageSerializer(serializers.ModelSerializer):
    text = serializers.CharField(source='message', read_only=True)
    role = serializers.SerializerMethodField()
    run_id = serializers.SerializerMethodField()

    class Meta:
        model = ChatbotMessage
        fields = ['id', 'role', 'text', 'cards', 'status', 'client_message_id', 'run_id', 'created_at']
        read_only_fields = fields

    def get_role(self, obj) -> str:
        return {'CUSTOMER': 'user', 'BOT': 'assistant', 'SYSTEM': 'system'}[obj.sender_type]

    def get_run_id(self, obj) -> str | None:
        run = getattr(obj, 'chatbot_run', None) if obj.sender_type == 'CUSTOMER' else getattr(obj, 'reply_run', None)
        return str(run.id) if run else None


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatbotRun
        fields = ['id', 'status', 'error_code', 'attempts', 'duration_ms', 'created_at', 'finished_at']
        read_only_fields = fields


class MessageReplySerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField()
    run = RunSerializer()
    user_message = MessageSerializer()
    assistant_message = MessageSerializer()
    replayed = serializers.BooleanField()


class RunDetailSerializer(serializers.Serializer):
    run = RunSerializer()
    user_message = MessageSerializer()
    assistant_message = MessageSerializer(allow_null=True)


class HelpArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = HelpArticle
        fields = ['id', 'slug', 'version', 'title', 'summary', 'sections', 'effective_from', 'source_document']
