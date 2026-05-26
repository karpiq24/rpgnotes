from __future__ import annotations

from pydantic import BaseModel, Field


class SessionData(BaseModel):
    title: str = Field(description="Tytuł sesji. Powinien być krótki, ale opisowy i chwytliwy.")
    events: list[str] = Field(
        description="Krótka, punktowa lista najważniejszych wydarzeń lub decyzji, które miały miejsce."
    )
    npcs: list[str] = Field(
        description="Lista najważniejszych postaci niezależnych (NPC), które pojawiły się lub odegrały kluczową rolę."
    )
    locations: list[str] = Field(description="Lista najważniejszych odwiedzonych lokacji.")
    items: list[str] = Field(description="Lista najważniejszych zdobytych lub użytych przedmiotów.")


class QuotesData(BaseModel):
    quotes: list[str] = Field(
        description=(
            "Lista 5-7 najbardziej pamiętnych, zabawnych lub ważnych cytatów z sesji, "
            'wraz z informacją, kto je wypowiedział. Np. \'Arevon: "Coś tu jest nie tak."\'.'
        )
    )
