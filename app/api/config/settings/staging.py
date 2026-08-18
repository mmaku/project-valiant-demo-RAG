from api.config.settings.base import BackendSettings, CoreSettings
from api.config.settings.environment import Environment


class CoreStageSettings(CoreSettings):
    DEBUG: bool = False
    APP_DESCRIPTION: str | None = "Staging Environment"
    ENVIRONMENT: Environment = Environment.STAGING


class BackendStageSettings(BackendSettings):
    core: CoreSettings = CoreStageSettings()
