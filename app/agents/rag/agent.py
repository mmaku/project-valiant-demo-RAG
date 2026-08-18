import json
import re
import time
from enum import StrEnum
import os
from functools import lru_cache
from typing import Literal, Final, Annotated

from typing_extensions import TypedDict

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery

from langgraph.graph import START, END, StateGraph, MessagesState
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import InjectedState, ToolNode
from langchain_core.runnables import RunnableConfig, RunnableWithFallbacks
from langchain_core.tools import tool, BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.managed import RemainingSteps
from langchain_openai import AzureOpenAIEmbeddings

from agents.rag.names import RagNames
from api.config.manager import settings
from api.config.settings.base import BackendSettings
from api.models.content import Citation
from agents.rag.prompts import rag_final_prompt, rag_rerank_prompt

from loguru import logger

from libs.utils.langchain import (
    GPTModels,
    get_llm_generator,
    LLMInfrastructureProvider,
    get_multiple_llm_generators,
)

TOP_K: Final[int] = 10  # fallback: fused hits returned to the LLM when reranking fails
VECTOR_K: Final[int] = 50  # candidates fetched on the vector leg before RRF fusion

# LLM reranking: fetch RERANK_CANDIDATES fused hybrid hits, then one cheap-LLM
# call selects the RERANK_TOP_N most relevant (RRF top-TOP_K on any failure).
RERANK_CANDIDATES: Final[int] = 30  # fused hits requested from Azure Search
RERANK_TOP_N: Final[int] = 8  # chunks kept after the LLM rerank
RERANK_CONTENT_CHARS: Final[int] = 1200  # per-candidate truncation in the rerank prompt

# Field names in the Azure AI Search index. These match the schema built by the
# in-repo ingestion pipeline (knowledge_base/ingestion/indexing_job.py). Override
# per-index by changing the constants here if the index schema changes.
SEARCH_CONTENT_FIELD: Final[str] = "content"
SEARCH_PAGE_NUMBER_FIELD: Final[str] = "page"
SEARCH_URL_FIELD: Final[str] = "filePath"
SEARCH_VECTOR_FIELD: Final[str] = "contentVector"
SEARCH_DOC_NAME_FIELD: Final[str] = "documentName"
SEARCH_SOURCE_TYPE_FIELD: Final[str] = "sourceType"
SEARCH_SHEET_FIELD: Final[str] = "sheetName"
SEARCH_ROW_START_FIELD: Final[str] = "rowStart"
SEARCH_ROW_END_FIELD: Final[str] = "rowEnd"
SEARCH_CHUNK_TYPE_FIELD: Final[str] = "chunkType"

# Project only the fields we use — critically this EXCLUDES the 3072-dim
# `contentVector`, which Azure would otherwise return for every hit.
SELECT_FIELDS: Final[list[str]] = [
    SEARCH_DOC_NAME_FIELD,
    SEARCH_URL_FIELD,
    SEARCH_SOURCE_TYPE_FIELD,
    SEARCH_PAGE_NUMBER_FIELD,
    SEARCH_SHEET_FIELD,
    SEARCH_ROW_START_FIELD,
    SEARCH_ROW_END_FIELD,
    SEARCH_CHUNK_TYPE_FIELD,
    SEARCH_CONTENT_FIELD,
]


class Profile(StrEnum):
    """
    Class storing different profiles for LLM configuration in RAG agent.
    """

    planning = "planning"
    tools = "tools"
    without_tools = "without_tools"
    rerank = "rerank"


# Rerank kwargs: only `timeout`/`max_tokens` may appear here — get_llm_generator
# already passes temperature/seed/max_retries/api_version explicitly, so those
# would raise a duplicate-keyword TypeError. Tight limits bound the added latency
# and cap the tiny `{"selected": [...]}` output.
AGENT_MODEL_CONFIG = {
    Profile.planning: {
        "primary": {GPTModels.gpt_large: {}},
        "fallbacks": {GPTModels.router: {}, GPTModels.gpt_nano: {}},
    },
    Profile.tools: {
        "primary": {GPTModels.router: {}},
        "fallbacks": {GPTModels.gpt_nano: {}, GPTModels.gpt_large: {}},
    },
    Profile.without_tools: {
        "primary": {GPTModels.gpt_large: {}},
        "fallbacks": {GPTModels.router: {}, GPTModels.gpt_nano: {}},
    },
    Profile.rerank: {
        "primary": {GPTModels.gpt_nano: {"timeout": 15, "max_tokens": 300}},
        "fallbacks": {
            GPTModels.router: {"timeout": 15, "max_tokens": 300},
            GPTModels.gpt_large: {"timeout": 15, "max_tokens": 300},
        },
    },
}


