import logging
import pathlib

import decouple
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = pathlib.Path(__file__).resolve().parents[3]


class CoreSettings(BaseSettings):
    # === APP ===
    APP_TITLE: str = "Valiant"
    APP_VERSION: str = "0.0.1"
    APP_DESCRIPTION: str | None = "IT service desk knowledge assistant"
    DEBUG: bool = False
    TIMEZONE: str = "UTC"
    RUN_FROM_FILE: bool = decouple.config("RUN_FROM_FILE", default=False, cast=bool)

    # === API ===
    API_PREFIX: str = "/api"
    API_DOCS_URL: str = "/docs"
    API_OPENAPI_URL: str = "/openapi.json"
    API_REDOC_URL: str = "/redoc"
    API_OPENAPI_PREFIX: str = ""

    # === SERVER ===
    SERVER_WORKERS: int = 1
    SERVER_PORT: int = 8000
    SERVER_HOST: str = decouple.config("SERVER_HOST", default="0.0.0.0")

    # === CORS ===
    ALLOWED_ORIGINS: list[str] = ["*"]
    ALLOW_CREDENTIALS: bool = True
    ALLOWED_METHODS: list[str] = ["*"]
    ALLOWED_HEADERS: list[str] = ["*"]

    # === LOGGING ===
    LOGGING_LEVEL: int = logging.INFO
    LOGGERS: tuple[str, str] = ("uvicorn.asgi", "uvicorn.access")


class AzureSettings(BaseSettings):
    # === Main Azure API ===
    OPENAI_ENDPOINT: str = decouple.config("AZURE_OPENAI_ENDPOINT")
    OPENAI_API_KEY: str = decouple.config("AZURE_OPENAI_API_KEY")

    # === Model deployments ===
    OPENAI_DEPLOYMENT_GPT_ROUTER: str = "gpt-standard"
    OPENAI_DEPLOYMENT_GPT_41: str = "gpt-41"
    OPENAI_DEPLOYMENT_GPT_51: str = "gpt-51"
    OPENAI_DEPLOYMENT_GPT_52: str = "gpt-52"

    # === Embeddings deployments ===
    OPENAI_EMBEDDINGS_ENDPOINT: str = decouple.config(
        "AZURE_EMBEDDINGS_OPENAI_ENDPOINT"
    )
    OPENAI_EMBEDDINGS_API_KEY: str = decouple.config("AZURE_EMBEDDINGS_OPENAI_API_KEY")
    OPENAI_EMBEDDINGS_DEPLOYMENT: str = "text-embedding-3-large"

    # === Azure AI Search ===
    SEARCH_ENDPOINT: str = decouple.config("AZURE_SEARCH_ENDPOINT")
    SEARCH_API_KEY: str = decouple.config("AZURE_SEARCH_API_KEY")
    SEARCH_INDEX_NAME: str = decouple.config(
        "AZURE_SEARCH_INDEX_NAME", "sharepoint-index"
    )


class BackendSettings(BaseSettings):
    """
    Final settings class, combining all sections.
    """

    core: CoreSettings = CoreSettings()
    azure: AzureSettings = AzureSettings()

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=f"{ROOT_DIR}/.env",
        validate_assignment=True,
        extra="allow",
    )

    @property
    def get_fastapi_app_attributes(self) -> dict[str, str | bool | None]:
        return {
            "title": self.core.APP_TITLE,
            "version": self.core.APP_VERSION,
            "description": self.core.APP_DESCRIPTION,
            "debug": self.core.DEBUG,
            "api_prefix": self.core.API_PREFIX,
            "docs_url": self.core.API_DOCS_URL,
            "openapi_url": self.core.API_OPENAPI_URL,
            "redoc_url": self.core.API_REDOC_URL,
            "openapi_prefix": self.core.API_OPENAPI_PREFIX,
        }


settings = BackendSettings()
