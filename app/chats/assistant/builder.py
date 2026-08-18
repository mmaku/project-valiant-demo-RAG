from datetime import datetime
from typing import Literal, Callable, Union, Any

from langgraph.graph import MessagesState, START, END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.graph.state import CompiledStateGraph
from langgraph.managed import RemainingSteps
from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.messages import HumanMessage
from langchain_core.runnables.graph import MermaidDrawMethod
from loguru import logger

from api.config.settings.base import BackendSettings
from api.models.chat import ChatMessage
from api.models.content import TextContentBlock
from libs.utils.langchain import (
    get_llm_generator,
    get_multiple_llm_generators,
    GPTModels,
    LLMInfrastructureProvider,
)
from chats.utils.names import ChatNames, ContextNames
from .parser import ChatParser
from .prompts import prompt_system_chat, prompt_final_answer

MAXIMUM_NUMBER_MESSAGE_HISTORY = 7

RECURSION_LIMIT = 9


def _content_to_text(content: str | list[TextContentBlock]) -> str:
    """Flatten message content to plain text for the string-based graph.

    Input may be a plain string or a list of text content blocks (LangChain
    format). Block annotations carried in conversation history are not used
    internally — only the text is extracted.
    """
    if isinstance(content, str):
        return content
    return "\n".join(block.text for block in content if block.text)


class ChatGraphState(MessagesState, total=False):
    """
    TypedDict for storing the state of a chat-based graph execution.

    Attributes:
        remaining_steps (RemainingSteps): The number of steps left in the graph execution process.
        user_question (str): The user's input question or query.
        references (dict): Reference store keyed by source (e.g. "RAG" -> dict[str, Citation]).
    """

    remaining_steps: RemainingSteps
    user_question: str
    references: dict


