#!/bin/bash

# Script para instalar dependências necessárias para o scraping do Globo Play
# Compatível com macOS (Homebrew) e Linux
# Cria ambiente virtual para evitar conflitos com sistema

echo "🚀 Instalando dependências para scraping do Globo Play..."

# Verifica se Python 3 está instalado
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Instale Python 3.7+ primeiro."
    echo "   macOS: brew install python3"
    echo "   Ubuntu/Debian: sudo apt install python3 python3-pip"
    exit 1
fi

echo "✅ Python 3 encontrado: $(python3 --version)"

# Cria ambiente virtual para evitar conflitos
VENV_DIR="globoplay_scraper_env"
echo "📦 Criando ambiente virtual em '$VENV_DIR'..."

if [ -d "$VENV_DIR" ]; then
    echo "🗑️  Removendo ambiente virtual existente..."
    rm -rf "$VENV_DIR"
fi

python3 -m venv "$VENV_DIR"

if [ $? -ne 0 ]; then
    echo "❌ Erro ao criar ambiente virtual"
    echo "💡 Dica: Execute 'python3 -m venv --help' para mais informações"
    exit 1
fi

echo "✅ Ambiente virtual criado com sucesso"

# Ativa o ambiente virtual
echo "🔄 Ativando ambiente virtual..."
source "$VENV_DIR/bin/activate"

if [ $? -ne 0 ]; then
    echo "❌ Erro ao ativar ambiente virtual"
    exit 1
fi

# Instala Selenium e dependências Python no ambiente virtual
echo "📦 Instalando bibliotecas Python..."
pip install selenium webdriver-manager requests beautifulsoup4 lxml

if [ $? -eq 0 ]; then
    echo "✅ Bibliotecas Python instaladas com sucesso"
else
    echo "❌ Erro ao instalar bibliotecas Python"
    echo "💡 Tentando com --break-system-packages (apenas se necessário)..."
    pip install --break-system-packages selenium webdriver-manager requests beautifulsoup4 lxml

    if [ $? -ne 0 ]; then
        echo "❌ Ainda erro ao instalar. Tente instalar manualmente:"
        echo "   pip install selenium webdriver-manager requests beautifulsoup4 lxml"
        exit 1
    fi
fi

# Instala ChromeDriver usando webdriver-manager
echo "🌐 Instalando ChromeDriver..."
python -c "from webdriver_manager.chrome import ChromeDriverManager; ChromeDriverManager().install()"

if [ $? -eq 0 ]; then
    echo "✅ ChromeDriver instalado com sucesso"
else
    echo "❌ Erro ao instalar ChromeDriver"
    echo "💡 Você pode baixar manualmente de: https://chromedriver.chromium.org/"
fi

# Verifica instalação do Google Chrome
if command -v google-chrome &> /dev/null || command -v chromium-browser &> /dev/null || command -v /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome &> /dev/null; then
    echo "✅ Navegador Chrome encontrado"
else
    echo "⚠️  Navegador Chrome não encontrado. Instale Google Chrome:"
    echo "   macOS: brew install --cask google-chrome"
    echo "   Ou baixe do site oficial: https://www.google.com/chrome/"
    echo ""
    echo "📝 Nota: O script funcionará mesmo sem Chrome, mas pode ter limitações"
fi

# Desativa ambiente virtual
deactivate

echo ""
echo "🎉 Instalação concluída!"
echo ""
echo "📖 Como usar:"
echo "   # Ative o ambiente virtual:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo "   # Execute o script:"
echo "   python scrape_globoplay_episodes.py"
echo ""
echo "   # Desative o ambiente virtual quando terminar:"
echo "   deactivate"
echo ""
echo "📁 Arquivos gerados:"
echo "   - globoplay_episodes.json (dados completos)"
echo "   - globoplay_episodes.csv (formato CSV)"
echo ""
echo "⚙️  O script irá:"
echo "   - Abrir o navegador em modo headless"
echo "   - Simular scroll infinito na página"
echo "   - Extrair todos os links de episódios"
echo "   - Salvar os dados em JSON e CSV"
echo ""
echo "🔧 Ambiente virtual criado em: $VENV_DIR"
echo "   Para removê-lo: rm -rf $VENV_DIR"
