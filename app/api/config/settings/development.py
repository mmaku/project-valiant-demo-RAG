from api.config.settings.base import BackendSettings, CoreSettings
from api.config.settings.environment import Environment


class CoreDevSettings(CoreSettings):
    DEBUG: bool = True
    APP_DESCRIPTION: str | None = "Development Environment"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT


class BackendDevSettings(BackendSettings):
    core: CoreSettings = CoreDevSettings()
