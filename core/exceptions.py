# rpgnotes/core/exceptions.py
"""
Exceções customizadas para RPG Notes.
"""

class RPGNotesError(Exception):
    """Exceção base para todos os erros do RPG Notes."""
    pass

class ConfigurationError(RPGNotesError):
    """Erro de configuração."""
    pass

class AudioProcessingError(RPGNotesError):
    """Erro no processamento de áudio."""
    pass

class TranscriptionError(RPGNotesError):
    """Erro na transcrição."""
    pass

class AIGenerationError(RPGNotesError):
    """Erro na geração de conteúdo com IA."""
    pass

class FileProcessingError(RPGNotesError):
    """Erro no processamento de arquivos."""
    pass

class ValidationError(RPGNotesError):
    """Erro de validação."""
    pass