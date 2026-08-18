from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_openai import AzureChatOpenAI

from api.config.settings.base import BackendSettings

MAX_TOKENS = 4096
MAX_RETRIES = 3
TIMEOUT = 30
TEMPERATURE = 0
SEED = 0


class LLMInfrastructureProvider(StrEnum):
    azure = "azure"


class GPTModels(StrEnum):
    router = "router"
    gpt_large = "gpt_large"
    gpt_nano = "gpt_nano"


def get_multiple_llm_generators(
    settings: BackendSettings,
    models: dict[str, dict],
) -> list[BaseChatModel]:
    """
    Creates and returns a list of LLM (Large Language Model) generators from the specified
    settings and model configurations.

    Args:
        settings (BaseSettings): The configuration settings required to initialize the LLM generators.
        models (dict[str, dict]): A dictionary where keys are model names (as strings) and values are
            dictionaries containing keyword arguments (`kwargs`) specific to each model's initialization.

    Returns:
        list[BaseChatModel]: A list of initialized LLM generator instances. Each instance
        corresponds to a model specified in the `models` dictionary.

    Example:
        settings = BaseSettings(...)
        models = {
            "model_a": {"param1": "value1", "param2": "value2"},
            "model_b": {"param3": "value3"}
        }
        llm_generators = get_multiple_llm_generators(settings, models)
        # llm_generators will contain instances of AzureChatOpenAI based on the models provided.
    """

    models_return = []
    for model_name, kwargs_params in models.items():
        models_return.append(
            get_llm_generator(settings=settings, model=model_name, **kwargs_params)
        )

    return models_return


# noinspection PyArgumentList
def get_llm_generator(
    settings: BackendSettings,
    model: str = "gpt",
    timeout: int = TIMEOUT,
    max_tokens: int = MAX_TOKENS,
    **kwargs,
) -> BaseChatModel:

    # Azure models
    if model == GPTModels.router:
        return AzureChatOpenAI(
            azure_deployment=settings.azure.OPENAI_DEPLOYMENT_GPT_ROUTER,
            openai_api_key=settings.azure.OPENAI_API_KEY,
            azure_endpoint=settings.azure.OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
            temperature=TEMPERATURE,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=MAX_RETRIES,
            seed=SEED,
            **kwargs,
        )
    elif model == GPTModels.gpt_large:
        return AzureChatOpenAI(
            azure_deployment=settings.azure.OPENAI_DEPLOYMENT_GPT_52,
            openai_api_key=settings.azure.OPENAI_API_KEY,
            azure_endpoint=settings.azure.OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=TEMPERATURE,
            max_retries=MAX_RETRIES,
            seed=SEED,
            **kwargs,
        )
    elif model == GPTModels.gpt_nano:
        return AzureChatOpenAI(
            azure_deployment=settings.azure.OPENAI_DEPLOYMENT_GPT_51,
            openai_api_key=settings.azure.OPENAI_API_KEY,
            azure_endpoint=settings.azure.OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=TEMPERATURE,
            max_retries=MAX_RETRIES,
            seed=SEED,
            **kwargs,
        )
    else:
        raise ValueError(f"Model {model} not implemented")
