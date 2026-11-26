"""OCPP base-class boundary; schema-validated payload classes remain library-owned."""

from logging import Logger, LoggerAdapter
from typing import Any

from . import call as call
from . import call_result as call_result

class ChargePoint:
    id: str
    def __init__(
        self,
        id: str,
        connection: object,
        response_timeout: int = 30,
        *,
        logger: LoggerAdapter[Logger],
    ) -> None: ...
    async def start(self) -> None: ...
    async def route_message(self, raw_msg: str | bytes) -> None: ...
    async def _send(self, message: str) -> None: ...
    async def call(self, payload: object, **kwargs: Any) -> Any: ...
