# Chat redaction, warnings and temporary send restrictions

Customer and worker text is processed by `apps/chat/service.py:send_text_message`.
REST and WebSocket share authorization, redaction, idempotency and enforcement.
Account status is never changed. Only the offending user's sending is restricted;
history, incoming messages, bookings and existing support channels remain available.

## Policy

Count one violation per submitted message across all of a user's conversations,
using a rolling 30-day window. Multiple categories in one message count once.

| Count | Action |
| --- | --- |
| 1–3 | Redact or reject offending content and privately warn the sender |
| 4 | Reject the message and lock sending for 1 day |
| 5 | Reject the message and lock sending for 3 days |
| 6+ | Reject the message and lock sending for 7 days |

Sends attempted during an active lock do not add violations or extend it.
A lock expires by server timestamp comparison; no scheduler is required. Counts
age out of the rolling window, but an already active lock runs until its expiry.
The next violation after an administrator unlock uses the remaining recent count.

## Detection and storage

`redaction.py` normalizes a copy with offsets back to the original Unicode text.
Phone numbers, email addresses and external URLs become `[SĐT đã ẩn]`,
`[Email đã ẩn]` and `[Liên kết đã ẩn]`; surrounding original prose is preserved.
Unicode digit, invisible-character, separator and email `[at]`/`[dot]` variants
are covered. Vietnamese spoken digits require contact context. Ordinary work
information and labelled bank account numbers are not automatically phones.

`CHAT_ALLOWED_LINK_HOSTS` is an environment variable with comma-separated exact
HTTP(S) hostnames. It is empty by default: all links are external. Explicitly
configure the actual CleanWise domains; subdomains require their own entries.
Userinfo URLs, other protocols and host lookalikes are not trusted.

The existing local regex and TF-IDF cosine filter still rejects residual private
contact invitations, off-platform payment requests and solicitation. Its settings
remain `CHAT_MODERATION_COSINE_THRESHOLD` (0.4) and `CHAT_MODERATION_COSINE_MARGIN`
(0.12). Scores express lexical similarity, not confidence or intent.

Only sanitized accepted text reaches ChatMessage, history, inbox previews and
message.created events. Content containing only contacts, remaining solicitation,
or the violation triggering a lock is not saved or published as a chat message.
Violation rows store categories, user, conversation, action and timestamp, without
raw contact values. System messages and existing history are not reprocessed.

## Transactions and retries

Both apps send `client_message_id` (1–100 ASCII letters/digits/underscore/hyphen),
retaining it when retrying a failed message. It is optional for older clients;
older clients without it do not receive idempotency guarantees.

A user-row lock serializes sends across conversations on PostgreSQL. A unique
user/client-message key stores a keyed HMAC fingerprint and the original outcome,
including rejections. Replays return that outcome without re-counting, re-saving
or re-publishing. Reusing a key for another conversation/text returns 403.
Records contain no raw submitted message. Retain attempt records while clients
may retry; deleting them removes their idempotency guarantees.

Policy rejections are returned from the inner transaction and raised only after
it commits, preserving warnings and locks. Do not wrap the send entry point in
an outer rollback-on-error transaction or enable ATOMIC_REQUESTS for it without
preserving this behavior.

## API and UI

Accepted sends return HTTP 201 with the usual serialized message plus sender-only
`moderation` (null for ordinary text, otherwise warning/status). WebSocket
message.accepted includes the same sender-only moderation. Recipient message.created
contains only safe text and client_message_id, without warning counts.

Blocked content returns HTTP 400 / `CHAT_CONTENT_BLOCKED`; active or newly applied
locks return HTTP 403 / `CHAT_SEND_LOCKED`. The existing error envelope's `errors`
contains code, message, violation_count, warning_limit, window_days, is_locked and
locked_until. Blocked content also includes violation_type. Socket errors carry
the same object in detail.

Conversation summaries include the current viewer's moderation status and a
user-specific can_send. A private `moderation.updated` socket invalidation refreshes
all of that sender's connected devices after a violation or administrator unlock.
The apps show private warnings, recent counts and a localized unlock date, disable
the composer while locked, refetch on focus/reconnect/app resume/expiry, and
reconcile sanitized socket messages by client_message_id even if HTTP is lost.

## Administration and rollout

Migration: `0005_chatmessage_client_message_id_chatrestriction_and_more`.
Apply migrations to the target database before restarting the backend, then ship
both app updates. No production database has been migrated by this code change.

Django Admin provides read-only ChatViolation and ChatRestrictionAudit history,
and a ChatRestriction action to unlock sending. Unlocks record the administrator,
previous expiry and timestamp and notify the user's connected devices. Violation
history is preserved. No separate dashboard page or account suspension is added.

Policy values can be overridden in Django settings: CHAT_VIOLATION_WINDOW_DAYS=30,
CHAT_WARNING_LIMIT=3, CHAT_LOCK_DAYS=(1, 3, 7). Keep values positive and lock days nonempty.

## Validation and limits

Run from the backend:

```powershell
myenv\Scripts\python.exe manage.py test apps.chat.tests_policy apps.chat.tests_moderation apps.chat.tests_websocket apps.chat.tests.ChatApiTests.test_blocked_messages_do_not_save_or_publish_for_either_participant apps.chat.tests.ChatApiTests.test_allowed_message_preserves_original_text apps.chat.tests.ChatApiTests.test_authorization_precedes_content_moderation --settings=core.settings.test --noinput
```

From CleanWiseAppFE, run `node --test scripts/tests/chat-moderation.test.cjs` to
exercise both actual app hooks. Run TypeScript checks in each frontend.

SQLite skips the row-lock concurrency test. Run it using an isolated PostgreSQL
test database before production rollout to validate concurrent enforcement.
Migration creation and application were separately checked on in-memory SQLite.

The full existing chat suite has nine pre-existing failures because claim_schedule
does not establish the conversations expected by those tests. This was already
recorded in the previous moderation documentation. New policy fixtures explicitly
establish a conversation; this change does not alter assignment behavior.

This version handles new text only. It does not inspect images, QR, audio,
attachments, profile fields or contacts split across messages, and unusual
obfuscation can evade detection. Detection is not proof of intentional misconduct.
Use a separate anonymized evaluation set to tune false positives and misses.
