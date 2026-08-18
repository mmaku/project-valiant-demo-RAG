from typing import Literal

from pydantic import Field, field_validator, model_validator

from api.models.base import BaseSchemaModel
from api.models.content import TextContentBlock
from libs.utils.langchain import LLMInfrastructureProvider


class ChatMessage(BaseSchemaModel):
    role: Literal["user", "assistant"] = Field(
        description=(
            "Role of the message author (OpenAI format). "
            "'system' is not allowed — the system prompt is injected by the backend."
        )
    )
    content: str | list[TextContentBlock] = Field(
        description="Message content: plain text or a list of text content blocks (LangChain format)"
    )

    @field_validator("content")
    @classmethod
    def content_not_blank(
        cls, value: str | list[TextContentBlock]
    ) -> str | list[TextContentBlock]:
        if isinstance(value, str):
            if not value.strip():
                raise ValueError("Message content must not be empty")
            return value
        if not value or all(not block.text.strip() for block in value):
            raise ValueError(
                "Message content must contain at least one non-empty text block"
            )
        return value


class ChatInput(BaseSchemaModel):
    messages: list[ChatMessage] = Field(
        description="Messages to AI model (OpenAI format)"
    )
    user_id: str | None = Field(None, description="ID of the user")
    context: dict = Field(
        {},
        description="Dictionary with information that can be consumed by the agent",
    )
    model_provider: LLMInfrastructureProvider = Field(
        LLMInfrastructureProvider.azure,
        description="LLM infrastructure provider",
    )

    @model_validator(mode="after")
    def validate_messages(self) -> "ChatInput":
        if not self.messages:
            raise ValueError("messages must contain at least one message")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must have role 'user'")
        return self


class ChatOutput(BaseSchemaModel):
    content: list[TextContentBlock] = Field(
        description="Answer as a list of text content blocks with citation annotations"
    )
