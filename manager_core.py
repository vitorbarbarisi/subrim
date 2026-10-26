"""Camada de dados do Subrim Manager — roda no SERVIDOR (subrim_server.py).

O manager (subrim_manager.py) virou só client: tudo o que lê ou grava no
repositório (assets/, warehouse/, logs, configs) mora aqui e é chamado pela
rede via ``subrim_remote.RemoteModule("manager_core")``. As funções públicas
(sem ``_``) são as que o servidor aceita chamar; o client importa daqui apenas
os utilitários puros (``PHASES``, ``wh_readable_name``, ``natural_key``).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import word_vocab
import youtube_monitor as ytm

# ─── Paths ─────────────────────────────────────────────────────────────────────
REPO      = Path(__file__).absolute().parent
ASSETS    = REPO / "assets"
SOURCE    = ASSETS / "source"
TEXTS     = ASSETS / "text"          # txt do modo Texto (um arquivo = um asset)
WAREHOUSE = REPO / "warehouse"
TEXT_WAREHOUSE = WAREHOUSE / "text"  # bases gerados pelo text_pipeline.py
FRAMES    = WAREHOUSE / "frames"   # cache de frames de episódios arquivados
FRAMES_PERIODS = WAREHOUSE / "frames_periods"   # idem, arquivados por período
DEEPSEEK_LOG = REPO / "deepseek_debug.log"


def _wh_frames_dir(prefix: str) -> Path | None:
    """Cache de frames do episódio — o de períodos tem precedência. None se não há."""
    for d in (FRAMES_PERIODS / prefix, FRAMES / prefix):
        if d.is_dir() and next(d.glob("line*.jpg"), None) is not None:
            return d
    return None


def _wh_is_archived(prefix: str) -> bool:
    """True se o episódio foi arquivado (sem mp4, mas com cache de frames)."""
    return _wh_frames_dir(prefix) is not None


def mount_roots() -> list:
    """Onde os HDs externos aparecem neste sistema.

    macOS: /Volumes. Linux: /media/<usuário> e /run/media/<usuário> (montagem
    automática) e /mnt — no WSL, os discos do Windows ficam em /mnt/<letra>."""
    if sys.platform == "darwin":
        return [Path("/Volumes")]
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    roots = [Path("/mnt")]
    if user:
        roots += [Path("/media") / user, Path("/run/media") / user]
    return roots


# Pastas de /mnt que o WSL usa para si, não são discos.
_NOT_DRIVES = {"wsl", "wslg"}


def _external_drives() -> list:
    """HDs externos graváveis montados (ordem alfabética).

    Exclui o disco de boot (mesmo device de "/", ex.: "Macintosh HD"), volumes
    somente-leitura (imagens .dmg montadas) e, no WSL, o disco do Windows
    (o C:, que também aparece em /mnt)."""
    root_dev = os.stat("/").st_dev
    out = []
    for root in mount_roots():
        try:
            vols = sorted(root.iterdir())
        except OSError:
            continue
        for v in vols:
            if v.name in _NOT_DRIVES:
                continue
            try:
                if not v.is_dir() or v.stat().st_dev == root_dev:
                    continue
                if os.statvfs(v).f_flag & os.ST_RDONLY:
                    continue
                if (v / "Windows" / "System32").is_dir():
                    continue
            except OSError:
                continue
            out.append(v)
    return out


def _wh_readable_name(stem: str) -> str:
    """Converte 'amor80_base' → 'Amor 80', 'Death_Becomes_Her_base' → 'Death Becomes Her'."""
    name = stem.replace("_base", "").replace("_", " ").strip()
    # separa letras de dígitos colados: 'amor80' → 'amor 80'
    name = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", name)
    name = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", name)
    return name.title()


# Assinaturas de canal no nome que não trazem o "@<canal>" do YouTube.
_WH_SIGNATURES = {"公視": "pts"}


def _wh_channel_rules():
    """(prefixos, assinaturas) dos canais do YouTube Monitor, para agrupar.

    Assinatura = "@<nome do canal>" → prefixo (ex.: "@TVBSNEWS01" → "tvbs")."""
    try:
        cfg = ytm.load_channels_config(ytm.DEFAULT_CONFIG, required=False)
    except Exception:  # noqa: BLE001
        return [], dict(_WH_SIGNATURES)
    prefixes, signatures = [], {}
    for c in cfg.get("channels", []):
        p = c.get("prefix")
        if not p:
            continue
        prefixes.append(p)
        if c.get("name"):
            signatures[f"@{c['name']}"] = p
    signatures.update(_WH_SIGNATURES)
    return prefixes, signatures


def _wh_group_keys(stems: list, prefixes: list, signatures: dict) -> dict:
    """Grupo de cada stem (sem "_base") da lista do Warehouse; None = "Outros".

    Ordem das regras: prefixo de canal explícito ("acquiring_…"), assinatura do
    canal no nome ("@TVBSNEWS01", "公視"), letras + número ("clone100" → "clone")
    e, por fim, série com sufixo numérico compartilhada por ≥2 itens
    ("Cinco_Relacionamento_Confucio_1/_2")."""
    out, series = {}, {}
    for stem in stems:
        key = next((p.lower() for p in prefixes if stem.startswith(f"{p}_")), None)
        if key is None:
            key = next((p.lower() for sig, p in signatures.items() if sig in stem), None)
        if key is None:
            m = re.match(r"([A-Za-z]+)\d", stem)
            if m:
                key = m.group(1).lower()
        if key is None:
            base = re.sub(r"[_ ]?\d+$", "", stem)
            if base != stem and base:
                series.setdefault(base, []).append(stem)
        out[stem] = key
    for base, members in series.items():
        if len(members) >= 2:
            for stem in members:
                out[stem] = base
    return out


def _natural_key(s: str):
    """Ordenação natural: 'Clone 37' antes de 'Clone 100'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _wh_group_list(stems: list) -> list:
    """Stems (sem "_base") agrupados como na lista do Warehouse.

    Devolve ``[(key, nome, [stems])]``: grupos por nome, "Outros" (key None)
    por último; dentro do grupo, ordem natural do nome legível."""
    prefixes, signatures = _wh_channel_rules()
    keys = _wh_group_keys(stems, prefixes, signatures)
    groups: dict = {}
    for stem in stems:
        groups.setdefault(keys[stem], []).append(stem)
    order = sorted(groups, key=lambda k: (k is None,
                                          _wh_readable_name(k).lower() if k else ""))
    return [(k, _wh_readable_name(k) if k else "Outros",
             sorted(groups[k], key=lambda s: _natural_key(_wh_readable_name(s))))
            for k in order]


