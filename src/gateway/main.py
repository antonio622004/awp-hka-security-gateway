import logging

from .app import create_app
from .config import Settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
# Never log OIDC callback query strings or token endpoint requests.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
app = create_app(Settings.from_env())
