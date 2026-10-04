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
    "min_free_disk_gb": 2,
    "force_progressive": false,
    "download_timeout_seconds": 1200,
    "sub_langs": ""
  },
  "channels": [
    {
      "name": "meu_canal",
      "url": "https://www.youtube.com/@meucanal/videos",
      "prefix": "meucanal",
      "enabled": true
    }
  ]
}
```
- `name` vira o nome da subpasta dentro de
  `assets/youtube_monitor_downloads/` — evite espaços e caracteres especiais.
- `prefix`: prefixo dos arquivos baixados — o vídeo sai como
  `<prefix>_<título>_<id>.mp4` e, depois de transcrito, vira o asset
  `<prefix>_…`. No upload ao Drive (merge_chunks.py), assets que começam com
  `<prefix>_` de algum canal vão para `videos/<prefix>` (como `clone40` →
  `videos/clone`). Só letras, números e hífen — sem `_`. Sem prefixo, o nome
  fica `<título>_<id>` como antes.
- `enabled`: `false` faz o monitor pular o canal.
- `url` deve apontar para a aba **Vídeos** do canal (`/videos` no final), não
  para a página inicial do canal.
- `lookback_hours` maior que o intervalo do cron (padrão 1h) dá folga contra
  execuções atrasadas, execuções que falharam e vídeos publicados bem na
  borda da hora.
- `download_timeout_seconds` (padrão 1200 = 20min): tempo máximo por
  download antes de matar o processo e marcar como falha — protege contra
  um yt-dlp travado numa conexão que nunca erra nem progride (ver seção
  "Proteção" abaixo).
- `sub_langs` (padrão vazio = desativado): ver seção "Legendas" abaixo.
- `max_height` (padrão vazio = melhor disponível): altura máxima do vídeo,
  ex.: `1080`. Sem limite, muitos canais vêm em 4K (~4x maior em disco, sem
  ganho para queimar legenda). `--max-height` sobrescreve na linha de comando.
- Baixar o histórico inteiro de um canal:
  `python3 youtube_monitor.py --channel <nome> --lookback-hours 1000000 --max-candidates 1000`.
  Há pausa de 5–15s entre vídeos; se o YouTube limitar a sessão ("rate-limited"),
  a execução para, os vídeos pendentes ficam como `failed` e o cron retoma
  sozinho nas próximas horas.
- Qualquer campo de `defaults` pode ser sobrescrito por canal (ex.: um canal
  com cookies próprios: adicione `"cookies_file": "outro_cookies.txt"` no
  item do canal).

## 📋 Como usar

### Gerenciar canais pela interface

No subrim_manager, aba **Downloads & Scraping**, a seção **YouTube Monitor**
edita este mesmo JSON: `+` adiciona canal, `−` remove (com confirmação),
duplo clique no prefixo edita e clique em "Ativo" liga/desliga. Cada mudança
é gravada na hora, e a próxima execução do cron já usa o estado novo.

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

## 📝 Legendas (reaproveitar em vez de transcrever)

Quando o canal já tem legenda real (feita pelo criador, não auto-gerada)
num idioma que interessa, configurar `sub_langs` baixa essa legenda junto
com o vídeo em vez de depender só da transcrição via Whisper depois — mais
rápido e, sendo legenda de verdade, geralmente mais precisa.

```json
{ "name": "meu_canal_com_legenda", "url": "...", "sub_langs": "zh-Hant,zh" }
```

`sub_langs` é uma lista de códigos de idioma em ordem de prioridade — baixa
só a primeira que existir (nunca a legenda auto-gerada, que não tem
qualidade suficiente). A legenda baixada é salva como
`<vídeo>.zht.srt` ao lado do `.mp4`, a mesma convenção de nome que
`transcribe_video.py` já usa para o resultado do Whisper — então
`transcribe_asset.py`/`transcribe_video.py` reconhecem e **pulam a
transcrição automaticamente** quando esse arquivo já existe. Para checar
quais idiomas um vídeo realmente tem disponível:
```bash
yt-dlp --list-subs "https://www.youtube.com/watch?v=<id>"
```
(procure a seção "Available subtitles", não "Available automatic
captions" — essa segunda é só a lista de tradução automática do YouTube,
não legenda de verdade.)

## 🔒 Proteção contra execuções sobrepostas e travamentos

O script usa `flock` num arquivo de lock (`youtube_monitor.lock`) para
garantir que só uma execução roda por vez — se uma ainda estiver em
andamento, a próxima chamada do cron simplesmente sai (código 0, não é
erro) em vez de rodar em paralelo. Para testes manuais onde isso atrapalha,
use `--no-lock` (nunca no cron).

Cada download individual também tem um **timeout** (`download_timeout_seconds`,
padrão 20min) — sem isso, um yt-dlp que trava numa conexão que para de
responder (sem erro, sem progresso) prendia o processo pra sempre, e com
ele o lock, travando todas as execuções seguintes do cron indefinidamente
(já aconteceu: uma execução ficou 6h30 presa num único vídeo). Se isso
acontecer mesmo com o timeout, o vídeo é marcado `"failed"` e tentado de
novo na próxima execução, como qualquer outra falha.

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
