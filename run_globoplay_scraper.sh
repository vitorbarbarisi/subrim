#!/bin/bash

# Script wrapper para executar o scraper do Globo Play
# Ativa automaticamente o ambiente virtual e executa o script
# Uso: ./run_globoplay_scraper.sh [URL] [OUTPUT_NAME] [INTERACTION_TIME]

VENV_DIR="globoplay_scraper_env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/$VENV_DIR"

# Valores padrão
DEFAULT_URL="https://globoplay.globo.com/v/13385190/?s=0s"
DEFAULT_OUTPUT="globoplay_episodes"
DEFAULT_INTERACTION_TIME=60

# Processa parâmetros
URL="${1:-$DEFAULT_URL}"
OUTPUT_NAME="${2:-$DEFAULT_OUTPUT}"
INTERACTION_TIME="${3:-$DEFAULT_INTERACTION_TIME}"

echo "🎬 Iniciando Globo Play Scraper..."
echo "📍 URL: $URL"
echo "📁 Output: $OUTPUT_NAME"
echo "⏱️  Tempo de interação: ${INTERACTION_TIME}s"

# Validações básicas
if [ -z "$URL" ]; then
    echo "❌ URL não pode ser vazia"
    echo "💡 Uso: $0 [URL] [OUTPUT_NAME]"
    exit 1
fi

if [ -z "$OUTPUT_NAME" ]; then
    echo "❌ Nome do output não pode ser vazio"
    echo "💡 Uso: $0 [URL] [OUTPUT_NAME]"
    exit 1
fi

# Verifica se o ambiente virtual existe
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Ambiente virtual não encontrado em: $VENV_PATH"
    echo "💡 Execute primeiro: ./install_dependencies.sh"
    exit 1
fi

# Verifica se o script Python existe
if [ ! -f "$SCRIPT_DIR/scrape_globoplay_episodes.py" ]; then
    echo "❌ Script Python não encontrado: $SCRIPT_DIR/scrape_globoplay_episodes.py"
    exit 1
fi

# Ativa o ambiente virtual
echo "🔄 Ativando ambiente virtual..."
source "$VENV_PATH/bin/activate"

if [ $? -ne 0 ]; then
    echo "❌ Erro ao ativar ambiente virtual"
    exit 1
fi

# Executa o script Python em modo visual com parâmetros
echo "🚀 Executando scraper em modo VISUAL..."
cd "$SCRIPT_DIR"
python scrape_globoplay_episodes.py --url "$URL" --output "$OUTPUT_NAME" --interaction-time "$INTERACTION_TIME"

# Salva o código de saída
EXIT_CODE=$?

# Desativa o ambiente virtual
deactivate

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ Scraper executado com sucesso!"
    echo "📁 Verifique os arquivos gerados:"
    echo "   - ${OUTPUT_NAME}.json"
    echo "   - ${OUTPUT_NAME}.csv"
    echo ""
    echo "🎯 Parâmetros utilizados:"
    echo "   URL: $URL"
    echo "   Output: $OUTPUT_NAME"
    echo "   Tempo de interação: ${INTERACTION_TIME}s"
else
    echo ""
    echo "❌ Erro durante execução (código: $EXIT_CODE)"
    echo "💡 Verifique os logs acima para detalhes"
fi

exit $EXIT_CODE
