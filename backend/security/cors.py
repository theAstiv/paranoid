"""CORS options derived from ``CORS_ORIGINS``.

With ``allow_credentials=True`` Starlette does not send a literal ``*``: it
echoes the request's Origin back, so ``CORS_ORIGINS="*"`` would mean "any site
may make credentialed requests and read the response". The web UI is served
from the same origin and never needs CORS, so a wildcard drops credentials and
only a concrete origin list keeps them.
"""

import logging


logger = logging.getLogger(__name__)


def parse_cors_origins(raw: str) -> tuple[list[str], bool]:
    """Return ``(allow_origins, allow_credentials)`` for ``CORSMiddleware``."""
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        if len(origins) > 1:
            logger.warning(
                "CORS_ORIGINS mixes '*' with concrete origins; treating it as '*' "
                "(any origin, without credentials). List only concrete origins to "
                "allow credentialed cross-origin requests."
            )
        return ["*"], False
    return origins, True
