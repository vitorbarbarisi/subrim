# 📺 YouTube Channel Monitor

Roda de hora em hora (via cron), verifica uma lista de canais do YouTube e
baixa localmente os vídeos publicados dentro da janela configurada. Feito
para rodar sem supervisão numa máquina Linux, sem duplicar downloads entre
execuções.

## 🚀 Instalação

### 1. Ambiente virtual e dependências
```bash
python3 -m venv youtube_monitor_env
source youtube_monitor_env/bin/activate
pip install -r requirements-youtube-monitor.txt
deactivate
```

### 2. ffmpeg (opcional, recomendado)
Sem `ffmpeg`, os downloads ficam limitados a streams progressivos (qualidade
menor, geralmente até 720p). Com `ffmpeg`, o script mescla o melhor
vídeo+áudio disponíveis.
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 3. cookies.txt
O YouTube às vezes bloqueia download automatizado sem indício de sessão
logada (detecção de bot). Como a máquina do cron não tem um navegador
logado, exporte os cookies do seu navegador para um arquivo `cookies.txt`
(formato Netscape) — por exemplo com a extensão "Get cookies.txt LOCALLY"
(Chrome/Firefox), estando logado no youtube.com. Salve o arquivo como
`cookies.txt` na raiz do repositório (ou aponte outro caminho via
`cookies_file` no config / `--cookies`).

Os cookies expiram — se os downloads começarem a falhar com erros de
autenticação/"confirm you're not a bot", reexporte o arquivo.

**`cookies.txt` é uma credencial: nunca versione esse arquivo** (já está no
`.gitignore`).

### 4. Lista de canais
```bash
cp youtube_channels.example.json youtube_channels.json
```
Edite `youtube_channels.json`:
```json
{
  "defaults": {
    "lookback_hours": 2,
    "cookies_file": "cookies.txt",
    "max_candidates_per_channel": 20,
    "yt_dlp_path": "yt-dlp",
    "min_free_disk_gb": 2
  },
  "channels": [
    {
      "name": "meu_canal",
      "url": "https://www.youtube.com/@meucanal/videos",
      "enabled": true
    }
  ]
}
```
- `name` vira o nome da subpasta dentro de
  `assets/youtube_monitor_downloads/` — evite espaços e caracteres especiais.
- `url` deve apontar para a aba **Vídeos** do canal (`/videos` no final), não
  para a página inicial do canal.
- `lookback_hours` maior que o intervalo do cron (padrão 1h) dá folga contra
  execuções atrasadas, execuções que falharam e vídeos publicados bem na
  borda da hora.
- Qualquer campo de `defaults` pode ser sobrescrito por canal (ex.: um canal
  com cookies próprios: adicione `"cookies_file": "outro_cookies.txt"` no
  item do canal).

## 📋 Como usar

### Testar sem baixar nada
```bash
python3 youtube_monitor.py --dry-run -v
```
Mostra quais vídeos seriam baixados (e por quê) sem tocar em disco ou no
arquivo de estado.

### Testar um canal específico com janela ampliada
Útil para validar de ponta a ponta sem esperar uma publicação recente:
```bash
python3 youtube_monitor.py --channel meu_canal --lookback-hours 24
```
Confirme: o arquivo aparece em
`assets/youtube_monitor_downloads/meu_canal/`; `youtube_monitor_state.json`
mostra `"status": "downloaded"` para o vídeo.

### Execução manual (igual ao cron)
```bash
./run_youtube_monitor.sh
```

## ⏰ Agendando no cron

```bash
crontab -e
```
Adicione (ajuste o caminho para onde o repositório vive na máquina Linux):
```
0 * * * * /home/<usuario>/subrim/run_youtube_monitor.sh >> /home/<usuario>/subrim/logs/youtube_monitor.log 2>&1
```

O diretório `logs/` é criado automaticamente na primeira execução se não
existir (crie-o manualmente com `mkdir -p logs` se preferir rodar antes de
agendar). Como o cron só concatena no arquivo de log para sempre, vale
rotacionar — um `logrotate` simples resolve:
```
# /etc/logrotate.d/youtube_monitor
/home/<usuario>/subrim/logs/youtube_monitor.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

## 🔒 Proteção contra execuções sobrepostas

O script usa `flock` num arquivo de lock (`youtube_monitor.lock`) para
garantir que só uma execução roda por vez — se um download demorar mais de
1h, a próxima chamada do cron simplesmente sai (código 0, não é erro) em vez
de rodar em paralelo. Para testes manuais onde isso atrapalha, use
`--no-lock` (nunca no cron).

## 🩺 Diagnóstico

- **Código de saída 0**: tudo certo (ou nada novo para baixar).
- **Código de saída 1**: pelo menos um canal falhou (URL inválida, cookies
  ausentes, disco cheio) — outros canais continuam sendo processados.
- Vídeo que falhou no download fica marcado `"status": "failed"` em
  `youtube_monitor_state.json` e é tentado de novo automaticamente na
  próxima execução — não precisa de intervenção manual.
- Os vídeos baixados ficam permanentemente em
  `assets/youtube_monitor_downloads/<canal>/` — o script não apaga nada;
  gerenciar espaço em disco (mover, arquivar, limpar) é responsabilidade de
  quem opera o cron.

## Dependências
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — listagem e download.
- `ffmpeg` (opcional) — mescla vídeo+áudio em melhor qualidade.