# Uma "palavra" precisa ter ao menos um caractere com conteúdo (CJK, letra ou
# dígito). Sem isso, pontuação solta que sobra do parsing entrava na tabela
# como se fosse vocabulário. A regra mora no word_vocab, que é o módulo comum
# a esta tela e ao registro em sanitize_base: filtrar só aqui escondia o lixo
# da tabela, mas continuava mandando-o para a API.


def _wh_split_items(arr: str) -> list:
    """Itens de um array de pares do base, tolerante a arrays malformados.

    O array é escrito com f-string à mão (não ``json.dumps``), então há duas
    malformações reais no corpus, e cada uma quebra uma estratégia diferente:

    - tradução com aspa — ``["「 (「): "", "嘰嘰喳喳 (jī ji zhā zhā): tagarelice", …]``
      — varrer pares de aspas dessincroniza e perde tudo depois do primeiro item;
      dividir pelo separador ``", "`` acerta.
    - aspa fechando cedo — ``… "佔 (zhàn)": pegar, "便宜 (pián yi)": vantagem]`` —
      aí é o inverso: o separador não aparece entre os dois últimos pares, então o
      split junta ambos num item e perde uma palavra; varrer aspas acerta.

    Como nenhuma domina, geramos as duas e ficamos com a que rende mais itens
    aproveitáveis. Perder palavra chinesa num contador de vocabulário é o pior
    resultado possível, então vale o custo de parsear duas vezes.
    """
    arr = arr.strip()
    if not arr.startswith("["):
        return []
    try:
        data = json.loads(arr)
        if isinstance(data, list):
            return [str(x) for x in data]
    except Exception:  # noqa: BLE001 - array malformado é o caso comum aqui
        pass

    inner = arr[1:-1] if arr.endswith("]") else arr[1:]
    por_separador = [c.strip().strip('"') for c in inner.split('", "')]
    por_aspas = re.findall(r'"([^"]*)"', arr)

    def _score(items):
        """(itens com pinyin E tradução, com pinyin, válidos) — maior é melhor."""
        ambos = com_py = validos = 0
        for it in items:
            p = _wh_parse_item(it)
            if not p:
                continue
            validos += 1
            if p[1]:
                com_py += 1
                if p[2]:
                    ambos += 1
        return (ambos, com_py, validos)

    melhor = max((por_separador, por_aspas), key=_score)
    return [c for c in melhor if c.strip()]


