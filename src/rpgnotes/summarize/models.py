from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["error", "suspicious", "question_for_user"]


class Finding(BaseModel):
    quote: str = Field(
        description="Dosłowny fragment tekstu z draftu, którego dotyczy problem."
    )
    issue: str = Field(description="Co jest nie tak lub czego nie da się zweryfikować.")
    severity: Severity = Field(
        description="Powaga: 'error' (prosta podmiana), 'suspicious' (do oceny), "
        "'question_for_user' (do weryfikacji przez człowieka)."
    )
    suggested_fix: str = Field(
        default="",
        description="Tekst zastępujący `quote` (dla 'error'), 'remove' aby usunąć, "
        "lub pusty string dla pozostałych.",
    )


class ValidationReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


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
