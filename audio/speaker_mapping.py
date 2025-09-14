# audio/speaker_mapping.py
"""
Mapeamento e combinação de transcrições com identificação de speakers
"""
import json
from pathlib import Path
from typing import Optional, Dict, List

class SpeakerMapper:
    """Classe para gerenciar mapeamento de speakers e combinação de transcrições"""
    
    def __init__(self, config):
        """
        Inicializa o mapper de speakers
        
        Args:
            config: Instância de Config com configurações do sistema
        """
        self.config = config
        self.speaker_mapping = {}
        self.ignored_speakers = {"craig", "botyan", "bot_yan", "bot yan"}
        
    def load_speaker_mapping(self) -> Dict[str, str]:
        """
        Carrega mapeamento Discord → personagem
        
        Returns:
            dict: Mapeamento de speakers
        """
        if self.config.DISCORD_MAPPING_FILE.exists():
            try:
                with open(self.config.DISCORD_MAPPING_FILE, 'r', encoding='utf-8') as f:
                    self.speaker_mapping = json.load(f)
                print(f"✅ Mapeamento de speakers carregado: {len(self.speaker_mapping)} entradas")
            except Exception as e:
                print(f"⚠️ Erro ao carregar mapeamento: {e}")
                self.speaker_mapping = {}
        else:
            print("⚠️ Arquivo de mapeamento não encontrado. Usando nomes originais.")
            self.speaker_mapping = {}
        
        return self.speaker_mapping
    
    def filter_unwanted_speakers(self, speaker_key: str) -> bool:
        """
        Verifica se um speaker deve ser ignorado
        
        Args:
            speaker_key: Identificador do speaker
            
        Returns:
            bool: True se deve ser ignorado
        """
        speaker_lower = speaker_key.lower().replace(" ", "").replace("_", "")
        return any(bot in speaker_lower for bot in self.ignored_speakers)
    
    def combine_transcriptions(self, session_number: int) -> Optional[Path]:
        """
        Combina transcrições individuais em um arquivo único com mapeamento de speakers
        
        Args:
            session_number: Número da sessão
            
        Returns:
            Path: Caminho para arquivo TXT combinado, ou None se erro
        """
        # Garante que diretório existe
        self.config.TRANSCRIPTIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Arquivos de saída
        combined_json = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.json"
        combined_txt = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.txt"
        
        # Verifica se já existe
        if combined_txt.exists():
            print(f"Transcrição combinada já existe: {combined_txt.name}")
            return combined_txt
        
        # Carrega mapeamento de speakers
        self.load_speaker_mapping()
        
        # Coleta todos os segmentos
        segments = self._collect_all_segments()
        
        if not segments:
            print("❌ Nenhum segmento encontrado para combinar")
            return None
        
        # Ordena por tempo de início
        segments.sort(key=lambda s: s["start"])
        
        # Salva arquivos combinados
        self._save_combined_json(segments, combined_json)
        self._save_combined_txt(segments, combined_txt)
        
        print(f"✅ Transcrição combinada criada: {len(segments)} segmentos")
        return combined_txt
    
    def _collect_all_segments(self) -> List[Dict]:
        """
        Coleta todos os segmentos das transcrições individuais
        
        Returns:
            list: Lista de segmentos com speakers mapeados
        """
        segments = []
        transcription_files = sorted(self.config.TEMP_TRANSCRIPTIONS.glob("*.json"))
        
        for seg_file in transcription_files:
            try:
                # Carrega dados do arquivo
                with open(seg_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Extrai speaker do nome do arquivo
                speaker_key = self._extract_speaker_from_filename(seg_file.stem)
                speaker_name = self.speaker_mapping.get(speaker_key, speaker_key)
                
                # Processa cada segmento
                for seg in data:
                    text = seg.get("text", "").strip()
                    if not text:
                        continue
                    
                    # Filtra speakers indesejados
                    if self.filter_unwanted_speakers(speaker_name):
                        continue
                    
                    # Adiciona informação do speaker
                    seg["speaker"] = speaker_name
                    seg["speaker_id"] = speaker_key
                    segments.append(seg)
                    
            except Exception as e:
                print(f"⚠️ Erro ao processar {seg_file.name}: {e}")
                continue
        
        return segments
    
    def _extract_speaker_from_filename(self, filename: str) -> str:
        """
        Extrai identificador do speaker do nome do arquivo
        
        Args:
            filename: Nome do arquivo (sem extensão)
            
        Returns:
            str: Identificador do speaker
        """
        # Formato esperado: "craig-timestamp-speaker_id"
        parts = filename.split("-", 2)
        if len(parts) >= 3:
            return parts[2]  # Última parte é o speaker_id
        elif len(parts) == 2:
            return parts[1]  # Fallback para formato mais simples
        else:
            return filename  # Usa nome completo como fallback
    
    def _save_combined_json(self, segments: List[Dict], filepath: Path):
        """
        Salva segmentos combinados em formato JSON
        
        Args:
            segments: Lista de segmentos
            filepath: Caminho do arquivo JSON
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(segments, f, indent=2, ensure_ascii=False)
            print(f"📄 JSON combinado salvo: {filepath.name}")
        except Exception as e:
            print(f"❌ Erro ao salvar JSON: {e}")
    
    def _save_combined_txt(self, segments: List[Dict], filepath: Path):
        """
        Salva segmentos combinados em formato TXT legível
        
        Args:
            segments: Lista de segmentos
            filepath: Caminho do arquivo TXT
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                current_speaker = None
                
                for seg in segments:
                    speaker = seg["speaker"]
                    text = seg["text"].strip()
                    
                    # Adiciona cabeçalho do speaker se mudou
                    if speaker != current_speaker:
                        f.write(f"\\n\\n[{speaker}]\\n")
                        current_speaker = speaker
                    
                    # Adiciona texto do segmento
                    f.write(text + " ")
            
            print(f"📄 TXT combinado salvo: {filepath.name}")
        except Exception as e:
            print(f"❌ Erro ao salvar TXT: {e}")
    
    def get_speaker_stats(self, session_number: int) -> Dict:
        """
        Retorna estatísticas dos speakers de uma sessão
        
        Args:
            session_number: Número da sessão
            
        Returns:
            dict: Estatísticas dos speakers
        """
        json_file = self.config.TRANSCRIPTIONS_OUTPUT_DIR / f"session{session_number}.json"
        
        if not json_file.exists():
            return {}
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                segments = json.load(f)
            
            speaker_stats = {}
            for seg in segments:
                speaker = seg.get('speaker', 'Unknown')
                if speaker not in speaker_stats:
                    speaker_stats[speaker] = {
                        'segments': 0,
                        'total_duration': 0,
                        'word_count': 0
                    }
                
                speaker_stats[speaker]['segments'] += 1
                speaker_stats[speaker]['total_duration'] += seg.get('end', 0) - seg.get('start', 0)
                speaker_stats[speaker]['word_count'] += len(seg.get('text', '').split())
            
            return speaker_stats
            
        except Exception as e:
            print(f"❌ Erro ao calcular estatísticas: {e}")
            return {}

def create_speaker_mapper(config):
    """Função utilitária para criar instância do speaker mapper"""
    return SpeakerMapper(config)