def _wh_parse_item(item: str):
    """``(palavra, pinyin, tradução)`` de um item, ou ``None`` se não der.

    Cobre as formas malformadas que existem de verdade no corpus, além da
    canônica — sem isso elas caem como "entrada nua" e aparecem na tabela como
    Conhecida=Sim mesmo tendo pinyin e tradução no arquivo.
    """
    # Aspas soltas sobram das malformações do array; nenhuma palavra as contém, e
    # sem tirar isso a palavra sai deformada (ex.: `[OSMAR]"` em vez de `[OSMAR]`).
    item = item.strip().strip('"').strip()
    if not item:
        return None

    pats = (
        r'^([^\s("]+)\s*\(([^)]*)\)\s*:\s*(.*)$',   # 當 (dāng): quando
        r'^([^\s("]+)\s*\(([^):]*)\s*:\s*(.*)$',    # 匯票 (huì piào: ordens…  (sem ")")
        r'^([^\s("]+)\s*\(([^)]*)\)\s*$',           # daughter (nǚ ér)  (sem tradução)
    )
    for i, pat in enumerate(pats):
        m = re.match(pat, item)
        if m:
            word = m.group(1)
            pinyin = m.group(2).strip()
            trad = m.group(3).strip() if i < 2 else ""
            break
    else:
        m = re.match(r'^([^\s(:"]+)\s*:\s*(.*)$', item)   # HELENA: Helena
        if m:
            word, pinyin, trad = m.group(1), "", m.group(2).strip()
        else:
            m = re.match(r'^([^\s(:"]+)', item)           # entrada nua
            if not m:
                return None
            word, pinyin, trad = m.group(1), "", ""

    if not word or not word_vocab.is_real_word(word):
        return None
    return (word, pinyin, trad)


