from enum import StrEnum


class ChatNames(StrEnum):
    # Agent steps
    tool_step = "tools"
    agent_step = "agent"
    final_step_answer = "final_answer"

    # Chat config
    user_question_config_key = "user_question"
    references_config_key = "references"
    user_question_prefix = "User question: "
    user_messages_key = "messages"

    # Agent keywords prompts
    execution_plan_key = "Execution plan:"
    ready_to_answer_key = "READY_TO_ANSWER:"
    final_answer_prefix = "# ANSWER_START"
    final_answer_paragraph_split = "END_PAR"
    final_answer_references_header = "# References"
    final_answer_references_splitter = "<s>"


class ContextNames(StrEnum):
    client = "OrganizationName"