class RagGraphState(TypedDict, MessagesState, total=False):
    """
    TypedDict for storing the state of a Retrieval-Augmented Generation (RAG) graph execution.

    Attributes:
        user_question (str): The user's input question or query.
        rag_references (dict): Mapping filename -> Citation for documents surfaced during retrieval.
        remaining_steps (RemainingSteps): The number of steps left in the graph execution process.
    """

    user_question: str
    rag_references: dict
    remaining_steps: RemainingSteps


class RagAgent:
    """
    This class is a Rag agent for questions related to document database (Azure AI Search).
    """

    def __init__(
        self,
        settings: BackendSettings,
        model_provider: LLMInfrastructureProvider = LLMInfrastructureProvider.azure,
    ):
        self.settings = settings

        self.model_start_planning = self._build_model_bundle(
            profile=Profile.planning,
            tools=self._get_tools(),
            force_tool=True,
        )
        self.model_with_tools = self._build_model_bundle(
            profile=Profile.tools,
            tools=self._get_tools(),
        )
        self.model_without_tools = self._build_model_bundle(
            profile=Profile.without_tools,
        )

        self.graph = self._build_graph()

    def _build_model_bundle(
        self,
        profile: Profile,
        tools: list[BaseTool] | None = None,
        force_tool: bool = False,
    ) -> RunnableWithFallbacks:
        configuration = AGENT_MODEL_CONFIG.get(profile)
        if configuration is None:
            msg = f"Unsupported profile: {profile}"
            logger.error(msg)
            raise ValueError(msg)

        base_llm, fallback_llms = self._get_llms_from_configuration(configuration)

        if tools:
            return base_llm.bind_tools(
                tools, tool_choice="any" if force_tool else None
            ).with_fallbacks(
                [
                    fb.bind_tools(tools, tool_choice="any" if force_tool else None)
                    for fb in fallback_llms
                ]
            )
        return base_llm.with_fallbacks(fallback_llms)

    def _get_llms_from_configuration(self, configuration: dict):
        try:
            primary_name, primary_kwargs = next(iter(configuration["primary"].items()))
            fallbacks_spec = configuration.get("fallbacks", {})
            primary_llm = get_llm_generator(
                settings=self.settings, model=primary_name, **primary_kwargs
            )
            fallback_llm = get_multiple_llm_generators(
                settings=self.settings, models=fallbacks_spec
            )
        except Exception as e:
            logger.error(f"Error getting LLMs from configuration: {e}")
            logger.warning(f"Using default llm and its copy as a fallback")
            primary_llm = get_llm_generator(settings=self.settings)
            fallback_llm = [get_llm_generator(settings=self.settings)]
        return primary_llm, fallback_llm

    @staticmethod
    def _get_tools() -> list[BaseTool]:
        return [
            get_information_from_rag_documents,
        ]

    # === Graph nodes methods & graph build ===

    async def _call_model(self, state: RagGraphState) -> RagGraphState:
        messages = state["messages"]
        if len(messages) == 2:
            response = await self.model_start_planning.ainvoke(messages)
        elif state["remaining_steps"] > 3:
            response = await self.model_with_tools.ainvoke(messages)
        else:
            response = await self.model_without_tools.ainvoke(messages)

        return {"messages": [response]}

    async def _call_model_with_final_prompt(
        self, state: RagGraphState
    ) -> RagGraphState:
        messages = state["messages"]

        updated_messages = messages + [
            HumanMessage(content=rag_final_prompt.format(USER_Q=state["user_question"]))
        ]
        response = await self.model_without_tools.ainvoke(updated_messages)

        response = response.text.lstrip("```json\n")
        response = AIMessage(content=response.rstrip("\n```"))
        return {"messages": [response]}

    @staticmethod
    async def _should_continue(
        state: RagGraphState,
    ) -> Literal["tools", "final_answer", "__end__"]:
        messages = state["messages"]
        last_message = messages[-1]

        if last_message.tool_calls:
            return "tools"

        if state["remaining_steps"] <= 3:
            if (
                "answer_paragraphs" in last_message.text
                and "Execution plan" not in last_message.text
            ):
                return END
            return "final_answer"

        if (
            "answer_paragraphs" not in last_message.text
            or "Execution plan" in last_message.text
        ):
            return "final_answer"

        return END

    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(RagGraphState)

        graph.add_node("agent", self._call_model)
        graph.add_node("tools", ToolNode(self._get_tools()))
        graph.add_node("final_answer", self._call_model_with_final_prompt)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent", self._should_continue, ["tools", "final_answer", END]
        )
        graph.add_edge("tools", "agent")
        graph.add_conditional_edges(
            "final_answer", self._should_continue, ["final_answer", END]
        )
        return graph.compile()

    def show_graph(self) -> None:
        """
        Visualizes the built graph.
        """
        print(self.graph.get_graph().draw_mermaid())