def _wh_analyse(base_path: Path, mastered=None, vocab=None) -> dict:
    """Analisa um base.txt do warehouse e retorna estatísticas de palavras.

    ``mastered`` (conjunto de dominadas) e ``vocab`` (``{palavra: (pinyin,
    tradução)}``) devem ser carregados pelo chamador — esta função roda em thread
    e não deve fazer I/O de rede. Se vierem ``None``, usa o cache do processo.

    Uma palavra é "conhecida" quando não há ajuda a exibir no render: o base não
    tem pinyin/tradução para ela (entrada nua) OU ela já é dominada na word-api.

    Pinyin e tradução exibidos vêm do PRÓPRIO base (é a tradução no contexto
    daquele episódio); quando a mesma palavra aparece com traduções diferentes,
    vale a mais frequente. Se o base não tiver, cai para o vocabulário da API e a
    entrada é marcada com ``from_api`` — a GUI colore essas linhas, para não
    ficar ambíguo de onde veio o dado.

    Retorna:
      total_words   – palavras distintas no array
      known         – palavras conhecidas (sem ajuda a exibir)
      unknown       – palavras a aprender (com pinyin+tradução e não dominadas)
      freq          – lista de dicts (word, count, conhecida, pinyin, traducao,
                      from_api) por frequência desc
    """
    if mastered is None:
        mastered = word_vocab.mastered_words()
    if vocab is None:
        vocab = word_vocab.vocabulary()

    from collections import Counter, defaultdict
    word_count: dict = defaultdict(int)
    word_meta: dict = {}                      # palavra → (has_pinyin, has_translation)
    pys: dict = defaultdict(Counter)          # palavra → Counter de pinyin
    trs: dict = defaultdict(Counter)          # palavra → Counter de traduções

    try:
        with open(base_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) < 5:
                    continue
                for item in _wh_split_items(parts[4]):
                    parsed = _wh_parse_item(item)
                    if not parsed:
                        continue
                    word, pinyin, trad = parsed
                    word_count[word] += 1
                    if pinyin:
                        pys[word][pinyin] += 1
                    if trad:
                        trs[word][trad] += 1
                    has_py, has_tr = bool(pinyin), bool(trad)
                    existing = word_meta.get(word, (False, False))
                    word_meta[word] = (existing[0] or has_py, existing[1] or has_tr)
    except Exception:
        pass

    def _top(counter):
        return counter.most_common(1)[0][0] if counter else ""

    freq = []
    for word in sorted(word_count.keys(), key=lambda w: -word_count[w]):
        has_py, has_tr = word_meta[word]
        pinyin, trad = _top(pys[word]), _top(trs[word])
        from_api = False
        if not pinyin or not trad:
            api_py, api_tr = vocab.get(word, ("", ""))
            if not pinyin and api_py:
                pinyin, from_api = api_py, True
            if not trad and api_tr:
                trad, from_api = api_tr, True
        freq.append({
            "word": word,
            "count": word_count[word],
            "conhecida": word_vocab.is_known(word, has_py, has_tr, mastered),
            "pinyin": pinyin,
            "traducao": trad,
            "from_api": from_api,
        })

    known = sum(1 for w, (hp, ht) in word_meta.items()
                if word_vocab.is_known(w, hp, ht, mastered))
    unknown = len(word_meta) - known
    return {
        "total_words": len(word_meta),
        "known": known,
        "unknown": unknown,
        "freq": freq,
    }



# ─── Pipeline phase metadata ───────────────────────────────────────────────────
PHASES = {
    "empty":    ("Vazio",        "#9E9E9E"),
    "ready":    ("Aguardando",   "#E67E22"),
    "phase1":   ("Legendas ✓",   "#3498DB"),
    "phase2":   ("Dividido",     "#9B59B6"),
    "phase3":   ("Processando",  "#E74C3C"),
    "merged":   ("Falta Drive ☁", "#F1C40F"),
    "complete": ("Completo ✓",   "#27AE60"),
}


# ─── Status detection ──────────────────────────────────────────────────────────
def detect_status(path: Path, drive_required: bool = True) -> dict:
    """``drive_required=False`` (envio ao Drive desmarcado): basta o merge para o
    asset contar como completo, em vez de ficar eternamente em "Falta Drive"."""
    sub = path.parent / f"{path.name}_sub"

    has_video = bool(list(path.glob("*.mp4")))
    has_srt   = bool(list(path.glob("*.srt")) + list(path.glob("*.vtt")))
    bases     = list(path.glob("*base.txt"))

    chromecasts = list(sub.glob("*_chromecast.mp4"))       if sub.exists() else []
    raw_chunks  = [f for f in sub.glob("*_chunk_*.mp4")
                   if "_processed" not in f.name]          if sub.exists() else []
    proc_chunks = list(sub.glob("*_processed.mp4"))        if sub.exists() else []
    merged      = (list(sub.glob("*_merged.mp4")) if sub.exists() else []) + \
                  list(path.glob("*_merged.mp4"))
    uploaded    = bool(list(sub.glob("*_drive.json"))) if sub.exists() else False

    n_total  = len(raw_chunks)
    n_done   = len(proc_chunks)
    denominator = max(n_total, n_done)
    progress = int(n_done / denominator * 100) if denominator > 0 else 0

    if merged and (uploaded or not drive_required):
        phase, progress = "complete", 100
    elif merged:
        # Merge pronto, mas o envio ao Drive (Fase 5) ainda não foi confirmado.
        phase, progress = "merged", 100
    elif proc_chunks:
        phase = "phase3"
    elif chromecasts:
        phase, progress = "phase2", 0
    elif bases:
        phase, progress = "phase1", 100
    elif has_video:
        phase, progress = "ready", 0
    else:
        phase, progress = "empty", 0

    return {
        "name":         path.name,
        "path":         path,
        "phase":        phase,
        "progress":     progress,
        "has_video":    has_video,
        "has_srt":      has_srt,
        "has_base":     bool(bases),
        "chunks_total": n_total,
        "chunks_done":  n_done,
        "complete":     bool(merged and (uploaded or not drive_required)),
        "merged":       bool(merged),
        "uploaded":     uploaded,
    }


