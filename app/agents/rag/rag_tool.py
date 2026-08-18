import json
from datetime import datetime
from typing import Annotated

# from json_repair import loads as repair_loads
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from loguru import logger

from agents.rag.agent import RagAgent
from agents.rag.names import RagNames
from agents.rag.prompts import rag_prompt
from api.config.manager import settings
from api.models.content import Citation
from chats.utils.names import ChatNames

RECURSION_LIMIT = 9

# TEMP: the Azure AI Search index is not available yet, so the RAG sub-agent
# cannot run end-to-end. While that is the case, `rag_agent_tool` short-circuits
# to a canned response so the parent chat flow can be exercised. Flip this to
# False (or remove the mock branch) once the index is wired up.
MOCK_RAG = False

# filename -> Citation, mirrors what the real agent stores in `rag_references`
_MOCK_RAG_REFERENCES: dict[str, Citation] = {
    "Incident_Management_SLA_Matrix_2026.pdf": Citation(
        id="Incident_Management_SLA_Matrix_2026.pdf",
        url="docs/Incident_Management_SLA_Matrix_2026.pdf",
        title="Incident_Management_SLA_Matrix_2026.pdf",
    ),
    "VPN_Remote_Access_Runbook_2026.pdf": Citation(
        id="VPN_Remote_Access_Runbook_2026.pdf",
        url="docs/VPN_Remote_Access_Runbook_2026.pdf",
        title="VPN_Remote_Access_Runbook_2026.pdf",
    ),
}

# matches the `answer_paragraphs` shape produced by the real RAG agent
_MOCK_RAG_ANSWER_PARAGRAPHS: list[dict] = [
    {
        "answer_text": (
            "According to the internal incident management SLA matrix, a P1 (critical) "
            "incident must be acknowledged within 15 minutes and restored within 4 hours, "
            "with mandatory escalation to the duty NOC manager if no progress is recorded "
            "after the first hour."
        ),
        "references": ["Incident_Management_SLA_Matrix_2026.pdf"],
    },
    {
        "answer_text": (
            "The remote access runbook states that repeated VPN authentication failures "
            "should first be checked against the user's Active Directory account lockout "
            "status and MFA enrolment; only after both are confirmed healthy should the "
            "ticket be escalated to the network security team."
        ),
        "references": ["VPN_Remote_Access_Runbook_2026.pdf"],
    },
]


def _store_mock_references(state: dict) -> None:
    """Write mock filename -> Citation pairs into the parent agent's reference map,
    mirroring the merge logic of the real `rag_agent_tool`."""
    references = state[ChatNames.references_config_key]
    if RagNames.main_references_key in references:
        for filename, citation in _MOCK_RAG_REFERENCES.items():
            references[RagNames.main_references_key].setdefault(filename, citation)
    else:
        references[RagNames.main_references_key] = dict(_MOCK_RAG_REFERENCES)


@tool()
async def rag_agent_tool(
    question: str, state: Annotated[dict, InjectedState], config: RunnableConfig
) -> str:
    """
    Call this tool to get RAG Agent working, which will get you the answer from the internal documents.
    The knowledge base contains the internal IT service desk documents of a telecommunications
    company (sourced from SharePoint, in English): runbooks, troubleshooting procedures,
    known-error articles, service catalogue and SLA definitions, escalation matrices, network
    and platform documentation, and tabular Excel data. When asking the question provide as much
    information as possible, so the tool better understands the context.

    Args:
        question (str): Full, self-contained user question for the document knowledge base
            (include systems, services, error codes, and context; English preferred).
        state (InjectedState): Propagated state of the execution process.
        config (RunnableConfig): Configuration for the RAG agent.
    """
    if MOCK_RAG:
        # TEMP: lets us exercise the "no answer in the documents" path without a
        # real index — when user_id == "error" the mock returns empty results.
        user_id = config.get("configurable", {}).get("user_id")
        if user_id == "error":
            logger.warning(
                "MOCK_RAG is enabled and user_id == 'error' — returning empty RAG results."
            )
            return (
                f"Answer from RagAgentTool to question: `{question}` - <answer>[]</answer>, "
                "no relevant information was found in the internal documents for this query."
            )
        logger.warning("MOCK_RAG is enabled — returning a canned RAG response.")
        _store_mock_references(state)
        answer = json.dumps(_MOCK_RAG_ANSWER_PARAGRAPHS, ensure_ascii=False)
        return f"Answer from RagAgentTool to question: `{question}` - <answer>{answer}</answer>, references are stored in answer JSON."

    agent = RagAgent(
        settings=settings, model_provider=config["configurable"]["model_provider"]
    )
    try:
        response = await agent.graph.ainvoke(
            {
                "messages": [
                    (
                        "system",
                        rag_prompt.format(
                            DATE_NOW=datetime.today().strftime("%Y-%m-%d")
                        ),
                    ),
                    (
                        "human",
                        f"User question is: `{question}`",
                    ),
                ],
                "user_question": question,
                RagNames.rag_references_key: {},
            },
            RunnableConfig(
                recursion_limit=RECURSION_LIMIT,
                configurable={
                    "model_provider": config["configurable"]["model_provider"],
                },
            ),
        )
        output = json.loads(response["messages"][-1].text)

        # We pop it as we use it only to steer llm output, to avoid irrelevant info
        output.pop("output_analysis", "")

        # Place to store RAG references: state["references"]["RAG"] (filename -> Citation)
        if RagNames.main_references_key in state[ChatNames.references_config_key]:
            for filename, citation in response.get(RagNames.rag_references_key).items():
                state[ChatNames.references_config_key][
                    RagNames.main_references_key
                ].setdefault(filename, citation)
        else:
            state[ChatNames.references_config_key][RagNames.main_references_key] = (
                response.get(RagNames.rag_references_key, {})
            )

        answer = json.dumps(output.get("answer_paragraphs"))

        return f"Answer from RagAgentTool to question: `{question}` - <answer>{answer}</answer>, references are stored in answer JSON."
    except Exception as e:
        logger.error(e)
        return "Error while calling RagAgentTool"
