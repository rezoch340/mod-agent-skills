"""Configuration loader for the model-dispatch demo.

The loader parses APP_DEBUG as a case-insensitive boolean with explicit
true/false values and APP_TIMEOUT as a positive integer.
"""


def load_settings(env):
    """Return application settings from a mapping of environment strings."""
    debug_raw = env.get("APP_DEBUG", "false").strip().lower()
    if debug_raw in {"true", "1", "yes", "on"}:
        debug = True
    elif debug_raw in {"false", "0", "no", "off"}:
        debug = False
    else:
        raise ValueError("invalid APP_DEBUG value")

    timeout_seconds = int(env.get("APP_TIMEOUT", "30"))
    if timeout_seconds <= 0:
        raise ValueError("APP_TIMEOUT must be greater than zero")

    return {
        "debug": debug,
        "timeout_seconds": timeout_seconds,
    }