def list_assets(drive_required: bool = True) -> list:
    if not ASSETS.exists():
        return []
    # "text" é a pasta do modo Texto, não um asset de vídeo — sem esta exclusão
    # ela aparecia na lista como um asset fantasma, eternamente "Vazio".
    dirs = sorted(
        d for d in ASSETS.iterdir()
        if d.is_dir() and not d.name.endswith("_sub")
        and d.name not in ("source", "text", "final")
    )
    return [detect_status(d, drive_required) for d in dirs]


def list_texts() -> list:
    """Assets do modo Texto: um ``assets/text/*.txt`` por item.

    "Arquivado" aqui significa exatamente ter o ``*_base.txt`` correspondente no
    ``warehouse/text/`` — não há etapa de arquivamento separada, porque o
    ``text_pipeline.py`` já escreve direto no destino final.
    """
    if not TEXTS.exists():
        return []
    out = []
    for f in sorted(TEXTS.glob("*.txt")):
        base = TEXT_WAREHOUSE / f"{f.stem}_base.txt"
        n_frases = 0
        if base.exists():
            try:
                n_frases = sum(1 for ln in base.read_text(encoding="utf-8").splitlines()
                               if ln.strip())
            except Exception:  # noqa: BLE001 - a lista nunca deve quebrar por I/O
                n_frases = 0
        try:
            n_linhas = sum(1 for ln in f.read_text(encoding="utf-8").splitlines()
                           if ln.strip())
        except Exception:  # noqa: BLE001
            n_linhas = 0
        out.append({
            "name":     f.stem,
            "path":     f,
            "base":     base,
            "archived": base.exists(),
            "linhas":   n_linhas,
            "frases":   n_frases,
        })
    return out


