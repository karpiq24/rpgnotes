# audio/transcriber.py
"""
Transcrição de áudio usando OpenAI Whisper
"""
import time
import json
import torch
from pathlib import Path
from whisper import load_model
from typing import Optional

class WhisperTranscriber:
    """Classe para gerenciar transcrição de áudio com Whisper"""
    
    def __init__(self, config):
        """
        Inicializa o transcriber
        
        Args:
            config: Instância de Config com configurações do sistema
        """
        self.config = config
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def load_whisper_model(self, model_size: str = "small"):
        """
        Carrega modelo Whisper
        
        Args:
            model_size: Tamanho do modelo ("tiny", "base", "small", "medium", "large")
        """
        print(f"🔄 Usando dispositivo para transcrição: {self.device}")
        print(f"Carregando modelo Whisper {model_size}...")
        
        self.model = load_model(model_size, device=self.device)
        print("✅ Modelo carregado.")
        
    def transcribe_audio(self) -> bool:
        """
        Transcreve todos os arquivos FLAC no diretório de áudio
        
        Returns:
            bool: True se transcrição foi bem-sucedida
        """
        # Garante que diretórios existem
        self.config.AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.config.TEMP_TRANSCRIPTIONS.mkdir(parents=True, exist_ok=True)
        
        # Carrega modelo se não foi carregado
        if not self.model:
            self.load_whisper_model()
        
        # Encontra arquivos FLAC
        flac_files = sorted(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))
        if not flac_files:
            print("Nenhum arquivo .flac para transcrever.")
            return False
        
        print(f"📁 Encontrados {len(flac_files)} arquivos para transcrever")
        
        # Processa cada arquivo
        for i, audio_file in enumerate(flac_files, 1):
            success = self._transcribe_single_file(audio_file, i, len(flac_files))
            if not success:
                print(f"⚠️ Falha na transcrição de {audio_file.name}")
        
        print("✅ Transcrição de todos os arquivos concluída.")
        return True
    
    def _transcribe_single_file(self, audio_file: Path, current: int, total: int) -> bool:
        """
        Transcreve um único arquivo de áudio
        
        Args:
            audio_file: Caminho para arquivo de áudio
            current: Número atual do arquivo
            total: Total de arquivos
            
        Returns:
            bool: True se transcrição foi bem-sucedida
        """
        output_json = self.config.TEMP_TRANSCRIPTIONS / f"{audio_file.stem}.json"
        
        # Pula se já foi transcrito
        if output_json.exists():
            print(f"[{current}/{total}] {audio_file.name} já transcrito, pulando.")
            return True
        
        print(f"[{current}/{total}] Transcrevendo {audio_file.name} ...")
        start_time = time.time()
        
        try:
            # Executa transcrição
            result = self.model.transcribe(
                str(audio_file),
                language="pt",
                fp16=(self.device == "cuda")  # usa FP16 na GPU para acelerar
            )
            
            # Filtra segmentos vazios
            segments = result["segments"]
            segments = [s for s in segments if s.get("text", "").strip()]
            
            # Salva resultado
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump(segments, f, indent=2, ensure_ascii=False)
            
            # Mostra estatísticas
            elapsed = (time.time() - start_time) / 60
            print(f" ✅ Concluído em {elapsed:.1f} minutos - {len(segments)} segmentos")
            return True
            
        except Exception as e:
            print(f" ❌ Erro ao transcrever {audio_file.name}: {e}")
            
            # Fallback para CPU caso falhe na GPU
            if self.device == "cuda":
                print(" ⚠️ Falha na GPU, tentando CPU...")
                self.device = "cpu"
                self.load_whisper_model()  # Recarrega modelo no CPU
                return self._transcribe_single_file(audio_file, current, total)
            
            # Se já está no CPU, marca como vazio e continua
            with open(output_json, "w", encoding="utf-8") as f:
                json.dump([], f)
            return False
    
    def process_transcription_batch(self, batch_size: int = 4) -> bool:
        """
        Processa transcrições em lotes (para otimização futura)
        
        Args:
            batch_size: Número de arquivos por lote
            
        Returns:
            bool: True se processamento foi bem-sucedido
        """
        # Por enquanto, chama transcrição individual
        # Futura implementação pode incluir processamento paralelo
        return self.transcribe_audio()
    
    def get_transcription_stats(self) -> dict:
        """
        Retorna estatísticas das transcrições
        
        Returns:
            dict: Estatísticas das transcrições
        """
        transcription_files = list(self.config.TEMP_TRANSCRIPTIONS.glob("*.json"))
        total_segments = 0
        total_duration = 0
        
        for file in transcription_files:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    total_segments += len(data)
                    if data:
                        total_duration += data[-1].get('end', 0)
            except Exception:
                continue
        
        return {
            'total_files': len(transcription_files),
            'total_segments': total_segments,
            'estimated_duration_minutes': total_duration / 60,
            'device_used': self.device
        }

def create_transcriber(config):
    """Função utilitária para criar instância do transcriber"""
    return WhisperTranscriber(config)