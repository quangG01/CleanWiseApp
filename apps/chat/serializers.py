from rest_framework import serializers

from .models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    conversation_id = serializers.IntegerField(read_only=True)
    sender_id = serializers.IntegerField(read_only=True)
    recipient_id = serializers.IntegerField(read_only=True)
    related_assignment_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = (
            'id', 'conversation_id', 'sender_id', 'recipient_id',
            'related_assignment_id', 'message', 'message_type',
            'attachment', 'is_read', 'created_at',
        )


class MessageListInputSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(min_value=1)
    cursor = serializers.IntegerField(min_value=1, allow_null=True, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=100, default=30)


class MessageSendInputSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(min_value=1)
    message = serializers.CharField(max_length=2000, trim_whitespace=True, allow_blank=False)


class MessageReadInputSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField(min_value=1)
