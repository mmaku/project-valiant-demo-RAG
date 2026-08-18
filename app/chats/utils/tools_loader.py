import json
from pathlib import Path
from typing import Literal
from loguru import logger

from langchain_core.tools import BaseTool, StructuredTool

from agents.rag.rag_tool import rag_agent_tool

MCP_SERVERS_CONFIG_JSON_FILENAME = "servers_config.json"


def load_tools_config() -> tuple[dict, dict]:
    """
    Loads server configurations from the local JSON file next to this module.

    Returns:
        tuple[dict, dict]: A tuple containing the processed server configurations
        and their descriptions.
    """
    local_path = Path(__file__).parent / MCP_SERVERS_CONFIG_JSON_FILENAME

    if not local_path.exists():
        raise FileNotFoundError(f"Local configuration file not found: {local_path}")

    with local_path.open("r", encoding="utf-8") as f:
        servers = json.load(f)

    logger.debug(f"Servers list: {servers}")

    server_desc = {}
    for key, value in servers.items():
        server_desc[key] = value.pop("description", None)

    logger.debug(f"Servers description: {server_desc}")
    return servers, server_desc


def get_internal_agents(agent_names: list[str]) -> list[BaseTool | StructuredTool]:
    """
    Given agents name from MCP_SERVERS_CONFIG_JSON take only the relevant agents. Name here matches keys in MCP_SERVERS_CONFIG_JSON
    """
    all_local_agents = {"rag": rag_agent_tool}

    local_agents = []
    for agent_name in agent_names:
        if agent_name in all_local_agents:
            local_agents.append(all_local_agents[agent_name])

    return local_agents


def select_servers_by_server_type(
    servers: dict[str, dict], sever_type: Literal["mcp", "tool"]
) -> dict | list[str]:
    """
    Filter and format the dict with servers to proper template for either internal agents or MultiServerMCPClient
    """

    if sever_type == "mcp":
        return {
            k: props
            for k, props in servers.items()
            if props.get("server_type") == sever_type
        }
    elif sever_type == "tool":
        return [
            agent_name
            for agent_name, props in servers.items()
            if props.get("server_type") == "tool"
        ]
    else:
        raise ValueError('Only ["mcp", "tool"] server_type work')
