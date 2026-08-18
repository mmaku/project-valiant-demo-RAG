import argparse
from http import HTTPStatus

import fastapi
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from api.config.manager import settings
from api.routes.endpoints import router as api_endpoint_router


def setup_exceptions(app: FastAPI) -> FastAPI:
    @app.exception_handler(Exception)
    async def unhandled_exceptions_handler(request: Request, exc: Exception):
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        if hasattr(exc, "status_code"):
            status_code = getattr(exc, "status_code")
        return JSONResponse(status_code=status_code, content={"error": str(exc)})

    return app


def initialize_backend_application() -> fastapi.FastAPI:
    app = fastapi.FastAPI(**settings.get_fastapi_app_attributes)  # type: ignore

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.core.ALLOWED_ORIGINS,
        allow_credentials=settings.core.ALLOW_CREDENTIALS,
        allow_methods=settings.core.ALLOWED_METHODS,
        allow_headers=settings.core.ALLOWED_HEADERS,
    )

    app.include_router(router=api_endpoint_router, prefix=settings.core.API_PREFIX)
    app = setup_exceptions(app)

    @app.get(
        "/health",
        name="health",
        response_class=JSONResponse,
        status_code=fastapi.status.HTTP_200_OK,
    )
    async def health_check():
        return {"status": "healthy"}

    return app


backend_app: fastapi.FastAPI = initialize_backend_application()


def __getattr__(name: str):
    """Build the FastAPI app lazily, only when `backend_app` is actually accessed.

    Keeps the `main:backend_app` import string working for uvicorn (including
    reload/workers, where the module is reimported and the attribute is read),
    while the `chat` CLI path never touches `backend_app` and therefore never
    imports the routers / FastAPI stack.
    """
    if name == "backend_app":
        app = initialize_backend_application()
        globals()["backend_app"] = app  # cache after first access
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def run_chat_cli(question: str, mock_rag: bool, user_id: str | None) -> None:
    """Run the main chat agent once and print the full ChatOutput as JSON.

    Mirrors the `/api/chat/get_answer` handler so the CLI exercises the exact
    same flow as the HTTP endpoint.
    """
    import json

    import agents.rag.rag_tool as rag_tool
    from api.models.chat import ChatInput, ChatMessage, ChatOutput
    from api.models.content import TextContentBlock
    from chats.assistant.builder import ChatBuilder
    from chats.utils.tools_loader import (
        get_internal_agents,
        load_tools_config,
        select_servers_by_server_type,
    )

    # `MOCK_RAG` is read at call time inside `rag_agent_tool`, so overriding the
    # module attribute here controls whether RAG is mocked for this run.
    rag_tool.MOCK_RAG = mock_rag

    chat_input = ChatInput(
        messages=[ChatMessage(role="user", content=question)],
        user_id=user_id,
    )

    servers, server_desc = load_tools_config()
    internal_agents_names = select_servers_by_server_type(servers, "tool")
    tools = get_internal_agents(internal_agents_names)

    chat = ChatBuilder(
        settings, tools, server_desc, model_provider=chat_input.model_provider
    )
    answer = await chat.async_run(
        chat_input.messages, chat_input.context, chat_input.user_id
    )

    chat_output = ChatOutput(content=[TextContentBlock(**block) for block in answer])
    print(
        json.dumps(chat_output.model_dump(by_alias=True), ensure_ascii=False, indent=2)
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    # Default IT service desk question used when the CLI is run without `-q/--question`.
    DEFAULT_SERVICE_DESK_QUESTION = (
        "What are the diagnostic steps for a customer reporting no FTTH connectivity, "
        "and what response and restoration times apply to a P1 incident according to "
        "our SLA procedures?"
    )

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Valiant AI engine entrypoint (server by default, or `chat` CLI).",
    )
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser(
        "chat",
        help="Run the main chat agent once from the CLI and print the full response.",
    )
    chat_parser.add_argument(
        "-q",
        "--question",
        default=DEFAULT_SERVICE_DESK_QUESTION,
        help="Question to ask the agent (default: a sample IT service desk question).",
    )
    chat_parser.add_argument(
        "--mock-rag",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use the real RAG sub-agent (default). Use --mock-rag to get a canned response.",
    )
    chat_parser.add_argument(
        "--user-id",
        default=None,
        help="Optional user_id. With --mock-rag, '--user-id error' forces the no-results path.",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    if args.command == "chat":
        import asyncio

        asyncio.run(run_chat_cli(args.question, args.mock_rag, args.user_id))
    elif settings.core.RUN_FROM_FILE:
        import uvicorn

        uvicorn_kwargs = {
            "app": "main:backend_app",
            "host": settings.core.SERVER_HOST,
            "port": settings.core.SERVER_PORT,
            "reload": settings.core.DEBUG,
            "workers": settings.core.SERVER_WORKERS,
            "log_level": settings.core.LOGGING_LEVEL,
        }

        uvicorn.run(**uvicorn_kwargs)
