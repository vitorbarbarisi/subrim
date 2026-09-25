#!/bin/bash

# Wrapper para rodar o youtube_monitor.py via cron.
# Ativa o ambiente virtual dedicado se existir (opcional: o script não tem
# dependências pip desde que o upload para o Drive foi removido — só precisa
# do binário yt-dlp). Propaga o código de saída.
# Uso: ./run_youtube_monitor.sh [argumentos extras para youtube_monitor.py]

# Cron roda com um PATH mínimo (sem /opt/homebrew/bin, /usr/local/bin etc.),
# então python3/ffmpeg podem não ser encontrados mesmo estando instalados.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH:/usr/bin:/bin:/usr/sbin:/sbin"

VENV_DIR="youtube_monitor_env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/$VENV_DIR"

if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    if [ $? -ne 0 ]; then
        echo "❌ Erro ao ativar ambiente virtual em $VENV_PATH"
        exit 1
    fi
fi

cd "$SCRIPT_DIR"
python3 youtube_monitor.py "$@"
EXIT_CODE=$?

if [ -d "$VENV_PATH" ]; then
    deactivate
fi

exit $EXIT_CODE