def list_sources() -> list:
    if not SOURCE.exists():
        return []
    result = []
    for f in sorted(SOURCE.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            n = len(data.get("episodes", []))
        except Exception:
            n = "?"
        result.append({
            "name":  f.stem,
            "path":  f,
            "episodes": n,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M"),
        })
    return result



# ─── API para o client ─────────────────────────────────────────────────────────
# Nomes públicos: o que o subrim_server aceita chamar. Os utilitários puros são
# reexportados para o client usar localmente, sem rede.
wh_readable_name = _wh_readable_name
natural_key = _natural_key
wh_group_list = _wh_group_list
external_drives = _external_drives


def wh_analyse(base_path: Path) -> dict:
    """``_wh_analyse`` com a maestria/vocabulário do cache deste processo."""
    return _wh_analyse(base_path)


def scraper_python() -> str:
    """Python da venv do scraper (selenium está instalado lá, não no Python do sistema)."""
    cand = REPO / "globoplay_scraper_env" / "bin" / "python3"
    return str(cand) if cand.exists() else sys.executable


def whisper_python() -> Path:
    return REPO / "whisper_env_py313" / "bin" / "python3"


def disk_free(path: Path) -> int:
    """Bytes livres no disco de ``path`` (HD externo ou o próprio repo)."""
    return shutil.disk_usage(path).free


# ── Vídeo, duração e chunks ────────────────────────────────────────────────────
_PROCESSED = ("_chromecast", "_merged", "_processed", "_chunk")


def original_video(asset_path: Path):
    """O mp4 original do asset (sem os derivados do pipeline), ou ``None``."""
    for cand in sorted(asset_path.glob("*.mp4")):
        if not any(s in cand.name for s in _PROCESSED):
            return cand
    return None


def source_video(asset_path: Path):
    """Vídeo de referência do asset: o chromecast do ``_sub`` se existir,
    senão o mp4 original. Retorna ``None`` se não houver vídeo."""
    sub = asset_path.parent / f"{asset_path.name}_sub"
    if sub.exists():
        cc = sorted(sub.glob("*_chromecast.mp4"))
        if cc:
            return cc[0]
    return original_video(asset_path)


def asset_video(name: str):
    """Vídeo a abrir: o merged se o asset já foi processado, senão o original."""
    path, sub = ASSETS / name, ASSETS / f"{name}_sub"
    if sub.exists():
        merged = (sorted(sub.glob("*_chromecast_merged.mp4"))
                  or sorted(sub.glob("*_merged.mp4")))
        if merged:
            return merged[0]
    merged = sorted(path.glob("*_merged.mp4"))
    if merged:
        return merged[0]
    return original_video(path)


def has_any_mp4(asset_path: Path) -> bool:
    """Recursivo: o youtube_monitor guarda os mp4 uma subpasta abaixo (por canal)."""
    return next(asset_path.rglob("*.mp4"), None) is not None


def video_duration(video: Path) -> float:
    """Duração do vídeo em segundos via ffprobe (rápido, sem decodificar)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def compute_chunk_total(asset_path: Path):
    """Quantos chunks o split vai gerar (total previsto) para o asset.

    Usa o mesmo algoritmo do split_video (subtitle-boundary aware), então o
    número bate com o que o pipeline realmente produz. ``None`` se não for
    possível determinar (sem base ou sem vídeo)."""
    bases = list(asset_path.glob("*base.txt"))
    if not bases:
        return None
    video = source_video(asset_path)
    if video is None:
        return None
    dur = video_duration(video)
    if dur <= 0:
        return None
    try:
        from split_video import parse_base_file, create_video_chunks
        return len(create_video_chunks(parse_base_file(str(bases[0])), dur))
    except Exception:
        return None


# Duração e total de chunks custam um ffprobe por vídeo: ficam em cache neste
# processo (chave = mtime) e são calculados numa thread. A lista devolve o que
# já se sabe e marca ``extras_pending`` para o client voltar a perguntar logo.
_extras: dict = {"dur": {}, "chunks": {}}
_extras_lock = threading.Lock()
_extras_running = False


def _extras_fill(pending: list):
    global _extras_running
    try:
        for kind, name, key, path in pending:
            if kind == "dur":
                val = video_duration(path)
            else:
                val = compute_chunk_total(path)
            with _extras_lock:
                _extras[kind][name] = (key, val)
    finally:
        _extras_running = False


def list_assets_full(drive_required: bool = True) -> dict:
    """``list_assets`` + ``duration`` (s) e ``chunk_total`` de cada asset.

    → ``{"assets": [...], "extras_pending": bool}``."""
    global _extras_running
    assets = list_assets(drive_required)
    pending = []
    for a in assets:
        name = a["name"]
        a["duration"] = a["chunk_total"] = None
        if a["has_video"]:
            video = source_video(a["path"])
            if video is not None:
                try:
                    key = (str(video), video.stat().st_mtime)
                except OSError:
                    key = None
                cached = _extras["dur"].get(name)
                if key and cached and cached[0] == key:
                    a["duration"] = cached[1]
                elif key:
                    pending.append(("dur", name, key, video))
        if a["has_base"]:
            bases = list(a["path"].glob("*base.txt"))
            if bases:
                key = bases[0].stat().st_mtime
                cached = _extras["chunks"].get(name)
                if cached and cached[0] == key:
                    a["chunk_total"] = cached[1]
                else:
                    pending.append(("chunks", name, key, a["path"]))
    with _extras_lock:
        start = bool(pending) and not _extras_running
        if start:
            _extras_running = True
    if start:
        threading.Thread(target=_extras_fill, args=(pending,), daemon=True).start()
    return {"assets": assets, "extras_pending": bool(pending)}


def trash(paths: list) -> list:
    """Move as pastas para a Lixeira do servidor (recuperável): Finder no
    macOS, ``gio trash`` (Lixeira do freedesktop) no Linux.

    → ``[(nome, erro)]`` das que falharam."""
    failed = []
    for p in paths:
        if sys.platform == "darwin":
            path = str(Path(p).resolve()).replace("\\", "\\\\").replace('"', '\\"')
            cmd = ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{path}"']
        elif shutil.which("gio"):
            cmd = ["gio", "trash", str(Path(p).resolve())]
        else:
            failed.append((Path(p).name, "sem 'gio' para mover à Lixeira (apt install libglib2.0-bin)"))
            continue
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            failed.append((Path(p).name, res.stderr.strip()))
    return failed


def hd_asset_names(hd: Path) -> list:
    """Pastas de asset no ``<HD>/assets`` (uma listagem só: o HD USB é lento)."""
    with os.scandir(hd) as it:
        return [e.name for e in it if e.is_dir() and not e.name.endswith("_sub")]


# ── Warehouse ──────────────────────────────────────────────────────────────────
def wh_root(text: bool) -> Path:
    return TEXT_WAREHOUSE if text else WAREHOUSE


def wh_available_assets(text: bool) -> list:
    """Assets com ``*_base.txt`` no warehouse do modo (para o filtro das Coleções)."""
    root = wh_root(text)
    if not root.exists():
        return []
    return sorted(b.stem.replace("_base", "") for b in root.glob("*_base.txt"))


def wh_rows(text: bool) -> dict:
    """Linhas da lista do Warehouse, já agrupadas.

    → ``{"missing_root": nome | None, "groups": [(key, nome, [(base, legível,
    status, tag)])], "n_bases", "complete", "archived"}``."""
    root = wh_root(text)
    if not root.exists():
        return {"missing_root": root.name, "groups": [], "n_bases": 0,
                "complete": 0, "archived": 0}
    bases = list(root.glob("*_base.txt"))
    rows = []
    complete = archived = 0
    for bf in bases:
        prefix = bf.stem.replace("_base", "")
        # No modo Texto todo base listado JÁ é o arquivo arquivado — não há
        # vídeo nem cache de frames a considerar, então o status é fixo.
        if text:
            status, tag = "Arquivado", "archived"
        else:
            # vídeo correspondente: mesmo prefixo sem _base, extensão .mp4
            has_video = any(True for _ in WAREHOUSE.glob(f"{prefix}.mp4"))
            fdir = _wh_frames_dir(prefix)
            complete += has_video
            archived += fdir is not None
            if has_video:
                status, tag = "Completo", "ok"
                if (WAREHOUSE / f"{prefix}_periods.txt").exists():
                    status = "Completo · períodos"
            elif fdir is not None:
                status, tag = "Arquivado", "archived"
                if fdir.parent == FRAMES_PERIODS:
                    status = "Arquivado · períodos"
            else:
                status, tag = "Falta vídeo", "missing"
        rows.append((bf, _wh_readable_name(bf.stem), status, tag))

    by_stem = {row[0].stem.replace("_base", ""): row for row in rows}
    groups = [(key, nome, [by_stem[st] for st in stems])
              for key, nome, stems in _wh_group_list(list(by_stem))]
    return {"missing_root": None, "groups": groups, "n_bases": len(bases),
            "complete": complete, "archived": archived}


def wh_mp4(prefix: str):
    """O mp4 original do episódio no warehouse, ou None."""
    return next(WAREHOUSE.glob(f"{prefix}.mp4"), None)


def wh_archivable(bases: list) -> list:
    """``[(base, prefixo, mp4)]`` dos bases que ainda têm mp4 original."""
    out = []
    for bf in bases:
        prefix = bf.stem.replace("_base", "")
        mp4 = wh_mp4(prefix)
        if mp4:
            out.append((bf, prefix, mp4))
    return out


def wh_frames_periods(prefix: str) -> bool:
    """True se o episódio foi arquivado POR PERÍODOS (frames numerados pelo arquivo)."""
    cache = _wh_frames_dir(prefix)
    return cache is not None and cache.parent == FRAMES_PERIODS


def clean_flags(matches: list) -> list:
    """``has_clean_sentence`` de cada frase, numa ida só ao servidor."""
    import collection_builder as cb
    return [cb.has_clean_sentence(m) for m in matches]


def wh_select_info(bf: Path, text: bool) -> dict:
    """Linhas fixas do painel de detalhes de um base (fonte e períodos)."""
    prefix = bf.stem.replace("_base", "")
    # Fonte: o mp4 no modo Vídeo, o txt de origem no modo Texto.
    if text:
        origem = TEXTS / f"{prefix}.txt"
        fonte_rot = "Texto  "
        fonte_line = origem.name if origem.exists() else "— (txt removido)"
    else:
        fonte_rot = "Vídeo  "
        mp4 = wh_mp4(prefix)
        if mp4:
            fonte_line = mp4.name
        elif _wh_is_archived(prefix):
            fdir = _wh_frames_dir(prefix)
            por = " por período" if fdir and fdir.parent == FRAMES_PERIODS else ""
            n_frames = len(list(fdir.glob("line*.jpg"))) if fdir else 0
            fonte_line = f"— (arquivado{por}: {n_frames} frames)"
        else:
            fonte_line = "—"

    periods_file = bf.with_name(f"{prefix}_periods.txt")
    if periods_file.exists():
        with periods_file.open(encoding="utf-8") as fh:
            n_per = sum(1 for _ in fh)
        periods_line = f"{periods_file.name} ({n_per} frase(s))"
    else:
        periods_line = "— (não gerado; o arquivamento gera)"
    return {"fonte_rot": fonte_rot, "fonte_line": fonte_line, "periods_line": periods_line}


def wh_archive_apply(mp4: Path) -> float:
    """Apaga o mp4 já arquivado em frames. → GB liberados."""
    freed = mp4.stat().st_size / (1024 ** 3)
    mp4.unlink()
    return freed


def wh_restore_status(hd: Path) -> dict:
    """``{asset: status}`` dos episódios em ``<HD>/warehouse``."""
    import collection_builder as cb
    status = {}
    for bf in hd.glob("*_base.txt"):
        a = bf.name[:-len("_base.txt")]
        status[a] = ("Já no computador" if (WAREHOUSE / bf.name).exists()
                     else cb.remote_status(hd, a))
    return status


def path_summary(paths: list) -> list:
    """``[(relativo ao warehouse, n_arquivos | None)]`` para a confirmação do expurgo."""
    out = []
    for p in paths:
        try:
            rel = str(p.relative_to(WAREHOUSE))
        except ValueError:
            rel = str(p)
        n = sum(1 for f in p.rglob("*") if f.is_file()) if p.is_dir() else None
        out.append((rel, n))
    return out


# ── Vocabulário, LLM, YouTube Monitor, log da DeepSeek ─────────────────────────
def reload_mastered() -> int:
    """Recarrega da word-api (local ao servidor) o conjunto de dominadas."""
    return word_vocab.reload_mastered()


def llm_local_model() -> str:
    import llm_provider
    return llm_provider.local_model()


def llm_status(provider: str) -> dict:
    import llm_provider
    return llm_provider.status(provider)


def ytm_load() -> dict:
    return ytm.load_channels_config(ytm.DEFAULT_CONFIG, required=False)


def ytm_save(cfg: dict) -> None:
    ytm.save_channels_config(ytm.DEFAULT_CONFIG, cfg)


def ds_records(limit: int = 500) -> list:
    """Últimas chamadas registradas no deepseek_debug.log (DEEPSEEK_DEBUG=1)."""
    records = []
    if DEEPSEEK_LOG.exists():
        with open(DEEPSEEK_LOG, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
    return records[-limit:]


def ds_clear() -> bool:
    """Apaga o deepseek_debug.log. False se ele não existia."""
    if not DEEPSEEK_LOG.exists():
        return False
    DEEPSEEK_LOG.unlink()
    return True
