from collections.abc import Callable
from typing import Any

def on[F: Callable[..., Any]](
    action: str, *, skip_schema_validation: bool = False
) -> Callable[[F], F]: ...
