#!/usr/bin/env python3
"""Subrim Manager — GUI para gerenciar o pipeline de processamento de vídeos."""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
from tkinter import ttk

# ─── Paths ─────────────────────────────────────────────────────────────────────
REPO      = Path(__file__).parent
ASSETS    = REPO / "assets"
SOURCE    = ASSETS / "source"
WAREHOUSE = REPO / "warehouse"
FRAMES    = WAREHOUSE / "frames"   # cache de frames de episódios arquivados
DEEPSEEK_LOG = REPO / "deepseek_debug.log"


def _wh_is_archived(prefix: str) -> bool:
    """True se o episódio foi arquivado (sem mp4, mas com cache de frames)."""
    d = FRAMES / prefix
    return d.is_dir() and next(d.glob("line*.jpg"), None) is not None


def _wh_readable_name(stem: str) -> str:
    """Converte 'amor80_base' → 'Amor 80', 'Death_Becomes_Her_base' → 'Death Becomes Her'."""
    name = stem.replace("_base", "").replace("_", " ").strip()
    # separa letras de dígitos colados: 'amor80' → 'amor 80'
    name = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", name)
    name = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", name)
    return name.title()


def _wh_analyse(base_path: Path) -> dict:
    """Analisa um base.txt do warehouse e retorna estatísticas de palavras.

    Retorna:
      total_words   – palavras distintas no array
      known         – palavras SEM pinyin e tradução (dominadas / confidence-3)
      unknown       – palavras COM pinyin e tradução (a aprender)
      freq          – lista [(palavra, count, is_conhecida)] por frequência desc
    """
    from collections import defaultdict
    word_count: dict = defaultdict(int)
    # conjunto de pares distintos para contar conhecido/desconhecido
    word_meta: dict = {}   # palavra → (has_pinyin, has_translation)

    try:
        with open(base_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 5:
                    continue
                arr = parts[4].strip()
                if not arr.startswith("["):
                    continue
                # extrai itens do array JSON-like
                for item in re.findall(r'"([^"]*)"', arr):
                    item = item.strip()
                    if not item:
                        continue
                    m = re.match(r'^([^\s\(]+)\s*\(([^)]*)\)\s*:\s*(.+)$', item)
                    if m:
                        word, pinyin, translation = m.group(1), m.group(2), m.group(3)
                        has_py = bool(pinyin.strip())
                        has_tr = bool(translation.strip())
                    else:
                        # entrada nua (palavra dominada sem pinyin/trad)
                        bare = re.match(r'^([^\s\(:]+)', item)
                        if not bare:
                            continue
                        word = bare.group(1)
                        has_py, has_tr = False, False
                    if word:
                        word_count[word] += 1
                        # known = sem pinyin OU sem tradução
                        existing = word_meta.get(word, (has_py, has_tr))
                        word_meta[word] = (existing[0] or has_py, existing[1] or has_tr)
    except Exception:
        pass

    # freq com is_conhecida: True se (not has_pinyin or not has_translation)
    freq = [
        (word, word_count[word], not word_meta[word][0] or not word_meta[word][1])
        for word in sorted(word_count.keys(), key=lambda w: -word_count[w])
    ]
    known = sum(1 for w, (hp, ht) in word_meta.items() if not hp or not ht)
    unknown = len(word_meta) - known
    return {
        "total_words": len(word_meta),
        "known": known,
        "unknown": unknown,
        "freq": freq,
    }


def _scraper_python() -> str:
    """Python da venv do scraper (selenium está instalado lá, não no Python do sistema)."""
    cand = REPO / "globoplay_scraper_env" / "bin" / "python3"
    return str(cand) if cand.exists() else sys.executable

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
def detect_status(path: Path) -> dict:
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

    if merged and uploaded:
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
        "complete":     bool(merged and uploaded),
        "merged":       bool(merged),
        "uploaded":     uploaded,
    }


def list_assets() -> list:
    if not ASSETS.exists():
        return []
    dirs = sorted(
        d for d in ASSETS.iterdir()
        if d.is_dir() and not d.name.endswith("_sub") and d.name != "source"
    )
    return [detect_status(d) for d in dirs]


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


