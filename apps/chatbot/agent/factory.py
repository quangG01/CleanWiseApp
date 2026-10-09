import json
import time

from django.conf import settings
from django.utils import timezone
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import (ModelCallLimitMiddleware, ModelRetryMiddleware,
                                         ToolCallLimitMiddleware, before_model, wrap_model_call)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from .checkpoint import open_checkpointer
from .errors import retryable_model_error
from .prompts import SYSTEM_PROMPT
from .schemas import AgentAnswer, AgentContext
from .tools import CUSTOMER_TOOLS
from ..exceptions import AgentUnavailable


@before_model
def enforce_deadline(state: AgentState, runtime: Runtime[AgentContext]):
    if time.monotonic() > runtime.context.deadline:
        raise TimeoutError('Chatbot run deadline exceeded')
    return None


@wrap_model_call
def enforce_model_budget(request, handler):
    remaining = request.runtime.context.deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Chatbot run deadline exceeded')
    return handler(request.override(model_settings={
        **request.model_settings,
        'timeout': min(settings.CHATBOT_MODEL_TIMEOUT, remaining),
    }))


def create_customer_agent(model, checkpointer):
    return create_agent(
        model=model,
        tools=CUSTOMER_TOOLS,
        system_prompt=SYSTEM_PROMPT + '\nThời điểm hiện tại: ' + timezone.localtime().isoformat(),
        context_schema=AgentContext,
        checkpointer=checkpointer,
        middleware=[
            enforce_deadline,
            ModelCallLimitMiddleware(run_limit=settings.CHATBOT_MAX_MODEL_CALLS, exit_behavior='error'),
            ToolCallLimitMiddleware(run_limit=settings.CHATBOT_MAX_TOOL_CALLS, exit_behavior='error'),
            ModelRetryMiddleware(max_retries=1, retry_on=retryable_model_error,
                                 initial_delay=1, max_delay=2, on_failure='error'),
            enforce_model_budget,
        ],
        name='cleanwise_customer_assistant',
    )


def extract_answer(result):
    messages = result['messages']
    final = messages[-1]
    if not isinstance(final, AIMessage) or final.tool_calls:
        raise ValueError('Agent did not produce a final answer')
    content = final.content
    if isinstance(content, list):
        content = '\n'.join(block.get('text', '') for block in content
                            if isinstance(block, dict) and block.get('type') == 'text')
    if not isinstance(content, str) or not content.strip() or len(content) > 12000:
        raise ValueError('Agent returned invalid content')
    candidates = {}
    detail_references = []
    mentioned_references = []
    selected_references = None
    source_references = []
    usage = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'model_calls': 0, 'tool_calls': 0}
    # Count only messages generated after the current user input, excluding
    # committed transcript pairs that are replayed as context.
    current_start = max(i for i, message in enumerate(messages) if isinstance(message, HumanMessage)) + 1
    for message in messages[current_start:]:
        if isinstance(message, AIMessage):
            usage['model_calls'] += 1
            for key in ('input_tokens', 'output_tokens', 'total_tokens'):
                usage[key] += int((message.usage_metadata or {}).get(key, 0))
        if isinstance(message, ToolMessage):
            usage['tool_calls'] += 1
            artifact = message.artifact or {}
            if isinstance(artifact, dict):
                for ref in artifact.get('cards', []):
                    if (isinstance(ref, dict) and ref.get('type') in ('service', 'booking', 'schedule', 'help')
                            and type(ref.get('id')) is int):
                        candidates[(ref['type'], ref['id'])] = ref
                        if ref['type'] == 'help' and ref not in source_references:
                            source_references.append(ref)
                if message.name in ('get_my_booking_detail', 'get_service_details', 'get_my_booking_schedules'):
                    detail_references = artifact.get('cards', [])
                if message.name == 'list_my_bookings':
                    try:
                        data = json.loads(message.content)
                        for item in data.get('results', []):
                            if item.get('booking_code') and item['booking_code'].casefold() in content.casefold():
                                mentioned_references.append({'type': 'booking', 'id': item['id']})
                    except (ValueError, TypeError, AttributeError):
                        pass
                if message.name == 'select_response_cards' and 'selected_cards' in artifact:
                    # The model can only select entities actually read in this turn.
                    selected_references = []
                    for ref in artifact['selected_cards']:
                        if not isinstance(ref, dict) or type(ref.get('id')) is not int:
                            continue
                        key = (ref.get('type'), ref['id'])
                        if key in candidates and candidates[key] not in selected_references:
                            selected_references.append(candidates[key])
    if selected_references is not None:
        references = selected_references
    else:
        # Fail conservatively when the model omits selection: never expose an
        # entire discovery list beside an answer about a single order.
        references = mentioned_references or detail_references
        if not references and len(candidates) == 1:
            references = list(candidates.values())
    # Always preserve retrieved source provenance, even if the model omits card selection.
    references = source_references + [ref for ref in references if ref not in source_references]
    return AgentAnswer(text=content.strip(), card_references=references[:5], usage=usage)


def run_agent(*, customer_id, history, text, thread_id):
    if not settings.CHATBOT_ENABLED or not settings.CHATBOT_GOOGLE_API_KEY:
        raise AgentUnavailable('Gemini key is not configured or chatbot is disabled.')
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(
        model=settings.CHATBOT_MODEL, api_key=settings.CHATBOT_GOOGLE_API_KEY,
        vertexai=False, timeout=settings.CHATBOT_MODEL_TIMEOUT, max_retries=0,
        max_tokens=settings.CHATBOT_MAX_OUTPUT_TOKENS,
    )
    messages = []
    for user_text, assistant_text in history:
        messages.extend([HumanMessage(content=user_text), AIMessage(content=assistant_text)])
    messages.append(HumanMessage(content=text))
    context = AgentContext(customer_id=customer_id, deadline=time.monotonic() + settings.CHATBOT_RUN_TIMEOUT)
    with open_checkpointer() as saver:
        agent = create_customer_agent(model, saver)
        result = agent.invoke(
            {'messages': messages},
            config={'configurable': {'thread_id': thread_id},
                    'recursion_limit': settings.CHATBOT_MAX_MODEL_CALLS * 4 + 10},
            context=context,
        )
    return extract_answer(result)