@lru_cache(maxsize=1)
def _get_embeddings() -> AzureOpenAIEmbeddings:
    """Build the embeddings client once and reuse it across tool calls.

    Constructing AzureOpenAIEmbeddings (and its underlying HTTP client) per call
    added connection setup on every retrieval; the RAG agent calls this tool
    several times per question. The cached client lives for the process lifetime.
    """
    return AzureOpenAIEmbeddings(
        azure_deployment=settings.azure.OPENAI_EMBEDDINGS_DEPLOYMENT,
        azure_endpoint=settings.azure.OPENAI_EMBEDDINGS_ENDPOINT,
        api_key=settings.azure.OPENAI_EMBEDDINGS_API_KEY,
    )


@lru_cache(maxsize=1)
def _get_rerank_llm() -> RunnableWithFallbacks:
    """Build the rerank LLM bundle once and reuse it across tool calls.

    Profile.rerank: gpt_nano primary with router/gpt_large fallbacks, tight
    timeout and max_tokens — the call only returns a small ``{"selected": [...]}``
    JSON, so a cheap model with a hard output cap is enough.
    """
    configuration = AGENT_MODEL_CONFIG[Profile.rerank]
    primary_name, primary_kwargs = next(iter(configuration["primary"].items()))
    primary = get_llm_generator(settings=settings, model=primary_name, **primary_kwargs)
    fallbacks = get_multiple_llm_generators(
        settings=settings, models=configuration.get("fallbacks", {})
    )
    return primary.with_fallbacks(fallbacks)


def _build_source_type_filter(source_type: str | None) -> str | None:
    """Compile an optional sourceType restriction into an OData ``$filter``.

    Returns None when no filter is requested. The value is lower-cased (source
    types are stored lower-case) and single quotes are escaped to keep the
    OData literal safe.
    """
    if not source_type:
        return None
    value = source_type.strip().lower().replace("'", "''")
    return f"{SEARCH_SOURCE_TYPE_FIELD} eq '{value}'"


def _format_rerank_candidates(chunks: list[dict]) -> str:
    """Render chunks as a numbered (1-based) candidate list for the rerank prompt.

    Content is truncated to RERANK_CONTENT_CHARS — chunk heads carry the
        ingestion metadata header (document name / page / ...) plus the opening
    text, which is enough signal to judge relevance.
    """
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        page = chunk["page_number"] if chunk["page_number"] is not None else "-"
        lines.append(
            f"[{i}] (document: {chunk['document_name']}, page: {page})\n"
            f"{chunk['content'][:RERANK_CONTENT_CHARS]}"
        )
    return "\n\n".join(lines)


