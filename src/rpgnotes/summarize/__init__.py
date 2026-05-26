from .gemini import generate_details, generate_quotes, generate_summary
from .models import QuotesData, SessionData

__all__ = [
    "QuotesData",
    "SessionData",
    "generate_details",
    "generate_quotes",
    "generate_summary",
]
