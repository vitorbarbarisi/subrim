# Guia de Transcrição de Vídeo com Whisper

Este guia explica como transcrever vídeos em mandarim usando Whisper.

## Problema com Python 3.14

O `openai-whisper` requer `numba`, que ainda não suporta Python 3.14. Se você está usando Python 3.14, use uma das alternativas abaixo.

## Opções de Instalação

### Opção 1: Usar Python 3.13 (Recomendado)

1. Instale Python 3.13 via Homebrew:
```bash
brew install python@3.13
```

2. Crie um ambiente virtual com Python 3.13:
```bash
python3.13 -m venv whisper_env
source whisper_env/bin/activate
pip install openai-whisper
```

3. Execute o script:
```bash
source whisper_env/bin/activate
python3 transcribe_video.py roseki01-1 --model medium --language zh
```

### Opção 2: Usar Docker

1. Instale Docker (se ainda não tiver)

2. Execute o script Docker:
```bash
./transcribe_video_docker.sh roseki01-1 medium zh
```

### Opção 3: Usar Whisper via pipx

1. Instale pipx:
```bash
brew install pipx
```

2. Instale whisper via pipx:
```bash
pipx install openai-whisper
```

3. Execute o script (ele detectará o whisper CLI automaticamente)

## Uso do Script

```bash
python3 transcribe_video.py <directory_name> [--model MODEL] [--language LANGUAGE]
```

### Parâmetros

- `directory_name`: Nome do diretório em `assets/` (ex: `roseki01-1`)
- `--model`: Modelo Whisper a usar (tiny, base, small, medium, large). Padrão: `medium`
- `--language`: Código de idioma (zh para chinês). Padrão: `zh`

### Exemplo

```bash
python3 transcribe_video.py roseki01-1 --model medium --language zh
```

## Saída

O script gera um arquivo `.zht.srt` no mesmo diretório do vídeo:
- `assets/roseki01-1/[nome_do_video].zht.srt`

## Modelos Disponíveis

- `tiny`: Mais rápido, menor precisão
- `base`: Balanceado
- `small`: Boa qualidade
- `medium`: Alta qualidade (recomendado para mandarim)
- `large`: Melhor qualidade, mais lento

## Troubleshooting

### Erro: "Cannot install on Python version 3.14"

Use Python 3.13 ou anterior, ou use Docker/pipx.

### Erro: "Whisper não está instalado"

Instale o whisper usando uma das opções acima.

### Erro: "Nenhum arquivo MP4 encontrado"

Certifique-se de que há um arquivo `.mp4` no diretório `assets/<directory_name>/`.

