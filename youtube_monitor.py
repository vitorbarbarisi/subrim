#!/usr/bin/env python3
"""
Monitor de canais do YouTube: a cada execução, verifica os canais listados em
youtube_channels.json e baixa localmente os vídeos publicados dentro da
janela configurada (lookback_hours, por padrão maior que o intervalo do
cron). Feito para rodar sem supervisão via cron (ver run_youtube_monitor.sh),
mas funciona igual rodando na mão.

Uso típico (cron, de hora em hora):
  python3 youtube_monitor.py

Uso para testar sem baixar nada:
  python3 youtube_monitor.py --dry-run -v

Uso para testar um canal específico com janela ampliada:
  python3 youtube_monitor.py --channel meu_canal --lookback-hours 24

Requisitos: yt-dlp no PATH (ou --yt-dlp-path) e cookies.txt exportado do
navegador logado no YouTube.
"""

import argparse
import fcntl
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO / "youtube_channels.json"
DEFAULT_STATE = REPO / "youtube_monitor_state.json"
LOCK_PATH = REPO / "youtube_monitor.lock"
DOWNLOADS_DIR = REPO / "assets" / "youtube_monitor_downloads"

# Fallback de formato: com ffmpeg, mescla o melhor vídeo+áudio disponíveis;
# sem ffmpeg, cai para um stream progressivo único (qualidade menor, mas sem
# dependência externa).
FORMAT_WITH_FFMPEG = (
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
)
FORMAT_NO_FFMPEG = "best[ext=mp4]/best"
# force_progressive com ffmpeg: tenta o progressivo primeiro (contorna o 403/SABR),
# mas cai para vídeo+áudio separados quando o vídeo não tem progressivo — o
# YouTube deixou de oferecer o formato 18 em muitos vídeos, e aí só o
# progressivo dava "Requested format is not available".
FORMAT_PROGRESSIVE_FIRST = (
    f"{FORMAT_NO_FFMPEG}/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio"
)

# Sem isso, um download travado numa conexão que para de responder (sem erro,
# sem dado novo) prende o processo pra sempre — e com ele o lock, bloqueando
# todas as execuções seguintes do cron. Aconteceu de verdade: uma execução
# ficou 6h30 presa num único vídeo.
DEFAULT_DOWNLOAD_TIMEOUT = 1200  # 20 min

# Extensões que nunca são "o vídeo baixado" — legendas e afins.
NON_VIDEO_SUFFIXES = {".part", ".ytdl", ".temp", ".srt", ".vtt", ".ttml", ".json3",
                       ".srv1", ".srv2", ".srv3"}


class ChannelListError(Exception):
    pass


class RateLimitedError(Exception):
    """O YouTube limitou a sessão (dura até ~1h). Insistir só prolonga o
    bloqueio — a execução inteira para e a próxima do cron tenta de novo."""


RATE_LIMIT_MARKERS = ("rate-limited", "HTTP Error 429")


def _is_rate_limited(text: str) -> bool:
    return any(m in (text or "") for m in RATE_LIMIT_MARKERS)


# --------------------------------------------------------------------------
# Utilidades de tempo / nomes
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _error_summary(stderr: str) -> str:
    """Linhas ERROR do yt-dlp; os WARNING (ex.: versão antiga) vêm antes e escondiam a causa."""
    errors = [ln.strip() for ln in stderr.splitlines() if ln.startswith("ERROR")]
    return " | ".join(dict.fromkeys(errors))[:500] or stderr.strip()[-300:] or "yt-dlp retornou erro sem detalhes"


def _format_age(delta: timedelta) -> str:
    total_minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h{minutes:02d}min"


def sanitize_name(name: str) -> str:
    """Normaliza um nome para uso seguro como diretório/arquivo/chave de estado."""
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    return name[:150] or "video"


# --------------------------------------------------------------------------
# Lock de execução única (protege contra sobreposição de execuções do cron)
# --------------------------------------------------------------------------

