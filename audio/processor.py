# audio/processor.py
"""
Processamento de arquivos de áudio Craig
"""
import zipfile
import shutil
import os
from pathlib import Path
from typing import Optional

class AudioProcessor:
    """Classe para processar arquivos de áudio Craig"""
    
    def __init__(self, config):
        """
        Inicializa o processador de áudio
        
        Args:
            config: Instância de Config com configurações do sistema
        """
        self.config = config
        self.supported_patterns = [
            "craig-*.flac.zip",
            "craig-*.aup.zip", 
            "*craig*.zip",
            "craig-*.flac"
        ]
    
    def find_audio_archive(self) -> Optional[Path]:
        """
        Procura por arquivos de áudio Craig em vários formatos
        
        Returns:
            Path: Caminho para arquivo encontrado ou None
        """
        print("🔍 Procurando arquivos de áudio...")
        
        for pattern in self.supported_patterns:
            files = list(self.config.AUDIO_SOURCE_DIR.glob(pattern))
            if files:
                # Retorna o mais recente se houver múltiplos
                newest = max(files, key=os.path.getmtime)
                print(f"🎵 Encontrado arquivo de áudio: {newest.name}")
                return newest
        
        print("❌ Nenhum arquivo de áudio encontrado nos formatos:")
        for pattern in self.supported_patterns:
            print(f"   - {pattern}")
        
        return None
    
    def extract_audio_files(self) -> bool:
        """
        Extrai arquivos de áudio de vários formatos
        
        Returns:
            bool: True se extração foi bem-sucedida
        """
        # Verifica se já existem arquivos extraídos
        if self._audio_files_already_extracted():
            print("✅ Arquivos de áudio já extraídos. Pulando extração.")
            return True
        
        # Procura arquivo de áudio
        audio_archive = self.find_audio_archive()
        if not audio_archive:
            return False
        
        try:
            if audio_archive.suffix == '.zip':
                return self._extract_zip_file(audio_archive)
            elif audio_archive.suffix == '.flac':
                return self._copy_flac_file(audio_archive)
            else:
                print(f"❌ Formato não suportado: {audio_archive.suffix}")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao extrair áudio: {e}")
            return False
    
    def _audio_files_already_extracted(self) -> bool:
        """Verifica se já existem arquivos FLAC extraídos"""
        return len(list(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))) > 0
    
    def _extract_zip_file(self, zip_file: Path) -> bool:
        """
        Extrai arquivo ZIP
        
        Args:
            zip_file: Caminho para arquivo ZIP
            
        Returns:
            bool: True se extração foi bem-sucedida
        """
        print(f"📦 Extraindo arquivo ZIP: {zip_file.name}")
        
        # Garante que diretório existe
        self.config.AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        try:
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(self.config.AUDIO_OUTPUT_DIR)
            
            print(f"✅ Arquivo ZIP extraído: {zip_file.name}")
            
            # Organiza estrutura de arquivos
            self._organize_extracted_files()
            
            # Lista arquivos FLAC encontrados
            self._list_flac_files()
            
            return True
            
        except Exception as e:
            print(f"❌ Erro ao extrair ZIP: {e}")
            return False
    
    def _copy_flac_file(self, flac_file: Path) -> bool:
        """
        Copia arquivo FLAC individual
        
        Args:
            flac_file: Caminho para arquivo FLAC
            
        Returns:
            bool: True se cópia foi bem-sucedida
        """
        print(f"📁 Copiando arquivo FLAC: {flac_file.name}")
        
        try:
            # Garante que diretório existe
            self.config.AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            
            # Copia arquivo
            dest_path = self.config.AUDIO_OUTPUT_DIR / flac_file.name
            shutil.copy2(flac_file, dest_path)
            
            print(f"✅ Arquivo FLAC copiado: {flac_file.name}")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao copiar FLAC: {e}")
            return False
    
    def _organize_extracted_files(self):
        """Organiza arquivos extraídos movendo FLACs para o diretório raiz"""
        print("📂 Organizando arquivos extraídos...")
        
        # Encontra todos os arquivos FLAC, incluindo subdiretórios
        flac_files = list(self.config.AUDIO_OUTPUT_DIR.rglob("*.flac"))
        
        if not flac_files:
            print("⚠️ Nenhum arquivo FLAC encontrado após extração")
            return
        
        # Move arquivos FLAC para o diretório raiz se estiverem em subdiretórios
        moved_count = 0
        for flac_file in flac_files:
            if flac_file.parent != self.config.AUDIO_OUTPUT_DIR:
                new_path = self.config.AUDIO_OUTPUT_DIR / flac_file.name
                try:
                    shutil.move(str(flac_file), str(new_path))
                    print(f"📁 Movido: {flac_file.name}")
                    moved_count += 1
                except Exception as e:
                    print(f"⚠️ Erro ao mover {flac_file.name}: {e}")
        
        if moved_count > 0:
            print(f"✅ {moved_count} arquivos reorganizados")
        
        # Remove diretórios vazios
        self._cleanup_empty_directories()
        
        # Remove arquivos não-FLAC
        self._remove_non_flac_files()
    
    def _cleanup_empty_directories(self):
        """Remove diretórios vazios após reorganização"""
        try:
            for item in self.config.AUDIO_OUTPUT_DIR.iterdir():
                if item.is_dir():
                    try:
                        item.rmdir()  # Remove apenas se vazio
                        print(f"🗑️ Diretório vazio removido: {item.name}")
                    except OSError:
                        # Diretório não vazio, remove recursivamente
                        shutil.rmtree(item)
                        print(f"🗑️ Diretório removido: {item.name}")
        except Exception as e:
            print(f"⚠️ Erro na limpeza de diretórios: {e}")
    
    def _remove_non_flac_files(self):
        """Remove arquivos que não são FLAC"""
        removed_count = 0
        try:
            for item in self.config.AUDIO_OUTPUT_DIR.iterdir():
                if item.is_file() and item.suffix.lower() != ".flac":
                    os.remove(item)
                    print(f"🗑️ Removido arquivo não-FLAC: {item.name}")
                    removed_count += 1
        except Exception as e:
            print(f"⚠️ Erro ao remover arquivos não-FLAC: {e}")
        
        if removed_count > 0:
            print(f"✅ {removed_count} arquivos não-FLAC removidos")
    
    def _list_flac_files(self):
        """Lista arquivos FLAC encontrados"""
        flac_files = sorted(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))
        
        if flac_files:
            print(f"✅ Total de arquivos FLAC prontos: {len(flac_files)}")
            for flac in flac_files:
                file_size_mb = flac.stat().st_size / (1024 * 1024)
                print(f"   🎵 {flac.name} ({file_size_mb:.1f}MB)")
        else:
            print("❌ Nenhum arquivo FLAC encontrado")
    
    def validate_audio_files(self) -> bool:
        """
        Valida se arquivos de áudio estão prontos para transcrição
        
        Returns:
            bool: True se arquivos são válidos
        """
        flac_files = list(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))
        
        if not flac_files:
            print("❌ Nenhum arquivo FLAC encontrado para validação")
            return False
        
        print(f"🔍 Validando {len(flac_files)} arquivos FLAC...")
        
        valid_count = 0
        for flac_file in flac_files:
            try:
                # Verifica se arquivo existe e tem tamanho > 0
                if flac_file.exists() and flac_file.stat().st_size > 0:
                    valid_count += 1
                else:
                    print(f"⚠️ Arquivo inválido: {flac_file.name}")
            except Exception as e:
                print(f"⚠️ Erro ao validar {flac_file.name}: {e}")
        
        if valid_count == len(flac_files):
            print(f"✅ Todos os {valid_count} arquivos são válidos")
            return True
        else:
            print(f"❌ Apenas {valid_count}/{len(flac_files)} arquivos são válidos")
            return False
    
    def get_audio_stats(self) -> dict:
        """
        Retorna estatísticas dos arquivos de áudio
        
        Returns:
            dict: Estatísticas dos arquivos
        """
        flac_files = list(self.config.AUDIO_OUTPUT_DIR.glob("*.flac"))
        
        total_size = sum(f.stat().st_size for f in flac_files)
        total_size_mb = total_size / (1024 * 1024)
        
        return {
            'total_files': len(flac_files),
            'total_size_mb': round(total_size_mb, 1),
            'files': [f.name for f in sorted(flac_files)]
        }

def create_audio_processor(config):
    """Função utilitária para criar instância do audio processor"""
    return AudioProcessor(config)