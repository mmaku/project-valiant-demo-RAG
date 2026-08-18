import typing

from api.config.settings.base import BackendSettings


def execute_backend_server_event_handler(settings: BackendSettings) -> typing.Any:
    async def launch_backend_server_events() -> None:
        pass

    return launch_backend_server_events