def acquire_lock(lock_path: Path):
    """Abre e trava lock_path com flock exclusivo não-bloqueante.

    Nunca apaga o arquivo de lock: sempre reabre o mesmo caminho e usa
    flock, que é liberado automaticamente pelo kernel quando o processo
    termina (mesmo em crash/SIGKILL) — não há lock "preso" para limpar.
    """
    lock_fh = open(lock_path, "a+")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fh.close()
        return None
    lock_fh.seek(0)
    lock_fh.truncate()
    lock_fh.write(f"pid={os.getpid()} started_at={now_iso()}\n")
    lock_fh.flush()
    return lock_fh


def release_lock(lock_fh) -> None:
    if lock_fh is None:
        return
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fh.close()


# --------------------------------------------------------------------------
# Config (youtube_channels.json)
# --------------------------------------------------------------------------

def load_channels_config(path: Path, required: bool = True) -> dict:
    if not path.exists():
        if not required:
            return {"defaults": {}, "channels": []}
        raise SystemExit(
            f"❌ Config não encontrada: {path}\n"
            f"   Copie youtube_channels.example.json para {path.name} e edite a lista de canais."
        )
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("defaults", {})
    cfg.setdefault("channels", [])
    return cfg


def save_channels_config(path: Path, cfg: dict) -> None:
    """Grava o config de forma atômica (tmp + replace): o cron pode ler o
    arquivo a qualquer momento e nunca deve pegar um JSON pela metade."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


PREFIX_RE = re.compile(r"^[A-Za-z0-9-]+$")


def is_valid_prefix(prefix: str) -> bool:
    """Prefixo de canal: letras, dígitos e hífen. Sem '_' — ele separa o
    prefixo do resto do nome do asset (``<prefixo>_<título>_<id>``)."""
    return bool(PREFIX_RE.match(prefix or ""))


def channel_prefixes(path: Path = DEFAULT_CONFIG) -> List[str]:
    """Prefixos não vazios dos canais do config (usado pelo upload ao Drive)."""
    try:
        cfg = load_channels_config(path, required=False)
    except Exception:
        return []
    return [c["prefix"] for c in cfg["channels"] if c.get("prefix")]


def channel_settings(cfg: dict, channel: dict) -> dict:
    defaults = cfg["defaults"]
    return {
        "lookback_hours": channel.get("lookback_hours") or defaults.get("lookback_hours", 2),
        "cookies_file": channel.get("cookies_file") or defaults.get("cookies_file", "cookies.txt"),
        "max_candidates_per_channel": (
            channel.get("max_candidates_per_channel")
            or defaults.get("max_candidates_per_channel", 20)
        ),
        "download_timeout_seconds": (
            channel.get("download_timeout_seconds")
            or defaults.get("download_timeout_seconds", DEFAULT_DOWNLOAD_TIMEOUT)
        ),
        # Códigos de idioma de legenda, em ordem de preferência (ex.: "zh-Hant,zh").
        # Vazio = não baixa legenda. Só pega legenda REAL (--write-subs, nunca
        # --write-auto-subs) — legenda auto-gerada não tem a qualidade necessária
        # para substituir a transcrição do Whisper.
        "sub_langs": channel.get("sub_langs") or defaults.get("sub_langs", ""),
        # Altura máxima do vídeo (ex.: 1080). 0/ausente = melhor disponível (pode
        # ser 4K — ~4x maior em disco sem ganho para queimar legenda).
        "max_height": int(channel.get("max_height") or defaults.get("max_height") or 0),
    }


# --------------------------------------------------------------------------
# Estado persistente (youtube_monitor_state.json)
# --------------------------------------------------------------------------

class MonitorState:
    """Estado de quais vídeos já foram vistos/baixados, por canal.

    status: pending -> downloaded (terminal), com "failed" alcançável a
    partir de uma falha de download. Só "downloaded" significa "nunca mais
    tocar" — "failed" é sempre reconsiderado na próxima execução.
    """

    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"⚠️  Falha ao ler {self.path.name}, iniciando estado vazio: {e}")
        return {"channels": {}}

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def channel(self, name: str) -> dict:
        return self.data["channels"].setdefault(name, {"last_checked": None, "videos": {}})

    def video_entry(self, channel_name: str, video_id: str) -> Optional[dict]:
        return self.channel(channel_name)["videos"].get(video_id)

    def upsert_video(self, channel_name: str, video_id: str, **fields) -> dict:
        ch = self.channel(channel_name)
        entry = ch["videos"].setdefault(video_id, {
            "title": None, "url": None, "uploaded_at": None,
            "status": "pending", "local_path": None, "subtitle_path": None,
            "attempts": 0, "last_error": None, "updated_at": None,
        })
        entry.update(fields)
        entry["updated_at"] = now_iso()
        return entry

    def set_last_checked(self, channel_name: str) -> None:
        self.channel(channel_name)["last_checked"] = now_iso()


# --------------------------------------------------------------------------
# yt-dlp: resolução do binário, listagem, detalhes, download
# --------------------------------------------------------------------------

def resolve_yt_dlp(configured_path: Optional[str]) -> Optional[str]:
    """Precedência: caminho configurado (--yt-dlp-path/config) > YT_DLP_PATH > PATH."""
    candidates = []
    if configured_path:
        candidates.append(configured_path)
    env_path = os.environ.get("YT_DLP_PATH")
    if env_path:
        candidates.append(env_path)
    which = shutil.which("yt-dlp")
    if which:
        candidates.append(which)

    for candidate in candidates:
        try:
            r = subprocess.run([candidate, "--version"], capture_output=True, text=True)
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            print(f"✅ yt-dlp {r.stdout.strip()} ({candidate})")
            return candidate
    return None


def check_ffmpeg() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


CHANNEL_ROOT_RE = re.compile(
    r"^(https?://(?:www\.|m\.)?youtube\.com/(?:@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+))/?$"
)


def channel_videos_url(channel_url: str) -> str:
    """Raiz do canal (``youtube.com/@handle``) → aba Vídeos (``.../videos``).

    Na raiz, o --flat-playlist devolve as abas do canal ("Videos", "Shorts")
    como entradas, não os vídeos — e o canal nunca teria candidatos.
    """
    m = CHANNEL_ROOT_RE.match(channel_url.strip())
    return f"{m.group(1)}/videos" if m else channel_url


def list_channel_video_ids(yt_bin: str, channel_url: str, max_candidates: int) -> List[str]:
    """Listagem barata via --flat-playlist (sem timestamp confiável)."""
    cmd = [yt_bin, "--flat-playlist", "--playlist-end", str(max_candidates), "-J",
           channel_videos_url(channel_url)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise ChannelListError("timeout ao listar vídeos do canal")
    if result.returncode != 0:
        raise ChannelListError(_error_summary(result.stderr))
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ChannelListError(f"saída inválida do yt-dlp: {e}")
    entries = data.get("entries") or []
    return [e["id"] for e in entries if e.get("id")]


def get_video_details(yt_bin: str, video_id: str, cookies_file: Path) -> Optional[dict]:
    """Extração completa de um vídeo específico, para obter a data real de publicação."""
    cmd = [
        yt_bin, "--cookies", str(cookies_file), "--skip-download", "-J",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print(f"   ⚠️  Timeout ao obter detalhes de {video_id}")
        return None
    if result.returncode != 0:
        if _is_rate_limited(result.stderr):
            raise RateLimitedError(f"ao obter detalhes de {video_id}")
        print(f"   ⚠️  Falha ao obter detalhes de {video_id}: {_error_summary(result.stderr)}")
        return None
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"   ⚠️  Saída inválida do yt-dlp para {video_id}")
        return None

    ts = info.get("timestamp")
    uploaded_at = None
    if ts:
        uploaded_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        upload_date = info.get("upload_date")
        if upload_date:
            try:
                uploaded_at = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                uploaded_at = None

    return {
        "id": info.get("id", video_id),
        "title": info.get("title") or video_id,
        "uploaded_at": uploaded_at,
        "webpage_url": info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
    }


def _run_streamed(cmd: List[str], timeout: float = DEFAULT_DOWNLOAD_TIMEOUT) -> bool:
    """Roda cmd espelhando stdout linha a linha, com um timeout de verdade.

    ``for line in proc.stdout`` sozinho bloqueia para sempre se o processo
    parar de produzir saída sem terminar (conexão travada) — usa select()
    para nunca esperar mais que ``timeout`` no total, e mata o processo se
    estourar.
    """
    print(f"      $ {' '.join(str(c) for c in cmd[:6])} …", flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    deadline = time.monotonic() + timeout
    rate_limited = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"   ❌ Timeout de {timeout:.0f}s excedido — encerrando processo travado")
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return False
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 5))
        if not ready:
            continue
        line = proc.stdout.readline()
        if line == "":
            break  # EOF — processo terminou
        print(f"      {line.rstrip()}", flush=True)
        rate_limited = rate_limited or _is_rate_limited(line)

    try:
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        print("   ❌ Processo não terminou após EOF do stdout — encerrando")
        proc.kill()
        proc.wait()
        return False
    if rc != 0:
        print(f"   ❌ yt-dlp encerrou com código {rc}")
        if rate_limited:
            raise RateLimitedError("durante o download")
    return rc == 0


def download_video(yt_bin: str, video_id: str, cookies_file: Path, out_template: Path,
                    download_format: str, has_ffmpeg: bool, sub_langs: str = "",
                    timeout: float = DEFAULT_DOWNLOAD_TIMEOUT, max_height: int = 0) -> bool:
    cmd = [
        yt_bin,
        "--cookies", str(cookies_file),
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "exp=1:5",
        "--sleep-requests", "1",
        # Pausa aleatória antes de cada vídeo: baixar um histórico inteiro em
        # sequência, sem intervalo, rendeu rate limit do YouTube após ~10 vídeos.
        "--sleep-interval", "5",
        "--max-sleep-interval", "15",
        "--throttled-rate", "100K",
        "--output", str(out_template),
        "--newline",
        "--no-warnings",
    ]
    cmd += ["--format", download_format]
    if max_height:
        # Ordenação, não filtro: o "best" dos seletores vira o melhor até
        # max_height; se o vídeo não tiver nada abaixo disso, pega o menor acima.
        cmd += ["-S", f"res:{max_height}"]
    if "+" in download_format:   # alguma alternativa mescla vídeo+áudio (ffmpeg)
        cmd += ["--merge-output-format", "mp4"]
    if sub_langs:
        # --write-subs (nunca --write-auto-subs): só legenda real do criador,
        # não a auto-gerada — essa não tem qualidade pra dispensar o Whisper.
        cmd += ["--write-subs", "--sub-langs", sub_langs, "--sub-format", "srt/best"]
        if has_ffmpeg:
            cmd += ["--convert-subs", "srt"]
    cmd.append(f"https://www.youtube.com/watch?v={video_id}")
    return _run_streamed(cmd, timeout=timeout)


def find_downloaded_file(local_dir: Path, prefix: str, video_id: str) -> Optional[Path]:
    matches = [
        p for p in local_dir.glob(f"{prefix}_{video_id}.*")
        if p.suffix not in NON_VIDEO_SUFFIXES
    ]
    return sorted(matches)[0] if matches else None


def select_and_normalize_subtitle(local_dir: Path, prefix: str, video_id: str,
                                   sub_langs: str) -> Optional[Path]:
    """Entre as legendas baixadas (uma por idioma pedido), fica só com a de
    maior prioridade em ``sub_langs`` e renomeia para ``<prefix>_<id>.zht.srt``
    — mesma convenção de nome que transcribe_video.py já usa para o resultado
    do Whisper, então o pipeline de transcrição aceita ela no lugar sem saber
    que veio do YouTube. Remove as legendas de idiomas alternativos baixadas
    a mais, se houver."""
    base = f"{prefix}_{video_id}"
    by_lang: Dict[str, Path] = {}
    for p in sorted(local_dir.glob(f"{base}.*.srt")):
        lang = p.name[len(base) + 1:-len(".srt")]
        by_lang[lang] = p

    chosen = None
    for lang in (l.strip() for l in sub_langs.split(",")):
        if lang in by_lang:
            chosen = by_lang.pop(lang)
            break

    for leftover in by_lang.values():
        try:
            leftover.unlink()
        except OSError:
            pass

    if chosen is None:
        return None
    target = local_dir / f"{base}.zht.srt"
    if chosen != target:
        chosen.replace(target)
    return target


def _check_disk_space(path: Path, min_free_gb: float) -> bool:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return True
    return (usage.free / (1024 ** 3)) >= min_free_gb


# --------------------------------------------------------------------------
# Seleção de vídeos a processar (janela de tempo + retries pendentes)
# --------------------------------------------------------------------------

def select_videos_to_process(state: MonitorState, channel_name: str, candidate_ids: List[str],
                              yt_bin: str, cookies_file: Path, lookback_hours: float,
                              verbose: bool = False) -> List[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    to_process: List[dict] = []
    seen_ids = set()

    for vid in candidate_ids:
        seen_ids.add(vid)
        entry = state.video_entry(channel_name, vid)

        if entry and entry.get("status") == "downloaded":
            if verbose:
                print(f"      · {vid} — já baixado, ignorando")
            continue

        if entry and entry.get("status") == "failed":
            # Já comprometido em uma execução anterior — sempre tenta de novo,
            # mesmo que tenha saído da janela de tempo nesse meio-tempo.
            if verbose:
                print(f"      · {vid} — tentativa anterior falhou, tentando de novo")
            to_process.append({
                "id": vid,
                "title": entry.get("title") or vid,
                "uploaded_at": _parse_iso(entry.get("uploaded_at")),
                "webpage_url": entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            })
            continue

        if entry and entry.get("uploaded_at"):
            # Já consultado antes: a data de publicação não muda, não pergunta
            # de novo ao YouTube (sem isso, todo candidato fora da janela era
            # consultado a cada execução do cron).
            details = {
                "id": vid,
                "title": entry.get("title") or vid,
                "uploaded_at": _parse_iso(entry.get("uploaded_at")),
                "webpage_url": entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            }
        else:
            details = get_video_details(yt_bin, vid, cookies_file)
            if details is None:
                continue  # falha transitória; a listagem vai trazê-lo de novo na próxima execução
            if details["uploaded_at"] is not None:
                state.upsert_video(
                    channel_name, vid, title=details["title"], url=details["webpage_url"],
                    uploaded_at=_iso(details["uploaded_at"]),
                )
        if details["uploaded_at"] is None:
            print(f"   ⚠️  Sem data de publicação confiável para {vid} — ignorando por segurança")
            continue
        if details["uploaded_at"] < cutoff:
            if verbose:
                age = _format_age(datetime.now(timezone.utc) - details["uploaded_at"])
                print(f"      · {vid} — fora da janela (publicado há {age}, limite {lookback_hours}h) — {details['title']}")
            continue
        if verbose:
            print(f"      · {vid} — dentro da janela — {details['title']}")
        to_process.append(details)

    # Recupera candidatos pendentes que saíram da lista desta rodada (canal
    # publicou muito, ou max_candidates_per_channel pequeno demais).
    for vid, entry in state.channel(channel_name)["videos"].items():
        if vid in seen_ids:
            continue
        if entry.get("status") == "failed":
            if verbose:
                print(f"      · {vid} — retry pendente fora da lista de candidatos desta rodada")
            to_process.append({
                "id": vid,
                "title": entry.get("title") or vid,
                "uploaded_at": _parse_iso(entry.get("uploaded_at")),
                "webpage_url": entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            })

    return to_process


# --------------------------------------------------------------------------
# Pipeline por vídeo / por canal
# --------------------------------------------------------------------------

def handle_video(channel_name: str, video: dict, yt_bin: str, cookies_file: Path,
                  download_format: str, has_ffmpeg: bool, sub_langs: str, download_timeout: float,
                  state: MonitorState, dry_run: bool, channel_prefix: str = "",
                  max_height: int = 0) -> None:
    vid = video["id"]
    entry = state.video_entry(channel_name, vid)
    if entry is None:
        entry = state.upsert_video(
            channel_name, vid,
            title=video.get("title"),
            url=video.get("webpage_url"),
            uploaded_at=_iso(video.get("uploaded_at")),
        )

    if entry["status"] == "downloaded":
        return

    if dry_run:
        print(f"   [dry-run] {channel_name}/{vid} — {video.get('title')} (status atual: {entry['status']})")
        return

    local_dir = DOWNLOADS_DIR / channel_name
    local_dir.mkdir(parents=True, exist_ok=True)
    # <prefixo do canal>_<título>: o prefixo agrupa os vídeos do canal (ex.: a
    # pasta videos/<prefixo> no Drive), como o "clone" dos assets clone40…
    stem = sanitize_name(video.get("title") or vid)
    if channel_prefix:
        stem = f"{channel_prefix}_{stem}"

    local_path = None
    if entry.get("local_path"):
        candidate = Path(entry["local_path"])
        if candidate.exists():
            local_path = candidate

    if local_path is not None:
        # Já baixado numa execução anterior (estado ficou "failed" por outro
        # motivo antes de ser marcado); nada mais a fazer.
        state.upsert_video(channel_name, vid, status="downloaded", local_path=str(local_path))
        state.save()
        return

    out_template = local_dir / f"{stem}_{vid}.%(ext)s"
    print(f"   ⬇️  Baixando {channel_name}/{vid} — {video.get('title')}")
    try:
        ok = download_video(yt_bin, vid, cookies_file, out_template, download_format, has_ffmpeg,
                             sub_langs=sub_langs, timeout=download_timeout, max_height=max_height)
    except RateLimitedError:
        # "failed" garante a nova tentativa numa próxima execução, mesmo fora da janela.
        state.upsert_video(
            channel_name, vid, status="failed",
            attempts=entry.get("attempts", 0) + 1, last_error="rate_limited",
        )
        state.save()
        raise
    found = find_downloaded_file(local_dir, stem, vid) if ok else None
    if not ok or found is None:
        state.upsert_video(
            channel_name, vid, status="failed",
            attempts=entry.get("attempts", 0) + 1, last_error="download_failed",
        )
        print(f"   ❌ Download falhou: {channel_name}/{vid}")
        state.save()
        return

    subtitle_path = None
    if sub_langs:
        subtitle_path = select_and_normalize_subtitle(local_dir, stem, vid, sub_langs)
        if subtitle_path:
            print(f"   📝 Legenda encontrada e reaproveitada: {subtitle_path.name}")

    state.upsert_video(
        channel_name, vid, status="downloaded", local_path=str(found),
        subtitle_path=str(subtitle_path) if subtitle_path else None, last_error=None,
    )
    state.save()
    print(f"   ✅ Baixado: {found.name}")


def process_channel(channel: dict, cfg: dict, state: MonitorState, yt_bin: str, download_format: str,
                     has_ffmpeg: bool, dry_run: bool, verbose: bool = False) -> bool:
    name = sanitize_name(channel["name"])
    settings = channel_settings(cfg, channel)
    cookies_file = Path(settings["cookies_file"])
    print(f"\n📺 Canal: {name}")

    try:
        candidate_ids = list_channel_video_ids(
            yt_bin, channel["url"], settings["max_candidates_per_channel"]
        )
    except ChannelListError as e:
        print(f"   ❌ Falha ao listar vídeos do canal: {e}")
        return False

    print(f"   🔎 {len(candidate_ids)} candidatos analisados (janela: {settings['lookback_hours']}h)")
    to_process = select_videos_to_process(
        state, name, candidate_ids, yt_bin, cookies_file, settings["lookback_hours"], verbose=verbose
    )

    if not to_process:
        print("   ✅ Nada novo dentro da janela configurada")
    for video in to_process:
        handle_video(name, video, yt_bin, cookies_file, download_format, has_ffmpeg,
                     settings["sub_langs"], settings["download_timeout_seconds"], state, dry_run,
                     channel_prefix=channel.get("prefix") or "",
                     max_height=settings["max_height"])

    if not dry_run:
        state.set_last_checked(name)
        state.save()
    return True


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Monitora canais do YouTube e baixa localmente os vídeos novos publicados.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="Caminho do JSON de canais (padrão: youtube_channels.json)")
    parser.add_argument("--state", default=str(DEFAULT_STATE),
                        help="Caminho do JSON de estado (padrão: youtube_monitor_state.json)")
    parser.add_argument("--cookies", help="Sobrescreve o cookies_file padrão de todos os canais")
    parser.add_argument("--lookback-hours", type=float,
                        help="Sobrescreve lookback_hours padrão de todos os canais")
    parser.add_argument("--max-candidates", type=int,
                        help="Sobrescreve max_candidates_per_channel padrão de todos os canais "
                             "(útil para baixar o histórico inteiro de um canal com --lookback-hours alto)")
    parser.add_argument("--sub-langs",
                        help="Sobrescreve sub_langs padrão de todos os canais (ex.: 'zh-Hant,zh'). "
                             "Baixa a legenda real (não auto-gerada) nesses idiomas, em ordem de "
                             "preferência, e reaproveita no lugar da transcrição via Whisper.")
    parser.add_argument("--max-height", type=int,
                        help="Altura máxima do vídeo (ex.: 1080); 0 = melhor disponível. "
                             "Sobrescreve max_height do config")
    parser.add_argument("--channel", action="append",
                        help="Restringe a execução a um canal (campo 'name' do config; repetível)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Lista o que seria baixado, sem tocar em disco ou no estado")
    parser.add_argument("--yt-dlp-path", help="Caminho do binário yt-dlp (padrão: procura no PATH)")
    parser.add_argument("--no-lock", action="store_true",
                        help="Pula o lock de execução única — uso manual apenas, nunca no cron")
    parser.add_argument("--force-progressive", action="store_true",
                        help="Prefere o formato progressivo (qualidade menor, mas contorna o "
                             "403/SABR que o bestvideo+bestaudio pode dar em algumas redes/versões "
                             "do yt-dlp); se o vídeo não tiver progressivo, cai para vídeo+áudio "
                             "separados")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log mais detalhado")
    args = parser.parse_args()

    lock_fh = None
    if not args.no_lock:
        lock_fh = acquire_lock(LOCK_PATH)
        if lock_fh is None:
            print("⚠️  Outra execução do youtube_monitor já está em andamento — saindo.")
            return 0

    try:
        cfg = load_channels_config(Path(args.config))
        if args.cookies:
            cfg["defaults"]["cookies_file"] = args.cookies
        if args.lookback_hours is not None:
            cfg["defaults"]["lookback_hours"] = args.lookback_hours
        if args.max_candidates is not None:
            cfg["defaults"]["max_candidates_per_channel"] = args.max_candidates
        if args.sub_langs is not None:
            cfg["defaults"]["sub_langs"] = args.sub_langs
        if args.max_height is not None:
            # Sobrescreve inclusive o max_height definido por canal.
            cfg["defaults"]["max_height"] = args.max_height
            for ch in cfg["channels"]:
                ch.pop("max_height", None)

        yt_bin = resolve_yt_dlp(args.yt_dlp_path or cfg["defaults"].get("yt_dlp_path"))
        if yt_bin is None:
            print("❌ yt-dlp não encontrado. Instale com: pip install yt-dlp")
            return 1

        force_progressive = args.force_progressive or bool(cfg["defaults"].get("force_progressive"))
        has_ffmpeg = check_ffmpeg()
        if not has_ffmpeg:
            download_format = FORMAT_NO_FFMPEG
            print("⚠️  ffmpeg não encontrado — downloads ficarão limitados a streams progressivos.")
            print("   Instale com: sudo apt install ffmpeg")
        elif force_progressive:
            download_format = FORMAT_PROGRESSIVE_FIRST
            print("ℹ️  Progressivo preferido (--force-progressive/config); sem ele, "
                  "cai para vídeo+áudio separados.")
        else:
            download_format = FORMAT_WITH_FFMPEG

        channels = [c for c in cfg["channels"] if c.get("enabled", True)]
        if args.channel:
            wanted = set(args.channel)
            channels = [c for c in channels if c.get("name") in wanted]
            missing = wanted - {c.get("name") for c in channels}
            if missing:
                print(f"⚠️  Canais não encontrados no config ou desabilitados: {', '.join(sorted(missing))}")

        if not channels:
            print("⚠️  Nenhum canal habilitado para processar.")
            return 0

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        state = MonitorState(Path(args.state))

        # Checa uma vez por caminho de cookies (evita repetir o mesmo aviso por canal).
        cookies_paths: Dict[Path, List[str]] = {}
        for channel in channels:
            cf = Path(channel.get("cookies_file") or cfg["defaults"].get("cookies_file", "cookies.txt"))
            cookies_paths.setdefault(cf, []).append(channel.get("name"))
        missing_cookies = (
            {cf: names for cf, names in cookies_paths.items() if not cf.exists()}
            if not args.dry_run else {}
        )
        for cf, names in missing_cookies.items():
            print(f"❌ cookies_file '{cf}' não encontrado — afeta os canais: {', '.join(names)}")
        if missing_cookies and len(missing_cookies) == len(cookies_paths):
            print("❌ Nenhum canal pode ser processado sem cookies.txt válido — abortando execução.")
            return 1

        print(f"\n🕐 Início: {now_iso()}  |  canais habilitados: {len(channels)}")

        any_channel_failed = False
        for channel in channels:
            if not channel.get("url"):
                print(f"   ⚠️  Canal '{channel.get('name')}' sem 'url' no config — pulando")
                any_channel_failed = True
                continue
            cf = Path(channel.get("cookies_file") or cfg["defaults"].get("cookies_file", "cookies.txt"))
            if cf in missing_cookies:
                any_channel_failed = True
                continue
            if not _check_disk_space(DOWNLOADS_DIR, cfg["defaults"].get("min_free_disk_gb", 2)):
                print(f"   ⚠️  Espaço em disco abaixo do mínimo configurado — pulando canal '{channel.get('name')}'")
                any_channel_failed = True
                continue
            try:
                ok = process_channel(channel, cfg, state, yt_bin, download_format, has_ffmpeg,
                                     args.dry_run, verbose=args.verbose)
            except RateLimitedError as e:
                state.save()
                print(f"\n⛔ YouTube limitou a sessão ({e}) — encerrando esta execução; "
                      "a próxima tenta de novo (o bloqueio dura até ~1h).")
                any_channel_failed = True
                break
            any_channel_failed = any_channel_failed or not ok

        print(f"\n🏁 Fim: {now_iso()}")
        return 1 if any_channel_failed else 0
    finally:
        release_lock(lock_fh)


if __name__ == "__main__":
    sys.exit(main())
