"""Keep OCPP library frames and exception payloads out of THOR logs."""
import logging


class OcppMetadataLogger(logging.LoggerAdapter):
    """Log transport activity without rendering payloads or exception strings."""

    def log(self, level, msg, *args, **kwargs):
        if not self.isEnabledFor(level):
            return
        # Library exception messages can contain whole frames, including tags.
        # Do not stringify arguments or forward exc_info/stack_info either.
        self.logger.log(level, "OCPP transport activity (payload omitted)")
