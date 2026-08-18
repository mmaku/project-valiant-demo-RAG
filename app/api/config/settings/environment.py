from enum import StrEnum


class Environment(StrEnum):
    PRODUCTION = "prod"  # type: ignore
    DEVELOPMENT = "dev"  # type: ignore
    STAGING = "staging"  # type: ignore
