# 🎬 Globo Play Episodes Scraper

Script Python que usa Selenium para extrair todos os episódios da novela "Volta Por Cima" do Globo Play, incluindo aqueles carregados dinamicamente via scroll infinito.

## 🚀 Instalação

### 1. Instalar dependências automaticamente (Recomendado)
```bash
chmod +x install_dependencies.sh
./install_dependencies.sh
```

### 2. Ou instalar manualmente

#### Instalar Python e pip (se não tiver)
```bash
# macOS
brew install python3

# Ubuntu/Debian
sudo apt install python3 python3-pip python3-venv

# Verificar instalação
python3 --version
pip3 --version
```

#### Criar e ativar ambiente virtual
```bash
# Criar ambiente virtual
python3 -m venv globoplay_scraper_env

# Ativar ambiente virtual
source globoplay_scraper_env/bin/activate
```

#### Instalar bibliotecas Python (no ambiente virtual)
```bash
pip install selenium webdriver-manager requests beautifulsoup4 lxml
```

#### Instalar Google Chrome
```bash
# macOS
brew install --cask google-chrome

# Ubuntu/Debian
sudo apt install chromium-browser

# Ou baixe do site oficial: https://www.google.com/chrome/
```

## 📋 Como Usar

### Execução automática (Recomendado - Modo Visual)
```bash
chmod +x run_globoplay_scraper.sh
./run_globoplay_scraper.sh [URL] [OUTPUT_NAME] [INTERACTION_TIME]
```

**Exemplos:**
```bash
# Usando valores padrão (60s de interação)
./run_globoplay_scraper.sh

# Com URL específica e tempo personalizado
./run_globoplay_scraper.sh "https://globoplay.globo.com/v/13385190/?s=0s" "volta_por_cima" 90

# Com nome customizado e mais tempo
./run_globoplay_scraper.sh "" "minha_novela" 120
```

**Parâmetros:**
- `URL`: URL da página do Globo Play (opcional, padrão: episódio atual)
- `OUTPUT_NAME`: Nome base para arquivos de saída (opcional, padrão: globoplay_episodes)
- `INTERACTION_TIME`: Tempo em segundos para interação (opcional, padrão: 60s)

**Nota:** O script roda em modo visual automaticamente, abrindo uma janela do Chrome com timer automático. **Não é necessário fechar a janela** - ela será fechada automaticamente após o tempo especificado.

#### Como Funciona o Timer Automático

1. **Script abre o navegador** e carrega a página
2. **Timer inicia automaticamente** (60 segundos por padrão)
3. **Durante o timer:** Você pode fazer scroll para carregar mais episódios
4. **Feedback em tempo real:** Mostra quantos episódios foram detectados
5. **Timer esgota:** Extração automática dos dados
6. **Arquivos salvos:** JSON e CSV criados automaticamente

**Vantagem:** Resolve o problema de perder dados quando a janela é fechada manualmente, pois o timer garante que a extração aconteça automaticamente.

### Execução manual
```bash
# Ativar ambiente virtual
source globoplay_scraper_env/bin/activate

# Executar script (modo visual por padrão)
python scrape_globoplay_episodes.py --url "https://globoplay.globo.com/v/13385190/?s=0s" --output "volta_por_cima" --interaction-time 90

# Ou forçar modo headless
python scrape_globoplay_episodes.py --headless --url "URL_AQUI" --output "NOME_SAIDA"

# Ver ajuda completa
python scrape_globoplay_episodes.py --help

# Desativar ambiente virtual
deactivate
```

### Execução com logs detalhados
```bash
./run_globoplay_scraper.sh "URL" "OUTPUT" 2>&1 | tee scraper_log.txt
```

### Modo Visual Interativo (Padrão)
```bash
# Ativar ambiente virtual
source globoplay_scraper_env/bin/activate

# Executar em modo visual (padrão)
python scrape_globoplay_episodes.py --url "URL_AQUI" --output "NOME_SAIDA"

# Desativar ambiente virtual
deactivate
```

#### Como usar o Modo Visual:
1. **A janela do Chrome abrirá automaticamente**
2. **Faça scroll manualmente** na página para carregar mais episódios
3. **Continue fazendo scroll** até carregar todos os episódios desejados
4. **Feche a janela do Chrome** quando terminar
5. **Os dados serão salvos automaticamente** nos arquivos especificados

**Dica:** Use a roda do mouse ou as setas do teclado para fazer scroll suave e carregar todos os episódios disponíveis.

#### Dicas de Configuração por Tipo de Conteúdo

**Para séries curtas (até 50 episódios):**
```bash
./run_globoplay_scraper.sh "URL" "minha_serie"
# Usa 60s padrão - tempo suficiente para carregar a maioria dos episódios
```

**Para séries longas (100+ episódios):**
```bash
./run_globoplay_scraper.sh "URL" "serie_longa" 120
# 2 minutos - tempo extra para carregar muitos episódios com scroll
```

**Para novelas diárias (200+ capítulos):**
```bash
./run_globoplay_scraper.sh "URL" "novela" 180
# 3 minutos - tempo máximo para carregar o máximo possível de capítulos
```

