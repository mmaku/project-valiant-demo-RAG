from api.config.settings.base import BackendSettings, CoreSettings
from api.config.settings.environment import Environment


class CoreProdSettings(CoreSettings):
    DEBUG: bool = False
    APP_DESCRIPTION: str | None = "Production Environment"
    ENVIRONMENT: Environment = Environment.PRODUCTION


class BackendProdSettings(BackendSettings):
    core: CoreSettings = CoreProdSettings()
