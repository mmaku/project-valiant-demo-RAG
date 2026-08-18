from typing import Literal

from pydantic import Field

from api.models.base import BaseSchemaModel


class Citation(BaseSchemaModel):
    """
    Reference annotation attached to a text content block, following the LangChain
    standard citation shape (subset of fields) - langchain.messages.Citation.
    """

    type: Literal["citation"] = "citation"
    id: str = Field(
        description="Stable identifier of the cited document (currently the filename the LLM cites by)"
    )
    url: str = Field(description="URL/URI to the source document")
    title: str = Field(description="Human-readable title (filename) of the source")
    page_number: int | None = Field(None, description="Page number")


class TextContentBlock(BaseSchemaModel):
    """
    LangChain v1 standard text content block. Used both on the chat input
    (message content) and output (answer paragraphs with citation annotations).
    """

    type: Literal["text"] = "text"
    text: str = Field(description="Text content")
    annotations: list[Citation] = Field(
        default_factory=list,
        description="Citations/references backing this text block",
    )
