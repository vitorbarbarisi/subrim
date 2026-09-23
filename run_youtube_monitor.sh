#!/bin/bash

# Wrapper para rodar o youtube_monitor.py via cron.
# Ativa o ambiente virtual dedicado e propaga o código de saída.
# Uso: ./run_youtube_monitor.sh [argumentos extras para youtube_monitor.py]

VENV_DIR="youtube_monitor_env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/$VENV_DIR"

if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Ambiente virtual não encontrado em: $VENV_PATH"
    echo "💡 Execute primeiro:"
    echo "   python3 -m venv $VENV_DIR"
    echo "   source $VENV_DIR/bin/activate && pip install -r requirements-youtube-monitor.txt"
    exit 1
fi

source "$VENV_PATH/bin/activate"

if [ $? -ne 0 ]; then
    echo "❌ Erro ao ativar ambiente virtual"
    exit 1
fi

cd "$SCRIPT_DIR"
python3 youtube_monitor.py "$@"
EXIT_CODE=$?

deactivate

exit $EXIT_CODE
