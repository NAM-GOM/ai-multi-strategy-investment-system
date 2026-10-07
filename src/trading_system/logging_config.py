"""Console/file logging with credential redaction and no HTTP wire logs."""

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class RedactFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(value for value in secrets if value)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for value in self._secrets:
            message = message.replace(value, "[REDACTED]")
        message = re.sub(r"(?i)(signature=)[^\s&]+", r"\1[REDACTED]", message)
        record.msg = message
        record.args = ()
        # No traceback output: transport exception messages can contain signed request URLs.
        record.exc_info = None
        record.exc_text = None
        return True


def configure_logging(
    *,
    log_file: Path = Path("logs/app.log"),
    secrets: tuple[str, ...] = (),
) -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).disabled = True
        logging.getLogger(name).setLevel(logging.WARNING)
    logger = logging.getLogger("trading_system")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in (
        logging.StreamHandler(sys.stderr),
        RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        handler.addFilter(RedactFilter(secrets))
        logger.addHandler(handler)
