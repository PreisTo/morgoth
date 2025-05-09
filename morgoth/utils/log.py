import logging
from morgoth.configuration import morgoth_config

logger = logging.getLogger("morgoth")
logger.setLevel(morgoth_config["logging"]["log_level"])