class ChatBuilder:
    """
    Class to create and manage a graph using the ReAct paradigm with asynchronous tools.

    """

    # TODO
    # What about guardrails
    # How to cut the context if to long -> summarize the context
    # Token usage
    # Latency
    # How long should be the answer
    # What tone should be the answer (always asking for opinion, to the point? )
    # Formatting the output, paragraphs is 1 step, but maybe we want something more
    # What models should know?

    # TODO Ideas for architecture
    # Start with execution plan (prestep to ReAct loop), then attach tools in next step

    # When we use tool with data, IMO model should also return to BE reference to exact data so user
    # can easily navigate to this section to see data on his own

    # Limitiations
    # Sometimes chat falls in to the inifinite loop while building the execution plan
    # Maybe pulling the creation of execution plan before starting the ReAct process could help (separate step)
    # However this may be problematic, as we would need to give this initial build and plan process limited numbers of tools
    # As with all tools given, model tend to already start the data gathering process, but we only want to draw
    # the execution plan. Unfortunately without all tools, execution plan can be wrongly drafted (ineffective)

    # Adding fields
    # Most likely we should add to the endpoint and also builder
    # fields that are selected by user (filters, market, brand etc) as
    # user writing in the chat will expect model to know the context

    # TODO Evaluation
    # We should establish LLM as Judge for Input output to make sure that common patters
    # always work

    def __init__(
        self,
        settings: BackendSettings,
        tools: list[BaseTool],
        tools_desc: dict,
        model_provider: LLMInfrastructureProvider = LLMInfrastructureProvider.azure,
    ):
        self.system_prompt = prompt_system_chat
        self.settings = settings
        self.tools_desc = tools_desc
        self.model_provider = model_provider
        # Langraph returns list of messages with proper formatting
        # Therefore we cannot use JSON output format, as it's not compatible (then JSON is the output)
        self.model_with_tools = self._get_models_with_tools(tools=tools)
        self.model_without_tools = self._get_models_without_tools()
        self.model_start = self._get_models_start(tools=tools)
        self.tool_node = ToolNode(tools)
        self.graph = self.build_graph()

    def _get_models_with_tools(
        self,
        tools: list[Union[BaseTool, Callable[[Union[Callable, Runnable]], BaseTool]],],
    ):
        llm = get_llm_generator(self.settings, model=GPTModels.router)
        fallbacks = get_multiple_llm_generators(
            self.settings, {GPTModels.gpt_nano: {}, GPTModels.gpt_large: {}}
        )
        return llm.bind_tools(tools).with_fallbacks(
            [fallback_model.bind_tools(tools) for fallback_model in fallbacks]
        )

    def _get_models_without_tools(self):
        llm = get_llm_generator(self.settings, model=GPTModels.gpt_large)
        fallbacks = get_multiple_llm_generators(
            self.settings, {GPTModels.router: {}, GPTModels.gpt_nano: {}}
        )
        return llm.with_fallbacks(fallbacks)

    def _get_models_start(
        self,
        tools: list[Union[BaseTool, Callable[[Union[Callable, Runnable]], BaseTool]],],
    ):
        llm = get_llm_generator(self.settings, model=GPTModels.gpt_nano)
        fallbacks = get_multiple_llm_generators(
            self.settings, {GPTModels.router: {}, GPTModels.gpt_large: {}}
        )
        return llm.bind_tools(tools).with_fallbacks(
            [fallback_model.bind_tools(tools) for fallback_model in fallbacks]
        )

    def build_graph(self) -> CompiledStateGraph:
        """
        Builds the asynchronous StateGraph with nodes and edges.

        Returns:
            CompiledStateGraph: The compiled graph ready for execution.
        """

        graph = StateGraph(ChatGraphState)

        async def async_call_model(state: ChatGraphState) -> ChatGraphState:
            messages = state[ChatNames.user_messages_key]

            last_message_content = messages[-1].text

            if last_message_content.startswith(ChatNames.user_question_prefix):
                # model that starts the plan must be clever enough
                # so it plans the tool / mcp usage and
                # good execution plan
                response = await self.model_start.ainvoke(messages)

            elif state["remaining_steps"] > 3:
                response = await self.model_with_tools.ainvoke(messages)
            else:
                # no tools to push to final message
                response = await self.model_without_tools.ainvoke(messages)

            return {ChatNames.user_messages_key: [response]}

        async def async_call_model_with_final_prompt(
            state: ChatGraphState,
        ) -> ChatGraphState:
            messages = state[ChatNames.user_messages_key]
            updated_messages = messages + [
                HumanMessage(
                    content=prompt_final_answer.format(
                        USER_Q=state[ChatNames.user_question_config_key],
                        DATE_NOW=datetime.today().strftime("%Y-%m-%d"),
                        ANSWER_PREFIX=ChatNames.final_answer_prefix,
                        END_PAR_KEY=ChatNames.final_answer_paragraph_split,
                        REFERENCES_KEY=ChatNames.final_answer_references_header,
                        MAP_REFERENCE_SPLIT=ChatNames.final_answer_references_splitter,
                    )
                )
            ]
            # we cannot use json mode here
            # as langraph uses Messages system, that enforces string usage
            response = await self.model_without_tools.ainvoke(updated_messages)
            return {ChatNames.user_messages_key: [response]}

        async def async_should_continue(
            state: ChatGraphState,
        ) -> Literal[
            ChatNames.tool_step,
            ChatNames.agent_step,
            ChatNames.final_step_answer,
            "__end__",
        ]:
            messages = state[ChatNames.user_messages_key]

            last_message = messages[-1]
            if state["remaining_steps"] < 3 and not last_message.tool_calls:
                if (
                    ChatNames.final_answer_prefix in last_message.text
                    and not ChatNames.execution_plan_key in last_message.text
                ):
                    return END
                return ChatNames.final_step_answer

            if last_message.tool_calls:
                return ChatNames.tool_step
            # we are past agent call, but it is not the final answer as agent still
            # have not decided to finish
            # TODO verify after adding RAG if makes sense
            elif (
                ChatNames.ready_to_answer_key not in last_message.text
                and ChatNames.final_answer_prefix not in last_message.text
            ):
                return ChatNames.agent_step
            else:
                # lets give it a chance to return proper format
                if (
                    ChatNames.final_answer_prefix not in last_message.text
                    or ChatNames.execution_plan_key in last_message.text
                ):
                    return ChatNames.final_step_answer
                return END

        graph.add_node(ChatNames.agent_step, async_call_model)
        graph.add_node(ChatNames.tool_step, self.tool_node)
        graph.add_node(ChatNames.final_step_answer, async_call_model_with_final_prompt)

        graph.add_edge(START, ChatNames.agent_step)
        graph.add_conditional_edges(
            ChatNames.agent_step,
            async_should_continue,
            [
                ChatNames.agent_step,
                ChatNames.tool_step,
                ChatNames.final_step_answer,
                END,
            ],
        )
        graph.add_edge(ChatNames.tool_step, ChatNames.agent_step)
        graph.add_conditional_edges(
            ChatNames.final_step_answer,
            async_should_continue,
            [ChatNames.final_step_answer, END],
        )

        return graph.compile()

    async def async_run(
        self,
        messages: list[ChatMessage],
        context: dict[str, Any],
        user_id: str | None,
    ) -> list[dict]:
        """
        Asynchronously executes the graph with the provided messages.

        Args:
            messages (list[ChatMessage]): A list of OpenAI-format messages
                (role, content) without system message. LangGraph's `add_messages`
                accepts these {"role", "content"} dicts natively.
            context (str): The context used for model context

        Returns:
            dict: The content of the final message in the graph.
        """
        formatted_context = self.prepare_context(context)

        fixed_messages = []
        # safety fix if user has a very long context
        for message in messages[-MAXIMUM_NUMBER_MESSAGE_HISTORY:]:
            # flatten content blocks to plain text for the string-based graph
            text = _content_to_text(message.content)
            # add prefix so its easier for model to track user question/statements
            # esp. for past messages with long thinking process
            if message.role == "user" and not text.startswith(
                ChatNames.user_question_prefix
            ):
                text = f"{ChatNames.user_question_prefix} {text}"
            fixed_messages.append({"role": message.role, "content": text})

        last_user_question = fixed_messages[-1]["content"]

        fixed_messages.insert(
            0,
            {
                "role": "system",
                "content": self.system_prompt.format(
                    DATE_NOW=datetime.today().strftime("%Y-%m-%d"),
                    CONTEXT=formatted_context,
                    TOOLS_DESCRIPTION=self.tools_desc,
                    READY_TO_ANSWER=ChatNames.ready_to_answer_key,
                    EXECUTION_PLAN=ChatNames.execution_plan_key,
                ),
            },
        )

        inputs = {
            ChatNames.user_messages_key: fixed_messages,
            ChatNames.references_config_key: {},
            ChatNames.user_question_config_key: last_user_question,
        }

        raw_result = await self.graph.ainvoke(
            inputs,
            RunnableConfig(
                recursion_limit=RECURSION_LIMIT,
                configurable={
                    "model_provider": self.model_provider,
                    "user_id": user_id,
                },
            ),
        )

        parser = ChatParser()
        parsed_output_new = parser.parse_raw_model_output(raw_result)

        return parsed_output_new

    @staticmethod
    def prepare_context(context: dict[str, Any]) -> str:
        client_name = context.get(ContextNames.client)
        prompt_context = "No context information was added"
        if client_name:
            prompt_context = f"The client works at the '{client_name}' market company."

        return prompt_context

    def save_graph_png(self, filename: str = "mermaid_graph.png") -> None:
        """
        Saves and displays the graph as a PNG file.

        Args:
            filename (str): The filename for the PNG file. Default is "mermaid_graph.png".
        """
        try:
            png_data = self.graph.get_graph().draw_mermaid_png(
                draw_method=MermaidDrawMethod.API,
            )

            with open(filename, "wb") as f:
                f.write(png_data)

            logger.info(f"Graph saved to {filename}")

        except Exception as e:
            logger.error(f"Error generating or saving graph: {e}")