# ─── Main application ──────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Subrim Manager")
        self.geometry("1180x700")
        self.minsize(960, 600)

        self._log_q: queue.Queue = queue.Queue()
        self._proc = None
        self._proc_lock = threading.Lock()
        self._selected = None

        # DeepSeek debug viewer
        self._ds_debug_on = tk.BooleanVar(value=False)   # injeta DEEPSEEK_DEBUG=1
        self._ds_auto = tk.BooleanVar(value=False)        # auto-atualizar a lista
        self._ds_records: list = []

        # Collections tab state
        self._col_matches: list = []
        self._col_sort_col = None
        self._col_sort_reverse = False
        self._col_index = 0
        # Filtro de assets: None = todos (sem filtro); set = só esses assets.
        self._col_asset_filter = None
        self._col_render_token = 0
        self._col_photo = None
        self._col_saving = False
        # Cronômetro de leitura (tempo por caractere)
        self._timing_active = False
        self._timing_records: list = []   # (n_caracteres, segundos) por imagem lida
        self._timing_start = None         # time.monotonic() do início da imagem atual
        self._timing_idx = None           # índice da imagem cujo tempo está correndo

        # Expected chunk-total cache: asset_name -> (base_mtime, total)
        self._chunk_total_cache: dict = {}
        self._total_fill_running = False
        # Total de chunks lido ao vivo dos logs do pipeline: asset_name -> total
        self._live_chunk_total: dict = {}
        self._log_current_asset = None

        self._setup_style()
        self._build_ui()
        self._schedule_refresh()
        self._poll_log()

    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("aqua")
        except tk.TclError:
            pass

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        bar = ttk.Frame(self, padding=(10, 5))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Subrim Manager", font=("", 14, "bold")).pack(side=tk.LEFT)
        self._status_var = tk.StringVar(value="Pronto")
        ttk.Label(bar, textvariable=self._status_var, foreground="#777").pack(side=tk.RIGHT, padx=8)
        self._stop_btn = ttk.Button(bar, text="⏹  Parar", command=self._stop, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.RIGHT)
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._build_assets_tab()
        self._build_warehouse_tab()
        self._build_downloads_tab()
        self._build_collections_tab()
        self._build_log_tab()
        self._build_deepseek_tab()

    # ── Assets Tab ─────────────────────────────────────────────────────────────
    def _build_assets_tab(self):
        outer = ttk.Frame(self._nb)
        self._nb.add(outer, text="  Assets  ")

        ctrl = ttk.Frame(outer, padding=(4, 6, 4, 2))
        ctrl.pack(fill=tk.X)

        ttk.Label(ctrl, text="Filtro:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._refresh_assets())
        ttk.Entry(ctrl, textvariable=self._filter_var, width=18).pack(side=tk.LEFT, padx=(2, 8))

        self._only_inc = tk.BooleanVar()
        ttk.Checkbutton(ctrl, text="Só incompletos", variable=self._only_inc,
                        command=self._refresh_assets).pack(side=tk.LEFT)
        ttk.Button(ctrl, text="↺", width=3, command=self._refresh_assets).pack(side=tk.LEFT, padx=4)

        ttk.Separator(ctrl, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=2)
        ttk.Label(ctrl, text="Batch (prefixo):").pack(side=tk.LEFT)
        self._batch_var = tk.StringVar()
        ttk.Entry(ctrl, textvariable=self._batch_var, width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="▶ Rodar Batch", command=self._run_batch).pack(side=tk.LEFT, padx=2)

        self._count_var = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._count_var, foreground="#888").pack(side=tk.RIGHT, padx=6)

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        # Left: asset list
        list_f = ttk.Frame(pw)
        pw.add(list_f, weight=3)

        cols = ("name", "status", "progress", "chunks")
        t = ttk.Treeview(list_f, columns=cols, show="headings", selectmode="browse")
        t.heading("name",     text="Asset",     anchor=tk.W)
        t.heading("status",   text="Status",    anchor=tk.CENTER)
        t.heading("progress", text="Progresso", anchor=tk.CENTER)
        t.heading("chunks",   text="Chunks",    anchor=tk.CENTER)
        t.column("name",     width=230, anchor=tk.W,      stretch=True)
        t.column("status",   width=120, anchor=tk.CENTER, stretch=False)
        t.column("progress", width=90,  anchor=tk.CENTER, stretch=False)
        t.column("chunks",   width=120, anchor=tk.CENTER, stretch=False)

        vsb = ttk.Scrollbar(list_f, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.bind("<<TreeviewSelect>>", self._on_asset_select)

        for phase, (_, color) in PHASES.items():
            t.tag_configure(phase, foreground=color)
        self._tree = t

        # Right: detail panel
        detail = ttk.Frame(pw, padding=12)
        pw.add(detail, weight=1)

        ttk.Label(detail, text="Detalhes", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        self._detail_text = tk.StringVar(value="← Selecione um asset")
        ttk.Label(detail, textvariable=self._detail_text, justify=tk.LEFT,
                  wraplength=210, foreground="#555").pack(anchor=tk.W)

        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(detail, text="Pipeline", font=("", 10, "bold")).pack(anchor=tk.W)

        # Opção "queimar com pausas" (default: sem pausas)
        self._burn_pause_on = tk.BooleanVar(value=False)
        self._burn_pause_rate = tk.StringVar(value="0.3")
        prow = ttk.Frame(detail)
        prow.pack(fill=tk.X, pady=(2, 2))
        ttk.Checkbutton(prow, text="Queimar com pausas", variable=self._burn_pause_on,
                        command=self._on_pause_toggle).pack(side=tk.LEFT)
        self._burn_pause_entry = ttk.Entry(prow, textvariable=self._burn_pause_rate,
                                           width=6, state=tk.DISABLED)
        self._burn_pause_entry.pack(side=tk.LEFT, padx=(6, 2))
        ttk.Label(prow, text="s/caractere", foreground="#888").pack(side=tk.LEFT)

        self._run_btn = ttk.Button(detail, text="▶  Iniciar / Retomar",
                                   command=self._run_selected, state=tk.DISABLED)
        self._run_btn.pack(fill=tk.X, pady=(3, 1))
        self._force_btn = ttk.Button(detail, text="↺  Forçar Reprocessamento",
                                     command=self._force_selected, state=tk.DISABLED)
        self._force_btn.pack(fill=tk.X, pady=1)
        self._open_btn = ttk.Button(detail, text="📂  Abrir Pasta",
                                    command=self._open_folder, state=tk.DISABLED)
        self._open_btn.pack(fill=tk.X, pady=1)
        self._cleanup_btn = ttk.Button(detail, text="🧹  Clean-up (arquivar)",
                                       command=self._cleanup_selected, state=tk.DISABLED)
        self._cleanup_btn.pack(fill=tk.X, pady=1)

        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(detail, text="Fases", font=("", 10, "bold")).pack(anchor=tk.W)

        self._phase_marks = {}
        for key, label in [
            ("processor", "1. Processor (base.txt)"),
            ("split",     "2. Split vídeo"),
            ("process",   "3. Queimar legendas"),
            ("merge",     "4. Merge final"),
            ("drive",     "5. Envio para o Drive"),
        ]:
            row = ttk.Frame(detail)
            row.pack(fill=tk.X, pady=2, anchor=tk.W)
            var = tk.StringVar(value="○")
            ttk.Label(row, textvariable=var, width=6, font=("Menlo", 10)).pack(side=tk.LEFT)
            ttk.Label(row, text=label, font=("", 9)).pack(side=tk.LEFT)
            self._phase_marks[key] = var

        self._refresh_assets()

    # ── Warehouse Tab ──────────────────────────────────────────────────────────
    def _build_warehouse_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Warehouse  ")

        # barra superior
        ctrl = ttk.Frame(outer)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(ctrl, text="↺  Atualizar", command=self._wh_refresh).pack(side=tk.LEFT)
        self._wh_archive_btn = ttk.Button(
            ctrl, text="🗄  Arquivar (trocar vídeo por frames)",
            command=self._wh_archive_selected, state=tk.DISABLED)
        self._wh_archive_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._wh_count_var = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._wh_count_var, foreground="#888").pack(side=tk.RIGHT)
        self._wh_selected_base = None
        self._wh_archiving = False

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # ── lista ──
        left = ttk.Frame(pw)
        pw.add(left, weight=2)

        cols = ("name", "status")
        wt = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        wt.heading("name",   text="Nome",   anchor=tk.W)
        wt.heading("status", text="Status", anchor=tk.CENTER)
        wt.column("name",   width=200, anchor=tk.W,      stretch=True)
        wt.column("status", width=110, anchor=tk.CENTER, stretch=False)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=wt.yview)
        wt.configure(yscrollcommand=vsb.set)
        wt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        wt.tag_configure("ok",       foreground="#27AE60")
        wt.tag_configure("archived", foreground="#2980B9")
        wt.tag_configure("missing",  foreground="#E74C3C")
        wt.bind("<<TreeviewSelect>>", self._wh_on_select)
        self._wh_tree = wt

        # ── detalhes ──
        right = ttk.Frame(pw, padding=(12, 0, 0, 0))
        pw.add(right, weight=3)

        ttk.Label(right, text="Detalhes", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(4, 8))

        self._wh_detail = tk.StringVar(value="Selecione um arquivo para ver os detalhes.")
        ttk.Label(right, textvariable=self._wh_detail, justify=tk.LEFT,
                  font=("Menlo", 11), foreground="#333").pack(anchor=tk.W)

        ttk.Label(right, text="Palavras por frequência:", font=("", 10, "bold")).pack(
            anchor=tk.W, pady=(14, 4))

        freq_f = ttk.Frame(right)
        freq_f.pack(fill=tk.BOTH, expand=True)
        fcols = ("word", "count", "conhecida")
        ft = ttk.Treeview(freq_f, columns=fcols, show="headings", selectmode="extended")
        ft.heading("word",      text="Palavra",      anchor=tk.W)
        ft.heading("count",     text="Ocorrências",  anchor=tk.CENTER)
        ft.heading("conhecida", text="Conhecida",    anchor=tk.CENTER)
        ft.column("word",      width=120, anchor=tk.W,      stretch=True)
        ft.column("count",     width=90,  anchor=tk.CENTER, stretch=False)
        ft.column("conhecida", width=80,  anchor=tk.CENTER, stretch=False)
        fvsb = ttk.Scrollbar(freq_f, orient=tk.VERTICAL, command=ft.yview)
        ft.configure(yscrollcommand=fvsb.set)
        ft.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fvsb.pack(side=tk.RIGHT, fill=tk.Y)
        ft.bind("<Button-1>", self._wh_freq_on_header_click)
        ft.bind("<Control-c>", self._wh_freq_copy_selection)
        self._wh_freq_tree = ft
        self._wh_freq_sort_col = "count"   # coluna de ordenação atual
        self._wh_freq_sort_reverse = True  # decrescente por padrão

        self._wh_refresh()

    def _wh_refresh(self):
        """Recarrega a lista de base.txt do warehouse, ordenada alfabeticamente por nome legível."""
        self._wh_tree.delete(*self._wh_tree.get_children())
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        self._wh_freq_data = []
        self._wh_detail.set("Selecione um arquivo para ver os detalhes.")

        if not WAREHOUSE.exists():
            self._wh_count_var.set("warehouse/ não encontrada")
            return

        bases = sorted(WAREHOUSE.glob("*_base.txt"),
                       key=lambda p: _wh_readable_name(p.stem).lower())
        for bf in bases:
            readable = _wh_readable_name(bf.stem)
            # vídeo correspondente: mesmo prefixo sem _base, extensão .mp4
            prefix = bf.stem.replace("_base", "")
            has_video = any(True for _ in WAREHOUSE.glob(f"{prefix}.mp4"))
            if has_video:
                status, tag = "Completo", "ok"
            elif _wh_is_archived(prefix):
                status, tag = "Arquivado", "archived"
            else:
                status, tag = "Falta vídeo", "missing"
            self._wh_tree.insert("", tk.END, iid=str(bf),
                                 values=(readable, status), tags=(tag,))

        total    = len(bases)
        complete = sum(1 for bf in bases
                       if any(True for _ in WAREHOUSE.glob(
                           f"{bf.stem.replace('_base', '')}.mp4")))
        archived = sum(1 for bf in bases
                       if _wh_is_archived(bf.stem.replace("_base", "")))
        extra = f" · {archived} arquivado(s)" if archived else ""
        self._wh_count_var.set(f"{complete}/{total} com vídeo{extra}")

    def _wh_on_select(self, _=None):
        sel = self._wh_tree.selection()
        if not sel:
            return
        bf = Path(sel[0])
        prefix = bf.stem.replace("_base", "")
        self._wh_selected_base = bf

        # vídeo
        mp4 = next(WAREHOUSE.glob(f"{prefix}.mp4"), None)
        if mp4:
            video_line = mp4.name
        elif _wh_is_archived(prefix):
            video_line = f"— (arquivado: {len(list((FRAMES / prefix).glob('line*.jpg')))} frames)"
        else:
            video_line = "—"
        # Só dá para arquivar quem ainda tem o mp4 original e não está arquivando.
        self._wh_archive_btn.config(
            state=(tk.NORMAL if (mp4 and not self._wh_archiving) else tk.DISABLED))

        # análise (em thread para não travar a UI)
        self._wh_detail.set("Analisando…")
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())

        def _work():
            stats = _wh_analyse(bf)
            detail = (
                f"Arquivo : {bf.name}\n"
                f"Vídeo   : {video_line}\n"
                f"\n"
                f"Palavras distintas : {stats['total_words']}\n"
                f"  Conhecidas (sem pinyin/trad) : {stats['known']}\n"
                f"  Desconhecidas (com pinyin+trad) : {stats['unknown']}"
            )
            freq = stats["freq"]
            self.after(0, lambda: self._wh_show_details(detail, freq))

        threading.Thread(target=_work, daemon=True).start()

    def _wh_archive_selected(self):
        """Extrai 1 frame por legenda para o cache e, só se tudo der certo, apaga o mp4.

        A busca/preview/salvamento na aba Coleções continuam funcionando via
        cache de frames (warehouse/frames/<asset>/). A remoção do mp4 é feita
        apenas após conferir que todos os frames foram extraídos.
        """
        if self._wh_archiving or self._wh_selected_base is None:
            return
        cb = self._col_import()
        if not cb:
            return

        bf = self._wh_selected_base
        prefix = bf.stem.replace("_base", "")
        readable = _wh_readable_name(bf.stem)
        mp4 = next(WAREHOUSE.glob(f"{prefix}.mp4"), None)
        if not mp4:
            messagebox.showinfo("Arquivar", "Este episódio não tem mp4 original para arquivar.")
            return

        size_gb = mp4.stat().st_size / (1024 ** 3)
        if not messagebox.askyesno(
                "Arquivar episódio",
                f"Arquivar “{readable}”?\n\n"
                f"• Extrai 1 frame por legenda para warehouse/frames/{prefix}/\n"
                f"• Depois APAGA {mp4.name} (~{size_gb:.2f} GB)\n\n"
                f"A busca e a visualização na aba Coleções continuam funcionando "
                f"pelos frames. Para reverter é preciso repor o vídeo original.\n\n"
                f"Continuar?"):
            return

        self._wh_archiving = True
        self._wh_archive_btn.config(state=tk.DISABLED)
        self._nb.select(4)  # aba Log
        self._log_line(f"🗄  Arquivando “{readable}” — extraindo frames…", "cmd")

        def _progress(i, total, msg):
            self._log_q.put((f"  [{i}/{total}] {msg}", "info"))

        def _work():
            try:
                res = cb.archive_asset(prefix, progress_cb=_progress)
            except Exception as e:  # noqa: BLE001
                self._log_q.put((f"Erro ao arquivar '{prefix}': {e}", "error"))
                self.after(0, lambda: self._wh_archive_done(prefix, None, mp4))
                return
            self.after(0, lambda: self._wh_archive_done(prefix, res, mp4))

        threading.Thread(target=_work, daemon=True).start()

    def _wh_archive_done(self, prefix: str, res, mp4: Path):
        self._wh_archiving = False
        if res is None:
            # Falha na extração: mantém o mp4 intacto.
            self._log_line("⚠️  Arquivamento abortado — vídeo mantido.", "warning")
            self._wh_refresh()
            return

        if res["ok"] == 0 or res["failed"] > 0:
            # Extração incompleta: NÃO apaga o vídeo, para não perder dados.
            self._log_line(
                f"⚠️  {res['failed']} frame(s) falharam ({res['ok']}/{res['total']} ok) — "
                f"vídeo NÃO foi apagado. Cache em {res['dir']}.", "warning")
            messagebox.showwarning(
                "Arquivamento incompleto",
                f"{res['failed']} frame(s) não puderam ser extraídos "
                f"({res['ok']}/{res['total']}).\n\n"
                f"O vídeo foi mantido por segurança. Verifique o log.")
            self._wh_refresh()
            return

        # Sucesso: todos os frames extraídos → remove o mp4.
        try:
            freed = mp4.stat().st_size / (1024 ** 3)
            mp4.unlink()
            self._log_line(
                f"✓ “{prefix}” arquivado: {res['ok']} frames em {res['dir']}. "
                f"Vídeo removido (~{freed:.2f} GB liberados).", "success")
        except Exception as e:  # noqa: BLE001
            self._log_line(
                f"⚠️  Frames extraídos ({res['ok']}), mas falha ao apagar o mp4: {e}",
                "warning")
        self._wh_refresh()

    def _wh_show_details(self, detail: str, freq: list):
        self._wh_detail.set(detail)
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        self._wh_freq_data = freq   # armazena para reclassificação
        # Popula com dados (respeita ordenação)
        self._wh_freq_refresh_view()

    def _wh_freq_refresh_view(self):
        """Recarrega a visualização da tabela respeitando a ordenação atual."""
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        if not hasattr(self, '_wh_freq_data'):
            return
        # Ordena pelos critérios atuais
        sort_key = {
            "word": lambda x: x[0],
            "count": lambda x: x[1],
            "conhecida": lambda x: (not x[2], x[0]),  # Desconhecidas primeiro (False antes True)
        }[self._wh_freq_sort_col]
        sorted_data = sorted(self._wh_freq_data, key=sort_key, reverse=self._wh_freq_sort_reverse)
        for word, count, is_conhecida in sorted_data:
            conhecida_str = "Sim" if is_conhecida else "Não"
            self._wh_freq_tree.insert("", tk.END, values=(word, count, conhecida_str))

    def _wh_freq_on_header_click(self, event):
        """Detecta clique no header da tabela de frequência para ordenar."""
        region = self._wh_freq_tree.identify_region(event.x, event.y)
        if region != "heading":
            return
        col_index = self._wh_freq_tree.identify_column(event.x)
        # Mapeia índice de coluna para nome
        col_name = self._wh_freq_tree.heading(col_index)["text"]
        col_map = {"Palavra": "word", "Ocorrências": "count", "Conhecida": "conhecida"}
        col = col_map.get(col_name)
        if not col:
            return
        # Se clicar na mesma coluna, inverte ordem; senão usa decrescente por padrão
        if self._wh_freq_sort_col == col:
            self._wh_freq_sort_reverse = not self._wh_freq_sort_reverse
        else:
            self._wh_freq_sort_col = col
            self._wh_freq_sort_reverse = True  # decrescente por padrão (exceto "Palavra")
            if col == "word":
                self._wh_freq_sort_reverse = False  # alfabético crescente
        self._wh_freq_refresh_view()

    def _wh_freq_copy_selection(self, _=None):
        """Copia as palavras selecionadas para a área de transferência (Ctrl+C)."""
        sel = self._wh_freq_tree.selection()
        if not sel:
            return
        words = []
        for iid in sel:
            values = self._wh_freq_tree.item(iid)["values"]
            if values:
                words.append(values[0])
        if words:
            text = "\n".join(words)
            self.clipboard_clear()
            self.clipboard_append(text)

    # ── Downloads & Scraping Tab ───────────────────────────────────────────────
    def _build_downloads_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Downloads & Scraping  ")

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: source files manager
        src_f = ttk.LabelFrame(pw, text="  Arquivos Source  ", padding=8)
        pw.add(src_f, weight=1)

        btn_row = ttk.Frame(src_f)
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="+ Novo Scraping", command=self._new_scraping_dialog).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="↺", width=3, command=self._refresh_sources).pack(side=tk.LEFT, padx=4)

        src_cols = ("name", "eps", "mtime")
        st = ttk.Treeview(src_f, columns=src_cols, show="headings", height=12)
        st.heading("name",  text="Série",      anchor=tk.W)
        st.heading("eps",   text="Episódios",  anchor=tk.CENTER)
        st.heading("mtime", text="Modificado", anchor=tk.CENTER)
        st.column("name",  width=140, anchor=tk.W)
        st.column("eps",   width=80,  anchor=tk.CENTER, stretch=False)
        st.column("mtime", width=110, anchor=tk.CENTER, stretch=False)

        vsb2 = ttk.Scrollbar(src_f, orient=tk.VERTICAL, command=st.yview)
        st.configure(yscrollcommand=vsb2.set)
        st.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb2.pack(side=tk.RIGHT, fill=tk.Y)
        self._src_tree = st

        src_act = ttk.Frame(src_f)
        src_act.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(src_act, text="📥  Baixar Episódios", command=self._download_source).pack(fill=tk.X)
        ttk.Button(src_act, text="👁  Ver Conteúdo",     command=self._view_source   ).pack(fill=tk.X, pady=(2, 0))

        self._refresh_sources()

        # Right: download tools
        right = ttk.Frame(pw, padding=4)
        pw.add(right, weight=1)

        # YouTube Downloader
        yt = ttk.LabelFrame(right, text="  YouTube Downloader  ", padding=10)
        yt.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(yt, text="URL:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self._yt_url = tk.StringVar()
        ttk.Entry(yt, textvariable=self._yt_url).grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=3)

        ttk.Label(yt, text="Nome:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self._yt_name = tk.StringVar()
        ttk.Entry(yt, textvariable=self._yt_name, width=18).grid(row=1, column=1, sticky=tk.EW, pady=3)

        ttk.Label(yt, text="Browser:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self._yt_browser = tk.StringVar(value="chrome")
        browser_cb = ttk.Combobox(yt, textvariable=self._yt_browser, width=10, state="readonly",
                                  values=["chrome", "firefox", "safari", "chromium", "edge", "brave"])
        browser_cb.grid(row=2, column=1, sticky=tk.W, pady=3)

        self._yt_subs = tk.BooleanVar()
        self._yt_vid  = tk.BooleanVar()
        ttk.Checkbutton(yt, text="Só legendas", variable=self._yt_subs).grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Checkbutton(yt, text="Só vídeo",    variable=self._yt_vid ).grid(row=3, column=1, sticky=tk.W, pady=2)
        ttk.Button(yt, text="▶ Baixar", command=self._run_yt).grid(row=3, column=2, sticky=tk.E, pady=(6, 0))
        yt.columnconfigure(1, weight=1)

        # Globoplay Scraper
        gp = ttk.LabelFrame(right, text="  Globoplay Scraper  ", padding=10)
        gp.pack(fill=tk.X)

        ttk.Label(gp, text="URL da série:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self._gp_url = tk.StringVar()
        ttk.Entry(gp, textvariable=self._gp_url).grid(row=0, column=1, columnspan=2, sticky=tk.EW, pady=3)

        ttk.Label(gp, text="Nome base:").grid(row=1, column=0, sticky=tk.W, pady=3)
        self._gp_name = tk.StringVar()
        ttk.Entry(gp, textvariable=self._gp_name, width=22).grid(row=1, column=1, sticky=tk.W, pady=3)

        self._gp_headless = tk.BooleanVar()
        ttk.Checkbutton(gp, text="Headless", variable=self._gp_headless).grid(row=2, column=0, sticky=tk.W)
        ttk.Label(gp, text="Tempo espera (s):").grid(row=2, column=1, sticky=tk.W, padx=(8, 0))
        self._gp_time = tk.StringVar(value="60")
        ttk.Entry(gp, textvariable=self._gp_time, width=6).grid(row=2, column=2, sticky=tk.W)

        ttk.Button(gp, text="▶ Iniciar Scraping", command=self._run_gp).grid(row=3, column=2, sticky=tk.E, pady=(8, 0))
        gp.columnconfigure(1, weight=1)

    # ── Collections Tab ──────────────────────────────────────────────────────────
    def _build_collections_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Coleções  ")

        # Search bar
        top = ttk.Frame(outer)
        top.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top, text="Palavra(s) (vírgula):").pack(side=tk.LEFT)
        self._col_word = tk.StringVar()
        e = ttk.Entry(top, textvariable=self._col_word, width=30, font=("", 14))
        e.pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", lambda _: self._col_do_search())
        ttk.Button(top, text="🔍 Buscar", command=self._col_do_search).pack(side=tk.LEFT)
        self._col_filter_btn = ttk.Button(top, text="⚙ Filtro",
                                          command=self._col_open_filter_dialog)
        self._col_filter_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._col_status = tk.StringVar(value="Digite uma ou mais palavras (ex.: 著,當,與) e busque no warehouse")
        ttk.Label(top, textvariable=self._col_status, foreground="#888").pack(side=tk.LEFT, padx=12)

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: matches list
        left = ttk.Frame(pw)
        pw.add(left, weight=2)
        cols = ("palavra", "asset", "time", "frase")
        t = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self._col_headers = {"palavra": "Palavra", "asset": "Asset",
                             "time": "Tempo", "frase": "Frase"}
        t.heading("palavra", text="Palavra", anchor=tk.W,
                  command=lambda: self._col_sort("palavra"))
        t.heading("asset", text="Asset",  anchor=tk.W,
                  command=lambda: self._col_sort("asset"))
        t.heading("time",  text="Tempo",  anchor=tk.CENTER,
                  command=lambda: self._col_sort("time"))
        t.heading("frase", text="Frase",  anchor=tk.W,
                  command=lambda: self._col_sort("frase"))
        t.column("palavra", width=60,  anchor=tk.W,      stretch=False)
        t.column("asset", width=100, anchor=tk.W,      stretch=False)
        t.column("time",  width=64,  anchor=tk.CENTER, stretch=False)
        t.column("frase", width=220, anchor=tk.W,      stretch=True)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.bind("<<TreeviewSelect>>", self._col_on_select)
        t.bind("<Delete>",    lambda _: self._col_delete_selected())
        t.bind("<BackSpace>", lambda _: self._col_delete_selected())
        t.bind("<Shift-Down>", lambda _: self._col_extend_selection(1)  or "break")
        t.bind("<Shift-Up>",   lambda _: self._col_extend_selection(-1) or "break")
        self._col_tree = t

        # Right: preview
        right = ttk.Frame(pw, padding=(8, 0))
        pw.add(right, weight=3)

        nav = ttk.Frame(right)
        nav.pack(fill=tk.X)
        ttk.Button(nav, text="◀ Anterior", command=lambda: self._col_step(-1)).pack(side=tk.LEFT)
        self._col_pos = tk.StringVar(value="—")
        ttk.Label(nav, textvariable=self._col_pos, width=10, anchor=tk.CENTER).pack(side=tk.LEFT, padx=6)
        ttk.Button(nav, text="Próxima ▶", command=lambda: self._col_step(1)).pack(side=tk.LEFT)

        self._timing_btn = ttk.Button(nav, text="⏱ Cronometrar",
                                      command=self._timing_toggle, state=tk.DISABLED)
        self._timing_btn.pack(side=tk.RIGHT)
        self._timing_info = tk.StringVar(value="")
        ttk.Label(nav, textvariable=self._timing_info, foreground="#888").pack(side=tk.RIGHT, padx=8)

        self._col_preview = ttk.Label(right, text="(preview r36s aparece aqui)",
                                      anchor=tk.CENTER, foreground="#888")
        self._col_preview.pack(fill=tk.BOTH, expand=True, pady=6)

        # Caption: frase em chinês e tradução em português (selecionável para copiar)
        self._col_caption = tk.Text(right, height=4, font=("", 11), wrap=tk.WORD,
                                     state=tk.DISABLED, bg=self.cget("bg"),
                                     relief=tk.FLAT, bd=0)
        self._col_caption.pack(fill=tk.X, anchor=tk.W)

        # Bottom: save
        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self._col_save_btn = ttk.Button(bottom, text="💾 Salvar coleção",
                                        command=self._col_save, state=tk.DISABLED)
        self._col_save_btn.pack(side=tk.LEFT)
        ttk.Label(bottom, text="→ warehouse/collections/<palavra>/ (original + r36s)",
                  foreground="#888").pack(side=tk.LEFT, padx=10)

    def _col_import(self):
        """Importa collection_builder de forma preguiçosa (cv2/PIL podem faltar)."""
        try:
            import collection_builder  # noqa: F401
            from PIL import Image, ImageTk  # noqa: F401
            return collection_builder
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Dependência ausente",
                                 f"Não foi possível carregar o módulo de coleções:\n{e}\n\n"
                                 "Verifique se opencv-python e Pillow estão instalados.")
            return None

    def _col_available_assets(self) -> list:
        """Lista de assets disponíveis (a partir dos *_base.txt do warehouse)."""
        if not WAREHOUSE.exists():
            return []
        return sorted(b.stem.replace("_base", "") for b in WAREHOUSE.glob("*_base.txt"))

    def _col_update_filter_btn(self):
        """Atualiza o rótulo do botão de filtro conforme o estado (ativo/inativo)."""
        if self._col_asset_filter:
            n = len(self._col_asset_filter)
            self._col_filter_btn.config(text=f"⚙ Filtro ({n}) ●")
        else:
            self._col_filter_btn.config(text="⚙ Filtro")

    def _col_open_filter_dialog(self):
        """Abre o pop-up de seleção de assets via checkboxes."""
        AssetFilterDialog(self)

    def _col_do_search(self):
        cb = self._col_import()
        if not cb:
            return
        raw = self._col_word.get().strip()
        # Aceita várias palavras separadas por vírgula (ex.: "著,當,與").
        words, seen = [], set()
        for w in raw.replace("，", ",").split(","):
            w = w.strip()
            if w and w not in seen:
                seen.add(w)
                words.append(w)
        if not words:
            messagebox.showwarning("Aviso", "Digite uma ou mais palavras (separadas por vírgula).")
            return

        asset_filter = self._col_asset_filter  # None = todos

        self._col_status.set("Buscando…")
        self._col_tree.delete(*self._col_tree.get_children())
        self._col_matches = []
        # Nova busca: zera a ordenação e os indicadores (▲/▼) dos cabeçalhos.
        self._col_sort_col = None
        self._col_sort_reverse = False
        for c, base in self._col_headers.items():
            self._col_tree.heading(c, text=base)

        # Modo especial "0": frases com 0 ou 1 palavra desconhecida (i+1 input).
        comprehensible_mode = words == ["0"]

        def _search_log(msg: str):
            tag = "warning" if msg.startswith("⚠️") else "info"
            self._log_q.put((msg, tag))

        def _apply_filter(matches):
            if asset_filter:
                matches = [m for m in matches if m.get("asset") in asset_filter]
            return matches

        if comprehensible_mode:
            self._log_line("🔎 Buscando frases i+1 (≤1 palavra desconhecida)…", "cmd")

            def _work():
                matches = _apply_filter(cb.search_comprehensible(log_cb=_search_log, max_unknown=1))
                self.after(0, lambda: self._col_show_results(matches))
        else:
            self._log_line(f"🔎 Buscando coleção: {', '.join(words)}", "cmd")

            def _work():
                matches = []
                for w in words:
                    matches.extend(cb.search(w, log_cb=_search_log))
                self.after(0, lambda: self._col_show_results(_apply_filter(matches)))

        threading.Thread(target=_work, daemon=True).start()

    def _col_show_results(self, matches: list):
        self._col_matches = matches
        self._col_tree.delete(*self._col_tree.get_children())
        for i, m in enumerate(matches):
            frase = (m["chinese"] or "").strip()
            self._col_tree.insert("", tk.END, iid=str(i),
                                  values=(m.get("word", ""), m["asset"], f"{m['avg_time']:.1f}s", frase[:60]))
        n = len(matches)
        words_set = {m.get("word", "") for m in matches}
        # modo i+1: palavras são "0"/"1" (contagem de desconhecidas)
        if words_set <= {"0", "1"}:
            n0 = sum(1 for m in matches if m.get("word") == "0")
            n1 = n - n0
            status = f"{n} frase(s) — {n0} sem desconhecidas, {n1} com 1 desconhecida"
        else:
            n_words = len(words_set)
            status = f"{n} frase(s) em {n_words} palavra(s)"
        self._col_status.set(status if n else "Nenhuma frase encontrada")
        self._col_save_btn.config(state=tk.NORMAL if n else tk.DISABLED)
        # Cronômetro: nova busca encerra qualquer sessão ativa e (re)habilita o botão.
        self._timing_reset()
        self._timing_btn.config(state=tk.NORMAL if n else tk.DISABLED)
        self._col_preview.config(image="", text="(preview r36s aparece aqui)")
        self._col_photo = None
        self._col_caption.config(state=tk.NORMAL)
        self._col_caption.delete("1.0", tk.END)
        self._col_caption.config(state=tk.DISABLED)
        self._col_pos.set(f"0/{n}")
        if n:
            self._col_tree.selection_set("0")
            self._col_tree.focus("0")

    def _col_on_select(self, _=None):
        sel = self._col_tree.selection()
        if not sel:
            return
        self._col_index = int(sel[0])
        if self._timing_active:
            self._timing_mark(self._col_index)
        self._col_render_current()

    def _col_sort(self, col: str):
        """Ordena a lista de resultados pela coluna clicada (toggle asc/desc)."""
        if not self._col_matches:
            return
        reverse = (self._col_sort_col == col) and not self._col_sort_reverse
        keyfns = {
            "palavra": lambda m: m.get("word", ""),
            "asset":   lambda m: m.get("asset", ""),
            "time":    lambda m: m.get("avg_time", 0.0),
            "frase":   lambda m: (m.get("chinese") or "").strip(),
        }
        self._col_matches = sorted(self._col_matches, key=keyfns.get(col, lambda m: ""),
                                   reverse=reverse)
        self._col_sort_col = col
        self._col_sort_reverse = reverse

        # Indicador visual (▲/▼) no cabeçalho ordenado; demais voltam ao label base.
        arrow = " ▼" if reverse else " ▲"
        for c, base in self._col_headers.items():
            self._col_tree.heading(c, text=base + (arrow if c == col else ""))

        self._col_show_results(self._col_matches)

    def _col_delete_selected(self):
        sel = self._col_tree.selection()
        if not sel:
            return
        to_delete = {int(iid) for iid in sel}
        new_matches = [m for i, m in enumerate(self._col_matches) if i not in to_delete]

        # find new selection: first surviving item after the deleted range
        max_del = max(to_delete)
        new_sel = max(0, len(new_matches) - 1)
        j = 0
        for i in range(len(self._col_matches)):
            if i in to_delete:
                continue
            if i > max_del:
                new_sel = j
                break
            j += 1

        self._col_show_results(new_matches)
        if new_matches:
            iid = str(new_sel)
            self._col_tree.selection_set(iid)
            self._col_tree.focus(iid)
            self._col_tree.see(iid)
            self._col_index = new_sel

    def _col_extend_selection(self, direction: int):
        focused = self._col_tree.focus()
        if not focused:
            return
        nxt = self._col_tree.next(focused) if direction > 0 else self._col_tree.prev(focused)
        if not nxt:
            return
        self._col_tree.selection_add(nxt)
        self._col_tree.focus(nxt)
        self._col_tree.see(nxt)

    def _col_step(self, delta: int):
        if not self._col_matches:
            return
        n = len(self._col_matches)
        self._col_index = (self._col_index + delta) % n
        iid = str(self._col_index)
        self._col_tree.selection_set(iid)
        self._col_tree.focus(iid)
        self._col_tree.see(iid)

    def _col_render_current(self):
        cb = self._col_import()
        if not cb or not self._col_matches:
            return
        idx = self._col_index
        m = self._col_matches[idx]
        n = len(self._col_matches)
        self._col_pos.set(f"{idx + 1}/{n}")
        self._col_caption.config(state=tk.NORMAL)
        self._col_caption.delete("1.0", tk.END)
        self._col_caption.insert(tk.END, f"{m['chinese']}\n{m['portuguese']}")
        self._col_caption.config(state=tk.DISABLED)
        self._col_preview.config(image="", text="Renderizando…")

        self._col_render_token += 1
        token = self._col_render_token

        def _work():
            try:
                img = cb.render_preview(m, "r36s")
            except Exception as e:  # noqa: BLE001
                img = None
                self._log_q.put((f"Erro ao renderizar preview: {e}", "error"))
            self.after(0, lambda: self._col_set_preview(token, img))

        threading.Thread(target=_work, daemon=True).start()

    # ── Cronômetro de leitura (tempo por caractere) ─────────────────────────────
    @staticmethod
    def _count_chars(text: str) -> int:
        """Conta os ideogramas CJK da frase (o que o usuário efetivamente lê)."""
        if not text:
            return 0
        cjk = sum(1 for ch in text
                  if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"
                  or "豈" <= ch <= "﫿")
        # fallback: se não houver CJK, conta caracteres não-espaço
        return cjk if cjk else len(text.replace(" ", "").replace("　", ""))

    def _timing_reset(self):
        """Zera o estado do cronômetro e devolve o botão ao estado inicial."""
        self._timing_active = False
        self._timing_records = []
        self._timing_start = None
        self._timing_idx = None
        self._timing_info.set("")
        self._timing_btn.config(text="⏱ Cronometrar")

    def _timing_mark(self, new_idx: int):
        """Registra o tempo da imagem que está sendo deixada e (re)inicia para a nova."""
        if (self._timing_idx is not None and self._timing_start is not None
                and new_idx != self._timing_idx):
            elapsed = time.monotonic() - self._timing_start
            chars = self._count_chars(self._col_matches[self._timing_idx].get("chinese", ""))
            if chars > 0 and elapsed > 0:
                self._timing_records.append((chars, elapsed))
                self._timing_info.set(
                    f"{len(self._timing_records)} lida(s) · "
                    f"{elapsed / chars:.2f}s/caractere (última)")
        self._timing_idx = new_idx
        self._timing_start = time.monotonic()

    def _timing_toggle(self):
        if not self._col_matches:
            return
        if not self._timing_active:
            # Inicia: zera registros e começa a contar na 1ª imagem. Pré-fixamos
            # o índice/início ANTES de mexer na seleção para que o evento de
            # seleção (se disparar) não registre um tempo espúrio da imagem anterior.
            self._timing_records = []
            self._timing_active = True
            self._timing_btn.config(text="⏹ Finalizar cronômetro")
            self._timing_info.set("0 lida(s)")
            self._log_line("⏱ Cronômetro iniciado — leia cada frase e clique 'Próxima ▶'.", "cmd")
            self._col_index = 0
            self._timing_idx = 0
            self._timing_start = time.monotonic()
            self._col_tree.selection_set("0")
            self._col_tree.focus("0")
            self._col_tree.see("0")
            self._col_render_current()
        else:
            self._timing_finalize()

    def _timing_finalize(self):
        # Registra a imagem que estava sendo lida no momento de finalizar.
        if self._timing_idx is not None and self._timing_start is not None:
            elapsed = time.monotonic() - self._timing_start
            chars = self._count_chars(self._col_matches[self._timing_idx].get("chinese", ""))
            if chars > 0 and elapsed > 0:
                self._timing_records.append((chars, elapsed))

        records = self._timing_records
        self._timing_active = False
        self._timing_btn.config(text="⏱ Cronometrar")
        self._timing_idx = None
        self._timing_start = None

        total_chars = sum(c for c, _ in records)
        total_time = sum(t for _, t in records)
        if total_chars > 0:
            avg = total_time / total_chars
            self._timing_info.set(f"média: {avg:.2f}s/caractere")
            self._log_line(
                f"⏱ Cronômetro finalizado: {avg:.2f}s/caractere "
                f"({len(records)} imagem(ns), {total_chars} caracteres, {total_time:.1f}s)",
                "success")
            messagebox.showinfo(
                "Resultado do cronômetro",
                f"Imagens lidas: {len(records)}\n"
                f"Caracteres lidos: {total_chars}\n"
                f"Tempo total: {total_time:.1f}s\n\n"
                f"⏱  Média geral: {avg:.2f}s por caractere")
        else:
            self._timing_info.set("")
            messagebox.showinfo("Resultado do cronômetro",
                                "Nenhuma leitura registrada.")

    def _col_set_preview(self, token: int, img):
        if token != self._col_render_token:
            return  # uma seleção mais nova já começou a renderizar
        if img is None:
            self._col_preview.config(image="", text="(falha ao renderizar frame)")
            self._col_photo = None
            return
        from PIL import ImageTk
        self._col_photo = ImageTk.PhotoImage(img)
        self._col_preview.config(image=self._col_photo, text="")

    def _col_save(self):
        cb = self._col_import()
        if not cb or not self._col_matches or self._col_saving:
            return

        # Agrupa os matches por palavra → uma coleção (pasta) por palavra.
        groups: dict = {}
        for m in self._col_matches:
            groups.setdefault(m.get("word", ""), []).append(m)
        groups = [(w, ms) for w, ms in groups.items() if w]
        if not groups:
            return

        n_total = sum(len(ms) for _, ms in groups)
        folders = [cb.collection_folder_name(w, ms) for w, ms in groups]
        shown = ", ".join(folders[:8]) + ("…" if len(folders) > 8 else "")
        if not messagebox.askyesno(
                "Salvar coleções",
                f"Gerar {n_total} imagem(ns) em {len(groups)} coleção(ões) (uma pasta por palavra)?\n"
                f"→ warehouse/collections/: {shown}"):
            return

        self._col_saving = True
        self._col_save_btn.config(state=tk.DISABLED)
        self._nb.select(4)
        self._log_line(f"💾 Salvando {len(groups)} coleção(ões) ({n_total} frases)…", "cmd")

        def _progress(i, total, msg):
            self._log_q.put((f"  [{i}/{total}] {msg}", "info"))

        def _work():
            last_out = None
            ok_count = 0
            for w, ms in groups:
                try:
                    self._log_q.put((f"💾 Coleção '{w}' ({len(ms)} frases)…", "cmd"))
                    out = cb.save_collection(w, ms, progress_cb=_progress)
                    self._log_q.put((f"✓ Coleção salva em {out}", "success"))
                    last_out = out
                    ok_count += 1
                except Exception as e:  # noqa: BLE001
                    self._log_q.put((f"Erro ao salvar coleção '{w}': {e}", "error"))
            self.after(0, lambda: self._col_save_done(last_out, ok_count, len(groups)))

        threading.Thread(target=_work, daemon=True).start()

    def _col_save_done(self, out, ok_count: int = 0, total: int = 0):
        self._col_saving = False
        self._col_save_btn.config(state=tk.NORMAL if self._col_matches else tk.DISABLED)
        if out is not None:
            # Abre a pasta de coleções (pai), já que pode haver várias.
            open_dir = out.parent if total > 1 else out
            if messagebox.askyesno(
                    "Concluído",
                    f"{ok_count}/{total} coleção(ões) salva(s).\nAbrir a pasta?"):
                subprocess.Popen(["open", str(open_dir)])

    # ── Log Tab ────────────────────────────────────────────────────────────────
    def _build_log_tab(self):
        f = ttk.Frame(self._nb, padding=(6, 6, 6, 0))
        self._nb.add(f, text="  Log  ")

        ctrl = ttk.Frame(f)
        ctrl.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(ctrl, text="Limpar", command=self._clear_log).pack(side=tk.LEFT)
        self._autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Auto-scroll", variable=self._autoscroll).pack(side=tk.LEFT, padx=8)
        self._log_label = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._log_label, foreground="#888", font=("Menlo", 9)).pack(side=tk.RIGHT)

        txt = scrolledtext.ScrolledText(
            f, state=tk.DISABLED, font=("Menlo", 10),
            bg="#1C1C1E", fg="#EBEBF5",
            insertbackground="white", relief=tk.FLAT,
        )
        txt.pack(fill=tk.BOTH, expand=True)
        txt.tag_configure("cmd",     foreground="#5AC8FA")
        txt.tag_configure("success", foreground="#30D158")
        txt.tag_configure("error",   foreground="#FF453A")
        txt.tag_configure("warning", foreground="#FF9F0A")
        txt.tag_configure("info",    foreground="#EBEBF5")
        self._log_txt = txt

    # ── DeepSeek Tab ─────────────────────────────────────────────────────────────
    def _build_deepseek_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  DeepSeek  ")

        ctrl = ttk.Frame(outer)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(ctrl, text="Registrar chamadas (DEEPSEEK_DEBUG)",
                        variable=self._ds_debug_on).pack(side=tk.LEFT)
        ttk.Button(ctrl, text="↺ Atualizar", command=self._ds_refresh).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(ctrl, text="Auto", variable=self._ds_auto).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="🗑 Limpar log", command=self._ds_clear).pack(side=tk.LEFT, padx=4)
        self._ds_count = tk.StringVar(value="")
        ttk.Label(ctrl, textvariable=self._ds_count, foreground="#888").pack(side=tk.RIGHT)

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Esquerda: lista de chamadas
        left = ttk.Frame(pw)
        pw.add(left, weight=2)
        cols = ("n", "ts", "prompt")
        t = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        t.heading("n",      text="#",       anchor=tk.CENTER)
        t.heading("ts",     text="Hora",    anchor=tk.W)
        t.heading("prompt", text="Prompt (início)", anchor=tk.W)
        t.column("n",      width=44,  anchor=tk.CENTER, stretch=False)
        t.column("ts",     width=150, anchor=tk.W,      stretch=False)
        t.column("prompt", width=300, anchor=tk.W,      stretch=True)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.bind("<<TreeviewSelect>>", self._ds_on_select)
        self._ds_tree = t

        # Direita: detalhe (prompt + response)
        right = ttk.Frame(pw, padding=(8, 0))
        pw.add(right, weight=3)

        ttk.Label(right, text="Prompt enviado", font=("", 10, "bold")).pack(anchor=tk.W)
        self._ds_prompt = scrolledtext.ScrolledText(
            right, height=12, font=("Menlo", 10), wrap=tk.WORD,
            bg="#1C1C1E", fg="#EBEBF5", relief=tk.FLAT)
        self._ds_prompt.pack(fill=tk.BOTH, expand=True, pady=(2, 6))

        ttk.Label(right, text="Response crua", font=("", 10, "bold")).pack(anchor=tk.W)
        self._ds_response = scrolledtext.ScrolledText(
            right, height=12, font=("Menlo", 10), wrap=tk.WORD,
            bg="#1C1C1E", fg="#30D158", relief=tk.FLAT)
        self._ds_response.pack(fill=tk.BOTH, expand=True, pady=(2, 0))

        self._ds_refresh()

    def _ds_refresh(self):
        """Recarrega as chamadas do deepseek_debug.log (mantém as últimas 500)."""
        records = []
        if DEEPSEEK_LOG.exists():
            try:
                with open(DEEPSEEK_LOG, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            continue
            except Exception as e:  # noqa: BLE001
                self._ds_count.set(f"erro ao ler log: {e}")
                return
        records = records[-500:]
        self._ds_records = records

        # Preserva seleção pelo índice atual
        prev = self._ds_tree.selection()
        self._ds_tree.delete(*self._ds_tree.get_children())
        for i, rec in enumerate(records):
            snippet = (rec.get("prompt", "") or "").replace("\n", " ")[:80]
            self._ds_tree.insert("", tk.END, iid=str(i),
                                 values=(i + 1, rec.get("ts", ""), snippet))
        n = len(records)
        self._ds_count.set(f"{n} chamada(s)" + (" (últimas 500)" if n >= 500 else ""))
        # Seleciona a última por padrão (acompanhar ao vivo)
        if n and (self._ds_auto.get() or not prev):
            iid = str(n - 1)
            self._ds_tree.selection_set(iid)
            self._ds_tree.see(iid)
            self._ds_on_select()

    def _ds_on_select(self, _=None):
        sel = self._ds_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self._ds_records):
            return
        rec = self._ds_records[idx]
        prompt = rec.get("prompt", "")
        raw = rec.get("response", "")
        # Tenta formatar o JSON da response para leitura
        try:
            raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except Exception:
            pass
        for widget, content in ((self._ds_prompt, prompt), (self._ds_response, raw)):
            widget.config(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, content)

    def _ds_clear(self):
        if not DEEPSEEK_LOG.exists():
            self._ds_refresh()
            return
        if messagebox.askyesno("Limpar log",
                               f"Apagar {DEEPSEEK_LOG.name}?\nIsso remove o histórico de chamadas."):
            try:
                DEEPSEEK_LOG.unlink()
            except OSError as e:
                messagebox.showerror("Erro", f"Não foi possível apagar: {e}")
            for w in (self._ds_prompt, self._ds_response):
                w.config(state=tk.NORMAL)
                w.delete("1.0", tk.END)
            self._ds_refresh()

    # ── Asset logic ────────────────────────────────────────────────────────────
    @staticmethod
    def _video_duration(video: Path) -> float:
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

    def _compute_chunk_total(self, asset_path: Path):
        """Calcula quantos chunks o split vai gerar (total previsto) para o asset.

        Usa o mesmo algoritmo do split_video (subtitle-boundary aware), então o
        número bate com o que o pipeline realmente produz. Retorna ``None`` se não
        for possível determinar (sem base ou sem vídeo)."""
        bases = list(asset_path.glob("*base.txt"))
        if not bases:
            return None
        base = bases[0]

        sub = asset_path.parent / f"{asset_path.name}_sub"
        video = None
        if sub.exists():
            cc = sorted(sub.glob("*_chromecast.mp4"))
            if cc:
                video = cc[0]
        if video is None:
            for cand in sorted(asset_path.glob("*.mp4")):
                if not any(s in cand.name for s in
                           ("_chromecast", "_merged", "_processed", "_chunk")):
                    video = cand
                    break
        if video is None:
            return None

        dur = self._video_duration(video)
        if dur <= 0:
            return None

        try:
            from split_video import parse_base_file, create_video_chunks
            subtitles = parse_base_file(str(base))
            return len(create_video_chunks(subtitles, dur))
        except Exception:
            return None

    def _maybe_fill_totals(self, assets: list):
        """Preenche o cache de totais previstos em background, sem travar a UI."""
        pending = []
        for a in assets:
            if not a["has_base"]:
                continue
            name = a["name"]
            bases = list(a["path"].glob("*base.txt"))
            if not bases:
                continue
            mtime = bases[0].stat().st_mtime
            cached = self._chunk_total_cache.get(name)
            if cached is None or cached[0] != mtime:
                pending.append((name, a["path"], mtime))

        if not pending or self._total_fill_running:
            return
        self._total_fill_running = True

        def worker():
            try:
                for name, path, mtime in pending:
                    total = self._compute_chunk_total(path)
                    self._chunk_total_cache[name] = (mtime, total)
            finally:
                self._total_fill_running = False
                self.after(0, self._refresh_assets)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_assets(self, *_):
        flt = self._filter_var.get().strip().lower()
        inc = self._only_inc.get()

        assets = list_assets()
        if flt:
            assets = [a for a in assets if flt in a["name"].lower()]
        if inc:
            assets = [a for a in assets if a["phase"] != "complete"]

        # Preserva seleção/foco/scroll para o refresh periódico não "deselecionar".
        prev_sel = set(self._tree.selection())
        prev_focus = self._tree.focus()
        try:
            prev_scroll = self._tree.yview()[0]
        except Exception:
            prev_scroll = None

        self._tree.delete(*self._tree.get_children())
        names = set()
        for a in assets:
            lbl, _ = PHASES[a["phase"]]
            prog   = f"{a['progress']}%" if a["phase"] not in ("empty", "ready") else "—"
            chunks = self._format_chunks(a)
            self._tree.insert("", tk.END, iid=a["name"],
                              values=(a["name"], lbl, prog, chunks), tags=(a["phase"],))
            names.add(a["name"])

        # Restaura o estado se os itens ainda existirem após o refresh.
        keep = [n for n in prev_sel if n in names]
        if keep:
            self._tree.selection_set(keep)
        if prev_focus in names:
            self._tree.focus(prev_focus)
        if prev_scroll is not None:
            self._tree.yview_moveto(prev_scroll)

        total    = len(assets)
        complete = sum(1 for a in assets if a["phase"] == "complete")
        self._count_var.set(f"{complete}/{total} completos")

        self._maybe_fill_totals(assets)

    def _format_chunks(self, a: dict) -> str:
        """Coluna Chunks: indicador binário (✓ ou ○) pois processamento é paralelo.

        Como chunks agora queimam em paralelo, não há progresso granular a mostrar.
        Indicador simples: ✓ se todos processados, ○ se não.
        """
        if a["phase"] in ("empty", "ready") or not a["has_base"]:
            return "—"
        done, generated = a["chunks_done"], a["chunks_total"]
        if generated > 0 and done == generated:
            return "✓"
        return "○"

    def _chunk_total_for(self, name: str):
        """Total previsto de chunks: prioriza o valor lido ao vivo dos logs."""
        live = self._live_chunk_total.get(name)
        if live:
            return live
        cached = self._chunk_total_cache.get(name)
        return cached[1] if cached else None

    def _on_asset_select(self, _):
        sel = self._tree.selection()
        if not sel:
            return
        s = detect_status(ASSETS / sel[0])
        self._selected = s
        self._update_detail(s)

    def _update_detail(self, s: dict):
        phase_lbl, _ = PHASES[s["phase"]]
        lines = [
            f"Nome:    {s['name']}",
            f"Status:  {phase_lbl}",
            f"Vídeo:   {'✓' if s['has_video'] else '✗'}",
            f"Legenda: {'✓' if s['has_srt'] else '✗'}",
            f"Base:    {'✓' if s['has_base'] else '✗'}",
        ]
        if s["chunks_total"] > 0:
            total = self._chunk_total_for(s["name"])
            if total:
                lines.append(f"Chunks:  {s['chunks_done']} / {s['chunks_total']} / {total}")
            else:
                lines.append(f"Chunks:  {s['chunks_done']}/{s['chunks_total']} ({s['progress']}%)")
        self._detail_text.set("\n".join(lines))

        self._run_btn.config(state=tk.NORMAL if s["has_video"] else tk.DISABLED)
        self._force_btn.config(state=tk.NORMAL if s.get("merged") else tk.DISABLED)
        self._open_btn.config(state=tk.NORMAL)
        # Clean-up só faz sentido após o upload ao Drive estar registrado.
        self._cleanup_btn.config(state=tk.NORMAL if s.get("uploaded") else tk.DISABLED)

        p = s["phase"]
        n, tot = s["chunks_done"], s["chunks_total"]

        self._phase_marks["processor"].set(
            "✓" if p in ("phase1","phase2","phase3","merged","complete") else
            ("⏳" if p == "ready" else "○")
        )
        self._phase_marks["split"].set(
            "✓" if p in ("phase2","phase3","merged","complete") else
            ("⏳" if p == "phase1" else "○")
        )
        self._phase_marks["process"].set(
            "✓" if p in ("merged","complete") else
            (f"⏳{n}/{tot}" if p == "phase3" else "○")
        )
        self._phase_marks["merge"].set(
            "✓" if p in ("merged","complete") else
            ("⏳" if p == "phase3" and n == tot and tot > 0 else "○")
        )
        self._phase_marks["drive"].set(
            "✓" if s.get("uploaded") else
            ("⏳" if p == "merged" else "○")
        )

    def _run_selected(self):
        if not self._selected:
            return
        self._launch(
            [sys.executable, str(REPO / "video_burner.py"), self._selected["name"], "--exact"],
            label=f"Pipeline: {self._selected['name']}",
        )

    def _force_selected(self):
        if not self._selected:
            return
        name = self._selected["name"]
        if messagebox.askyesno("Confirmar", f"Reprocessar '{name}' do zero?\nIsso irá sobrescrever os arquivos existentes."):
            self._launch(
                [sys.executable, str(REPO / "video_burner.py"), name, "--exact", "--force"],
                label=f"Pipeline (force): {name}",
            )

    def _run_batch(self):
        prefix = self._batch_var.get().strip()
        if not prefix:
            messagebox.showwarning("Aviso", "Informe um prefixo para o batch.\nEx: 'onibus' processa todos os assets onibus*")
            return
        self._launch(
            [sys.executable, str(REPO / "video_burner.py"), prefix],
            label=f"Batch: {prefix}*",
            pause_rate=0.0,  # batch nunca usa pausas, independente do checkbox
        )

    def _cleanup_selected(self):
        if not self._selected:
            return
        name = self._selected["name"]
        if not self._selected.get("uploaded"):
            messagebox.showwarning(
                "Upload pendente",
                f"O asset '{name}' ainda não tem upload registrado no Drive.\n"
                "O clean-up só roda depois que a Fase 5 (Envio para o Drive) concluir.")
            return
        if messagebox.askyesno(
                "Confirmar clean-up",
                f"Arquivar '{name}'?\n\n"
                "Após validar o upload no Drive, o vídeo original e o base.txt vão "
                "para o warehouse e as pastas\n"
                f"  • assets/{name}/\n  • assets/{name}_sub/\n"
                "serão REMOVIDAS do disco. Esta ação é irreversível."):
            self._launch(
                [sys.executable, str(REPO / "cleanup_asset.py"), name],
                label=f"Clean-up: {name}",
            )

    def _open_folder(self):
        if self._selected:
            subprocess.Popen(["open", str(self._selected["path"])])

    # ── Source / download logic ────────────────────────────────────────────────
    def _refresh_sources(self):
        self._src_tree.delete(*self._src_tree.get_children())
        for f in list_sources():
            self._src_tree.insert("", tk.END, iid=f["name"],
                                  values=(f["name"], f["episodes"], f["mtime"]))

    def _new_scraping_dialog(self):
        NewScrapingDialog(self)

    def _download_source(self):
        sel = self._src_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma série primeiro")
            return
        DownloadDialog(self, sel[0])

    def _view_source(self):
        sel = self._src_tree.selection()
        if not sel:
            messagebox.showwarning("Aviso", "Selecione uma série primeiro")
            return
        SourceViewerDialog(self, SOURCE / f"{sel[0]}.json")

    def _run_yt(self):
        url  = self._yt_url.get().strip()
        name = self._yt_name.get().strip()
        if not url:
            messagebox.showwarning("Aviso", "Informe a URL do YouTube")
            return
        if not name:
            messagebox.showwarning("Aviso", "Informe o Nome do asset (ex.: clone45)")
            return
        cmd = [sys.executable, str(REPO / "youtube_downloader.py"), url,
               "--name", name,
               "--browser", self._yt_browser.get()]
        if self._yt_subs.get():
            cmd.append("--subs-only")
        elif self._yt_vid.get():
            cmd.append("--video-only")
        self._launch(cmd, label=f"YouTube → {name}")

    def _run_gp(self):
        url  = self._gp_url.get().strip()
        name = self._gp_name.get().strip()
        if not url or not name:
            messagebox.showwarning("Aviso", "Preencha URL e Nome base")
            return
        SOURCE.mkdir(exist_ok=True)
        cmd = [_scraper_python(), str(REPO / "scrape_globoplay_episodes.py"),
               "--url", url, "--output", str(SOURCE / name),
               "--interaction-time", self._gp_time.get()]
        if self._gp_headless.get():
            cmd.append("--headless")
        self._launch(cmd, label=f"Scraping: {name}")

    # ── Queimar com pausas ──────────────────────────────────────────────────────
    def _on_pause_toggle(self):
        self._burn_pause_entry.config(
            state=tk.NORMAL if self._burn_pause_on.get() else tk.DISABLED)

    def _pause_rate_value(self) -> float:
        """Tempo (s) por caractere se 'com pausas' estiver ligado; senão 0."""
        if not self._burn_pause_on.get():
            return 0.0
        try:
            rate = float(self._burn_pause_rate.get().replace(",", "."))
        except (ValueError, AttributeError):
            return 0.0
        return rate if rate > 0 else 0.0

    # ── Process management ─────────────────────────────────────────────────────
    def _launch(self, cmd: list, label: str = "", pause_rate: float = None):
        with self._proc_lock:
            if self._proc and self._proc.poll() is None:
                messagebox.showwarning("Processo em execução",
                                       "Aguarde ou pare o processo atual antes de iniciar outro.")
                return

        self._nb.select(4)
        self._log_line(f"$ {' '.join(str(c) for c in cmd)}", "cmd")
        self._status_var.set(f"▶  {label}")
        self._stop_btn.config(state=tk.NORMAL)
        self._log_label.set(label)

        # None = use checkbox value; caller can force 0.0 to disable pauses.
        if pause_rate is None:
            pause_rate = self._pause_rate_value()

        debug_ds = self._ds_debug_on.get()

        def _run():
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            if pause_rate > 0:
                env["BURN_PAUSE_RATE"] = f"{pause_rate}"
            else:
                env.pop("BURN_PAUSE_RATE", None)
            if debug_ds:
                env["DEEPSEEK_DEBUG"] = "1"
            else:
                env.pop("DEEPSEEK_DEBUG", None)
            p = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, cwd=str(REPO), env=env,
            )
            with self._proc_lock:
                self._proc = p
            for raw in p.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                lo = line.lower()
                tag = (
                    "error"   if any(k in lo for k in ("error", "erro", "exception", "traceback")) else
                    "warning" if any(k in lo for k in ("warn", "aviso", "skip")) else
                    "success" if any(k in line for k in ("[OK]", "✓", "Done", "done", "DONE",
                                                          "Completo", "merged", "completed")) else
                    "info"
                )
                self._log_q.put((line, tag))
            p.wait()
            sep = "─" * 70
            tag = "success" if p.returncode == 0 else "error"
            self._log_q.put((sep, "info"))
            self._log_q.put((f"Encerrado  (código {p.returncode})", tag))
            self.after(0, self._on_proc_done)

        threading.Thread(target=_run, daemon=True).start()

    def _on_proc_done(self):
        self._status_var.set("Pronto")
        self._log_label.set("")
        self._stop_btn.config(state=tk.DISABLED)
        self._refresh_assets()
        self._refresh_sources()

    def _stop(self):
        with self._proc_lock:
            if self._proc:
                self._proc.terminate()
        self._log_line("⏹  Processo interrompido pelo usuário", "warning")

    # ── Logging ────────────────────────────────────────────────────────────────
    def _log_line(self, msg: str, tag: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_txt.config(state=tk.NORMAL)
        self._log_txt.insert(tk.END, f"[{ts}]  {msg}\n", tag)
        self._log_txt.config(state=tk.DISABLED)
        if self._autoscroll.get():
            self._log_txt.see(tk.END)

    def _clear_log(self):
        self._log_txt.config(state=tk.NORMAL)
        self._log_txt.delete("1.0", tk.END)
        self._log_txt.config(state=tk.DISABLED)

    _RE_DIR   = re.compile(r"Processando diret[óo]rio:\s*(.+?)\s*$")
    _RE_CHUNK = re.compile(r"Gerando chunk\s+\d+/(\d+)")

    def _poll_log(self):
        new_total = False
        try:
            while True:
                msg, tag = self._log_q.get_nowait()
                self._log_line(msg, tag)
                new_total = self._scan_log_for_total(msg) or new_total
        except queue.Empty:
            pass
        if new_total:
            self._refresh_assets()
        self.after(80, self._poll_log)

    def _scan_log_for_total(self, msg: str) -> bool:
        """Extrai o total de chunks anunciado pelo pipeline (ex.: 'chunk 042/109').

        Retorna ``True`` quando descobre um total novo, para forçar refresh da tabela."""
        m = self._RE_DIR.search(msg)
        if m:
            self._log_current_asset = m.group(1).strip()
            return False
        m = self._RE_CHUNK.search(msg)
        if m and self._log_current_asset:
            total = int(m.group(1))
            if self._live_chunk_total.get(self._log_current_asset) != total:
                self._live_chunk_total[self._log_current_asset] = total
                return True
        return False

    # ── Auto-refresh ───────────────────────────────────────────────────────────
    def _schedule_refresh(self):
        def _tick():
            with self._proc_lock:
                running = self._proc is not None and self._proc.poll() is None
            self._refresh_assets()
            if self._ds_auto.get():
                self._ds_refresh()
            self.after(3000 if running else 12000, _tick)
        self.after(12000, _tick)


# ─── Dialog: Asset Filter (Coleções) ────────────────────────────────────────────
class AssetFilterDialog(tk.Toplevel):
    """Pop-up de seleção de assets (checkboxes) para filtrar a busca de coleções."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Filtrar por assets")
        self.geometry("320x460")
        self.minsize(260, 300)
        self.grab_set()

        assets = app._col_available_assets()
        current = app._col_asset_filter  # None = todos

        f = ttk.Frame(self, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Selecione os assets da busca", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(f, text="Nenhum marcado = buscar em todos.",
                  foreground="#888", font=("", 9)).pack(anchor=tk.W, pady=(0, 6))

        top = ttk.Frame(f)
        top.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(top, text="Marcar todos",  command=self._select_all).pack(side=tk.LEFT)
        ttk.Button(top, text="Desmarcar todos", command=self._clear_all).pack(side=tk.LEFT, padx=4)

        # Área rolável de checkboxes
        canvas_f = ttk.Frame(f)
        canvas_f.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(canvas_f, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_f, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Scroll com mouse no Mac
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        self._vars = {}
        for name in assets:
            checked = (current is None) or (name in current)
            var = tk.BooleanVar(value=checked)
            self._vars[name] = var
            cb = ttk.Checkbutton(inner, text=name, variable=var)
            cb.pack(anchor=tk.W, pady=1)
            # Propaga scroll do mouse para o Canvas
            cb.bind("<MouseWheel>", _on_mousewheel)

        if not assets:
            ttk.Label(inner, text="(nenhum base.txt no warehouse)",
                      foreground="#888").pack(anchor=tk.W)

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Aplicar",  command=self._apply).pack(side=tk.RIGHT)

    def _select_all(self):
        for v in self._vars.values():
            v.set(True)

    def _clear_all(self):
        for v in self._vars.values():
            v.set(False)

    def _apply(self):
        selected = {name for name, v in self._vars.items() if v.get()}
        # Tudo marcado (ou nada marcado) → sem filtro (None = todos).
        if not selected or selected == set(self._vars):
            self.app._col_asset_filter = None
        else:
            self.app._col_asset_filter = selected
        self.app._col_update_filter_btn()
        self.destroy()


# ─── Dialog: New Scraping ──────────────────────────────────────────────────────
class NewScrapingDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Novo Scraping")
        self.geometry("500x260")
        self.resizable(False, False)
        self.grab_set()

        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Scraping de Episódios (Globoplay)", font=("", 12, "bold")).pack(anchor=tk.W)
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(f, text="URL da série:").pack(anchor=tk.W)
        self._url = tk.StringVar()
        ttk.Entry(f, textvariable=self._url, width=56).pack(fill=tk.X, pady=(0, 8))

        ttk.Label(f, text="Nome base (ex: onibus, amor, clone):").pack(anchor=tk.W)
        self._name = tk.StringVar()
        ttk.Entry(f, textvariable=self._name, width=28).pack(anchor=tk.W, pady=(0, 8))

        opts = ttk.Frame(f)
        opts.pack(fill=tk.X, pady=2)
        self._headless = tk.BooleanVar()
        ttk.Checkbutton(opts, text="Headless (scroll automático)", variable=self._headless).pack(side=tk.LEFT)
        ttk.Label(opts, text="  Espera:").pack(side=tk.LEFT)
        self._time = tk.StringVar(value="60")
        ttk.Entry(opts, textvariable=self._time, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(opts, text="s").pack(side=tk.LEFT)

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btns, text="Cancelar",     command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="▶ Iniciar",    command=self._start ).pack(side=tk.RIGHT)

    def _start(self):
        url  = self._url.get().strip()
        name = self._name.get().strip()
        if not url or not name:
            messagebox.showwarning("Campos obrigatórios", "Preencha URL e Nome base.", parent=self)
            return
        SOURCE.mkdir(exist_ok=True)
        cmd = [_scraper_python(), str(REPO / "scrape_globoplay_episodes.py"),
               "--url", url, "--output", str(SOURCE / name),
               "--interaction-time", self._time.get()]
        if self._headless.get():
            cmd.append("--headless")
        self.app._launch(cmd, label=f"Scraping: {name}")
        self.destroy()


# ─── Dialog: Download from Source ─────────────────────────────────────────────
class DownloadDialog(tk.Toplevel):
    def __init__(self, app: App, series_name: str):
        super().__init__(app)
        self.app = app
        self.series = series_name
        self.title(f"Baixar — {series_name}")
        self.geometry("400x260")
        self.resizable(False, True)
        self.grab_set()

        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text=f"Baixar episódios: {series_name}", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        # Show how many episodes are available
        try:
            data = json.loads((SOURCE / f"{series_name}.json").read_text(encoding="utf-8"))
            eps = data.get("episodes", [])
            nums = [int(e["episode_number"]) for e in eps if str(e.get("episode_number","")).isdigit()]
            if nums:
                ttk.Label(f, text=f"Episódios disponíveis: {min(nums)} → {max(nums)}  ({len(nums)} total)",
                          foreground="#555").pack(anchor=tk.W, pady=(0, 6))
        except Exception:
            pass

        # Modo: único ou lote
        self._mode = tk.StringVar(value="batch")
        mode_f = ttk.Frame(f)
        mode_f.pack(fill=tk.X, pady=(0, 6))
        ttk.Radiobutton(mode_f, text="Próximos 6 a partir de",
                        variable=self._mode, value="batch",
                        command=self._on_mode).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_f, text="Episódio único",
                        variable=self._mode, value="single",
                        command=self._on_mode).pack(side=tk.LEFT, padx=(12, 0))

        row = ttk.Frame(f)
        row.pack(fill=tk.X)
        self._ep_label = ttk.Label(row, text="Episódio inicial:")
        self._ep_label.pack(side=tk.LEFT)
        self._start = tk.StringVar(value="1")
        ttk.Entry(row, textvariable=self._start, width=6).pack(side=tk.LEFT, padx=6)

        self._hint = ttk.Label(f, text="(máximo 6 episódios por vez)", foreground="#999",
                               font=("", 9))
        self._hint.pack(anchor=tk.W, pady=(4, 0))

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btns, text="Cancelar",  command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="📥 Baixar", command=self._start_download).pack(side=tk.RIGHT)

    def _on_mode(self):
        single = self._mode.get() == "single"
        self._ep_label.config(text="Número do episódio:" if single else "Episódio inicial:")
        self._hint.config(text="" if single else "(máximo 6 episódios por vez)")

    def _start_download(self):
        ep = self._start.get().strip()
        if not ep.isdigit():
            messagebox.showwarning("Aviso", "Número do episódio inválido", parent=self)
            return
        single = self._mode.get() == "single"
        cmd = [sys.executable, str(REPO / "video_fetcher.py"), self.series, ep]
        if single:
            cmd.append("--only")
        label = f"Download: {self.series} ep{ep}" if single else f"Download: {self.series} ep{ep}+"
        self.app._launch(cmd, label=label)
        self.destroy()


# ─── Dialog: Source file viewer ────────────────────────────────────────────────
class SourceViewerDialog(tk.Toplevel):
    def __init__(self, parent, path: Path):
        super().__init__(parent)
        self.title(f"Source: {path.stem}")
        self.geometry("800x520")
        self.grab_set()

        f = ttk.Frame(self, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text=str(path), font=("Menlo", 9), foreground="#666").pack(anchor=tk.W)
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        try:
            data     = json.loads(path.read_text(encoding="utf-8"))
            episodes = data.get("episodes", [])
        except Exception as e:
            ttk.Label(f, text=f"Erro ao ler arquivo: {e}", foreground="red").pack()
            return

        # Search bar
        search_f = ttk.Frame(f)
        search_f.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(search_f, text="Filtro:").pack(side=tk.LEFT)
        search_var = tk.StringVar()
        search_e = ttk.Entry(search_f, textvariable=search_var, width=20)
        search_e.pack(side=tk.LEFT, padx=4)
        ttk.Label(search_f, text=f"{len(episodes)} episódios", foreground="#888").pack(side=tk.RIGHT)

        cols = ("num", "date", "title", "url")
        tree = ttk.Treeview(f, columns=cols, show="headings")
        tree.heading("num",   text="#",       anchor=tk.CENTER)
        tree.heading("date",  text="Data",    anchor=tk.CENTER)
        tree.heading("title", text="Título",  anchor=tk.W)
        tree.heading("url",   text="URL",     anchor=tk.W)
        tree.column("num",   width=45,  anchor=tk.CENTER, stretch=False)
        tree.column("date",  width=100, anchor=tk.CENTER, stretch=False)
        tree.column("title", width=300, anchor=tk.W)
        tree.column("url",   width=300, anchor=tk.W)

        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        def _populate(flt=""):
            tree.delete(*tree.get_children())
            for ep in episodes:
                title = ep.get("title", "")
                if flt and flt.lower() not in title.lower() and flt not in ep.get("episode_number", ""):
                    continue
                tree.insert("", tk.END, values=(
                    ep.get("episode_number", ""),
                    ep.get("chapter_date", ""),
                    title,
                    ep.get("url", ""),
                ))

        search_var.trace_add("write", lambda *_: _populate(search_var.get()))
        _populate()


# ─── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
