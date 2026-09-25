from ..core import config
from .gemini import GeminiProvider
from .mock import MockProvider

_provider = None


def get_provider():
    """Process-wide provider: Gemini when a key is configured, else the offline mock."""
    global _provider
    if _provider is None:
        _provider = MockProvider() if config.MOCK_MODE else GeminiProvider(
            config.GEMINI_API_KEY, config.GEMINI_MODEL, embed_model=config.GEMINI_EMBED_MODEL)
    return _provider
