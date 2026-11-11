# Chat API

All endpoints require `Authorization: Bearer <access_token>`. Successful responses use the project's standard `success`, `status_code`, `message`, `data`, and `timestamp` envelope. IDs in response bodies are numeric. The server gets the current user from the token; callers must not supply sender or recipient IDs.

| Method | Path | Input | Result |
| --- | --- | --- | --- |
| GET | `/api/chat/assignments/{assignment_id}/conversation/` | Assignment ID in path | Conversation and selected assignment |
| GET | `/api/chat/conversations/` | Optional `page` query parameter | Page of conversations, per-conversation `unread_count`, and `total_unread` across all pages |
| GET | `/api/chat/conversations/{conversation_id}/` | Conversation ID in path | Conversation and associated assignments |
| POST | `/api/chat/messages/list/` | `{"conversation_id": 12, "cursor": null, "limit": 30}` | Visible messages in chronological order, `next_cursor` |
| POST | `/api/chat/messages/send/` | `{"conversation_id": 12, "message": "Xin chào"}` | Saved text message |
| POST | `/api/chat/messages/read/` | `{"conversation_id": 12}` | `marked_read` count |

`cursor` is the oldest message ID returned by the previous page. Omit it or send `null` for the newest page. `limit` defaults to 30 and is capped at 100.

The customer and worker share one conversation across their accepted assignments. Text messages are visible to both. Each assignment creates two `SYSTEM` messages: one visible only to the customer and one visible only to the worker. `sender_id` is `null` for system messages; `recipient_id` identifies the intended viewer. The conversation list's preview and unread count use the same visibility rule.

History remains readable after an assignment ends. Sending requires an accepted assignment with an active schedule and booking, and an `ACTIVE` conversation. The caller must be a participant. A new worker has a different conversation and cannot read the previous worker's messages.

Booking detail now includes `assignment_id` and `conversation_id` on each assigned schedule. Both are `null` when no worker has accepted that schedule.

Conversation summaries include `latest_assignment` with the most recently assigned booking code and schedule, so the inbox can label a pair-wide conversation without treating it as belonging to only one booking.

## Development sample data

With `DJANGO_SETTINGS_MODULE=core.settings.dev`, run `python manage.py migrate chat`, then `python manage.py seed_chat_demo`. The command creates isolated `chat_demo_customer` and `chat_demo_worker` users, two accepted schedules on booking `CHAT-DEMO-001`, four private assignment notices and three shared text messages. It is repeatable and refuses to run outside `DEBUG`. It prints random passwords when it creates the users; use `--reset-demo-passwords` to rotate those passwords later. Do not use demo accounts for real customer data.

## WebSocket

Participant text is redacted before saving or publishing. Send payloads may include
`client_message_id` for idempotent retries. REST sends may return HTTP 400 with
`error_code: CHAT_CONTENT_BLOCKED` or HTTP 403 with `CHAT_SEND_LOCKED`; socket
sends return an `error` with the same code, `conversation_id`, and structured
`detail`. Accepted REST sends and socket `message.accepted` include sender-only
`moderation` warning/status. Conversation summaries include current-user
`moderation` and user-specific `can_send`. A private `moderation.updated` event
asks that user's clients to refresh their conversation state. See
[chat moderation](chat_moderation.md) for policies, reference samples, configuration
and full error contracts.

Connect to `/ws/chat/` on the same ASGI server (`ws://` locally, `wss://` over TLS). The server accepts the socket and requires the first frame within 10 seconds:

```json
{"type":"auth","access_token":"<JWT access token>"}
```

Success returns `{"type":"auth.ok","user_id":101}`. Invalid or expired access tokens close the connection with code `4401`. Tokens are passed in the first frame, so they do not appear in the URL. Reconnect with a fresh access token after expiry.

After authentication, the client may send:

```json
{"type":"message.send","conversation_id":12,"message":"Xin chào"}
{"type":"messages.read","conversation_id":12}
{"type":"typing.start","conversation_id":12}
{"type":"typing.stop","conversation_id":12}
{"type":"ping"}
```

The server emits `message.created` with a `message` object matching the REST serializer, `messages.read` with a read receipt, `message.accepted` for a successful socket send, `messages.read.ack`, `pong`, or `error`. A customer or worker can receive `message.created` while viewing a different screen, so the client should use `conversation_id` to update its inbox and open chat. Private `SYSTEM` messages are delivered only to their `recipient_id`. REST sends and assignment notices emit the same socket event after the database transaction commits. On reconnect, reload REST history to catch events missed while disconnected.

Typing is ephemeral and requires the sender to be a conversation participant with an active assignment. `typing.start` and `typing.stop` emit `{"type":"typing.changed","conversation_id":12,"user_id":101,"is_typing":true}` only to the other participant. The server sends a stop event when the sender's socket disconnects; clients should also expire the indicator after a short timeout if an event is missed. No typing state is stored in the database.

Run the API with an ASGI server such as Daphne: `daphne -b 0.0.0.0 -p 8000 core.asgi:application`. Set `DJANGO_SETTINGS_MODULE` to a configured settings module before starting it. Set `REDIS_URL` for a shared Redis channel layer in deployments with multiple processes. For a single local development process, `CHAT_USE_IN_MEMORY_LAYER=1` skips Redis; it must not be used for multi-process deployment.
