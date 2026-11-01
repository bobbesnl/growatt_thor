from typing import Any

websocket_command: Any
async_response: Any
async_register_command: Any

class ActiveConnection:
    def send_error(self, id: int, code: str, message: str) -> None: ...
    def send_result(self, id: int, result: object) -> None: ...
