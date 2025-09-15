# ai/models.py
"""
Modelos Pydantic para dados estruturados do sistema
"""
from pydantic import BaseModel, Field
from typing import List

class SessionData(BaseModel):
    """Modelo Pydantic para dados estruturados extraídos da sessão"""
    
    title: str = Field(description="Título da sessão")
    events: List[str] = Field(description="Eventos principais")
    npcs: List[str] = Field(description="NPCs importantes")
    locations: List[str] = Field(description="Locais visitados")
    items: List[str] = Field(description="Itens relevantes")
    quotes: List[str] = Field(description="Citações memoráveis")
    hooks: List[str] = Field(description="Ganchos para próxima sessão")
    images: List[str] = Field(description="Prompts de imagem em inglês")
    videos: List[str] = Field(description="Prompts de vídeo em inglês")