def _parse_rerank_selection(text: str, n_candidates: int) -> list[int]:
    """Extract the selected candidate numbers from the rerank LLM output.

    Tolerates ``` fences, surrounding prose, a bare list instead of the
    ``{"selected": [...]}`` object, and stray non-numeric items. Returns []
    on any structural failure — the caller falls back to RRF order.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}|\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("selected")
    if not isinstance(data, list):
        return []
    selected: list[int] = []
    for item in data:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= n_candidates and index not in selected:
            selected.append(index)
    return selected


async def _rerank_chunks(
    query: str, user_question: str, chunks: list[dict]
) -> list[dict]:
    """Prune hybrid-search candidates to the most relevant few with one LLM call.

    The model sees the numbered candidates and returns the best RERANK_TOP_N
    indices in relevance order; selecting fewer is deliberate (relevance cut).
    Any failure falls back to the first TOP_K chunks in Azure's RRF order —
    reranking must never break retrieval.
    """
    if len(chunks) <= RERANK_TOP_N:
        return chunks
    try:
        started = time.perf_counter()
        prompt = rag_rerank_prompt.format(
            QUERY=query,
            USER_QUESTION=user_question or query,
            TOP_N=RERANK_TOP_N,
            CANDIDATES=_format_rerank_candidates(chunks),
        )
        response = await _get_rerank_llm().ainvoke([HumanMessage(content=prompt)])
        selected = _parse_rerank_selection(response.text, len(chunks))
        if not selected:
            raise ValueError(
                f"Unparseable or empty rerank selection: {response.text[:200]!r}"
            )
        logger.debug(
            f"Rerank kept {min(len(selected), RERANK_TOP_N)}/{len(chunks)} chunks "
            f"in {time.perf_counter() - started:.2f}s: {selected[:RERANK_TOP_N]}"
        )
        return [chunks[i - 1] for i in selected[:RERANK_TOP_N]]
    except Exception as e:
        logger.warning(f"Rerank failed, falling back to RRF top-{TOP_K}: {e}")
        return chunks[:TOP_K]


@tool(response_format="content")
async def get_information_from_rag_documents(
    query: str,
    state: Annotated[dict, InjectedState],
    config: RunnableConfig,
    source_type: str | None = None,
) -> str:
    """
    Call when you want to browse the documents database and get the answer to the query.
    The knowledge base contains internal IT service desk documents of a telecommunications
    company (in English): runbooks, troubleshooting procedures, known-error articles, service
    catalogue and SLA definitions, escalation matrices, network and platform documentation,
    plus page summaries, markdown tables, and text descriptions of figures, diagrams, and
    flowcharts.

    query: str - short keyword-style phrase (2-6 words, in English — the language
        of the documents) to look up in the hybrid search index, NOT a full question.
        Example: 'P1 incident escalation matrix', not 'how do I escalate a P1 incident?'
                 'eSIM activation procedure' instead of 'how does a customer activate an eSIM?'
    source_type: str | None - OPTIONAL. Restrict the search to a single document
        type ('pdf', 'docx', 'pptx', 'xlsx', 'xlsm', 'txt', 'md'). Leave unset (None)
        by default to search across all document types.

    Output is a JSON list of text chunks from the documents with source document names
    to cite as references.
    """
    try:
        query_vector = await _get_embeddings().aembed_query(query)

        async with SearchClient(
            endpoint=settings.azure.SEARCH_ENDPOINT,
            index_name=settings.azure.SEARCH_INDEX_NAME,
            credential=AzureKeyCredential(settings.azure.SEARCH_API_KEY),
        ) as search_client:
            results = await search_client.search(
                search_text=query,  # BM25 keyword leg over content + documentName
                vector_queries=[
                    VectorizedQuery(
                        vector=query_vector,
                        k_nearest_neighbors=VECTOR_K,
                        fields=SEARCH_VECTOR_FIELD,
                    )
                ],
                select=SELECT_FIELDS,  # skip contentVector — big payload win
                filter=_build_source_type_filter(source_type),
                top=RERANK_CANDIDATES,
            )

            chunks: list[dict] = []
            seen_content: set[str] = set()
            async for doc in results:
                try:
                    content = (doc.get(SEARCH_CONTENT_FIELD) or "").strip()
                    if not content or content in seen_content:
                        continue  # drop empty / exact-duplicate chunks
                    seen_content.add(content)

                    document_name = (
                        doc.get(SEARCH_DOC_NAME_FIELD)
                        or os.path.basename(doc.get(SEARCH_URL_FIELD, ""))
                        or "unknown"
                    )
                    file_path = doc.get(SEARCH_URL_FIELD, "")
                    page = doc.get(SEARCH_PAGE_NUMBER_FIELD)
                    # `page` is 0 for non-paged sources (Excel/txt/md); keep it as
                    # None so it satisfies Citation.page_number (int | None).
                    page_number = page if isinstance(page, int) and page > 0 else None

                    chunks.append(
                        {
                            "content": content,
                            "document_name": document_name,
                            "file_path": file_path,
                            "page_number": page_number,
                        }
                    )
                except Exception as e:
                    logger.warning(f"Exception occured during extraction: {e}")

        if not chunks:
            logger.debug(
                f"No information was found for the query '{query}' in the get_information_from_rag_documents tool"
            )
            return f"No information was found for the query '{query}' in the get_information_from_rag_documents tool"

        # `user_question` may be absent when the tool is exercised outside the
        # graph (e.g. scripts/debug_hybrid_search.py passes a minimal state).
        chunks = await _rerank_chunks(
            query=query,
            user_question=state.get("user_question", ""),
            chunks=chunks,
        )

        logger.debug(f"Chunks: {chunks}")

        # Persist documentName -> Citation mapping for the parent agent's reference resolver.
        for chunk in chunks:
            state[RagNames.rag_references_key].setdefault(
                chunk["document_name"],
                Citation(
                    id=chunk["document_name"],
                    url=chunk["file_path"],
                    title=chunk["document_name"],
                    page_number=chunk["page_number"],
                ),
            )

        dict_text_refs = [
            {"answer": chunk["content"], "references": [chunk["document_name"]]}
            for chunk in chunks
        ]

        return f"Answer from get_information_from_rag_documents tool for a query - {query}, answer is: <answer> {json.dumps(dict_text_refs)} </answer>"

    except Exception as e:
        logger.error(e)
        return "Error while calling get_information_from_rag_documents"


if __name__ == "__main__":
    from api.config.manager import settings

    agent = RagAgent(settings)
    print(agent.show_graph())
