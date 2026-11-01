"""Keep OCPP library frames and exception payloads out of THOR logs."""

import logging
from typing import Any


class OcppMetadataLogger(logging.LoggerAdapter[logging.Logger]):
    """Log transport activity without rendering payloads or exception strings."""

    def log(self, level: int, msg: object, *args: object, **kwargs: Any) -> None:
        if not self.isEnabledFor(level):
            return
        # Library exception messages can contain whole frames, including tags.
        # Do not stringify arguments or forward exc_info/stack_info either.
        self.logger.log(level, "OCPP transport activity (payload omitted)")
