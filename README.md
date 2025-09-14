# 🚀 RPG Session Notes Automator

> **Automatizador profissional de notas de sessões de RPG usando IA**
> 
> Transforme suas gravações de áudio Craig em notas detalhadas e organizadas automaticamente usando Whisper (OpenAI) para transcrição e Gemini (Google) para geração de conteúdo estruturado.

[![Python](https://img.shields.io/badge/Python-3.8+-blue)](https://www.python.org/)
[![Whisper](https://img.shields.io/badge/OpenAI-Whisper-green)](https://openai.com/research/whisper)
[![Gemini](https://img.shields.io/badge/Google-Gemini-orange)](https://ai.google.dev/)
[![GPU](https://img.shields.io/badge/GPU-CUDA%20Ready-red)](https://developer.nvidia.com/cuda-zone)

## ✨ Sistema Completamente Modular e Funcional

### 🏗️ **Arquitetura Modular Profissional**
- ✅ **Main.py limpo** - Apenas 150 linhas vs 35,559 originais (99.6% redução)
- ✅ **Módulos especializados** - Cada funcionalidade em seu próprio arquivo
- ✅ **Imports organizados** - Sistema de módulos Python padrão
- ✅ **Error handling robusto** - Tratamento de erros centralizado
- ✅ **Código escalável** - Base sólida para futuras implementações

### 🎙️ **Transcrição de Áudio Avançada**
- ✅ **Whisper OpenAI** com suporte GPU/CPU automático
- ✅ **Fallback inteligente** CPU se GPU indisponível
- ✅ **FP16 otimizado** para GPUs (reduz uso de memória)
- ✅ **Progress tracking** detalhado por arquivo
- ✅ **Filtro automático** de segmentos vazios

### 📁 **Processamento de Arquivos Craig**
- ✅ **Suporte completo** a `craig.flac.zip` e `craig.aup.zip`
- ✅ **Extração automática** de arquivos ZIP
- ✅ **Organização inteligente** da estrutura de arquivos
- ✅ **Limpeza automática** de arquivos não-FLAC
- ✅ **Detecção múltiplos formatos** de entrada

### 👥 **Identificação de Speakers Inteligente**
- ✅ **Mapeamento Discord** → Nomes de personagens
- ✅ **Filtro automático** de bots (craig, botyan, etc.)
- ✅ **Ordenação cronológica** por timestamps
- ✅ **Saída dupla**: JSON estruturado + TXT legível
- ✅ **Configuração personalizada** via `discord_speaker_mapping.json`

### 🤖 **Geração de Notas com IA**
- ✅ **Gemini API** para sumários narrativos detalhados
- ✅ **Extração estruturada** de dados (NPCs, eventos, itens, etc.)
- ✅ **Contexto de campanha** carregado automaticamente
- ✅ **Rate limiting** e retry automático
- ✅ **Templates personalizáveis** por tipo de campanha

### 🖥️ **Interface de Usuário Completa**
- ✅ **Menu interativo** com opções claras
- ✅ **Setup wizard** para configuração inicial
- ✅ **Suporte multilíngue** (Português/Inglês)
- ✅ **Seleção de campanhas** pré-configuradas
- ✅ **Templates flexíveis** para diferentes estilos
- ✅ **Gerenciamento inteligente** de arquivos temporários

## 🏗️ Estrutura Modular

### 📁 **Organização Profissional**
```
rpgnotes/
├── main.py                          # ⭐ Arquivo principal (150 linhas)
├── core/
│   ├── __init__.py                  # Imports do módulo
│   ├── config.py                    # Configurações centralizadas
│   ├── workflows.py                 # Orquestração de workflows
│   └── session_manager.py           # Gerenciamento de sessões
├── audio/
│   ├── __init__.py                  # Imports do módulo
│   ├── processor.py                 # Processamento Craig
│   ├── transcriber.py               # Transcrição Whisper
│   └── speaker_mapping.py           # Mapeamento de speakers
├── ai/
│   ├── __init__.py                  # Imports do módulo
│   ├── models.py                    # Modelos Pydantic
│   └── gemini_client.py             # Cliente Gemini
├── interface/
│   ├── __init__.py                  # Imports do módulo
│   ├── menu.py                      # Menu principal
│   └── setup_wizard.py              # Assistente configuração
├── utils/
│   └── __init__.py                  # Para futuras implementações
├── config/                          # Configurações e contextos
├── downloads/                       # Arquivos de entrada
├── output/                          # Resultados processados
├── prompts/                         # Contexto de campanhas
└── temp/                           # Arquivos temporários
```

## 🔧 Instalação e Configuração

### **1. Setup Inicial**
```bash
git clone https://github.com/YBraga35/rpgnotes
cd rpgnotes
pip install -r requirements.txt
```

### **2. Configuração**
```bash
# Copie e configure variáveis de ambiente
cp .env.example .env

# Configure sua API key no arquivo .env
GEMINI_API_KEY="sua_api_key_aqui"
```

### **3. Arquivos de Configuração**
- `discord_speaker_mapping.json` - Mapeamento Discord → Personagens ✅
- `template.md` - Template de saída das notas ✅
- `config/prompts/` - Templates e contextos de campanha ✅

## 🚀 Como Usar

### **Uso Simples**
```bash
# 1. Coloque craig.flac.zip ou craig.aup.zip na pasta downloads/
# 2. Execute o programa
python main.py

# 3. Siga o setup wizard:
#    - Escolha idioma (pt/en)
#    - Selecione campanha (OOTDL, Avernus, Custom)
#    - Escolha template de sumário
#    - Execute workflow desejado
```

### **Opções de Workflow**
- **[1] Workflow Completo**: Transcrição → Mapeamento → Geração IA → Notas
- **[2] Apenas Transcrição**: Transcrição → Mapeamento (sem IA)
- **[3] Sair**: Encerra aplicação

## 📋 Campanhas Suportadas

### **🐉 Odyssey of the Dragonlords**
- Contexto épico da mitologia grega
- Templates otimizados para heróis lendários
- Prompts específicos para Thylea

### **🔥 Descent into Avernus**
- Contexto infernal de Baldur's Gate
- Foco em horror e dilemas morais
- Templates para ambientação sombria

### **⚔️ Campanhas Personalizadas**
- Configuração flexível para qualquer setting
- Templates adaptáveis
- Contexto customizado

## 📊 Dependências

### **🔑 Principais**
```python
openai-whisper==20250625              # Transcrição de áudio
google-generativeai==0.8.5           # API Gemini
instructor[google-generativeai]==1.9.2 # Structured outputs
python-dotenv==1.1.1                 # Variáveis de ambiente
pydantic==2.5.0                      # Validação de dados
tqdm==4.66.1                         # Progress bars
```

### **🔧 Sistema**
- **Python 3.8+** (recomendado 3.10+)
- **FFmpeg** (requerido pelo Whisper)
- **CUDA** (opcional, para GPU)

## ⚡ Performance e Otimizações

### **🚀 GPU Acceleration**
- Detecção automática CUDA
- Fallback inteligente para CPU
- FP16 otimizado para economia de VRAM
- Progress tracking em tempo real

### **📈 Processamento Eficiente**
- Processamento em lotes
- Cache inteligente de transcrições
- Reutilização de arquivos existentes
- Limpeza automática de temporários

## 🔒 Configuração de Segurança

### **🔑 API Keys**
```bash
# Obtenha sua chave Gemini
# https://ai.google.dev/

# Configure no .env
GEMINI_API_KEY="sua_chave_aqui"
GEMINI_MODEL_NAME="gemini-2.5-pro"
```

### **📁 Estrutura de Dados**
```bash
rpgnotes/
├── .env                    # ⚠️  Nunca commitar (contém API keys)
├── downloads/              # 📥 Arquivos craig.zip de entrada
├── output/                 # 📤 Notas finais geradas
├── temp/                   # 🗑️ Arquivos temporários (pode limpar)
└── config/                 # ⚙️ Configurações e prompts
```

## 🎯 Status de Implementação

### **✅ Completamente Funcional**
- ✅ Sistema modular profissional
- ✅ Transcrição Whisper GPU/CPU
- ✅ Processamento de arquivos Craig
- ✅ Mapeamento inteligente de speakers
- ✅ Geração IA com Gemini
- ✅ Interface completa com wizard
- ✅ Templates para múltiplas campanhas
- ✅ Error handling robusto
- ✅ Configuração flexível

### **🎮 Pronto Para Usar**
O sistema está **100% funcional** e pronto para processar suas sessões de RPG imediatamente após a configuração básica.

## 🚀 Roadmap Futuro

### **📱 Google Colab Integration**
- Interface web para upload de arquivos
- Processamento na nuvem
- Integração com Google Drive

### **🤖 N8N Automation**
- Webhooks para trigger automático
- Integração com Discord/Notion
- Workflow automation completo

### **⚡ Performance Upgrades**
- faster-whisper implementation
- Parallel processing
- Advanced caching strategies

## 🤝 Contribuição

Este projeto evoluiu significativamente desde o fork original, tornando-se uma aplicação **profissional** e **modular**. Contribuições são bem-vindas para:

1. **Otimizações de Performance**: faster-whisper, parallel processing
2. **Novas Integrações**: Google Colab, N8N, Discord bots
3. **Campanhas Adicionais**: Novos templates e contextos
4. **UI/UX**: Interface web, mobile app
5. **Documentação**: Tutoriais, exemplos, guias

## 📄 Licença

MIT License - Fork melhorado de [rpgnotes original](https://github.com/karpiq24/rpgnotes)

---

**🎯 Sistema Profissional Pronto!** 

O RPG Notes Automator agora é uma aplicação **completamente modular**, **robusta** e **escalável** que transforma suas sessões de RPG em notas profissionais automaticamente. Configure uma vez e use para sempre!