**Para testes rápidos:**
```bash
./run_globoplay_scraper.sh "URL" "teste" 30
# 30 segundos - apenas para verificar se está funcionando
```

### Resolução de Problemas

#### Problema: "0 episódios encontrados"
**Sintomas:** Arquivo JSON/CSV criado mas sem episódios
**Solução:** Aumente o tempo de interação
```bash
./run_globoplay_scraper.sh "URL" "output" 120  # 2 minutos
```

#### Problema: Poucos episódios carregados
**Sintomas:** Apenas alguns episódios encontrados
**Solução:**
- Aumente o tempo de interação para séries longas
- Faça scroll mais rápido durante o timer
- Use mouse wheel ou Page Down para scroll mais eficiente

#### Problema: Arquivo não criado com nome correto
**Sintomas:** Arquivo criado com nome errado
**Solução:** Verifique se passou os parâmetros corretamente
```bash
./run_globoplay_scraper.sh "URL_VALIDA" "nome_correto"
```

#### Problema: Timer não funciona
**Sintomas:** Script não respeita o tempo configurado
**Solução:** Use apenas números inteiros para tempo
```bash
./run_globoplay_scraper.sh "URL" "output" 90  # ✅ Correto
./run_globoplay_scraper.sh "URL" "output" "90"  # ❌ String
```

### Logs de Debug

Para ver logs detalhados da execução:
```bash
./run_globoplay_scraper.sh "URL" "output" 60 2>&1 | tee debug.log
```

Os logs mostram:
- ✅ Episódios detectados em tempo real
- ✅ Progresso da extração
- ✅ Status de salvamento dos arquivos
- ✅ Tempo restante do timer

### Exemplo Completo de Uso

```bash
# 1. Preparar ambiente (primeira vez apenas)
./install_dependencies.sh

# 2. Executar scraper para "Volta Por Cima"
./run_globoplay_scraper.sh "https://globoplay.globo.com/v/13385190/?s=0s" "volta_por_cima" 90

# 3. Resultado esperado:
# 📁 volta_por_cima.json (dados estruturados)
# 📁 volta_por_cima.csv (formato planilha)
# 📊 ~24-180 episódios extraídos dependendo do tempo

# 4. Verificar resultado
head -5 volta_por_cima.csv
# episode_number,chapter_date,id,title,url,type
# 1,30/09/2024,12968000,"Episódio 1, 30/09/2024",https://...,episode
```

### Funcionalidades Principais

- 🎯 **Extração Inteligente:** Detecta automaticamente episódios na página
- ⏱️ **Timer Configurável:** Controle total sobre tempo de interação
- 📊 **Feedback em Tempo Real:** Mostra progresso durante execução
- 💾 **Salvamento Automático:** Arquivos JSON e CSV criados automaticamente
- 🔄 **Modo Flexível:** Visual interativo ou headless
- 🛠️ **Parâmetros Avançados:** URL, nome de saída e tempo customizáveis
- 📱 **Responsivo:** Funciona com qualquer resolução de tela

### Estrutura dos Arquivos Gerados

**JSON (dados completos):**
```json
{
  "metadata": {
    "source_url": "https://...",
    "extraction_date": "2025-09-03 23:57:12",
    "total_episodes": 24
  },
  "episodes": [
    {
      "id": "12968000",
      "episode_number": "1",
      "chapter_date": "30/09/2024",
      "title": "Episódio 1, 30/09/2024",
      "url": "https://globoplay.globo.com/v/12968000/?s=0s",
      "type": "episode"
    }
  ]
}
```

**CSV (formato planilha):**
```csv
episode_number,chapter_date,id,title,url,type
1,30/09/2024,12968000,Episódio 1, 30/09/2024,https://globoplay.globo.com/v/12968000/?s=0s,episode
2,01/10/2024,12971263,Episódio 2, 01/10/2024,https://globoplay.globo.com/v/12971263/?s=0s,episode
```

### Compatibilidade e Limitações

#### ✅ Sistemas Suportados
- **macOS** (10.15+)
- **Linux** (Ubuntu, Debian, CentOS)
- **Windows** (através de WSL)

#### ✅ Navegadores Suportados
- **Google Chrome** (recomendado)
- **Chromium**
- **Outros navegadores baseados em Chromium**

#### ⚠️ Limitações Conhecidas
- **Sem suporte a Firefox:** Apenas navegadores Chromium
- **Requer ChromeDriver:** Instalado automaticamente
- **Modo headless limitado:** Algumas páginas bloqueiam
- **Dependente de JavaScript:** Sites sem JS não funcionam

#### 🔒 Considerações de Uso
- **Respeite os termos de serviço** do Globo Play
- **Não use para scraping massivo** que possa sobrecarregar os servidores
- **Uso pessoal/educacional** recomendado
- **Intervalos entre execuções** ajudam a evitar bloqueios

#### 🆘 Suporte
Para problemas específicos:
1. Verifique os logs com `2>&1 | tee debug.log`
2. Teste com diferentes tempos de interação
3. Verifique se o Chrome está atualizado
4. Use modo headless se o visual apresentar problemas

---

**🎬 Globo Play Scraper - Extração Inteligente de Episódios**  
**Criado para facilitar a coleta de dados de séries e novelas do Globo Play**
