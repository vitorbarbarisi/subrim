#!/bin/bash
# Script para transcrever vídeo usando Whisper via Docker
# Uso: ./transcribe_video_docker.sh roseki01-1 [model] [language]

DIRECTORY=$1
MODEL=${2:-medium}
LANGUAGE=${3:-zh}

if [ -z "$DIRECTORY" ]; then
    echo "❌ Uso: $0 <directory_name> [model] [language]"
    echo "   Exemplo: $0 roseki01-1 medium zh"
    exit 1
fi

ASSETS_DIR="assets/$DIRECTORY"
if [ ! -d "$ASSETS_DIR" ]; then
    echo "❌ Diretório não encontrado: $ASSETS_DIR"
    exit 1
fi

# Find video file
VIDEO_FILE=$(find "$ASSETS_DIR" -name "*.mp4" | head -1)
if [ -z "$VIDEO_FILE" ]; then
    echo "❌ Nenhum arquivo MP4 encontrado em $ASSETS_DIR"
    exit 1
fi

echo "📹 Vídeo encontrado: $(basename "$VIDEO_FILE")"
echo "🤖 Usando modelo Whisper: $MODEL"
echo "🌐 Idioma: $LANGUAGE"

# Run Whisper via Docker
docker run --rm -it \
    -v "$(pwd)/$ASSETS_DIR:/workspace" \
    -w /workspace \
    onerahmet/openai-whisper-asr-webservice:latest-gpu \
    whisper "$(basename "$VIDEO_FILE")" \
    --model "$MODEL" \
    --language "$LANGUAGE" \
    --output_format srt

# Rename output file
VIDEO_STEM=$(basename "$VIDEO_FILE" .mp4)
OUTPUT_SRT="$ASSETS_DIR/${VIDEO_STEM}.zht.srt"
if [ -f "$ASSETS_DIR/${VIDEO_STEM}.srt" ]; then
    mv "$ASSETS_DIR/${VIDEO_STEM}.srt" "$OUTPUT_SRT"
    echo "✅ Arquivo gerado: $OUTPUT_SRT"
else
    echo "❌ Arquivo SRT não foi gerado"
    exit 1
fi

