from functools import lru_cache

import decouple

from api.config.settings.base import BackendSettings
from api.config.settings.development import BackendDevSettings
from api.config.settings.environment import Environment
from api.config.settings.production import BackendProdSettings
from api.config.settings.staging import BackendStageSettings


class BackendSettingsFactory:
    def __init__(self, environment: str):
        self.environment = environment

    def __call__(self) -> BackendSettings:
        if self.environment == Environment.DEVELOPMENT:
            return BackendDevSettings()
        elif self.environment == Environment.STAGING:
            return BackendStageSettings()
        return BackendProdSettings()


@lru_cache()
def get_settings() -> BackendSettings:
    return BackendSettingsFactory(environment=decouple.config("FAST_API_ENVIRONMENT", default="dev"))()  # type: ignore


settings: BackendSettings = get_settings()
