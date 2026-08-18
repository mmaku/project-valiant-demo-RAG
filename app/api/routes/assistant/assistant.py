import fastapi
from loguru import logger

from api.config.manager import settings
from api.models.chat import (
    ChatInput,
    ChatOutput,
)
from api.models.content import TextContentBlock
from chats.assistant.builder import ChatBuilder
from api.utilities.exceptions.http.exc_500 import http_500_llm_error
from chats.utils.tools_loader import (
    load_tools_config,
    get_internal_agents,
    select_servers_by_server_type,
)

router = fastapi.APIRouter(prefix="/chat", tags=["assistant_chat"])


@router.post(
    "/get_answer",
    name="assistant_chat:get_answer",
    response_model=ChatOutput,
    status_code=fastapi.status.HTTP_200_OK,
)
async def get_answer(
    input: ChatInput,
):
    try:
        servers, server_desc = load_tools_config()
        internal_agents_names = select_servers_by_server_type(servers, "tool")
        internal_agents_tools = get_internal_agents(internal_agents_names)

        tools = internal_agents_tools
        chat = ChatBuilder(
            settings, tools, server_desc, model_provider=input.model_provider
        )

        answer = await chat.async_run(input.messages, input.context, input.user_id)

        chat_output = ChatOutput(
            content=[TextContentBlock(**block) for block in answer]
        )
    except Exception as e:
        logger.exception(f"Error happened during chat response creation: {e}")
        raise await http_500_llm_error()

    return chat_output
