#!/usr/bin/env python3
"""Subrim Manager — GUI (client) do pipeline de processamento de vídeos.

Esta máquina só exibe: vídeos, bases, coleções e todo o processamento (inclusive
as chamadas à DeepSeek e à word-api) ficam no servidor (subrim_server.py) de
outra máquina da rede local, cujo IP vai no campo "Servidor" do topo. Os
caminhos abaixo são ``RemotePath`` — cada operação de arquivo é uma chamada ao
servidor (ver subrim_remote.py); a lógica de dados mora em manager_core.py.
"""

import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import project_python
project_python.ensure("tkinter")  # python3 do brew pode vir sem Tk

from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
from tkinter import ttk

import subrim_remote as sr
from subrim_remote import CLIENT, PY, SCRAPER_PY, WHISPER_PY, RemoteError, RemoteModule, RemotePath
# Só utilitários puros (sem I/O): rodam aqui mesmo, sem ida ao servidor.
from manager_core import PHASES, wh_readable_name as _wh_readable_name
import youtube_monitor as ytm   # idem: só sanitize_name/is_valid_prefix
from app_identity import set_app_name

APP_NAME = "Subrim Manager"

# ─── Arquivos locais (só preferências da interface) ───────────────────────────
LOCAL = Path(__file__).parent
# Ajustes de leitura do preview das Coleções (painel à direita). Sobrevivem a
# fechar o app; só a visualização os usa, nunca o salvar coleção.
VIEWER_PREFS = LOCAL / ".subrim_viewer.json"
VIEWER_DEFAULTS = {"trad_opaque": False, "trad_scale": 1.0, "trad_hide": False,
                   "leg_opaque": False, "leg_scale": 1.0, "leg_hide": False,
                   "auto_audio": False}
VIEWER_SCALE_MIN, VIEWER_SCALE_MAX = 0.6, 2.0
# Último IP digitado no campo "Servidor".
CLIENT_PREFS = LOCAL / ".subrim_client.json"

# ─── Paths no servidor ────────────────────────────────────────────────────────
REPO      = RemotePath(".")
ASSETS    = REPO / "assets"
SOURCE    = ASSETS / "source"
TEXTS     = ASSETS / "text"          # txt do modo Texto (um arquivo = um asset)
WAREHOUSE = REPO / "warehouse"
TEXT_WAREHOUSE = WAREHOUSE / "text"  # bases gerados pelo text_pipeline.py

# Módulos que rodam no servidor.
core = RemoteModule("manager_core")
cb = RemoteModule("collection_builder")
periods_base = RemoteModule("periods_base")

# Nota (0-10) das frases — os mesmos valores do collection_builder, que não é
# importado aqui (puxa OpenCV).
NOTA_MIN, NOTA_MAX, NOTA_DEFAULT = 0, 10, 5


def clamp_nota(value: int) -> int:
    return max(NOTA_MIN, min(NOTA_MAX, int(value)))


def _load_client_prefs() -> dict:
    try:
        return json.loads(CLIENT_PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_client_prefs(prefs: dict) -> None:
    try:
        CLIENT_PREFS.write_text(json.dumps(prefs, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError:
        pass


def _open_url(url: str) -> None:
    """Abre uma URL do servidor no app padrão (vídeo: navegador, em streaming)."""
    subprocess.Popen(["open", url])


# ─── Processos em execução ─────────────────────────────────────────────────────
class Job:
    """Um processo lançado pelo _launch, com a sua própria sub-aba de log.

    Um lote (Iniciar/Clean-up com vários assets) é um Job só: os itens rodam
    em série dentro dele, na mesma sub-aba. Jobs diferentes rodam em paralelo.
    """
    _next_id = 0

    def __init__(self, label: str):
        Job._next_id += 1
        self.id = Job._next_id
        self.label = label
        self.proc = None
        self.frame = None
        self.txt = None
        self.status = "running"     # running | ok | error | stopped
        self.returncode = None
        self.queue: list = []       # itens de lote ainda não iniciados: (cmd, label)
        self.queue_total = 0
        self.on_done = None         # callback de encadeamento do _launch
        self.current_asset = None   # asset anunciado no log (total de chunks)
        self.stopped = False

    def running(self) -> bool:
        return self.status == "running"


# ─── Main application ──────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        # Guardado em self: o Tk não é dono do PhotoImage, então deixá-lo ser
        # coletado derruba o ícone. Caminho absoluto porque o app nem sempre é
        # iniciado a partir da raiz do repo.
        try:
            self._icon_image = tk.PhotoImage(file=str(LOCAL / "subrim_icon.png"))
            self.iconphoto(True, self._icon_image)
        except tk.TclError as e:
            print(f"Ícone não carregado: {e}")
        self.geometry("1180x700")
        self.minsize(960, 600)

        # Modo da janela: "video" (pipeline completo) ou "texto" (só base.txt).
        # Define quais abas ficam visíveis e o escopo de Warehouse e Coleções.
        self._mode = tk.StringVar(value="video")
        self._text_mode = False   # espelho do _mode, seguro fora da thread do Tk
        self._text_selected = None

        # Itens: (msg, tag) → sub-aba Geral; (job_id, msg, tag) → sub-aba do job.
        self._log_q: queue.Queue = queue.Queue()
        # Processos em paralelo: job_id -> Job (inclui os já encerrados cuja
        # sub-aba ainda está aberta).
        self._jobs: dict = {}
        self._proc_lock = threading.Lock()
        self._selected = None
        self._selected_many: list = []   # seleção múltipla na lista de Assets
        # Ordenação da lista de Assets (clique no cabeçalho, como nas Coleções)
        self._assets_sort_col = None
        self._assets_sort_reverse = False
        self._assets_headers = {"name": "Asset", "status": "Status",
                                "progress": "Progresso", "duration": "Duração"}

        # DeepSeek debug viewer
        self._ds_debug_on = tk.BooleanVar(value=False)   # injeta DEEPSEEK_DEBUG=1
        self._ds_auto = tk.BooleanVar(value=False)        # auto-atualizar a lista
        self._ds_records: list = []

        # Collections tab state
        self._col_matches: list = []
        # Texto integral da última busca (normalizado). É o nome da pasta ao
        # salvar — a coleção inteira vai para uma só. Vazio antes da 1ª busca,
        # quando o botão Salvar ainda está desabilitado.
        self._col_query = ""
        # Modo da última busca: "word" (por palavra), "i+1" (busca "0") ou
        # "all" (busca "1"). Define como o status dos resultados é formatado —
        # antes isso era inferido dos dados, o que confundia os modos.
        self._col_mode = "word"
        self._col_sort_col = None
        self._col_sort_reverse = False
        self._col_index = 0
        # Filtro de assets: None = todos (sem filtro); set = só esses assets.
        self._col_asset_filter = None
        # Grupos abertos no pop-up de filtro (lembrados na sessão).
        self._col_filter_open: set = set()
        self._col_render_token = 0
        self._col_audio_token = 0
        self._col_audio_proc = None  # subprocess.Popen do afplay em curso, ou None
        self._col_photo = None
        self._col_view = self._col_view_load()
        # Tela cheia: Toplevel e Label enquanto aberta, senão None.
        self._col_fs = None
        self._col_fs_label = None
        self._col_fs_photo = None
        self._col_fs_loading = None   # aviso "Carregando…" sobre a imagem
        self._col_fs_done = 0         # token do último render já exibido
        self._col_saving = False
        # Últimas escolhas do pop-up de salvar (reabre nelas na mesma sessão).
        self._col_save_mode = "r36s"
        self._col_skip_zero = True
        self._col_make_bundle = False
        self._col_variants = False
        # Nota (0-10) da frase selecionada. A gravação no base é serializada numa
        # thread única, para que navegar em rajada vire poucas reescritas.
        self._nota_q: queue.Queue = queue.Queue()
        self._nota_typing = ""            # buffer de dígitos ("1" → "10")
        self._nota_typing_at = 0.0        # time.monotonic() do último dígito
        # Cronômetro de leitura (tempo por caractere)
        self._timing_active = False
        self._timing_records: list = []   # (n_caracteres, segundos) por imagem lida
        self._timing_start = None         # time.monotonic() do início da imagem atual
        self._timing_idx = None           # índice da imagem cujo tempo está correndo

        # Expected chunk-total cache: asset_name -> (base_mtime, total)
        self._chunk_total_cache: dict = {}
        self._total_fill_running = False
        # Duração do vídeo: asset_name -> (video_path, mtime, seconds)
        self._duration_cache: dict = {}
        self._duration_fill_running = False
        # Total de chunks lido ao vivo dos logs do pipeline: asset_name -> total
        self._live_chunk_total: dict = {}

        # Conexão com o servidor (campo "Servidor" do topo).
        self._prefs = _load_client_prefs()
        self._server_var = tk.StringVar(value=self._prefs.get("server", ""))
        self._attached_procs: set = set()   # ids remotos com sub-aba de log aberta

        self._setup_style()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        CLIENT.on_change(lambda ok, info: self.after(0, self._on_conn_change, ok, info))
        CLIENT.set_host(self._server_var.get())
        CLIENT.start_monitor()
        self._schedule_refresh()
        self._poll_log()
        self._nota_start_writer()

    def report_callback_exception(self, exc, val, tb):
        """Sem servidor, qualquer ação vira aviso na barra — não um traceback."""
        if isinstance(val, RemoteError):
            self._status_var.set("⚠ " + str(val).splitlines()[0][:90])
            self._log_line(f"⚠️ {val}", "warning")
            return
        super().report_callback_exception(exc, val, tb)

    # ── Conexão com o servidor ─────────────────────────────────────────────────
    def _apply_server(self, _=None):
        """Enter/sair do campo: aponta para o IP digitado e o guarda para a próxima vez."""
        texto = self._server_var.get().strip()
        if texto == self._prefs.get("server", "") and CLIENT.base:
            return
        self._prefs["server"] = texto
        _save_client_prefs(self._prefs)
        if not CLIENT.set_host(texto):
            self._conn_icon.config(foreground="#E74C3C")
            self._status_var.set("IP inválido" if texto else "Informe o IP do servidor")
            return
        self._conn_icon.config(foreground="#E67E22")   # tentando…
        self._status_var.set(f"Conectando a {CLIENT.base}…")

    def _on_conn_change(self, ok: bool, info: dict):
        if ok:
            self._conn_icon.config(foreground="#27AE60")
            self._conn_tip = f"Conectado a {info.get('host', '?')} ({CLIENT.base})"
            self._log_line(f"🔌 {self._conn_tip}", "success")
            self._update_job_controls()
            self._refresh_all()
            self._attach_remote_jobs()
        else:
            self._conn_icon.config(foreground="#E74C3C")
            self._conn_tip = ("Servidor não configurado" if not CLIENT.base
                              else f"Servidor inacessível ({CLIENT.base})")
            self._status_var.set(self._conn_tip)
            if CLIENT.base:
                self._log_line(f"🔌 {self._conn_tip}", "warning")

    def _refresh_all(self):
        """Recarrega as telas que vêm do servidor (ao conectar)."""
        for fn in (self._refresh_llm_labels, self._apply_mode, self._refresh_sources,
                   self._ytm_refresh, self._ds_refresh):
            try:
                fn()
            except RemoteError:
                return

    def _attach_remote_jobs(self):
        """Processos que já rodam no servidor (iniciados antes de abrir o app, ou
        antes de a rede cair) ganham uma sub-aba de log e seguem acompanhados."""
        def _work():
            try:
                lista = CLIENT.procs()
            except RemoteError:
                return
            self.after(0, lambda: self._attach_jobs(lista))
        threading.Thread(target=_work, daemon=True).start()

    def _attach_jobs(self, lista: list):
        for info in lista:
            if not info["running"] or info["id"] in self._attached_procs:
                continue
            job = self._new_job(info["label"])
            self._log_line(f"↪ Retomando o acompanhamento (processo #{info['id']} no servidor)",
                           "cmd", job)
            self._follow(job, sr.RemoteProc(info["id"]))
        self._update_job_controls()

    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("aqua")
        except tk.TclError:
            pass
        # Checkbox de grupo no pop-up de filtro de assets (Coleções).
        s.configure("Group.TCheckbutton", font=("", 12, "bold"))

    # ── UI construction ────────────────────────────────────────────────────────
    def _build_ui(self):
        bar = ttk.Frame(self, padding=(10, 5))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Subrim Manager", font=("", 14, "bold")).pack(side=tk.LEFT)

        # Servidor: IP (ou IP:porta) da máquina com o subrim_server. O ● fica
        # verde conectado, laranja tentando e vermelho sem conexão.
        srv = ttk.Frame(bar)
        srv.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(srv, text="Servidor", foreground="#777").pack(side=tk.LEFT)
        ent = ttk.Entry(srv, textvariable=self._server_var, width=16)
        ent.pack(side=tk.LEFT, padx=(6, 4))
        ent.bind("<Return>", self._apply_server)
        ent.bind("<KP_Enter>", self._apply_server)
        ent.bind("<FocusOut>", self._apply_server)
        self._conn_tip = ""
        self._conn_icon = ttk.Label(srv, text="●", font=("", 14),
                                    foreground="#E67E22" if self._server_var.get() else "#E74C3C")
        self._conn_icon.pack(side=tk.LEFT)
        self._conn_icon.bind("<Button-1>", lambda _: self._conn_tip and
                             self._status_var.set(self._conn_tip))

        self._status_var = tk.StringVar(value="Pronto")
        ttk.Label(bar, textvariable=self._status_var, foreground="#777").pack(side=tk.RIGHT, padx=8)
        self._stop_all_btn = ttk.Button(bar, text="⏹  Parar todos", command=self._stop_all,
                                        state=tk.DISABLED)
        self._stop_all_btn.pack(side=tk.RIGHT)

        # O toggle é empacotado por ÚLTIMO e com expand=True para ficar centrado
        # na barra: o pack só distribui a sobra depois que os widgets de largura
        # fixa das duas pontas já reservaram o espaço deles.
        toggle = ttk.Frame(bar)
        toggle.pack(side=tk.LEFT, expand=True)
        for rot, val in (("Vídeo", "video"), ("Texto", "texto")):
            ttk.Radiobutton(toggle, text=rot, value=val, variable=self._mode,
                            style="Toolbutton",
                            command=self._on_mode_change).pack(side=tk.LEFT)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # Ordem de criação = ordem final das abas em CADA modo. O Notebook.hide()
        # tira a aba da vista mas guarda a posição, então esconder as que não
        # pertencem ao modo já produz as duas sequências desejadas:
        #   Vídeo → Assets · Warehouse · Downloads · Coleções · Log · DeepSeek
        #   Texto → Assets · Warehouse · Coleções · Log
        self._build_assets_tab()
        self._build_text_assets_tab()
        self._build_warehouse_tab()
        self._build_downloads_tab()
        self._build_collections_tab()
        self._build_log_tab()
        self._build_deepseek_tab()
        self._apply_mode()

    # ── Modo Vídeo / Texto ─────────────────────────────────────────────────────
    def _is_text_mode(self) -> bool:
        return self._text_mode

    def _apply_mode(self):
        """Mostra/esconde as abas do modo atual e reaponta o escopo das compartilhadas."""
        self._text_mode = self._mode.get() == "texto"
        texto = self._text_mode
        # (aba, aparece_no_modo_texto)
        for tab, in_text in ((self._tab_assets, False),
                             (self._tab_text_assets, True),
                             (self._tab_downloads, False),
                             (self._tab_deepseek, False)):
            if in_text == texto:
                self._nb.add(tab)
            else:
                self._nb.hide(tab)

        self._wh_archive_btn.config(state=tk.DISABLED)
        # Restaurar só existe para vídeo (o HD espelha warehouse/, não text/).
        self._wh_restore_btn.config(state=tk.DISABLED if texto else tk.NORMAL)
        self._wh_open.clear()   # os grupos de um modo não existem no outro
        self._wh_refresh()
        self._col_clear_results()
        if texto:
            self._refresh_texts()
        else:
            self._refresh_assets()

    def _on_mode_change(self):
        self._apply_mode()
        self._log_line(
            f"🔀 Modo {'Texto' if self._is_text_mode() else 'Vídeo'}", "cmd")

    # ── Assets Tab ─────────────────────────────────────────────────────────────
    def _build_assets_tab(self):
        outer = ttk.Frame(self._nb)
        self._nb.add(outer, text="  Assets  ")
        self._tab_assets = outer

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

        cols = ("name", "status", "progress", "duration")
        # extended: ⇧+clique seleciona intervalo, ⌘+clique alterna (Aqua).
        t = ttk.Treeview(list_f, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            t.heading(c, text=self._assets_headers[c],
                      anchor=tk.W if c == "name" else tk.CENTER,
                      command=lambda c=c: self._assets_sort(c))
        t.column("name",     width=230, anchor=tk.W,      stretch=True)
        t.column("status",   width=120, anchor=tk.CENTER, stretch=False)
        t.column("progress", width=90,  anchor=tk.CENTER, stretch=False)
        t.column("duration", width=90,  anchor=tk.CENTER, stretch=False)

        vsb = ttk.Scrollbar(list_f, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.bind("<<TreeviewSelect>>", self._on_asset_select)
        t.bind("<Shift-Down>", lambda _: self._assets_extend_selection(1)  or "break")
        t.bind("<Shift-Up>",   lambda _: self._assets_extend_selection(-1) or "break")
        # Menu de contexto. No Tk do Aqua o botão direito chega como Button-2
        # (Button-3 é o do meio) — o inverso de X11/Windows — e Control+clique é
        # o clique secundário histórico do macOS. Os três são gestos de menu.
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            t.bind(seq, self._assets_context_menu)
        t.bind("<Double-1>", self._assets_open_video)

        for phase, (_, color) in PHASES.items():
            t.tag_configure(phase, foreground=color)
        self._tree = t

        self._assets_menu = tk.Menu(self, tearoff=0)
        self._assets_menu.add_command(label="Transcrever...", command=self._transcrever_selected)
        self._assets_menu.add_command(
            label="Abrir vídeo",
            command=lambda: self._selected and self._open_asset_video(self._selected["name"]))
        self._assets_menu.add_separator()
        self._assets_menu.add_command(label="Excluir...", command=self._excluir_selected)
        self._assets_menu.add_command(label="Expurgar...", command=self._assets_purge_selected)
        self._assets_hd_busy = False   # expurgo/restauro de assets em andamento

        # Right: detail panel — rolável inteiro (texto, opções, botões e fases),
        # para caber em janelas baixas e em seleções múltiplas longas.
        detail_outer = ttk.Frame(pw)
        pw.add(detail_outer, weight=1)
        dcanvas = tk.Canvas(detail_outer, highlightthickness=0, borderwidth=0)
        dvsb = ttk.Scrollbar(detail_outer, orient=tk.VERTICAL, command=dcanvas.yview)
        dcanvas.configure(yscrollcommand=dvsb.set)
        dvsb.pack(side=tk.RIGHT, fill=tk.Y)
        dcanvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail = ttk.Frame(dcanvas, padding=12)
        dwin = dcanvas.create_window((0, 0), window=detail, anchor=tk.NW)
        detail.bind("<Configure>",
                    lambda _: dcanvas.configure(scrollregion=dcanvas.bbox("all")))
        # O frame interno acompanha a largura visível (botões com fill=X).
        dcanvas.bind("<Configure>", lambda e: dcanvas.itemconfigure(dwin, width=e.width))
        self._detail_canvas = dcanvas

        ttk.Label(detail, text="Detalhes", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        self._detail_text = tk.StringVar(value="← Selecione um asset")
        ttk.Label(detail, textvariable=self._detail_text, justify=tk.LEFT,
                  wraplength=210, foreground="#555").pack(anchor=tk.W)

        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        ttk.Label(detail, text="Pipeline", font=("", 10, "bold")).pack(anchor=tk.W)

        ttk.Label(detail, text="Modo", foreground="#888").pack(anchor=tk.W)

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

        # Extrai o áudio do vídeo original (<asset>.mp3); o clean-up o leva para
        # assets/final/. Vale também no batch.
        self._extract_audio_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(detail, text="Extrair audio no assets/final",
                        variable=self._extract_audio_on).pack(anchor=tk.W, pady=(2, 2))
        # Envio ao Google Drive ao fim do pipeline (default: ligado). Desligado,
        # o Clean-up também deixa de exigir o upload. Vale também no batch.
        self._drive_upload_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(detail, text="Enviar para o drive",
                        variable=self._drive_upload_on,
                        command=self._on_drive_toggle).pack(anchor=tk.W, pady=(2, 2))

        # LLM dos pares/traduções desta queima (também no batch e no text
        # pipeline): DeepSeek (API) ou modelo local no Ollama. Ver llm_provider.py.
        ttk.Label(detail, text="LLM", foreground="#888").pack(anchor=tk.W, pady=(6, 0))
        # As duas rodam no servidor: esta máquina nunca chama a DeepSeek.
        self._llm_provider = tk.StringVar(value="deepseek")
        self._llm_radios = {}
        for value, text in (("deepseek", "DeepSeek"), ("local", "Local (Ollama)")):
            rb = ttk.Radiobutton(detail, text=text, value=value, variable=self._llm_provider,
                                 command=self._refresh_llm_status)
            rb.pack(anchor=tk.W, pady=(1, 1))
            self._llm_radios[value] = rb
        self._llm_status = tk.StringVar(value="")
        ttk.Label(detail, textvariable=self._llm_status, foreground="#888",
                  wraplength=210, justify=tk.LEFT).pack(anchor=tk.W)
        self._refresh_llm_status()

        ttk.Label(detail, text="Estilo", foreground="#888").pack(anchor=tk.W,
                                                                 pady=(6, 0))

        # Fundo opaco atrás da legenda: vale com ou sem pausas, e também no batch.
        self._burn_box_opaque_on = tk.BooleanVar(value=True)
        ttk.Checkbutton(detail, text="Queimar com fundo opaco",
                        variable=self._burn_box_opaque_on).pack(anchor=tk.W,
                                                                pady=(2, 2))
        # Frase traduzida em amarelo no topo, como nas Coleções (também no batch).
        self._burn_top_translation_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(detail, text="Queimar com tradução no topo",
                        variable=self._burn_top_translation_on).pack(anchor=tk.W,
                                                                     pady=(2, 2))
        # Quebra a legenda em várias linhas só quando numa linha os caracteres
        # se sobreporiam, como nas Coleções (também no batch).
        self._burn_multiline_on = tk.BooleanVar(value=False)
        ttk.Checkbutton(detail, text="Permitir múltiplas linhas",
                        variable=self._burn_multiline_on).pack(anchor=tk.W,
                                                               pady=(2, 2))

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

        # Roda do mouse/trackpad em qualquer ponto do painel rola o Canvas: uma
        # bindtag própria em cada widget, em vez de bind_all (que roubaria o
        # scroll da lista de Assets ao lado).
        def _detail_wheel(event):
            if dcanvas.yview() == (0.0, 1.0):
                return "break"   # conteúdo cabe inteiro: nada a rolar
            dcanvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
        self.bind_class("DetailScroll", "<MouseWheel>", _detail_wheel)
        stack = [dcanvas]
        while stack:
            w = stack.pop()
            w.bindtags(("DetailScroll",) + w.bindtags())
            stack.extend(w.winfo_children())

        self._refresh_assets()

    # ── Assets Tab (modo Texto) ────────────────────────────────────────────────
    def _build_text_assets_tab(self):
        """Assets do modo Texto: os ``assets/text/*.txt``.

        Aba separada da de vídeo (e não uma versão parametrizada dela) porque as
        duas telas são realmente diferentes: aqui não há fases, chunks, progresso
        nem clean-up — só "tem base.txt ou não tem".
        """
        outer = ttk.Frame(self._nb)
        self._nb.add(outer, text="  Assets  ")
        self._tab_text_assets = outer

        ctrl = ttk.Frame(outer, padding=(4, 6, 4, 2))
        ctrl.pack(fill=tk.X)
        ttk.Button(ctrl, text="↺", width=3, command=self._refresh_texts).pack(side=tk.LEFT)
        ttk.Label(ctrl, text="assets/text/*.txt  →  warehouse/text/*_base.txt",
                  foreground="#888").pack(side=tk.LEFT, padx=8)
        self._txt_count_var = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._txt_count_var,
                  foreground="#888").pack(side=tk.RIGHT, padx=6)

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        left = ttk.Frame(pw)
        pw.add(left, weight=3)
        cols = ("name", "status", "linhas", "frases")
        t = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        t.heading("name",   text="Texto",   anchor=tk.W)
        t.heading("status", text="Status",  anchor=tk.CENTER)
        t.heading("linhas", text="Linhas",  anchor=tk.CENTER)
        t.heading("frases", text="Frases",  anchor=tk.CENTER)
        t.column("name",   width=230, anchor=tk.W,      stretch=True)
        t.column("status", width=120, anchor=tk.CENTER, stretch=False)
        t.column("linhas", width=80,  anchor=tk.CENTER, stretch=False)
        t.column("frases", width=80,  anchor=tk.CENTER, stretch=False)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.tag_configure("archived", foreground="#27AE60")
        t.tag_configure("pending",  foreground="#E67E22")
        t.bind("<<TreeviewSelect>>", self._on_text_select)
        self._txt_tree = t

        detail = ttk.Frame(pw, padding=12)
        pw.add(detail, weight=1)
        ttk.Label(detail, text="Detalhes", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        self._txt_detail = tk.StringVar(value="← Selecione um texto")
        ttk.Label(detail, textvariable=self._txt_detail, justify=tk.LEFT,
                  wraplength=210, foreground="#555").pack(anchor=tk.W)

        ttk.Separator(detail, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)
        self._txt_run_btn = ttk.Button(detail, text="▶  Gerar base.txt",
                                       command=self._run_text_selected, state=tk.DISABLED)
        self._txt_run_btn.pack(fill=tk.X, pady=(3, 1))
        self._txt_force_btn = ttk.Button(detail, text="↺  Forçar reprocessamento",
                                         command=self._force_text_selected, state=tk.DISABLED)
        self._txt_force_btn.pack(fill=tk.X, pady=1)
        self._txt_open_btn = ttk.Button(detail, text="📂  Abrir pasta",
                                        command=self._open_text_folder, state=tk.DISABLED)
        self._txt_open_btn.pack(fill=tk.X, pady=1)

        self._refresh_texts()

    def _refresh_texts(self, *_):
        sel = self._text_selected["name"] if self._text_selected else None
        self._txt_tree.delete(*self._txt_tree.get_children())
        texts = core.list_texts() if CLIENT.connected else []
        for t in texts:
            status = "Arquivado ✓" if t["archived"] else "Aguardando"
            tag = "archived" if t["archived"] else "pending"
            self._txt_tree.insert("", tk.END, iid=t["name"], tags=(tag,),
                                  values=(t["name"], status, t["linhas"],
                                          t["frases"] or "—"))
        self._texts = {t["name"]: t for t in texts}
        n_arq = sum(1 for t in texts if t["archived"])
        self._txt_count_var.set(f"{n_arq}/{len(texts)} com base.txt")

        if sel and sel in self._texts:
            self._txt_tree.selection_set(sel)
        else:
            self._text_selected = None
            self._txt_detail.set("← Selecione um texto")
            for b in (self._txt_run_btn, self._txt_force_btn, self._txt_open_btn):
                b.config(state=tk.DISABLED)

    def _on_text_select(self, _=None):
        sel = self._txt_tree.selection()
        if not sel:
            return
        t = self._texts.get(sel[0])
        if not t:
            return
        self._text_selected = t
        estado = (f"base.txt com {t['frases']} frase(s)" if t["archived"]
                  else "sem base.txt")
        self._txt_detail.set(
            f"{t['name']}.txt\n{t['linhas']} linha(s)\n{estado}")
        self._txt_run_btn.config(
            state=tk.DISABLED if t["archived"] else tk.NORMAL)
        self._txt_force_btn.config(
            state=tk.NORMAL if t["archived"] else tk.DISABLED)
        self._txt_open_btn.config(state=tk.NORMAL)

    def _run_text_selected(self):
        if not self._text_selected:
            return
        name = self._text_selected["name"]
        self._launch([PY, str(REPO / "text_pipeline.py"), name],
                     label=f"Texto: {name}", pause_rate=0.0)

    def _force_text_selected(self):
        if not self._text_selected:
            return
        name = self._text_selected["name"]
        if messagebox.askyesno(
                "Confirmar",
                f"Reprocessar '{name}' do zero?\n"
                f"O warehouse/text/{name}_base.txt atual será descartado."):
            self._launch(
                [PY, str(REPO / "text_pipeline.py"), name, "--force"],
                label=f"Texto (force): {name}", pause_rate=0.0)

    def _open_text_folder(self):
        self._show_server_path(TEXTS)

    def _show_server_path(self, path):
        """As pastas moram no servidor: mostra o caminho de lá e o copia."""
        repo = CLIENT.info.get("repo", "")
        full = str(path) if str(path).startswith("/") else f"{repo}/{path}".rstrip("/.")
        self.clipboard_clear()
        self.clipboard_append(full)
        messagebox.showinfo("Pasta no servidor",
                            f"Esta pasta fica no servidor ({CLIENT.info.get('host', '?')}):\n\n"
                            f"{full}\n\nCaminho copiado para a área de transferência.")

    # ── Warehouse Tab ──────────────────────────────────────────────────────────
    def _build_warehouse_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Warehouse  ")
        self._tab_warehouse = outer

        # barra superior
        ctrl = ttk.Frame(outer)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(ctrl, text="↺  Atualizar", command=self._wh_refresh).pack(side=tk.LEFT)
        self._wh_archive_btn = ttk.Button(
            ctrl, text="🗄  Arquivar (trocar vídeo por frames)",
            command=self._wh_archive_selected, state=tk.DISABLED)
        self._wh_archive_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._wh_periods_btn = ttk.Button(
            ctrl, text="📐  Gerar períodos",
            command=self._wh_periods_selected, state=tk.DISABLED)
        self._wh_periods_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._wh_restore_btn = ttk.Button(
            ctrl, text="Restaurar...", command=self._wh_restore_dialog)
        self._wh_restore_btn.pack(side=tk.LEFT, padx=(8, 0))
        self._wh_restoring = False
        self._wh_count_var = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._wh_count_var, foreground="#888").pack(side=tk.RIGHT)
        self._wh_selected_base = None
        self._wh_archiving = False
        self._wh_purging = False

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # ── lista ──
        left = ttk.Frame(pw)
        pw.add(left, weight=2)

        # Árvore de dois níveis: grupo por prefixo ("Clone (32)") → bases. A
        # coluna #0 é o Nome, com a seta de expandir/recolher.
        wt = ttk.Treeview(left, columns=("status",), show="tree headings",
                          selectmode="extended")
        wt.heading("#0",     text="Nome",   anchor=tk.W)
        wt.heading("status", text="Status", anchor=tk.CENTER)
        wt.column("#0",     width=200, anchor=tk.W,      stretch=True)
        wt.column("status", width=160, anchor=tk.CENTER, stretch=False)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=wt.yview)
        wt.configure(yscrollcommand=vsb.set)
        wt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        wt.tag_configure("ok",       foreground="#27AE60")
        wt.tag_configure("archived", foreground="#2980B9")
        wt.tag_configure("missing",  foreground="#E74C3C")
        wt.tag_configure("group",    font=("", 12, "bold"))
        # Grupos abertos sobrevivem ao _wh_refresh (Atualizar, arquivar…).
        self._wh_open: set = set()
        wt.bind("<<TreeviewOpen>>",
                lambda _: self._wh_open.add(self._wh_tree.focus()))
        wt.bind("<<TreeviewClose>>",
                lambda _: self._wh_open.discard(self._wh_tree.focus()))
        wt.bind("<<TreeviewSelect>>", self._wh_on_select)
        wt.bind("<Double-1>", self._wh_open_in_collections)
        wt.bind("<Shift-Down>", lambda _: self._wh_extend_selection(1)  or "break")
        wt.bind("<Shift-Up>",   lambda _: self._wh_extend_selection(-1) or "break")
        # Menu de contexto (mesmos gestos da lista de frequências, abaixo).
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            wt.bind(seq, self._wh_context_menu)
        self._wh_tree = wt
        self._wh_menu = tk.Menu(self, tearoff=0)
        self._wh_menu.add_command(label="Expurgar...", command=self._wh_purge_selected)

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

        # Filtro por Conhecida + quantas linhas estão visíveis.
        fbar = ttk.Frame(right)
        fbar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(fbar, text="Conhecida:", foreground="#888").pack(side=tk.LEFT)
        self._wh_freq_filter = tk.StringVar(value="todas")
        for rot, val in (("Todas", "todas"), ("Sim", "sim"), ("Não", "nao")):
            ttk.Radiobutton(fbar, text=rot, value=val,
                            variable=self._wh_freq_filter,
                            command=self._wh_freq_refresh_view).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(fbar, text="Copiar tudo...",
                   command=self._wh_freq_copy_all).pack(side=tk.LEFT, padx=(12, 0))
        self._wh_freq_shown = tk.StringVar(value="")
        ttk.Label(fbar, textvariable=self._wh_freq_shown,
                  foreground="#888", font=("", 9)).pack(side=tk.RIGHT)

        freq_f = ttk.Frame(right)
        freq_f.pack(fill=tk.BOTH, expand=True)
        # Ordem: conteúdo da palavra à esquerda, metadados no fim.
        fcols = ("word", "pinyin", "traducao", "count", "conhecida")
        ft = ttk.Treeview(freq_f, columns=fcols, show="headings", selectmode="extended")
        ft.heading("word",      text="Palavra",      anchor=tk.W)
        ft.heading("pinyin",    text="Pinyin",       anchor=tk.W)
        ft.heading("traducao",  text="Tradução",     anchor=tk.W)
        ft.heading("count",     text="Ocorrências",  anchor=tk.CENTER)
        ft.heading("conhecida", text="Conhecida",    anchor=tk.CENTER)
        ft.column("word",      width=90,  anchor=tk.W,      stretch=False)
        ft.column("pinyin",    width=110, anchor=tk.W,      stretch=False)
        # "traducao" é o texto livre: absorve a sobra e mantém as duas últimas
        # colunas ancoradas à direita com largura fixa.
        ft.column("traducao",  width=170, anchor=tk.W,      stretch=True)
        ft.column("count",     width=80,  anchor=tk.CENTER, stretch=False)
        ft.column("conhecida", width=80,  anchor=tk.CENTER, stretch=False)
        # Linhas cujo pinyin/tradução vieram da word-api (entrada nua no base).
        ft.tag_configure("from_api", foreground="#2980B9")
        fvsb = ttk.Scrollbar(freq_f, orient=tk.VERTICAL, command=ft.yview)
        ft.configure(yscrollcommand=fvsb.set)
        ft.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fvsb.pack(side=tk.RIGHT, fill=tk.Y)
        ft.bind("<Button-1>", self._wh_freq_on_header_click)
        # Cópia: Ctrl+C, ⌘C e o evento virtual da plataforma.
        ft.bind("<Control-c>", self._wh_freq_copy_selection)
        ft.bind("<Command-c>", self._wh_freq_copy_selection)
        ft.bind("<<Copy>>",    self._wh_freq_copy_selection)
        # Menu de contexto. No Tk do Aqua o botão direito chega como Button-2
        # (Button-3 é o do meio) — o inverso de X11/Windows — e Control+clique é
        # o clique secundário histórico do macOS. Os três são gestos de menu.
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            ft.bind(seq, self._wh_freq_context_menu)
        self._wh_freq_tree = ft
        self._wh_freq_sort_col = "count"   # coluna de ordenação atual
        self._wh_freq_sort_reverse = True  # decrescente por padrão

        self._wh_freq_menu = tk.Menu(self, tearoff=0)
        self._wh_freq_menu.add_command(label="Copiar",
                                       command=self._wh_freq_copy_selection)

        ttk.Label(right, text="Azul = pinyin/tradução vindos da word-api",
                  foreground="#888", font=("", 9)).pack(anchor=tk.W, pady=(3, 0))

        self._wh_refresh()

    def _wh_root(self) -> RemotePath:
        """Diretório varrido pela aba Warehouse no modo atual."""
        return TEXT_WAREHOUSE if self._is_text_mode() else WAREHOUSE

    def _wh_refresh(self):
        """Recarrega a lista de base.txt do warehouse, agrupada por prefixo.

        Grupos ("Clone (32)") em ordem alfabética, "Outros" por último; dentro
        de cada grupo, ordem natural do nome legível (Clone 37 < Clone 100)."""
        self._wh_tree.delete(*self._wh_tree.get_children())
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        self._wh_freq_data = []
        self._wh_selected_base = None
        self._wh_detail.set("Selecione um arquivo para ver os detalhes.")

        if not CLIENT.connected:
            self._wh_count_var.set("sem servidor")
            return
        texto = self._is_text_mode()
        data = core.wh_rows(texto)
        if data["missing_root"]:
            self._wh_count_var.set(f"{data['missing_root']}/ não encontrada")
            return
        groups = data["groups"]
        complete, archived = data["complete"], data["archived"]
        bases = range(data["n_bases"])   # só a contagem é usada abaixo
        for key, nome, members in groups:
            gid = f"grp:{key or ''}"
            n_ok  = sum(1 for r in members if r[3] == "ok")
            n_arq = sum(1 for r in members if r[3] == "archived")
            n_mis = sum(1 for r in members if r[3] == "missing")
            resumo = " · ".join(t for t in (
                f"{n_ok} completo(s)" if n_ok else "",
                f"{n_arq} arquiv." if n_arq else "",
                f"{n_mis} falta vídeo" if n_mis else "") if t)
            self._wh_tree.insert("", tk.END, iid=gid, text=f"{nome}  ({len(members)})",
                                 values=(resumo,), tags=("group",),
                                 open=gid in self._wh_open)
            for bf, readable, status, tag in members:
                self._wh_tree.insert(gid, tk.END, iid=str(bf), text=readable,
                                     values=(status,), tags=(tag,))

        n_grupos = sum(1 for k, _, _ in groups if k)
        grupos = f" · {n_grupos} grupo(s)"
        if texto:
            self._wh_count_var.set(f"{len(bases)} texto(s) arquivado(s){grupos}")
            return
        extra = f" · {archived} arquivado(s)" if archived else ""
        self._wh_count_var.set(f"{complete}/{len(bases)} com vídeo{extra}{grupos}")

    def _wh_selected_bases(self) -> list:
        """Bases da seleção, na ordem da árvore; um grupo vale todos os filhos."""
        tree = self._wh_tree
        sel = set(tree.selection())
        out = []
        for gid in tree.get_children():
            filhos = tree.get_children(gid)
            for iid in filhos:
                if gid in sel or iid in sel:
                    out.append(RemotePath(iid))
        return out

    def _wh_extend_selection(self, direction: int):
        """Estende a seleção com Shift+Seta (espelha a aba Coleções)."""
        focused = self._wh_tree.focus()
        if not focused:
            return
        nxt = self._wh_tree.next(focused) if direction > 0 else self._wh_tree.prev(focused)
        if not nxt:
            return
        self._wh_tree.selection_add(nxt)
        self._wh_tree.focus(nxt)
        self._wh_tree.see(nxt)

    def _wh_archivable_selection(self):
        """Bases selecionadas que ainda têm mp4 original (candidatas a arquivar)."""
        bases = self._wh_selected_bases()
        return core.wh_archivable(bases) if bases else []

    def _wh_update_archive_btn(self):
        """Habilita/rotula o botão conforme a seleção (1 ou vários com mp4)."""
        n = len(self._wh_archivable_selection())
        ocupado = self._wh_archiving or self._wh_purging or self._wh_restoring
        if n > 1:
            self._wh_archive_btn.config(text=f"🗄  Arquivar {n} selecionados")
        else:
            self._wh_archive_btn.config(text="🗄  Arquivar (trocar vídeo por frames)")
        self._wh_archive_btn.config(
            state=(tk.NORMAL if (n and not ocupado) else tk.DISABLED))
        # Gerar períodos não precisa de mp4 — vale para qualquer base selecionado.
        self._wh_periods_btn.config(
            state=(tk.NORMAL if (self._wh_selected_bases() and not ocupado)
                   else tk.DISABLED))

    def _wh_on_select(self, _=None):
        sel = self._wh_tree.selection()
        self._wh_update_archive_btn()
        if not sel:
            return
        # Detalhes: mostra o item com foco (ou o primeiro da seleção).
        focus = self._wh_tree.focus()
        item = focus if focus in sel else sel[0]
        if item.startswith("grp:"):
            self._wh_show_group(item)
            return
        bf = RemotePath(item)
        self._wh_selected_base = bf

        # análise (em thread para não travar a UI) — fonte, períodos e a
        # frequência de palavras vêm todos do servidor.
        self._wh_detail.set("Analisando…")
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        texto = self._is_text_mode()

        def _work():
            try:
                info = core.wh_select_info(bf, texto)
                stats = core.wh_analyse(bf)
            except RemoteError as e:
                erro = f"Erro: {e}"
                self.after(0, lambda: self._wh_detail.set(erro))
                return
            detail = (
                f"Arquivo : {bf.name}\n"
                f"{info['fonte_rot']} : {info['fonte_line']}\n"
                f"Períodos: {info['periods_line']}\n"
                f"\n"
                f"Palavras distintas : {stats['total_words']}\n"
                f"  Conhecidas (nuas ou dominadas) : {stats['known']}\n"
                f"  A aprender : {stats['unknown']}"
            )
            freq = stats["freq"]
            self.after(0, lambda: self._wh_show_details(detail, freq))

        threading.Thread(target=_work, daemon=True).start()

    def _wh_open_in_collections(self, event):
        """Duplo clique num episódio: abre-o nas Coleções com todas as frases.

        Filtro só com ele e busca "1". Num grupo, segue o padrão (abrir/fechar)."""
        iid = self._wh_tree.identify_row(event.y)
        if not iid or iid.startswith("grp:"):
            return None
        prefix = RemotePath(iid).stem.replace("_base", "")
        self._col_asset_filter = {prefix}
        self._col_update_filter_btn()
        self._col_word.set("1")
        self._nb.select(self._tab_collections)
        self._col_do_search()
        return "break"

    def _wh_show_group(self, gid: str):
        """Detalhes de um grupo: contagem por status; a frequência fica vazia."""
        self._wh_selected_base = None
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        self._wh_freq_data = []
        self._wh_freq_shown.set("")
        tree = self._wh_tree
        filhos = tree.get_children(gid)
        tags = [tree.item(i, "tags")[0] for i in filhos]
        self._wh_detail.set(
            f"Grupo   : {tree.item(gid, 'text')}\n"
            f"\n"
            f"Bases          : {len(filhos)}\n"
            f"  Completos    : {tags.count('ok')}\n"
            f"  Arquivados   : {tags.count('archived')}\n"
            f"  Falta vídeo  : {tags.count('missing')}\n"
            f"\n"
            f"Arquivar / Gerar períodos agem sobre o grupo inteiro.")

    def _wh_periods_selected(self):
        """(Re)gera o ``*_periods.txt`` dos bases selecionados.

        O base não é tocado — o arquivo de períodos é um segundo arquivo, com o
        mesmo formato, onde cada linha é uma frase inteira em vez do pedaço que
        coube na legenda. É dele que o arquivamento passa a tirar os frames.

        Episódio já arquivado POR PERÍODOS é pulado: os frames dele estão
        numerados pelo arquivo atual, e regerá-lo trocaria a imagem de cada
        frase sem avisar. Para refazer, é preciso repor o vídeo original.
        """
        if self._wh_archiving:
            return

        bases = self._wh_selected_bases()
        if not bases:
            return

        self._nb.select(self._tab_log)
        self._log_line(f"📐 Gerando períodos para {len(bases)} base(s)…", "cmd")

        def _work():
            feito = pulado = erro = 0
            for bf in bases:
                prefix = bf.stem.replace("_base", "")
                if core.wh_frames_periods(prefix):
                    self._log_q.put((
                        f"    ↷ '{prefix}' já foi arquivado por períodos — mantido "
                        f"(os frames estão numerados pelo arquivo atual).", "warning"))
                    pulado += 1
                    continue
                try:
                    res = periods_base.generate(bf)
                    self._log_q.put((
                        "    ✓ " + periods_base.format_stats(RemotePath(res["path"]).name, res),
                        "success"))
                    feito += 1
                except Exception as e:  # noqa: BLE001
                    self._log_q.put((f"    Erro em '{prefix}': {e}", "error"))
                    erro += 1
            self._log_q.put((f"📐 Períodos: {feito} gerado(s), {pulado} pulado(s), "
                             f"{erro} com erro.", "success" if feito else "warning"))
            self.after(0, self._wh_refresh)

        threading.Thread(target=_work, daemon=True).start()

    def _wh_archive_selected(self):
        """Arquiva em lote os episódios selecionados que ainda têm mp4.

        Para cada um: gera o arquivo de períodos (se faltar), extrai 1 frame por
        FRASE para o cache (warehouse/frames_periods/<asset>/) e, dentro da
        tolerância a frames perdidos, apaga o mp4. Busca/preview/salvamento na
        aba Coleções seguem funcionando pelos frames. Um episódio com perda
        relevante mantém o vídeo.
        """
        if self._wh_archiving or self._wh_purging or self._wh_restoring:
            return
        cb = self._col_import()
        if not cb:
            return

        targets = self._wh_archivable_selection()  # [(bf, prefix, mp4)]
        if not targets:
            messagebox.showinfo("Arquivar",
                                "Selecione ao menos um episódio com mp4 original.")
            return

        total_gb = sum(mp4.stat().st_size for _, _, mp4 in targets) / (1024 ** 3)
        names = [_wh_readable_name(bf.stem) for bf, _, _ in targets]
        shown = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
        if not messagebox.askyesno(
                "Arquivar episódios",
                f"Arquivar {len(targets)} episódio(s)?\n\n"
                f"{shown}\n\n"
                f"• Gera o <asset>_periods.txt (frases inteiras) e extrai\n"
                f"  1 frame + 1 áudio por FRASE para warehouse/frames_periods/<asset>/\n"
                f"  e warehouse/audio_periods/<asset>/\n"
                f"• Depois APAGA o(s) mp4 (~{total_gb:.2f} GB no total)\n\n"
                f"Busca e visualização na aba Coleções seguem funcionando pelos "
                f"frames. Para reverter é preciso repor o vídeo original.\n\n"
                f"Continuar?"):
            return

        self._wh_archiving = True
        self._wh_archive_btn.config(state=tk.DISABLED)
        self._nb.select(self._tab_log)
        n = len(targets)
        self._log_line(f"🗄  Arquivamento em lote: {n} episódio(s)…", "cmd")

        def _work():
            summary = {"n": n, "done": 0, "kept": 0, "freed_gb": 0.0}
            for k, (bf, prefix, mp4) in enumerate(targets, 1):
                readable = _wh_readable_name(bf.stem)
                self._log_q.put((f"[{k}/{n}] 🗄  “{readable}” — extraindo frames…", "cmd"))

                def _progress(i, total, msg):
                    self._log_q.put((f"    ({i}/{total}) {msg}", "info"))

                try:
                    res = cb.archive_asset(prefix, progress_cb=_progress)
                except Exception as e:  # noqa: BLE001
                    self._log_q.put((f"    Erro ao arquivar '{prefix}': {e} — vídeo mantido.",
                                     "error"))
                    summary["kept"] += 1
                    continue

                outcome = self._wh_apply_archive_result(prefix, res, mp4)
                if outcome["archived"]:
                    summary["done"] += 1
                    summary["freed_gb"] += outcome["freed_gb"]
                else:
                    summary["kept"] += 1

            self.after(0, lambda: self._wh_batch_done(summary))

        threading.Thread(target=_work, daemon=True).start()

    def _wh_apply_archive_result(self, prefix: str, res: dict, mp4: Path) -> dict:
        """Aplica a tolerância e, se aprovado, remove o mp4. Roda na thread de
        trabalho e loga via fila. Retorna ``{"archived": bool, "freed_gb": float}``.
        """
        # Tolerância: uns poucos frames ilegíveis (tipicamente a última legenda,
        # cujo timestamp corrigido cai além do fim do vídeo) não impedem o
        # arquivamento; perda relevante mantém o vídeo.
        total = res["total"] or 1
        tolerance = max(2, int(total * 0.01))  # ≤2 frames ou ≤1% do total
        dropped = res.get("dropped", [])

        # Áudio nunca bloqueia o apagamento do mp4 — só a extração de frames
        # decide isso (mesma tolerância acima). Falha de áudio é só aviso.
        audio_ok = res.get("audio_ok", 0)
        audio_failed = res.get("audio_failed", 0)
        if audio_failed:
            self._log_q.put((
                f"    ⚠️  áudio: {audio_ok} ok, {audio_failed} falha(s) "
                f"(linhas {res.get('audio_dropped', [])[:20]}"
                f"{'…' if audio_failed > 20 else ''}).", "warning"))
        elif audio_ok:
            self._log_q.put((f"    🔊 áudio: {audio_ok} clipe(s) extraído(s).", "info"))

        if res["ok"] == 0 or res["failed"] > tolerance:
            self._log_q.put((
                f"    ⚠️  {res['failed']} frame(s) falharam ({res['ok']}/{res['total']}) — "
                f"acima da tolerância ({tolerance}). Vídeo NÃO apagado. "
                f"Linhas: {dropped[:20]}{'…' if len(dropped) > 20 else ''}", "warning"))
            return {"archived": False, "freed_gb": 0.0}

        if dropped:
            self._log_q.put((
                f"    ℹ️  {len(dropped)} frame(s) sem imagem (dentro da tolerância) — "
                f"linhas {dropped}. Essas frases não terão preview.", "warning"))

        try:
            freed = mp4.stat().st_size / (1024 ** 3)
            mp4.unlink()
            self._log_q.put((
                f"    ✓ “{prefix}” arquivado: {res['ok']} frames. "
                f"Vídeo removido (~{freed:.2f} GB).", "success"))
            return {"archived": True, "freed_gb": freed}
        except Exception as e:  # noqa: BLE001
            self._log_q.put((
                f"    ⚠️  Frames extraídos ({res['ok']}), mas falha ao apagar o mp4: {e}",
                "warning"))
            return {"archived": False, "freed_gb": 0.0}

    def _wh_batch_done(self, summary: dict):
        self._wh_archiving = False
        self._log_line(
            f"🗄  Lote concluído: {summary['done']} arquivado(s), "
            f"{summary['kept']} mantido(s). ~{summary['freed_gb']:.2f} GB liberados.",
            "success" if summary["done"] else "warning")
        messagebox.showinfo(
            "Arquivamento em lote",
            f"{summary['done']} de {summary['n']} episódio(s) arquivado(s).\n"
            f"{summary['kept']} mantido(s) (falha/tolerância).\n\n"
            f"~{summary['freed_gb']:.2f} GB liberados.")
        self._wh_refresh()
        self._wh_update_archive_btn()

    # ── Expurgo: move o episódio do warehouse para o HD externo ────────────────
    def _wh_context_menu(self, event):
        """Menu do botão direito na lista: 'Expurgar...' (só no modo Vídeo)."""
        row = self._wh_tree.identify_row(event.y)
        if not row:
            return "break"   # cabeçalho ou área vazia: não abre menu
        if row not in self._wh_tree.selection():
            # Fora da seleção: o menu age só sobre a linha clicada (um grupo
            # vale todos os episódios dele).
            self._wh_tree.selection_set(row)
            self._wh_tree.focus(row)
        n = len(self._wh_selected_bases())
        ok = (n > 0 and not self._is_text_mode()
              and not self._wh_purging and not self._wh_archiving
              and not self._wh_restoring)
        self._wh_menu.entryconfigure(
            0, label="Expurgar..." if n <= 1 else f"Expurgar {n} itens...",
            state=tk.NORMAL if ok else tk.DISABLED)
        try:
            self._wh_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._wh_menu.grab_release()
        return "break"

    def _wh_pick_drive(self):
        """HD externo de destino. None se não há (já avisa) ou se cancelou."""
        drives = core.external_drives()
        if not drives:
            messagebox.showerror(
                "Expurgar",
                "Nenhum HD externo gravável encontrado no servidor.\n\n"
                "Conecte o HD (ex.: SUBRIM) e tente de novo.")
            return None
        # Com vários, prefere os que já têm o warehouse espelhado.
        com_wh = [d for d in drives if (d / "warehouse").is_dir()]
        drives = com_wh or drives
        if len(drives) == 1:
            return drives[0]

        dlg = tk.Toplevel(self)
        dlg.title("Expurgar")
        dlg.transient(self)
        dlg.resizable(False, False)
        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Mais de um HD externo conectado. Expurgar para:").pack(anchor=tk.W)
        var = tk.StringVar(value=str(drives[0]))
        ttk.Combobox(frm, textvariable=var, values=[str(d) for d in drives],
                     state="readonly", width=40).pack(fill=tk.X, pady=8)
        chosen = {"v": None}

        def _ok():
            chosen["v"] = RemotePath(var.get())
            dlg.destroy()

        btns = ttk.Frame(frm)
        btns.pack(anchor=tk.E)
        ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="OK", command=_ok).pack(side=tk.LEFT)
        dlg.grab_set()
        self.wait_window(dlg)
        return chosen["v"]

    def _wh_purge_selected(self):
        """Expurga os episódios das frases selecionadas para <HD>/warehouse/.

        Serve tanto para o episódio completo (com mp4) quanto para o arquivado
        (só frames/áudio): leva o que existir, na mesma estrutura de pastas,
        confere e só então apaga do computador local.
        """
        if (self._wh_purging or self._wh_archiving or self._wh_restoring
                or self._is_text_mode()):
            return
        assets = [bf.stem.removesuffix("_base") for bf in self._wh_selected_bases()]
        if not assets:
            return
        cb = self._col_import()
        if not cb:
            return
        drive = self._wh_pick_drive()
        if drive is None:
            return
        dest = drive / "warehouse"

        plan = []   # [(asset, paths, bytes)]
        for a in assets:
            paths = cb.asset_footprint(a)
            if paths:
                plan.append((a, paths, cb.footprint_size(paths)))
        if not plan:
            messagebox.showinfo("Expurgar", "Nada desse(s) episódio(s) no warehouse local.")
            return

        total = sum(n for _, _, n in plan)
        try:
            livre = core.disk_free(drive)
        except OSError as e:
            messagebox.showerror("Expurgar", f"Não foi possível ler o HD {drive}:\n{e}")
            return
        if total > livre:
            messagebox.showerror(
                "Expurgar",
                f"Espaço insuficiente em {drive.name}: precisa de "
                f"{total / 1024**3:.2f} GB, livre {livre / 1024**3:.2f} GB.")
            return

        linhas = []
        for a, paths, n in plan[:5]:
            estado = ("com vídeo" if any(p.suffix == ".mp4" for p in paths)
                      else "arquivado")
            linhas.append(f"“{_wh_readable_name(a)}” ({estado}, {n / 1024**2:.0f} MB)")
            if len(plan) == 1:
                linhas += [f"    • {rel}" + (f"/ ({n} arquivo(s))" if n is not None else "")
                           for rel, n in core.path_summary(paths)]
        if len(plan) > 5:
            linhas.append(f"… e mais {len(plan) - 5} episódio(s)")
        if not messagebox.askyesno(
                "Expurgar vídeo" if len(plan) == 1 else "Expurgar vídeos",
                f"Expurgar para {dest}?\n\n"
                + "\n".join(linhas)
                + f"\n\nTotal ~{total / 1024**2:.0f} MB · livre no HD: "
                  f"{livre / 1024**3:.0f} GB\n\n"
                  "Copia, confere e APAGA do computador local. Para recuperar, "
                  "basta copiar de volta do HD para o warehouse.",
                icon=messagebox.WARNING, default=messagebox.NO):
            return

        self._wh_purging = True
        self._log_line(f"📦 Expurgo: {len(plan)} episódio(s) → {dest}", "cmd")

        def _wait_notes():
            # Notas pendentes gravam no _base.txt que vai sair daqui: espera a
            # fila esvaziar e a janela de coalescência do escritor passar.
            for _ in range(50):
                if self._nota_q.empty():
                    break
                time.sleep(0.1)
            time.sleep(0.5)

        self._hd_batch(
            [a for a, _, _ in plan], lambda a, pcb: cb.purge_asset(a, dest, progress_cb=pcb),
            emoji="📦", erro="expurgar", feito="movidos para o HD", before=_wait_notes,
            on_done=lambda summary: self._wh_purge_done(summary, dest))

    def _wh_purge_done(self, summary: dict, dest: Path):
        self._wh_purging = False
        ok = set(summary["ok"])
        if ok:
            self._wh_refresh()
            self._wh_update_archive_btn()
            # Frases desses episódios na busca das Coleções não têm mais
            # base/frames locais: saem da lista.
            if any(m.get("asset") in ok for m in self._col_matches):
                self._col_show_results([m for m in self._col_matches
                                        if m.get("asset") not in ok])
        self._hd_report("Expurgar", summary, "📦 Expurgo", "liberados",
                        f"episódio(s) expurgado(s) para {dest}.",
                        "liberados no computador.", "mantidos no computador")

    # ── Lote HD externo (expurgo/restauro de warehouse e assets) ─────────────
    def _hd_batch(self, names: list, fn, emoji: str, erro: str, feito: str,
                  on_done, before=None):
        """Roda ``fn(nome, progress_cb)`` para cada nome numa thread, logando via
        fila; no fim chama ``on_done(summary)`` na thread da UI.

        ``summary`` = ``{"ok": [...], "failed": [...], "bytes": int}``."""
        def _work():
            if before:
                before()
            summary = {"ok": [], "failed": [], "bytes": 0}
            for k, a in enumerate(names, 1):
                self._log_q.put((f"[{k}/{len(names)}] {emoji} “{_wh_readable_name(a)}”…", "cmd"))

                def _progress(i, n, msg):
                    self._log_q.put((f"    ({i}/{n}) {msg}", "info"))

                try:
                    res = fn(a, _progress)
                except Exception as e:  # noqa: BLE001
                    self._log_q.put((f"    ❌ Erro ao {erro} '{a}': {e}", "error"))
                    summary["failed"].append(a)
                    continue
                summary["ok"].append(a)
                summary["bytes"] += res["bytes"]
                self._log_q.put((
                    f"    ✓ {res['files']} arquivo(s), "
                    f"{res['bytes'] / 1024**2:.0f} MB {feito}.", "success"))
            self.after(0, lambda: on_done(summary))

        threading.Thread(target=_work, daemon=True).start()

    def _hd_report(self, title: str, summary: dict, log_prefix: str, log_gb: str,
                   msg_ok: str, msg_gb: str, failed_note: str, extra: str = ""):
        """Linha final no Log + resumo em messagebox de um ``_hd_batch``."""
        ok = summary["ok"]
        gb = summary["bytes"] / 1024**3
        self._log_line(
            f"{log_prefix} concluído: {len(ok)} ok, {len(summary['failed'])} falha(s). "
            f"~{gb:.2f} GB {log_gb}.", "success" if ok else "warning")
        msg = f"{len(ok)} {msg_ok}\n~{gb:.2f} GB {msg_gb}" + (f"\n{extra}" if extra else "")
        if summary["failed"]:
            msg += (f"\n\nFalharam ({failed_note}; veja o Log):\n"
                    + "\n".join(f"  • {_wh_readable_name(a)}" for a in summary["failed"][:10]))
            messagebox.showwarning(title, msg)
        else:
            messagebox.showinfo(title, msg)

    @staticmethod
    def _hd_ask_restore(parent, plan: list, status: dict, onde: str):
        """Confirma o restauro e pergunta o destino da cópia do HD.

        ``plan`` = [(nome, bytes)]. Devolve True (apagar do HD), False (manter)
        ou None (cancelar)."""
        total = sum(n for _, n in plan)
        linhas = [f"“{_wh_readable_name(a)}” ({status[a].lower()}, "
                  f"{n / 1024**2:.0f} MB)" for a, n in plan[:5]]
        if len(plan) > 5:
            linhas.append(f"… e mais {len(plan) - 5} item(ns)")
        return messagebox.askyesnocancel(
            "Restaurar",
            f"Restaurar {len(plan)} item(ns) para {onde}?\n\n"
            + "\n".join(linhas)
            + f"\n\nTotal ~{total / 1024**2:.0f} MB\n\n"
              "Apagar a cópia do HD depois de restaurar?\n\n"
              "Sim = restaura e apaga do HD\n"
              "Não = restaura e mantém no HD\n"
              "Cancelar = não faz nada",
            default=messagebox.CANCEL, parent=parent)

    # ── Restauro: traz episódios do HD externo de volta ao warehouse ─────────
    def _wh_restore_dialog(self):
        """Abre o modal com os episódios do HD externo (botão "Restaurar...")."""
        if self._is_text_mode():
            return
        if self._wh_archiving or self._wh_purging or self._wh_restoring:
            messagebox.showinfo("Restaurar",
                                "Aguarde o arquivamento/expurgo/restauro em andamento.")
            return
        cb = self._col_import()
        if not cb:
            return
        drive = self._wh_pick_drive()
        if drive is None:
            return
        hd = drive / "warehouse"
        if not hd.is_dir():
            messagebox.showerror("Restaurar", f"Esse HD não tem warehouse/:\n{drive}")
            return

        def _scan():
            return core.wh_restore_status(hd)

        RestoreDialog(self, hd, title="Restaurar do HD", scan=_scan,
                      size=lambda a: cb.footprint_size(cb.asset_footprint(a, hd)),
                      local_root=WAREHOUSE, onde="o warehouse local",
                      run=lambda plan, delete: self._wh_restore_run(hd, plan, delete))

    def _wh_restore_run(self, hd: Path, plan: list, delete_src: bool):
        """Restaura em thread. ``plan`` = [(asset, bytes)]."""
        self._wh_restoring = True
        self._wh_update_archive_btn()
        acao = "apagando do HD" if delete_src else "mantendo no HD"
        self._log_line(f"📥 Restauro: {len(plan)} episódio(s) de {hd} ({acao})", "cmd")
        self._hd_batch(
            [a for a, _ in plan],
            lambda a, pcb: cb.restore_asset(a, hd, delete_src=delete_src, progress_cb=pcb),
            emoji="📥", erro="restaurar", feito="restaurados",
            on_done=lambda summary: self._wh_restore_done(summary, hd, delete_src))

    def _wh_restore_done(self, summary: dict, hd: Path, delete_src: bool):
        self._wh_restoring = False
        if summary["ok"]:
            self._wh_refresh()
        self._wh_update_archive_btn()
        self._hd_report("Restaurar", summary, "📥 Restauro", "trazidos",
                        f"episódio(s) restaurado(s) de {hd}.",
                        "trazidos para o computador.", "intactos no HD",
                        "Cópias apagadas do HD." if delete_src else "Cópias mantidas no HD.")

    def _wh_show_details(self, detail: str, freq: list):
        self._wh_detail.set(detail)
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        self._wh_freq_data = freq   # armazena para reclassificação
        # Popula com dados (respeita ordenação)
        self._wh_freq_refresh_view()

    def _wh_freq_refresh_view(self):
        """Recarrega a tabela respeitando ordenação e filtro atuais."""
        self._wh_freq_tree.delete(*self._wh_freq_tree.get_children())
        if not hasattr(self, "_wh_freq_data"):
            return

        # Filtro por Conhecida. Lê o bool de _wh_freq_data, não o "Sim"/"Não" da
        # tela — a string é só apresentação.
        modo = self._wh_freq_filter.get()
        dados = self._wh_freq_data
        if modo == "sim":
            dados = [r for r in dados if r["conhecida"]]
        elif modo == "nao":
            dados = [r for r in dados if not r["conhecida"]]

        # .get para uma coluna nova sem chave aqui não derrubar a tabela.
        sort_key = {
            "word":      lambda r: r["word"],
            "pinyin":    lambda r: (r["pinyin"] == "", r["pinyin"]),
            "traducao":  lambda r: (r["traducao"] == "", r["traducao"]),
            "count":     lambda r: r["count"],
            # Desconhecidas primeiro (False antes de True), empate alfabético
            "conhecida": lambda r: (not r["conhecida"], r["word"]),
        }.get(self._wh_freq_sort_col, lambda r: r["count"])
        dados = sorted(dados, key=sort_key, reverse=self._wh_freq_sort_reverse)

        for r in dados:
            self._wh_freq_tree.insert(
                "", tk.END,
                values=(r["word"], r["pinyin"], r["traducao"], r["count"],
                        "Sim" if r["conhecida"] else "Não"),
                tags=("from_api",) if r["from_api"] else ())

        total = len(self._wh_freq_data)
        self._wh_freq_shown.set(f"mostrando {len(dados)} de {total}" if total else "")

    def _wh_freq_on_header_click(self, event):
        """Detecta clique no header da tabela de frequência para ordenar."""
        region = self._wh_freq_tree.identify_region(event.x, event.y)
        if region != "heading":
            return
        col_index = self._wh_freq_tree.identify_column(event.x)
        # Mapeia índice de coluna para nome
        col_name = self._wh_freq_tree.heading(col_index)["text"]
        col_map = {"Palavra": "word", "Pinyin": "pinyin", "Tradução": "traducao",
                   "Ocorrências": "count", "Conhecida": "conhecida"}
        col = col_map.get(col_name)
        if not col:
            return
        # Se clicar na mesma coluna, inverte ordem; senão usa decrescente por padrão
        if self._wh_freq_sort_col == col:
            self._wh_freq_sort_reverse = not self._wh_freq_sort_reverse
        else:
            self._wh_freq_sort_col = col
            self._wh_freq_sort_reverse = True  # decrescente por padrão
            if col in ("word", "pinyin", "traducao"):
                self._wh_freq_sort_reverse = False  # texto: alfabético crescente
        self._wh_freq_refresh_view()

    def _wh_freq_copy_selection(self, _=None):
        """Copia as palavras selecionadas, uma por linha (Ctrl+C, ⌘C ou o menu)."""
        sel = set(self._wh_freq_tree.selection())
        if not sel:
            return
        # Percorre a ORDEM EXIBIDA (get_children) e não a ordem de clique que o
        # selection() devolveria.
        self._wh_freq_copy_words(
            [iid for iid in self._wh_freq_tree.get_children() if iid in sel])

    def _wh_freq_copy_all(self):
        """Copia todas as palavras visíveis (já filtradas), uma por linha."""
        self._wh_freq_copy_words(self._wh_freq_tree.get_children())

    def _wh_freq_copy_words(self, iids):
        # str() porque o Tk converte valores que parecem número de volta para
        # int — palavras como "71" existem no corpus e faziam o join estourar
        # TypeError.
        words = []
        for iid in iids:
            values = self._wh_freq_tree.item(iid)["values"]
            if values:
                words.append(str(values[0]))
        if words:
            self.clipboard_clear()
            self.clipboard_append("\n".join(words))
            self._log_q.put((f"📋 {len(words)} palavra(s) copiada(s).", "info"))

    def _wh_freq_context_menu(self, event):
        """Menu flutuante com 'Copiar' no botão direito (ou Control+clique)."""
        row = self._wh_freq_tree.identify_row(event.y)
        if not row:
            return "break"   # cabeçalho ou área vazia: não abre menu
        # Clicar fora da seleção passa a seleção para a linha clicada; clicar
        # dentro preserva a multi-seleção. Sem isso o Copiar agiria sobre algo
        # que o usuário não vê selecionado.
        if row not in self._wh_freq_tree.selection():
            self._wh_freq_tree.selection_set(row)
        self._wh_freq_tree.focus(row)

        n = len(self._wh_freq_tree.selection())
        self._wh_freq_menu.entryconfigure(
            0, label="Copiar palavra" if n <= 1 else f"Copiar {n} palavras")
        try:
            self._wh_freq_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._wh_freq_menu.grab_release()
        return "break"       # Control+clique não deve cair no <Button-1>

    # ── Downloads & Scraping Tab ───────────────────────────────────────────────
    def _build_downloads_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Downloads & Scraping  ")
        self._tab_downloads = outer

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: source files manager
        src_f = ttk.LabelFrame(pw, text="  Arquivos Source  ", padding=8)
        pw.add(src_f, weight=1)

        btn_row = ttk.Frame(src_f)
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="+ Novo Scraping", command=self._new_scraping_dialog).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="↺", width=3, command=self._refresh_sources).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Restaurar...",
                   command=self._assets_restore_dialog).pack(side=tk.LEFT)

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
        gp.pack(fill=tk.X, pady=(0, 12))

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

        # YouTube Monitor: editor do youtube_channels.json. Cada mudança é gravada
        # na hora — o cron relê o JSON a cada execução, então a próxima já usa o
        # estado novo.
        ym = ttk.LabelFrame(right, text="  YouTube Monitor  ", padding=10)
        ym.pack(fill=tk.BOTH, expand=True)

        ym_btns = ttk.Frame(ym)
        ym_btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        ttk.Button(ym_btns, text="+", width=3, command=self._ytm_add_dialog).pack(side=tk.LEFT)
        ttk.Button(ym_btns, text="−", width=3, command=self._ytm_remove).pack(side=tk.LEFT, padx=4)
        ttk.Button(ym_btns, text="↺", width=3, command=self._ytm_refresh).pack(side=tk.LEFT)
        ttk.Label(ym_btns, text="Duplo clique no prefixo edita · clique em Ativo alterna",
                  foreground="#888", font=("", 9)).pack(side=tk.RIGHT)

        ym_cols = ("name", "url", "prefix", "active")
        yt_tree = ttk.Treeview(ym, columns=ym_cols, show="headings", height=6,
                               selectmode="browse")
        yt_tree.heading("name",   text="Canal",   anchor=tk.W)
        yt_tree.heading("url",    text="URL",     anchor=tk.W)
        yt_tree.heading("prefix", text="Prefixo", anchor=tk.W)
        yt_tree.heading("active", text="Ativo",   anchor=tk.CENTER)
        yt_tree.column("name",   width=110, anchor=tk.W)
        yt_tree.column("url",    width=200, anchor=tk.W)
        yt_tree.column("prefix", width=90,  anchor=tk.W, stretch=False)
        yt_tree.column("active", width=50,  anchor=tk.CENTER, stretch=False)
        vsb_ym = ttk.Scrollbar(ym, orient=tk.VERTICAL, command=yt_tree.yview)
        yt_tree.configure(yscrollcommand=vsb_ym.set)
        yt_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb_ym.pack(side=tk.RIGHT, fill=tk.Y)
        yt_tree.bind("<Button-1>", self._ytm_on_click)
        yt_tree.bind("<Double-1>", self._ytm_on_double_click)
        self._ytm_tree = yt_tree
        self._ytm_cfg = {"defaults": {}, "channels": []}
        self._ytm_editor = None

        self._ytm_refresh()

    # ── Collections Tab ──────────────────────────────────────────────────────────
    def _build_collections_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  Coleções  ")
        self._tab_collections = outer

        # Search bar
        top = ttk.Frame(outer)
        top.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top, text="Termos ( , = ou · - = e ):").pack(side=tk.LEFT)
        self._col_word = tk.StringVar()
        e = ttk.Entry(top, textvariable=self._col_word, width=30, font=("", 14))
        e.pack(side=tk.LEFT, padx=6)
        e.bind("<Return>", lambda _: self._col_do_search())
        ttk.Button(top, text="🔍 Buscar", command=self._col_do_search).pack(side=tk.LEFT)
        self._col_filter_btn = ttk.Button(top, text="⚙ Filtro",
                                          command=self._col_open_filter_dialog)
        self._col_filter_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._col_vocab_btn = ttk.Button(top, text="↻ Vocab",
                                         command=self._col_reload_vocab)
        self._col_vocab_btn.pack(side=tk.LEFT, padx=(6, 0))
        # Vale na PRÓXIMA busca, como o ⚙ Filtro — não refiltra o resultado atual.
        self._col_hide_dups = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Ocultar duplicadas",
                        variable=self._col_hide_dups).pack(side=tk.LEFT, padx=(12, 0))
        self._col_status = tk.StringVar(
            value="著,當 = ou  ·  放-結束 = e  ·  0 = frases i+1  ·  1 = todas as frases")
        ttk.Label(top, textvariable=self._col_status, foreground="#888").pack(side=tk.LEFT, padx=12)

        pw = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: matches list
        left = ttk.Frame(pw)
        pw.add(left, weight=2)
        cols = ("palavra", "asset", "time", "frase", "nota")
        t = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended")
        self._col_headers = {"palavra": "Palavra", "asset": "Asset",
                             "time": "Tempo", "frase": "Frase", "nota": "Nota"}
        t.heading("palavra", text="Palavra", anchor=tk.W,
                  command=lambda: self._col_sort("palavra"))
        t.heading("asset", text="Asset",  anchor=tk.W,
                  command=lambda: self._col_sort("asset"))
        t.heading("time",  text="Tempo",  anchor=tk.CENTER,
                  command=lambda: self._col_sort("time"))
        t.heading("frase", text="Frase",  anchor=tk.W,
                  command=lambda: self._col_sort("frase"))
        t.heading("nota",  text="Nota",   anchor=tk.CENTER,
                  command=lambda: self._col_sort("nota"))
        t.column("palavra", width=60,  anchor=tk.W,      stretch=False)
        t.column("asset", width=100, anchor=tk.W,      stretch=False)
        t.column("time",  width=64,  anchor=tk.CENTER, stretch=False)
        # "frase" é a única que estica, então "nota" fica ancorada à direita.
        t.column("frase", width=220, anchor=tk.W,      stretch=True)
        t.column("nota",  width=48,  anchor=tk.CENTER, stretch=False)
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

        # Imagem à esquerda, stepper da nota à direita.
        mid = ttk.Frame(right)
        mid.pack(fill=tk.BOTH, expand=True, pady=6)

        self._col_preview = ttk.Label(mid, text="(preview r36s aparece aqui)",
                                      anchor=tk.CENTER, foreground="#888")
        self._col_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        nota_box = ttk.Frame(mid)
        nota_box.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Label(nota_box, text="Nota:", foreground="#888").pack(anchor=tk.CENTER)

        # Caixa focável: recebe as teclas só quando selecionada, para não roubar
        # as setas da tabela (que navegam entre as frases).
        self._nota_frame = tk.Frame(nota_box, highlightthickness=2,
                                    highlightbackground="#c8c8c8",
                                    highlightcolor="#c8c8c8",
                                    takefocus=True, bg=self.cget("bg"))
        self._nota_frame.pack(pady=(4, 6))
        self._nota_var = tk.StringVar(value="—")
        tk.Label(self._nota_frame, textvariable=self._nota_var, font=("", 26),
                 width=2, anchor=tk.CENTER, bg=self.cget("bg")).pack(padx=10, pady=6)

        btns = ttk.Frame(nota_box)
        btns.pack()
        ttk.Button(btns, text="∨", width=2,
                   command=lambda: self._nota_bump(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="∧", width=2,
                   command=lambda: self._nota_bump(1)).pack(side=tk.LEFT, padx=2)

        self._col_audio_btn = tk.Button(nota_box, text="🔇", font=("", 20),
                                        width=3, bg=self.cget("bg"),
                                        command=self._col_play_audio,
                                        state=tk.DISABLED)
        self._col_audio_btn.pack(pady=(10, 0))
        self._build_col_view_panel(nota_box)

        for w in (self._nota_frame, *self._nota_frame.winfo_children()):
            w.bind("<Button-1>", lambda _: self._nota_frame.focus_set())
        self._nota_frame.bind("<FocusIn>", self._nota_focus_in)
        self._nota_frame.bind("<FocusOut>", self._nota_focus_out)
        # Tab/Shift+Tab alternam entre a lista e a nota. São só dois destinos,
        # então os dois sentidos levam ao outro widget; o "break" impede o
        # traversal padrão do Tk de sair para os botões da barra.
        self._nota_bind_tab(self._col_tree, self._nota_frame)
        self._nota_bind_tab(self._nota_frame, self._col_tree)
        self._nota_frame.bind("<Up>",    lambda _: self._nota_bump(1)  or "break")
        self._nota_frame.bind("<Down>",  lambda _: self._nota_bump(-1) or "break")
        self._nota_frame.bind("<plus>",  lambda _: self._nota_bump(1)  or "break")
        self._nota_frame.bind("<minus>", lambda _: self._nota_bump(-1) or "break")
        for d in "0123456789":
            self._nota_frame.bind(
                f"<Key-{d}>", lambda _, d=d: self._nota_type_digit(d) or "break")

        # Caption: frase em chinês e tradução em português (selecionável para copiar)
        self._col_caption = tk.Text(right, height=4, font=("", 11), wrap=tk.WORD,
                                     state=tk.DISABLED, bg=self.cget("bg"),
                                     relief=tk.FLAT, bd=0)
        self._col_caption.pack(fill=tk.X, anchor=tk.W)

        # Tela cheia: botão no canto inferior direito da IMAGEM (que fica
        # centralizada no label), reposicionado a cada render e resize.
        self._col_expand_btn = tk.Button(self._col_preview, text="⛶", font=("", 14),
                                         takefocus=False,
                                         command=self._col_fullscreen_open)
        self._col_preview.bind("<Configure>", lambda _: self._col_place_expand())
        self._col_bind_mouse_nav(self._col_preview)

        # Atalhos da aba. No toplevel (todo widget da janela principal herda a
        # bindtag "."), filtrados pela aba ativa. Na lista, espaço e setas são
        # tratados ali mesmo com "break": o Treeview usa espaço para alternar
        # a seleção e ←/→ para abrir/fechar itens.
        self._col_bind_view_keys(self, guard=True)
        for seq, fn in (("<space>", lambda: self._col_step(1)),
                        ("<Left>", lambda: self._col_step(-1)),
                        ("<Right>", lambda: self._col_step(1))):
            self._col_tree.bind(seq, lambda _, fn=fn: fn() or "break")

        # Bottom: save
        bottom = ttk.Frame(outer)
        bottom.pack(fill=tk.X, pady=(6, 0))
        self._col_save_btn = ttk.Button(bottom, text="💾 Salvar coleção…",
                                        command=self._col_save, state=tk.DISABLED)
        self._col_save_btn.pack(side=tk.LEFT)
        ttk.Label(bottom, text="→ warehouse/collections/<palavra>_<formato>/",
                  foreground="#888").pack(side=tk.LEFT, padx=10)

    def _col_import(self):
        """O collection_builder do servidor (renderiza com o OpenCV de lá; aqui
        só o Pillow, para exibir). None — e avisa — se não há conexão."""
        try:
            from PIL import Image, ImageTk  # noqa: F401
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Dependência ausente",
                                 f"Não foi possível carregar o Pillow:\n{e}\n\n"
                                 "Instale com: pip install Pillow")
            return None
        if not CLIENT.connected:
            self._status_var.set("⚠ Sem conexão com o servidor")
            return None
        return cb

    def _col_available_assets(self) -> list:
        """Lista de assets disponíveis (a partir dos *_base.txt do warehouse do modo)."""
        return core.wh_available_assets(self._is_text_mode())

    # ── Nota: persistência serializada ──────────────────────────────────────────
    def _nota_start_writer(self):
        """Thread única que grava as notas no base, coalescendo rajadas.

        Selecionar uma frase já grava, então navegar com as setas dispara muita
        escrita. Após o primeiro item a thread espera uma janela curta e drena
        tudo o que chegou, colapsando por (asset, linha) e agrupando por asset —
        assim passar por 50 linhas do mesmo episódio vira UMA reescrita. Também
        neutraliza o estado intermediário de digitar "1" e depois "0" (=10).
        """
        def _work():
            while True:
                try:
                    item = self._nota_q.get()
                    time.sleep(0.2)   # janela de coalescência
                    pending = {}
                    while True:
                        asset, line_num, nota = item
                        pending[(asset, line_num)] = nota
                        try:
                            item = self._nota_q.get_nowait()
                        except queue.Empty:
                            break

                    by_asset: dict = {}
                    for (asset, line_num), nota in pending.items():
                        by_asset.setdefault(asset, {})[line_num] = nota

                    for asset, notes in by_asset.items():
                        try:
                            cb.set_notes(asset, notes, text=self._is_text_mode())
                        except Exception as e:  # noqa: BLE001
                            self._log_q.put(
                                (f"Erro ao gravar nota em {asset}: {e}", "error"))
                except Exception as e:  # noqa: BLE001 - a thread nunca deve morrer
                    self._log_q.put((f"Erro na fila de notas: {e}", "error"))

        threading.Thread(target=_work, daemon=True).start()

    def _nota_enqueue(self, match: dict, nota) -> bool:
        """Atualiza o match em memória e enfileira a gravação. Não toca na tabela.

        Devolve True se houve mudança (permite pular quem já tem a nota).
        """
        if match.get("nota") == nota:
            return False
        match["nota"] = nota
        self._nota_q.put((match["asset"], match["line_num"], nota))
        return True

    def _nota_persist(self, match: dict, nota):
        """Como ``_nota_enqueue``, mas reflete também na linha selecionada."""
        if not self._nota_enqueue(match, nota):
            return
        iid = str(self._col_index)
        if self._col_tree.exists(iid):
            vals = list(self._col_tree.item(iid, "values"))
            if vals:
                vals[-1] = "" if nota is None else str(nota)
                self._col_tree.item(iid, values=vals)

    def _nota_current_match(self):
        """Match selecionado, ou None se não há seleção válida."""
        if not self._col_matches:
            return None
        if not (0 <= self._col_index < len(self._col_matches)):
            return None
        return self._col_matches[self._col_index]

    def _nota_show(self, nota):
        """Atualiza só o visor do stepper."""
        self._nota_var.set("—" if nota is None else str(nota))

    def _nota_bump(self, delta: int):
        """Incrementa/decrementa a nota da frase selecionada e persiste."""
        m = self._nota_current_match()
        if m is None:
            return
        base = m.get("nota")
        if base is None:
            base = NOTA_DEFAULT
        novo = clamp_nota(base + delta)
        self._nota_typing = ""
        self._nota_persist(m, novo)
        self._nota_show(novo)

    def _nota_type_digit(self, digit: str):
        """Dígito digitado: define a nota direto; "1" seguido de "0" vira 10."""
        m = self._nota_current_match()
        if m is None:
            return
        agora = time.monotonic()
        # Só continua o número anterior se o dígito veio logo em seguida.
        if self._nota_typing == "1" and digit == "0" and (agora - self._nota_typing_at) < 1.0:
            self._nota_typing = "10"
        else:
            self._nota_typing = digit
        self._nota_typing_at = agora
        novo = clamp_nota(int(self._nota_typing))
        self._nota_persist(m, novo)
        self._nota_show(novo)

    def _nota_bind_tab(self, origem, destino):
        """Tab e Shift+Tab em ``origem`` levam o foco para ``destino``.

        ``<ISO_Left_Tab>`` é o keysym do Shift+Tab em alguns builds do Tk; nem
        todo build o aceita, daí o try.
        """
        def _go(_=None):
            destino.focus_set()
            return "break"

        for seq in ("<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>"):
            try:
                origem.bind(seq, _go)
            except tk.TclError:
                pass   # keysym inexistente neste build

    def _nota_focus_in(self, _=None):
        self._nota_frame.config(highlightbackground="#7048e8", highlightcolor="#7048e8")

    def _nota_focus_out(self, _=None):
        self._nota_typing = ""
        self._nota_frame.config(highlightbackground="#c8c8c8", highlightcolor="#c8c8c8")

    def _col_reload_vocab(self):
        """Recarrega da word-api quais palavras estão dominadas.

        O conjunto fica em cache pela sessão: é ele que decide, no render, quais
        palavras aparecem sem pinyin/tradução, e quais contam como conhecidas na
        busca i+1 e na coluna Conhecida do Warehouse.
        """
        self._col_vocab_btn.config(state=tk.DISABLED, text="↻ …")
        self._log_line("📚 Recarregando vocabulário da word-api…", "cmd")

        def _work():
            try:
                n = core.reload_mastered()
                self._log_q.put((f"✓ vocabulário recarregado: {n} palavra(s) dominada(s)",
                                 "success"))
            except Exception as e:  # noqa: BLE001
                n = None
                self._log_q.put((f"Erro ao recarregar vocabulário: {e}", "error"))
            self.after(0, lambda: self._col_reload_vocab_done(n))

        threading.Thread(target=_work, daemon=True).start()

    def _col_reload_vocab_done(self, n):
        self._col_vocab_btn.config(state=tk.NORMAL, text="↻ Vocab")
        if n is not None:
            self._col_status.set(f"Vocabulário: {n} dominada(s) — refaça a busca para aplicar")

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
        # Dois níveis: vírgula separa buscas independentes cujos resultados são
        # concatenados (OU, ex.: "著,當,與"); traço junta termos que precisam
        # aparecer na MESMA frase (E, ex.: "放-結束").
        #
        # O traço largo "－" é normalizado como a vírgula larga "，" já era.
        # Termos vazios ("放-", "-放", "放--結束") e repetidos ("放-放") somem aqui,
        # então o resto do fluxo só vê grupos já limpos.
        groups, seen = [], set()
        for term in raw.replace("，", ",").split(","):
            subs, sub_seen = [], set()
            for s in term.replace("－", "-").split("-"):
                s = s.strip()
                if s and s not in sub_seen:
                    sub_seen.add(s)
                    subs.append(s)
            if not subs:
                continue
            key = "-".join(subs)
            if key not in seen:
                seen.add(key)
                groups.append(subs)
        if not groups:
            messagebox.showwarning(
                "Aviso", "Digite um ou mais termos — vírgula = ou, traço = e (ex.: 著,放-結束).")
            return

        asset_filter = self._col_asset_filter  # None = todos
        is_text = self._is_text_mode()
        hide_dups = self._col_hide_dups.get()
        self._col_hidden_dups = 0

        self._col_status.set("Buscando…")
        self._col_tree.delete(*self._col_tree.get_children())
        self._col_matches = []
        # Nova busca: zera a ordenação e os indicadores (▲/▼) dos cabeçalhos.
        self._col_sort_col = None
        self._col_sort_reverse = False
        for c, base in self._col_headers.items():
            self._col_tree.heading(c, text=base)

        # Modos especiais por número:
        #   "0" → frases i+1 (0 ou 1 palavra desconhecida)
        #   "1" → TODAS as frases disponíveis (sem filtro de palavra)
        # Os números valem em QUALQUER posição — sozinhos, como termo da vírgula
        # ou dentro de um grupo com traço ("0-放" = i+1 que também contêm 放).
        # O modo aqui só escolhe o texto do status; quem despacha é o _work.
        if groups == [["0"]]:
            self._col_mode = "i+1"
        elif groups == [["1"]]:
            self._col_mode = "all"
        else:
            self._col_mode = "word"

        def _search_log(msg: str):
            tag = "warning" if msg.startswith("⚠️") else "info"
            self._log_q.put((msg, tag))

        def _apply_filter(matches):
            """Filtra por asset e, se pedido, remove frases repetidas.

            Os três modos passam por aqui — inclusive o de palavra, que chama
            isto inline dentro do _col_show_results. Fazer o dedup junto (e não
            num segundo passo) é o que garante que nenhum ramo fique de fora.

            Ordem importa: asset ANTES do dedup. No inverso, uma frase de um
            asset excluído pelo filtro poderia consumir a ocorrência e esconder a
            única cópia visível.

            Duplicatas são linhas distintas de bases distintas: ocultar uma não a
            apaga. Dar nota na cópia visível grava só na linha dela — as gêmeas
            escondidas mantêm a nota que tinham.
            """
            if asset_filter:
                matches = [m for m in matches if m.get("asset") in asset_filter]
            if not hide_dups:
                return matches
            matches, self._col_hidden_dups = cb.dedupe_sentences(matches)
            return matches

        scope = (f"{len(asset_filter)} asset(s) do filtro" if asset_filter
                 else "todos os assets")
        self._col_query = ", ".join("-".join(g) for g in groups)
        self._log_line(f"🔎 Buscando coleção: {self._col_query}", "cmd")

        def _work():
            """Um grupo de cada vez; os resultados são concatenados (vírgula = ou).

            Grupo de um termo só continua indo pela busca dedicada de hoje — é
            ela que produz o diagnóstico por base. Só o grupo com traço (E) cai
            no search_terms, que faz uma varredura avaliando todos os termos.
            """
            matches = []
            for g in groups:
                if g == ["0"]:
                    _search_log("🔎 Frases i+1 (≤1 palavra desconhecida)…")
                    matches.extend(cb.search_comprehensible(
                        log_cb=_search_log, max_unknown=1, text=is_text))
                elif g == ["1"]:
                    _search_log(f"🔎 TODAS as frases disponíveis ({scope})…")
                    matches.extend(cb.search_all(log_cb=_search_log, text=is_text))
                elif len(g) == 1:
                    matches.extend(cb.search(g[0], log_cb=_search_log, text=is_text))
                else:
                    matches.extend(cb.search_terms(
                        g, log_cb=_search_log, max_unknown=1, text=is_text))
            self.after(0, lambda: self._col_show_results(_apply_filter(matches)))

        threading.Thread(target=_work, daemon=True).start()

    def _col_show_results(self, matches: list):
        self._col_matches = matches
        self._col_tree.delete(*self._col_tree.get_children())
        for i, m in enumerate(matches):
            frase = (m["chinese"] or "").strip()
            nota = m.get("nota")
            pos = (str(m["line_num"]) if self._is_text_mode()
                   else f"{m['avg_time']:.1f}s")
            self._col_tree.insert("", tk.END, iid=str(i),
                                  values=(m.get("word", ""), m["asset"],
                                          pos, frase[:60],
                                          "" if nota is None else str(nota)))
        n = len(matches)
        if self._col_mode == "i+1":
            # A contagem de desconhecidas vem de n_unknown; "word" é sempre "0"
            # (o termo buscado), para o modo virar uma pasta só ao salvar.
            n0 = sum(1 for m in matches if m.get("n_unknown") == 0)
            status = f"{n} frase(s) — {n0} sem desconhecidas, {n - n0} com 1 desconhecida"
        elif self._col_mode == "all":
            n_assets = len({m.get("asset", "") for m in matches})
            status = f"{n} frase(s) (todas) em {n_assets} asset(s)"
        else:
            n_words = len({m.get("word", "") for m in matches})
            status = f"{n} frase(s) em {n_words} termo(s)"
        # Sem isso o efeito de "ocultar duplicadas" seria invisível. Vale para os
        # três modos, e sobrevive a ordenar/excluir porque mora em self.
        ocultas = getattr(self, "_col_hidden_dups", 0)
        if ocultas:
            status += f"  ·  {ocultas} duplicada(s) oculta(s)"
        self._col_status.set(status if n else "Nenhuma frase encontrada")
        self._col_save_btn.config(state=tk.NORMAL if n else tk.DISABLED)
        # Cronômetro: nova busca encerra qualquer sessão ativa e (re)habilita o botão.
        self._timing_reset()
        self._timing_btn.config(state=tk.NORMAL if n else tk.DISABLED)
        # Estado definitivo do botão de áudio é decidido por _col_render_current
        # (depende da frase, não só de haver resultado); aqui só cobre o caso
        # "nenhum resultado" (sem seleção pra disparar aquele render).
        self._col_set_audio_btn(False)
        self._col_preview.config(image="", text="(preview r36s aparece aqui)")
        self._col_photo = None
        self._col_place_expand()
        self._col_caption.config(state=tk.NORMAL)
        self._col_caption.delete("1.0", tk.END)
        self._col_caption.config(state=tk.DISABLED)
        self._col_pos.set(f"0/{n}")
        if n:
            self._col_tree.selection_set("0")
            self._col_tree.focus("0")
        else:
            self._nota_show(None)

    def _col_clear_results(self):
        """Zera a aba Coleções — os resultados são do escopo do modo anterior.

        Chamado na troca de Vídeo/Texto: manter na tela frases de um warehouse e
        salvar no outro produziria uma coleção com o frame errado (ou nenhum).
        O filtro de assets também vai junto, porque os nomes não se repetem
        entre os dois escopos.
        """
        self._col_asset_filter = None
        self._col_filter_open.clear()
        self._col_update_filter_btn()
        self._col_headers["time"] = "Linha" if self._is_text_mode() else "Tempo"
        for c, base in self._col_headers.items():
            self._col_tree.heading(c, text=base)
        self._col_query = ""
        self._col_hidden_dups = 0
        self._col_show_results([])
        self._col_status.set(
            "著,當 = ou  ·  放-結束 = e  ·  0 = frases i+1  ·  1 = todas as frases")

    def _col_on_select(self, _=None):
        sel = self._col_tree.selection()
        if not sel:
            return
        self._col_index = int(sel[0])
        if self._timing_active:
            self._timing_mark(self._col_index)
        self._nota_on_select()
        self._col_render_current()

    def _nota_on_select(self):
        """Mostra a nota da frase selecionada; sem nota, grava a padrão (5).

        Selecionar é o gesto que registra a frase como avaliada. Idempotente:
        quem já tem nota não é reescrito.
        """
        m = self._nota_current_match()
        if m is None:
            self._nota_show(None)
            return
        self._nota_typing = ""
        if m.get("nota") is None:
            self._nota_persist(m, NOTA_DEFAULT)
        self._nota_show(m.get("nota"))

    def _col_sort(self, col: str):
        """Ordena a lista de resultados pela coluna clicada (toggle asc/desc)."""
        if not self._col_matches:
            return
        reverse = (self._col_sort_col == col) and not self._col_sort_reverse
        keyfns = {
            "palavra": lambda m: m.get("word", ""),
            "asset":   lambda m: m.get("asset", ""),
            "time":    (lambda m: m.get("line_num", 0)) if self._is_text_mode() \
                       else (lambda m: m.get("avg_time", 0.0)),
            "frase":   lambda m: (m.get("chinese") or "").strip(),
            # sem nota vai para o fim na ordem crescente
            "nota":    lambda m: m.get("nota") if m.get("nota") is not None else -1,
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

        # Tirar a frase da lista é o gesto de reprová-la: grava nota 0 no base.
        # A fila coalesce e agrupa por asset, então excluir 50 de uma vez ainda
        # é uma reescrita por arquivo.
        zeradas = 0
        for i in to_delete:
            if 0 <= i < len(self._col_matches):
                if self._nota_enqueue(self._col_matches[i], 0):
                    zeradas += 1
        if zeradas:
            self._log_line(f"🗑️  {zeradas} frase(s) removida(s) da lista — nota 0 gravada.",
                           "info")

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
        self._col_set_audio_btn(cb.audio_available_for_match(m))
        self._col_caption.config(state=tk.NORMAL)
        self._col_caption.delete("1.0", tk.END)
        self._col_caption.insert(tk.END, f"{m['chinese']}\n{m['portuguese']}")
        self._col_caption.config(state=tk.DISABLED)
        if self._col_fs is None:
            self._col_preview.config(image="", text="Renderizando…")
            self._col_photo = None
            self._col_place_expand()
        self._col_rerender()
        # Só a troca de frase toca o áudio sozinha; redesenhar por um ajuste
        # do painel (ou ao sair da tela cheia) não.
        self._col_autoplay_token = self._col_render_token

    def _col_maybe_autoplay(self, token: int):
        """Toca o áudio quando a imagem de uma NOVA frase acaba de aparecer."""
        if (token == getattr(self, "_col_autoplay_token", None)
                and self._col_view["auto_audio"]
                and str(self._col_audio_btn.cget("state")) == tk.NORMAL):
            self._col_autoplay_token = None   # uma vez por frase
            self._col_play_audio()

    def _col_rerender(self):
        """Redesenha só a imagem da frase atual, com os ajustes do painel.

        Na tela cheia renderiza na resolução nativa do frame (mais nítida que
        ampliar o 640x480) e o resultado vai para a janela de tela cheia.
        """
        cb = self._col_import()
        m = self._nota_current_match()
        if not cb or m is None:
            return
        self._col_render_token += 1
        token = self._col_render_token
        fs = self._col_fs is not None
        style = self._col_view_style()
        if fs:
            # Só aparece se demorar: render rápido não pisca o aviso.
            self.after(150, lambda: self._col_fs_show_loading(token))

        def _work():
            try:
                img = cb.render_preview(m, "original" if fs else "r36s", style=style)
            except Exception as e:  # noqa: BLE001
                img = None
                self._log_q.put((f"Erro ao renderizar preview: {e}", "error"))
            self.after(0, lambda: self._col_set_preview(token, img, fs))

        threading.Thread(target=_work, daemon=True).start()

    def _col_set_audio_btn(self, available: bool):
        """Reflete a disponibilidade de áudio no botão — ícone E estado.

        Só desabilitar (``state=tk.DISABLED``) não é visível o bastante: no
        Tk, emoji coloridos como "🔊" não escurecem quando o botão desabilita
        (a cor do glifo vem da fonte de emoji, não do ``disabledforeground``),
        então habilitado e desabilitado pareciam idênticos. Trocar pro glifo
        "🔇" deixa o estado óbvio em qualquer plataforma.
        """
        self._col_audio_btn.config(
            state=tk.NORMAL if available else tk.DISABLED,
            text="🔊" if available else "🔇")

    def _col_play_audio(self):
        """Toca o áudio da frase atual — do cache, ou extraindo na hora do mp4."""
        m = self._nota_current_match()
        if m is None:
            return
        cb = self._col_import()
        if not cb:
            return

        self._col_audio_token += 1
        token = self._col_audio_token
        self._col_audio_btn.config(state=tk.DISABLED, text="⏳")

        def _work():
            # O clipe é gerado/lido no servidor e baixado para um temporário
            # local só para tocar (some no próximo clique ou ao fechar).
            try:
                remoto = cb.audio_clip_for_match(m)
                path = self._col_audio_local(remoto) if remoto is not None else None
            except Exception as e:  # noqa: BLE001
                path = None
                self._log_q.put((f"Erro ao extrair áudio: {e}", "error"))
            self.after(0, lambda: self._col_audio_ready(token, path))

        threading.Thread(target=_work, daemon=True).start()

    def _col_audio_ready(self, token: int, path):
        if token != self._col_audio_token:
            return  # um clique mais novo já assumiu
        self._col_set_audio_btn(path is not None)
        if path is None:
            messagebox.showinfo(
                "Áudio indisponível",
                "Não há clipe de áudio em cache para esta frase, e o vídeo "
                "original não está mais disponível (episódio arquivado antes "
                "deste recurso existir).")
            return
        self._col_play_path(path)

    def _col_audio_local(self, remoto) -> Path:
        data = CLIENT.fetch(remoto)
        old = getattr(self, "_col_audio_tmp", None)
        fd, tmp = tempfile.mkstemp(prefix="subrim_audio_", suffix=remoto.suffix or ".mp3")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        self._col_audio_tmp = tmp
        if old:
            try:
                os.unlink(old)
            except OSError:
                pass
        return Path(tmp)

    def _col_play_path(self, path):
        if self._col_audio_proc is not None and self._col_audio_proc.poll() is None:
            try:
                self._col_audio_proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._col_audio_proc = subprocess.Popen(["afplay", str(path)])
        except Exception as e:  # noqa: BLE001
            self._log_q.put((f"Erro ao tocar áudio: {e}", "error"))

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

    def _col_set_preview(self, token: int, img, fs: bool = False):
        if token != self._col_render_token:
            return  # uma seleção mais nova já começou a renderizar
        from PIL import Image, ImageTk
        if fs:
            if self._col_fs is None:
                return
            self._col_fs_done = token
            if img is None:
                self._col_fs_loading.config(text="Falha ao carregar a imagem")
                self._col_fs_loading.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
                return
            self._col_fs_loading.place_forget()
            self._col_fs_img, self._col_fs_size = img, None
            self._col_fs_fit()
            self._col_maybe_autoplay(token)
            return
        if img is None:
            self._col_preview.config(image="", text="(falha ao renderizar frame)")
            self._col_photo = None
            self._col_place_expand()
            return
        self._col_photo = ImageTk.PhotoImage(img)
        self._col_preview.config(image=self._col_photo, text="")
        self._col_maybe_autoplay(token)
        self._col_place_expand()

    # ── Painel de visualização (fundo, fonte, ocultar) ──────────────────────────
    @staticmethod
    def _col_view_load() -> dict:
        view = dict(VIEWER_DEFAULTS)
        try:
            salvo = json.loads(VIEWER_PREFS.read_text(encoding="utf-8"))
            view.update({k: type(VIEWER_DEFAULTS[k])(v) for k, v in salvo.items()
                         if k in VIEWER_DEFAULTS})
        except (OSError, ValueError, TypeError):
            pass   # sem arquivo (1ª vez) ou corrompido: padrões
        return view

    def _col_view_style(self) -> dict:
        """Ajustes do painel no formato de ``add_subtitles_to_frame(style=)``."""
        v = self._col_view
        return {"top_opaque": v["trad_opaque"], "top_scale": v["trad_scale"],
                "hide_top": v["trad_hide"], "bottom_opaque": v["leg_opaque"],
                "bottom_scale": v["leg_scale"], "hide_bottom": v["leg_hide"]}

    def _build_col_view_panel(self, parent):
        self._col_view_vars = {}
        self._col_scale_vars = {}
        # takefocus=False: com o foco num checkbox o espaço o alternaria,
        # além de tocar o áudio.
        for prefixo, titulo, atalhos in (
                ("trad", "Tradução", {"hide": "⌘T"}),
                ("leg", "Legenda", {"opaque": "⌘O", "hide": "⌘L", "font": "⌘− ⌘+"})):
            box = ttk.LabelFrame(parent, text=titulo, padding=(6, 2, 6, 4))
            box.pack(fill=tk.X, pady=(10, 0))
            for campo, rot in (("opaque", "Fundo opaco"), ("hide", "Ocultar")):
                key = f"{prefixo}_{campo}"
                var = tk.BooleanVar(value=self._col_view[key])
                self._col_view_vars[key] = var
                linha = ttk.Frame(box)
                linha.pack(fill=tk.X)
                ttk.Checkbutton(linha, text=rot, variable=var, takefocus=False,
                                command=lambda k=key: self._col_view_set(
                                    k, self._col_view_vars[k].get())
                                ).pack(side=tk.LEFT)
                if campo in atalhos:
                    ttk.Label(linha, text=atalhos[campo], foreground="#888").pack(side=tk.RIGHT)
                if campo == "opaque":
                    key_s = f"{prefixo}_scale"
                    fonte = ttk.Frame(box)
                    fonte.pack(fill=tk.X, pady=2)
                    ttk.Label(fonte, text="Fonte").pack(side=tk.LEFT)
                    for txt, d in (("−", -0.1), ("+", 0.1)):
                        ttk.Button(fonte, text=txt, width=2, takefocus=False,
                                   command=lambda k=key_s, d=d: self._col_view_bump(k, d)
                                   ).pack(side=tk.LEFT, padx=(2, 0))
                    self._col_scale_vars[key_s] = tk.StringVar()
                    ttk.Label(fonte, textvariable=self._col_scale_vars[key_s],
                              width=5, anchor=tk.E).pack(side=tk.LEFT, padx=(4, 0))
                    if "font" in atalhos:
                        ttk.Label(fonte, text=atalhos["font"],
                                  foreground="#888").pack(side=tk.RIGHT)
        self._col_view_vars["auto_audio"] = tk.BooleanVar(value=self._col_view["auto_audio"])
        ttk.Checkbutton(parent, text="Tocar áudio na transição", takefocus=False,
                        variable=self._col_view_vars["auto_audio"],
                        command=lambda: self._col_view_set(
                            "auto_audio", self._col_view_vars["auto_audio"].get())
                        ).pack(anchor=tk.W, pady=(10, 0))
        ttk.Label(parent, text="S: áudio\nEspaço: próxima\n← → frases\n"
                       "Clique na imagem: próxima\nBotão direito: anterior\n⌘F tela cheia",
                  foreground="#888", justify=tk.CENTER).pack(pady=(8, 0))
        self._col_view_sync()

    def _col_view_sync(self):
        for k, var in self._col_view_vars.items():
            var.set(self._col_view[k])
        for k, var in self._col_scale_vars.items():
            var.set(f"{round(self._col_view[k] * 100)}%")

    def _col_view_set(self, key: str, value):
        if key.endswith("_scale"):
            value = round(min(VIEWER_SCALE_MAX, max(VIEWER_SCALE_MIN, value)), 1)
        if self._col_view.get(key) == value:
            return
        self._col_view[key] = value
        self._col_view_sync()
        try:
            VIEWER_PREFS.write_text(json.dumps(self._col_view, indent=2), encoding="utf-8")
        except OSError as e:
            self._log_line(f"Erro ao gravar {VIEWER_PREFS.name}: {e}", "error")
        if key != "auto_audio":   # não muda o desenho
            self._col_rerender()

    def _col_view_toggle(self, key: str):
        self._col_view_set(key, not self._col_view[key])

    def _col_view_bump(self, key: str, delta: float):
        self._col_view_set(key, self._col_view[key] + delta)

    def _col_key_audio(self):
        if str(self._col_audio_btn.cget("state")) == tk.NORMAL:
            self._col_play_audio()

    def _col_bind_view_keys(self, widget, guard: bool):
        """Atalhos de visualização em ``widget`` (janela principal ou tela cheia).

        Com ``guard`` só valem na aba Coleções, e espaço/setas são ignorados
        quando o foco está num campo de texto (a busca)."""
        def _wrap(fn, typing_safe):
            def _h(_=None):
                if guard:
                    if self._nb.select() != str(self._tab_collections):
                        return None
                    try:
                        foco = self.focus_get()
                    except (KeyError, tk.TclError):
                        foco = None   # foco num popdown do Tk: não é campo de texto
                    if not typing_safe and foco is not None and \
                            foco.winfo_class() in ("Entry", "TEntry", "Text"):
                        return None
                fn()
                return "break"
            return _h

        acoes = [
            ("<Command-o>", lambda: self._col_view_toggle("leg_opaque"), True),
            ("<Command-t>", lambda: self._col_view_toggle("trad_hide"), True),
            ("<Command-l>", lambda: self._col_view_toggle("leg_hide"), True),
            ("<Command-plus>",  lambda: self._col_view_bump("leg_scale", 0.1), True),
            ("<Command-equal>", lambda: self._col_view_bump("leg_scale", 0.1), True),
            ("<Command-minus>", lambda: self._col_view_bump("leg_scale", -0.1), True),
            ("<Command-f>", self._col_fullscreen_open, True),
            # Tecla solta: como espaço e setas, ignorada ao digitar na busca.
            ("<Key-s>", self._col_key_audio, False),
            ("<Key-S>", self._col_key_audio, False),
            # Sem isto o Tk casa ⌘S com <Key-s> (modificador sobrando é ignorado).
            ("<Command-s>", lambda: None, True),
            ("<space>", lambda: self._col_step(1), False),
            ("<Left>",  lambda: self._col_step(-1), False),
            ("<Right>", lambda: self._col_step(1), False),
        ]
        for seq, fn, typing_safe in acoes:
            widget.bind(seq, _wrap(fn, typing_safe))

    def _col_bind_mouse_nav(self, widget):
        """Clique avança (como o espaço), botão direito volta.

        O botão direito é o Button-3, inclusive no macOS a partir do Tk 8.7/9;
        no Tk 8.6 do macOS (aqua) ele era o Button-2, e Ctrl+clique também
        conta como clique direito. Liga-se tudo: no Tk 9 o Button-2 é o botão
        do meio, e voltar com ele não atrapalha."""
        widget.bind("<Button-1>", lambda _: self._col_step(1) or "break")
        aqua = self.tk.call("tk", "windowingsystem") == "aqua"
        direitos = ("<Button-3>",) + (("<Button-2>", "<Control-Button-1>") if aqua else ())
        for seq in direitos:
            widget.bind(seq, lambda _: self._col_step(-1) or "break")

    def _col_place_expand(self):
        """Põe o botão de tela cheia no canto inferior direito da imagem."""
        if self._col_photo is None:
            self._col_expand_btn.place_forget()
            return
        lw, lh = self._col_preview.winfo_width(), self._col_preview.winfo_height()
        iw, ih = self._col_photo.width(), self._col_photo.height()
        x = (lw + min(iw, lw)) // 2 - 6
        y = (lh + min(ih, lh)) // 2 - 6
        self._col_expand_btn.place(x=x, y=y, anchor=tk.SE)

    # ── Tela cheia: só atalhos, Esc sai ─────────────────────────────────────────
    def _col_fullscreen_open(self):
        if self._col_fs is not None or self._nota_current_match() is None:
            return
        fs = tk.Toplevel(self, bg="black")
        # O macOS põe a tela cheia no monitor onde a janela está, e um Toplevel
        # novo nasce na tela principal. Nasce em cima da janela principal, então
        # a tela cheia abre no monitor onde o app está.
        fs.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty()}")
        fs.update_idletasks()
        fs.attributes("-fullscreen", True)
        lbl = tk.Label(fs, bg="black", bd=0, highlightthickness=0)
        lbl.pack(fill=tk.BOTH, expand=True)
        # Contador discreto (8/458): o mesmo _col_pos da barra de navegação,
        # então acompanha as setas sem código extra. Criado depois do label da
        # imagem para ficar por cima dele.
        tk.Label(fs, textvariable=self._col_pos, bg="black", fg="#555",
                 font=("", 12)).place(relx=1.0, rely=1.0, x=-14, y=-10, anchor=tk.SE)
        # Fica por cima da imagem anterior enquanto a próxima renderiza.
        self._col_fs_loading = tk.Label(fs, text="Carregando…", bg="black", fg="#aaa",
                                        font=("", 16), padx=16, pady=8)
        self._col_fs, self._col_fs_label = fs, lbl
        self._col_bind_view_keys(fs, guard=False)
        # No Toplevel: vale para a tela toda (imagem, faixas pretas, contador).
        self._col_bind_mouse_nav(fs)
        fs.bind("<Escape>", lambda _: self._col_fullscreen_close())
        # O tamanho final só chega depois da animação de tela cheia; reajusta.
        fs.bind("<Configure>", lambda e: e.widget is fs and self._col_fs_fit())
        fs.protocol("WM_DELETE_WINDOW", self._col_fullscreen_close)
        fs.focus_force()
        self._col_rerender()

    def _col_fs_show_loading(self, token: int):
        if (self._col_fs is None or token != self._col_render_token
                or token == self._col_fs_done):
            return   # já terminou, ou uma navegação mais nova assumiu
        self._col_fs_loading.config(text="Carregando…")
        self._col_fs_loading.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self._col_fs_loading.lift()

    def _col_fs_fit(self):
        """Ajusta a imagem renderizada ao tamanho atual da janela de tela cheia.

        Usa o tamanho da janela, não ``winfo_screenwidth`` — no macOS esse é
        sempre o da tela principal, mesmo com a janela em outro monitor.
        """
        fs, img = self._col_fs, getattr(self, "_col_fs_img", None)
        if fs is None or img is None:
            return
        from PIL import Image, ImageTk
        w, h = fs.winfo_width(), fs.winfo_height()
        if w <= 1 or h <= 1:
            w, h = fs.winfo_screenwidth(), fs.winfo_screenheight()
        size = (max(1, int(img.width * min(w / img.width, h / img.height))),
                max(1, int(img.height * min(w / img.width, h / img.height))))
        if self._col_fs_photo is not None and getattr(self, "_col_fs_size", None) == size:
            return   # <Configure> sem mudança de tamanho
        self._col_fs_size = size
        self._col_fs_photo = ImageTk.PhotoImage(img.resize(size, Image.LANCZOS))
        self._col_fs_label.config(image=self._col_fs_photo)

    def _col_fullscreen_close(self):
        if self._col_fs is None:
            return
        fs = self._col_fs
        self._col_fs = self._col_fs_label = self._col_fs_photo = None
        self._col_fs_img = self._col_fs_size = None
        self._col_fs_loading = None
        fs.destroy()
        self.focus_force()
        self._col_tree.focus_set()
        self._col_rerender()

    def _col_save_items(self, skip_zero: bool):
        """Frases a salvar, na ORDEM da tabela, e os motivos de descarte.

        → ``(itens, motivos)``. Uma lista só: a coleção inteira vai para UMA
        pasta, então esta ordem é o prefixo numérico do arquivo salvo (``001_``,
        ``002_``…) e reflete a ordenação escolhida pelo usuário. NÃO reordenar.

        Três descartes, contados em separado porque são coisas diferentes, e o
        pop-up e o log precisam dizer o mesmo:

        - nota 0: o que a exclusão da lista grava — o descarte explícito do
          usuário. Frase SEM nota (None, nunca visitada) não é filtrada;
        - frase que zera na limpeza de caracteres (só ``♪``/pontuação): o save
          não a gera, então contá-la aqui faria o pop-up prometer mais imagens
          do que entrega;
        - frase repetida: a busca por vírgula devolve a mesma frase uma vez por
          termo. O ``save_collection`` remove de todo jeito — a passada aqui é
          para a contagem do pop-up bater com o que vai para o disco.
        """
        cb = self._col_import()
        itens, n_zero, n_sem_cjk = [], 0, 0
        candidatas = []
        for m in self._col_matches:
            if skip_zero and m.get("nota") == 0:
                n_zero += 1
                continue
            candidatas.append(m)
        limpas = core.clean_flags(candidatas) if cb else [True] * len(candidatas)
        for m, limpa in zip(candidatas, limpas):
            if not limpa:
                n_sem_cjk += 1
                continue
            itens.append(m)
        n_repetidas = 0
        if cb:
            itens, n_repetidas = cb.dedupe_sentences(itens)

        motivos = []
        if n_zero:
            motivos.append(f"{n_zero} com nota 0")
        if n_sem_cjk:
            motivos.append(f"{n_sem_cjk} sem texto chinês")
        if n_repetidas:
            motivos.append(f"{n_repetidas} repetida(s)")
        return itens, motivos

    def _col_save(self):
        """Abre o pop-up de formato. A gravação em si é o _col_save_run."""
        cb = self._col_import()
        if not cb or not self._col_matches or self._col_saving:
            return
        SaveCollectionDialog(self)

    def _col_save_run(self, mode: str, skip_zero: bool, make_bundle: bool = False,
                      variants: bool = False):
        """Grava a coleção INTEIRA numa pasta só (chamado pelo pop-up)."""
        cb = self._col_import()
        if not cb or self._col_saving:
            return

        # Lembra as escolhas para o próximo save da sessão.
        self._col_save_mode = mode
        self._col_skip_zero = skip_zero
        self._col_make_bundle = make_bundle
        self._col_variants = variants

        itens, motivos = self._col_save_items(skip_zero)
        if not itens:
            return
        is_text = self._is_text_mode()
        # O nome da pasta é a busca que produziu a coleção. O fallback só existe
        # para não gerar pasta sem nome se o rótulo vier vazio por algum caminho.
        label = self._col_query or "coleção"

        self._col_saving = True
        self._col_save_btn.config(state=tk.DISABLED)
        self._nb.select(self._tab_log)
        extra = f" · ignoradas: {', '.join(motivos)}" if motivos else ""
        if variants:
            extra += " · com variantes (3 imagens por frase)"
        self._log_line(
            f"💾 Salvando a coleção '{label}' ({len(itens)} frases) "
            f"em {mode}{extra}…", "cmd")

        def _progress(i, total, msg):
            self._log_q.put((f"  [{i}/{total}] {msg}", "info"))

        def _work():
            try:
                out = cb.save_collection(label, itens, mode=mode, progress_cb=_progress,
                                         text=is_text, variants=variants)
                self._log_q.put((f"✓ Coleção salva em {out}", "success"))
            except Exception as e:  # noqa: BLE001
                self._log_q.put((f"Erro ao salvar coleção '{label}': {e}", "error"))
                out = None
            self.after(0, lambda: self._col_save_done(out, make_bundle))

        threading.Thread(target=_work, daemon=True).start()

    def _col_save_done(self, saida, make_bundle: bool = False):
        self._col_saving = False
        self._col_save_btn.config(state=tk.NORMAL if self._col_matches else tk.DISABLED)
        if saida is None:
            return

        if make_bundle:
            # Sem o prompt de abrir pasta aqui: o askyesno bloqueia a thread do
            # Tk, que é justamente quem drena o log — o streaming do ditado
            # congelaria atrás do modal.
            self._log_line(f"🎴 Coleção salva — gerando o ditado de {saida.name}…", "cmd")
            self._col_bundle_run(saida)
            return

        if messagebox.askyesno("Concluído",
                               f"Coleção salva no servidor em {saida.name}.\n"
                               "Mostrar o caminho?"):
            self._show_server_path(saida)

    def _col_bundle_run(self, pasta):
        """Roda o make_bundle.py na pasta da coleção.

        Uma pasta, uma execução: o make_bundle fatia o index.json inteiro em
        blocos de 150, então o ditado quebra considerando a coleção toda.
        """
        self._launch(
            [PY, str(REPO / "dictation" / "make_bundle.py"), str(pasta)],
            label=f"Ditado: {pasta.name}",
            pause_rate=0.0,
        )

    # ── Log Tab ────────────────────────────────────────────────────────────────
    def _build_log_tab(self):
        f = ttk.Frame(self._nb, padding=(6, 6, 6, 0))
        self._nb.add(f, text="  Log  ")
        self._tab_log = f

        # Os botões agem sobre a sub-aba selecionada (Geral ou um processo).
        ctrl = ttk.Frame(f)
        ctrl.pack(fill=tk.X, pady=(0, 4))
        self._job_stop_btn = ttk.Button(ctrl, text="⏹  Parar", command=self._stop,
                                        state=tk.DISABLED)
        self._job_stop_btn.pack(side=tk.LEFT)
        ttk.Button(ctrl, text="Limpar", command=self._clear_log).pack(side=tk.LEFT, padx=(6, 0))
        self._job_close_btn = ttk.Button(ctrl, text="Fechar", command=self._close_job_tab,
                                         state=tk.DISABLED)
        self._job_close_btn.pack(side=tk.LEFT, padx=(6, 0))
        self._autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Auto-scroll", variable=self._autoscroll).pack(side=tk.LEFT, padx=8)
        self._log_label = tk.StringVar()
        ttk.Label(ctrl, textvariable=self._log_label, foreground="#888", font=("Menlo", 9)).pack(side=tk.RIGHT)

        # Uma sub-aba por processo; "Geral" (fixa) recebe as mensagens do app.
        self._log_nb = ttk.Notebook(f)
        self._log_nb.pack(fill=tk.BOTH, expand=True)
        self._log_nb.bind("<<NotebookTabChanged>>", lambda _: self._update_job_controls())
        self._log_general, self._log_txt = self._new_log_pane()
        self._log_nb.add(self._log_general, text="  Geral  ")

    def _new_log_pane(self):
        frame = ttk.Frame(self._log_nb)
        txt = scrolledtext.ScrolledText(
            frame, state=tk.DISABLED, font=("Menlo", 10),
            bg="#1C1C1E", fg="#EBEBF5",
            insertbackground="white", relief=tk.FLAT,
        )
        txt.pack(fill=tk.BOTH, expand=True)
        txt.tag_configure("cmd",     foreground="#5AC8FA")
        txt.tag_configure("success", foreground="#30D158")
        txt.tag_configure("error",   foreground="#FF453A")
        txt.tag_configure("warning", foreground="#FF9F0A")
        txt.tag_configure("info",    foreground="#EBEBF5")
        return frame, txt

    # ── DeepSeek Tab ─────────────────────────────────────────────────────────────
    def _build_deepseek_tab(self):
        outer = ttk.Frame(self._nb, padding=8)
        self._nb.add(outer, text="  DeepSeek  ")
        self._tab_deepseek = outer

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
        """Recarrega as chamadas do deepseek_debug.log do servidor (últimas 500).

        O log é escrito pelos processos do servidor — esta máquina nunca chama a
        DeepSeek; aqui só se lê o registro."""
        if not CLIENT.connected:
            self._ds_count.set("sem servidor")
            return
        try:
            records = core.ds_records(500)
        except RemoteError as e:
            self._ds_count.set(f"erro ao ler log: {e}")
            return
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
        if not self._ds_records:
            self._ds_refresh()
            return
        if messagebox.askyesno("Limpar log",
                               "Apagar deepseek_debug.log no servidor?\n"
                               "Isso remove o histórico de chamadas."):
            try:
                core.ds_clear()
            except RemoteError as e:
                messagebox.showerror("Erro", f"Não foi possível apagar: {e}")
            for w in (self._ds_prompt, self._ds_response):
                w.config(state=tk.NORMAL)
                w.delete("1.0", tk.END)
            self._ds_refresh()

    # ── Asset logic ────────────────────────────────────────────────────────────
    def _format_duration(self, name: str) -> str:
        """Coluna Duração: ``M:SS`` ou ``H:MM:SS``; ``—`` se ainda desconhecida."""
        cached = self._duration_cache.get(name)
        if not cached or cached[2] <= 0:
            return "—"
        h, rem = divmod(int(round(cached[2])), 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _refresh_assets(self, *_):
        flt = self._filter_var.get().strip().lower()
        inc = self._only_inc.get()

        if not CLIENT.connected:
            self._count_var.set("sem servidor")
            return
        # Duração e total previsto de chunks vêm prontos do servidor (ffprobe
        # lá, em cache); enquanto calcula, a lista volta a ser pedida em breve.
        res = core.list_assets_full(self._drive_upload_on.get())
        assets = res["assets"]
        for a in assets:
            self._duration_cache[a["name"]] = (None, None, a["duration"] or 0)
            self._chunk_total_cache[a["name"]] = (None, a["chunk_total"])
        if res["extras_pending"] and not self._total_fill_running:
            self._total_fill_running = True

            def _again():
                self._total_fill_running = False
                self._refresh_assets()
            self.after(3000, _again)
        if flt:
            assets = [a for a in assets if flt in a["name"].lower()]
        if inc:
            assets = [a for a in assets if a["phase"] != "complete"]
        if self._assets_sort_col:
            assets.sort(key=self._assets_sort_key(self._assets_sort_col),
                        reverse=self._assets_sort_reverse)

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
            dur    = self._format_duration(a["name"])
            self._tree.insert("", tk.END, iid=a["name"],
                              values=(a["name"], lbl, prog, dur), tags=(a["phase"],))
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
        if len(sel) > 1:
            self._selected = None
            self._selected_many = [core.detect_status(ASSETS / n, self._drive_upload_on.get())
                                   for n in sel]
            self._update_detail_multi(self._selected_many)
            return
        self._selected_many = []
        s = core.detect_status(ASSETS / sel[0], self._drive_upload_on.get())
        self._selected = s
        self._update_detail(s)

    def _assets_extend_selection(self, direction: int):
        """Estende a seleção com Shift+Seta (espelha o Warehouse e as Coleções)."""
        focused = self._tree.focus()
        if not focused:
            return
        nxt = self._tree.next(focused) if direction > 0 else self._tree.prev(focused)
        if not nxt:
            return
        self._tree.selection_add(nxt)
        self._tree.focus(nxt)
        self._tree.see(nxt)

    def _update_detail_multi(self, lst: list):
        """Painel de detalhe para vários assets: lista + botões de lote."""
        lines = [f"{len(lst)} assets selecionados"]
        lines += [f"  • {a['name']}   {PHASES[a['phase']][0]}" for a in lst]
        self._detail_text.set("\n".join(lines))

        n_run = sum(1 for a in lst if a["has_video"])
        n_up = sum(1 for a in lst if self._can_cleanup(a))
        self._run_btn.config(text=f"▶  Iniciar / Retomar ({n_run})",
                             state=tk.NORMAL if n_run else tk.DISABLED)
        self._cleanup_btn.config(text=f"🧹  Clean-up (arquivar) ({n_up})",
                                 state=tk.NORMAL if n_up else tk.DISABLED)
        self._force_btn.config(state=tk.DISABLED)
        self._open_btn.config(state=tk.DISABLED)
        for var in self._phase_marks.values():
            var.set("")

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

        self._run_btn.config(text="▶  Iniciar / Retomar",
                             state=tk.NORMAL if s["has_video"] else tk.DISABLED)
        self._force_btn.config(state=tk.NORMAL if s.get("merged") else tk.DISABLED)
        self._open_btn.config(state=tk.NORMAL)
        # Clean-up só faz sentido após o upload ao Drive estar registrado.
        self._cleanup_btn.config(text="🧹  Clean-up (arquivar)",
                                 state=tk.NORMAL if self._can_cleanup(s) else tk.DISABLED)

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
            "—" if not self._drive_upload_on.get() else
            ("⏳" if p == "merged" else "○")
        )

    def _on_drive_toggle(self):
        # O status "Falta Drive" x "Completo" depende do checkbox: recalcula a
        # lista e o painel da seleção atual.
        self._refresh_assets()
        self._on_asset_select(None)

    def _can_cleanup(self, a: dict) -> bool:
        """Com o envio ao Drive desligado, basta o merge; senão exige o upload."""
        return bool(a.get("uploaded")
                    or (not self._drive_upload_on.get() and a.get("merged")))

    def _cleanup_cmd(self, a: dict) -> list:
        cmd = [PY, str(REPO / "cleanup_asset.py"), a["name"]]
        if not a.get("uploaded"):
            cmd.append("--skip-drive")
        return cmd

    def _run_selected(self):
        if self._selected_many:
            names = [a["name"] for a in self._selected_many if a["has_video"]]
            self._run_queue([
                ([PY, str(REPO / "video_burner.py"), n, "--exact"],
                 f"Pipeline: {n}")
                for n in names
            ])
            return
        if not self._selected:
            return
        self._launch(
            [PY, str(REPO / "video_burner.py"), self._selected["name"], "--exact"],
            label=f"Pipeline: {self._selected['name']}",
        )

    def _force_selected(self):
        if not self._selected:
            return
        name = self._selected["name"]
        if messagebox.askyesno("Confirmar", f"Reprocessar '{name}' do zero?\nIsso irá sobrescrever os arquivos existentes."):
            self._launch(
                [PY, str(REPO / "video_burner.py"), name, "--exact", "--force"],
                label=f"Pipeline (force): {name}",
            )

    def _run_batch(self):
        prefix = self._batch_var.get().strip()
        if not prefix:
            messagebox.showwarning("Aviso", "Informe um prefixo para o batch.\nEx: 'onibus' processa todos os assets onibus*")
            return
        self._launch(
            [PY, str(REPO / "video_burner.py"), prefix],
            label=f"Batch: {prefix}*",
            pause_rate=0.0,  # batch nunca usa pausas, independente do checkbox
        )

    def _cleanup_selected(self):
        if self._selected_many:
            self._cleanup_many(self._selected_many)
            return
        if not self._selected:
            return
        name = self._selected["name"]
        if not self._can_cleanup(self._selected):
            messagebox.showwarning(
                "Upload pendente",
                f"O asset '{name}' ainda não tem upload registrado no Drive.\n"
                "O clean-up só roda depois que a Fase 5 (Envio para o Drive) concluir.")
            return
        if messagebox.askyesno(
                "Confirmar clean-up",
                f"Arquivar '{name}'?\n\n"
                + ("Após validar o upload no Drive, " if self._selected.get("uploaded")
                   else "Sem verificação no Drive (envio desativado), ")
                + "o vídeo merged (e o áudio .mp3, "
                "se houver) é copiado para assets/final/, o vídeo original e o base.txt vão para o "
                "warehouse e as pastas\n"
                f"  • assets/{name}/\n  • assets/{name}_sub/\n"
                "serão REMOVIDAS do disco. Esta ação é irreversível."):
            self._launch(
                self._cleanup_cmd(self._selected),
                label=f"Clean-up: {name}",
            )

    def _cleanup_many(self, lst: list):
        """Clean-up em lote: uma confirmação só, depois um cleanup_asset por vez."""
        ok = [a for a in lst if self._can_cleanup(a)]
        skip = [a["name"] for a in lst if not self._can_cleanup(a)]
        if not ok:
            return
        msg = (f"Arquivar {len(ok)} asset(s)?\n\n"
               + "\n".join(f"  • {a['name']}"
                           + ("" if a.get("uploaded") else "  (sem Drive)") for a in ok)
               + "\n\nApós validar o upload no Drive (exceto os marcados sem Drive), "
               "o vídeo merged de cada um "
               "(e o áudio .mp3, se houver) é copiado para assets/final/, o vídeo original e o base.txt vão para "
               "o warehouse e as pastas do asset (e _sub) serão REMOVIDAS do disco. "
               "Esta ação é irreversível.")
        if skip:
            msg += ("\n\nSerão PULADOS (sem upload registrado no Drive):\n"
                    + "\n".join(f"  • {n}" for n in skip))
        if messagebox.askyesno("Confirmar clean-up em lote", msg):
            self._run_queue([
                (self._cleanup_cmd(a), f"Clean-up: {a['name']}")
                for a in ok
            ])

    # ── Fila de lote ───────────────────────────────────────────────────────────
    def _run_queue(self, items: list):
        """Roda ``(cmd, label)`` em série num job só (uma sub-aba de log).

        Cada asset é independente: a falha de um não interrompe os demais. O
        "Parar" esvazia a fila do job (ver _stop). Outros jobs seguem em paralelo."""
        if not items:
            return
        job = self._new_job(f"Lote ({len(items)})")
        job.queue = list(items)
        job.queue_total = len(items)
        self._launch_next(job)

    def _launch_next(self, job: "Job"):
        if not job.queue:
            if job.queue_total and not job.stopped:
                self._log_line(f"✅ Lote concluído: {job.queue_total} item(ns)", "success", job)
            return
        cmd, label = job.queue.pop(0)
        i = job.queue_total - len(job.queue)
        self._log_line(f"━━ Lote {i}/{job.queue_total}: {label} ━━", "cmd", job)
        self._launch(cmd, label=f"{label} [{i}/{job.queue_total}]",
                     on_done=lambda: self._launch_next(job), job=job)

    # ── Ordenação da lista de Assets ───────────────────────────────────────────
    def _assets_sort(self, col: str):
        """Ordena a lista pela coluna clicada (toggle asc/desc), como nas Coleções."""
        reverse = (self._assets_sort_col == col) and not self._assets_sort_reverse
        self._assets_sort_col = col
        self._assets_sort_reverse = reverse
        arrow = " ▼" if reverse else " ▲"
        for c, base in self._assets_headers.items():
            self._tree.heading(c, text=base + (arrow if c == col else ""))
        self._refresh_assets()

    def _assets_sort_key(self, col: str):
        phase_order = list(PHASES)
        return {
            "name":     lambda a: a["name"].lower(),
            "status":   lambda a: phase_order.index(a["phase"]),
            # "—" (vazio/aguardando) fica antes de 0% na ordem crescente
            "progress": lambda a: -1 if a["phase"] in ("empty", "ready") else a["progress"],
            "duration": lambda a: (self._duration_cache.get(a["name"]) or (0, 0, -1))[2],
        }[col]

    def _open_folder(self):
        if self._selected:
            self._show_server_path(self._selected["path"])

    def _open_asset_video(self, name: str):
        """Abre o vídeo do servidor em streaming (navegador), sem copiá-lo para cá."""
        video = core.asset_video(name)
        if video:
            _open_url(CLIENT.file_url(video))
        else:
            self._log_line(f"⚠️ {name}: nenhum vídeo para abrir", "warning")

    def _assets_open_video(self, event):
        """Duplo clique: abre o vídeo do asset no player padrão."""
        row = self._tree.identify_row(event.y)
        if row:
            self._open_asset_video(row)

    def _assets_context_menu(self, event):
        """Menu flutuante com 'Transcrever...' no botão direito (ou Control+clique)."""
        row = self._tree.identify_row(event.y)
        if not row:
            return "break"   # cabeçalho ou área vazia: não abre menu
        sel = self._tree.selection()
        if row in sel and len(sel) > 1:
            # Clique dentro de uma seleção múltipla: mantém a seleção. Só o
            # Excluir age em lote; Transcrever e Abrir vídeo são de um item só.
            self._assets_menu.entryconfigure(0, state=tk.DISABLED)
            self._assets_menu.entryconfigure(1, state=tk.DISABLED)
            self._assets_menu.entryconfigure(3, label=f"Excluir {len(sel)} itens...")
            self._assets_menu.entryconfigure(4, label=f"Expurgar {len(sel)} itens...")
        else:
            # Fora da seleção: o menu age só sobre o item clicado, senão os
            # botões de lote continuariam apontando para os outros itens.
            self._tree.selection_set(row)
            self._tree.focus(row)
            self._selected_many = []
            self._selected = core.detect_status(ASSETS / row, self._drive_upload_on.get())
            self._update_detail(self._selected)

            # Recursivo (ao contrário de has_video): pastas como a do youtube_monitor
            # guardam os mp4 uma subpasta abaixo (uma por canal), não soltos aqui.
            has_any_mp4 = core.has_any_mp4(self._selected["path"])
            self._assets_menu.entryconfigure(
                0, state=tk.NORMAL if has_any_mp4 else tk.DISABLED)
            self._assets_menu.entryconfigure(
                1, state=tk.NORMAL if core.asset_video(row) else tk.DISABLED)
            self._assets_menu.entryconfigure(3, label="Excluir...")
            self._assets_menu.entryconfigure(4, label="Expurgar...")
        self._assets_menu.entryconfigure(
            4, state=tk.DISABLED if self._assets_hd_busy else tk.NORMAL)
        try:
            self._assets_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._assets_menu.grab_release()
        return "break"

    def _whisper_python(self) -> RemotePath:
        return REPO / "whisper_env_py313" / "bin" / "python3"

    def _transcrever_selected(self):
        if not self._selected:
            return
        name = self._selected["name"]
        py = self._whisper_python()
        if not py.exists():
            messagebox.showerror(
                "Ambiente Whisper ausente",
                f"Não encontrei {py}.\nVeja README_TRANSCRIBE.md para criar o venv.")
            return
        if not messagebox.askyesno(
                "Transcrever",
                f"Transcrever vídeo(s) de '{name}' para .zht.srt?\n\n"
                "Se houver mais de um .mp4 na pasta, cada um será movido para uma "
                "pasta própria (nome = nome do vídeo) antes de transcrever."):
            return
        self._launch(
            [WHISPER_PY, str(REPO / "transcribe_asset.py"), name],
            label=f"Transcrever: {name}",
            on_done=self._refresh_assets,
        )

    def _assets_busy_jobs(self, names: list) -> list:
        """Rótulos dos processos em execução que mexem num destes assets
        (nome no rótulo, ou batch cujo prefixo os cobre)."""
        def _usa(label: str, n: str) -> bool:
            m = re.match(r"Batch: (.+)\*$", label)
            if m:
                return n.startswith(m.group(1))
            return re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", label) is not None
        return [j.label for j in self._running_jobs()
                if any(_usa(j.label, n) for n in names)]

    # ── Expurgo/restauro de material bruto (assets/ ↔ <HD>/assets/) ──────────
    def _assets_purge_selected(self):
        """Move a pasta de cada asset selecionado (e a _sub) para <HD>/assets/,
        na mesma estrutura: copia, confere e só então apaga do computador."""
        if self._assets_hd_busy:
            return
        names = list(self._tree.selection())
        if not names:
            return
        ocupados = self._assets_busy_jobs(names)
        if ocupados:
            messagebox.showwarning(
                "Processo em execução",
                "Aguarde ou pare antes de expurgar:\n"
                + "\n".join(f"  • {l}" for l in ocupados))
            return
        drive = self._wh_pick_drive()
        if drive is None:
            return
        dest = drive / "assets"

        plan = []   # [(nome, bytes)]
        for n in names:
            paths = cb.raw_asset_paths(n)
            if paths:
                plan.append((n, cb.footprint_size(paths)))
        if not plan:
            return
        total = sum(b for _, b in plan)
        try:
            livre = core.disk_free(drive)
        except OSError as e:
            messagebox.showerror("Expurgar", f"Não foi possível ler o HD {drive}:\n{e}")
            return
        if total > livre:
            messagebox.showerror(
                "Expurgar",
                f"Espaço insuficiente em {drive.name}: precisa de "
                f"{total / 1024**3:.2f} GB, livre {livre / 1024**3:.2f} GB.")
            return

        linhas = [f"“{n}” ({b / 1024**2:.0f} MB"
                  + (", com _sub)" if (ASSETS / f"{n}_sub").exists() else ")")
                  for n, b in plan[:5]]
        if len(plan) > 5:
            linhas.append(f"… e mais {len(plan) - 5} asset(s)")
        if not messagebox.askyesno(
                "Expurgar asset" if len(plan) == 1 else "Expurgar assets",
                f"Expurgar para {dest}?\n\n"
                + "\n".join(linhas)
                + f"\n\nTotal ~{total / 1024**2:.0f} MB · livre no HD: "
                  f"{livre / 1024**3:.0f} GB\n\n"
                  "Copia, confere e APAGA do computador local (pasta do asset e "
                  "_sub). Para recuperar: Downloads & Scraping → Restaurar...",
                icon=messagebox.WARNING, default=messagebox.NO):
            return

        self._assets_hd_busy = True
        self._log_line(f"📦 Expurgo de assets: {len(plan)} → {dest}", "cmd")
        self._hd_batch(
            [n for n, _ in plan], lambda n, pcb: cb.purge_raw_asset(n, dest, progress_cb=pcb),
            emoji="📦", erro="expurgar", feito="movidos para o HD",
            on_done=lambda summary: self._assets_purge_done(summary, dest))

    def _assets_purge_done(self, summary: dict, dest: Path):
        self._assets_hd_busy = False
        if summary["ok"]:
            self._selected = None
            self._selected_many = []
            self._refresh_assets()
        self._hd_report("Expurgar", summary, "📦 Expurgo de assets", "liberados",
                        f"asset(s) expurgado(s) para {dest}.",
                        "liberados no computador.", "mantidos no computador")

    def _assets_restore_dialog(self):
        """Modal com os assets do HD externo (botão em Downloads & Scraping)."""
        if self._assets_hd_busy:
            messagebox.showinfo("Restaurar", "Aguarde o expurgo/restauro de assets em andamento.")
            return
        drive = self._wh_pick_drive()
        if drive is None:
            return
        hd = drive / "assets"
        if not hd.is_dir():
            messagebox.showerror("Restaurar", f"Esse HD não tem assets/:\n{drive}")
            return

        def _scan():
            # Uma listagem só, sem stat por asset: o HD USB pode ser lento.
            nomes = core.hd_asset_names(hd)
            locais = {a.name for a in ASSETS.iterdir()}
            return {n: "Já no computador" if n in locais else "Só no HD" for n in nomes}

        RestoreDialog(self, hd, title="Restaurar assets do HD", scan=_scan,
                      size=lambda n: cb.footprint_size(cb.raw_asset_paths(n, hd)),
                      local_root=ASSETS, onde="assets/",
                      run=lambda plan, delete: self._assets_restore_run(hd, plan, delete))

    def _assets_restore_run(self, hd: Path, plan: list, delete_src: bool):
        self._assets_hd_busy = True
        acao = "apagando do HD" if delete_src else "mantendo no HD"
        self._log_line(f"📥 Restauro de assets: {len(plan)} de {hd} ({acao})", "cmd")
        self._hd_batch(
            [n for n, _ in plan],
            lambda n, pcb: cb.restore_raw_asset(n, hd, delete_src=delete_src, progress_cb=pcb),
            emoji="📥", erro="restaurar", feito="restaurados",
            on_done=lambda summary: self._assets_restore_done(summary, hd, delete_src))

    def _assets_restore_done(self, summary: dict, hd: Path, delete_src: bool):
        self._assets_hd_busy = False
        if summary["ok"]:
            self._refresh_assets()
        self._hd_report("Restaurar", summary, "📥 Restauro de assets", "trazidos",
                        f"asset(s) restaurado(s) de {hd}.",
                        "trazidos para o computador.", "intactos no HD",
                        "Cópias apagadas do HD." if delete_src else "Cópias mantidas no HD.")

    def _excluir_selected(self):
        """Move a pasta de cada asset selecionado (e a _sub, se houver) para a
        Lixeira do macOS. Aceita seleção múltipla."""
        names = list(self._tree.selection())
        if not names:
            return
        ocupados = self._assets_busy_jobs(names)
        if ocupados:
            messagebox.showwarning(
                "Processo em execução",
                "Aguarde ou pare antes de excluir:\n"
                + "\n".join(f"  • {l}" for l in ocupados))
            return
        targets = [p for n in names
                   for p in (ASSETS / n, ASSETS / f"{n}_sub") if p.exists()]
        if not targets:
            return
        shown = targets[:15]
        listing = "\n".join(f"  • assets/{p.name}/" for p in shown)
        if len(targets) > len(shown):
            listing += f"\n  … e mais {len(targets) - len(shown)} pasta(s)"
        what = f"'{names[0]}'" if len(names) == 1 else f"{len(names)} assets"
        msg = (f"Tem certeza que deseja excluir {what}?\n\n"
               "Serão movidas para a Lixeira:\n" + listing)
        if not messagebox.askyesno("Excluir asset" if len(names) == 1 else "Excluir assets",
                                   msg, icon=messagebox.WARNING, default=messagebox.NO):
            return
        # Finder do servidor em vez de rmtree: vai para a Lixeira de lá, recuperável.
        failed = set()
        for nome, erro in core.trash(targets):
            failed.add(nome)
            self._log_line(f"❌ Não foi possível excluir {nome}: {erro}", "error")
        for n in names:
            if n not in failed and f"{n}_sub" not in failed:
                self._log_line(f"🗑 Excluído: {n}", "success")
        if failed:
            messagebox.showerror("Erro ao excluir",
                                 "Não foi possível excluir:\n"
                                 + "\n".join(f"  • {f}" for f in sorted(failed)))
        self._selected = None
        self._selected_many = []
        self._refresh_assets()

    # ── Source / download logic ────────────────────────────────────────────────
    def _refresh_sources(self):
        self._src_tree.delete(*self._src_tree.get_children())
        for f in (core.list_sources() if CLIENT.connected else []):
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
        cmd = [PY, str(REPO / "youtube_downloader.py"), url,
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
        cmd = [SCRAPER_PY, str(REPO / "scrape_globoplay_episodes.py"),
               "--url", url, "--output", str(SOURCE / name),
               "--interaction-time", self._gp_time.get()]
        if self._gp_headless.get():
            cmd.append("--headless")
        self._launch(cmd, label=f"Scraping: {name}")

    # ── YouTube Monitor (youtube_channels.json) ──────────────────────────────────
    def _ytm_refresh(self):
        """Relê o JSON do disco e redesenha a tabela."""
        if not CLIENT.connected:
            return
        try:
            self._ytm_cfg = core.ytm_load()
        except Exception as e:
            messagebox.showerror("YouTube Monitor",
                                 f"Não foi possível ler {ytm.DEFAULT_CONFIG.name}:\n{e}")
            self._ytm_cfg = {"defaults": {}, "channels": []}
        tree = self._ytm_tree
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for i, ch in enumerate(self._ytm_cfg["channels"]):
            tree.insert("", tk.END, iid=str(i), values=(
                ch.get("name", ""), ch.get("url", ""), ch.get("prefix", ""),
                "☑" if ch.get("enabled", True) else "☐"))
        if sel and tree.exists(sel[0]):
            tree.selection_set(sel[0])

    def _ytm_save(self) -> bool:
        """Grava o config (atômico) e redesenha. Em erro, volta ao que está no disco."""
        try:
            core.ytm_save(self._ytm_cfg)
        except Exception as e:
            messagebox.showerror("YouTube Monitor", f"Falha ao salvar o config:\n{e}")
            self._ytm_refresh()
            return False
        self._ytm_refresh()
        return True

    def _ytm_prefix_error(self, prefix: str, skip_index: int = None):
        """Mensagem de erro para um prefixo inválido/duplicado, ou None se ok."""
        if not prefix:
            return "Informe um prefixo."
        if not ytm.is_valid_prefix(prefix):
            return "Prefixo só pode ter letras, números e hífen (sem espaços nem '_')."
        for i, ch in enumerate(self._ytm_cfg["channels"]):
            if i != skip_index and ch.get("prefix") == prefix:
                return f"O prefixo '{prefix}' já é usado pelo canal '{ch.get('name')}'."
        return None

    def _ytm_on_click(self, event):
        tree = self._ytm_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != "#4":   # coluna Ativo
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        ch = self._ytm_cfg["channels"][int(row)]
        ch["enabled"] = not ch.get("enabled", True)
        tree.selection_set(row)
        self._ytm_save()

    def _ytm_on_double_click(self, event):
        tree = self._ytm_tree
        if tree.identify_column(event.x) != "#3":   # coluna Prefixo
            return
        row = tree.identify_row(event.y)
        if row:
            self._ytm_edit_prefix(row)
        return "break"

    def _ytm_edit_prefix(self, row: str):
        """Entry sobreposto à célula do prefixo: Enter/sair confirma, Esc cancela."""
        tree = self._ytm_tree
        bbox = tree.bbox(row, "prefix")
        if not bbox:
            return
        if self._ytm_editor is not None:
            self._ytm_editor.destroy()
        idx = int(row)
        current = self._ytm_cfg["channels"][idx].get("prefix", "")
        var = tk.StringVar(value=current)
        ent = ttk.Entry(tree, textvariable=var)
        x, y, w, h = bbox
        ent.place(x=x, y=y, width=w, height=h)
        ent.focus_set()
        ent.select_range(0, tk.END)
        self._ytm_editor = ent
        done = {"v": False}

        def _close():
            done["v"] = True
            self._ytm_editor = None
            ent.destroy()

        def _commit(_=None):
            if done["v"]:
                return
            new = var.get().strip()
            if new == current:
                _close()
                return
            err = self._ytm_prefix_error(new, skip_index=idx)
            if err:
                _close()
                messagebox.showwarning("Prefixo inválido", err)
                return
            _close()
            self._ytm_cfg["channels"][idx]["prefix"] = new
            self._ytm_save()

        def _cancel(_=None):
            if not done["v"]:
                _close()

        ent.bind("<Return>", _commit)
        ent.bind("<KP_Enter>", _commit)
        ent.bind("<FocusOut>", _commit)
        ent.bind("<Escape>", _cancel)

    def _ytm_add_dialog(self):
        AddChannelDialog(self)

    def _ytm_add_channel(self, name: str, url: str, prefix: str, enabled: bool) -> bool:
        # Relê antes de alterar: o JSON pode ter sido editado fora da UI.
        self._ytm_refresh()
        self._ytm_cfg["channels"].append(
            {"name": name, "url": url, "prefix": prefix, "enabled": enabled})
        if not self._ytm_save():
            return False
        last = str(len(self._ytm_cfg["channels"]) - 1)
        if self._ytm_tree.exists(last):
            self._ytm_tree.selection_set(last)
            self._ytm_tree.see(last)
        return True

    def _ytm_remove(self):
        sel = self._ytm_tree.selection()
        if not sel:
            messagebox.showinfo("YouTube Monitor", "Selecione um canal para remover.")
            return
        idx = int(sel[0])
        name = self._ytm_cfg["channels"][idx].get("name", "")
        if not messagebox.askyesno(
                "Remover canal",
                f"Remover o canal “{name}” do monitor?\n\n"
                "Vídeos já baixados e o histórico não são apagados.",
                icon=messagebox.WARNING, parent=self):
            return
        del self._ytm_cfg["channels"][idx]
        self._ytm_save()

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
    def _running_jobs(self) -> list:
        return [j for j in self._jobs.values() if j.running()]

    def _any_running(self) -> bool:
        return bool(self._running_jobs())

    def _new_job(self, label: str) -> "Job":
        """Cria o job e a sub-aba de log dele, já selecionada."""
        job = Job(label)
        job.frame, job.txt = self._new_log_pane()
        self._jobs[job.id] = job
        self._log_nb.add(job.frame, text=self._job_tab_text(job))
        self._nb.select(self._tab_log)
        self._log_nb.select(job.frame)
        return job

    @staticmethod
    def _job_tab_text(job: "Job") -> str:
        mark = {"running": "●", "ok": "✓"}.get(job.status, "✗")
        label = job.label if len(job.label) <= 32 else job.label[:31] + "…"
        return f" {mark} {label} "

    def _selected_job(self):
        try:
            cur = self._log_nb.select()
        except tk.TclError:
            return None
        for j in self._jobs.values():
            if str(j.frame) == cur:
                return j
        return None

    def _update_job_controls(self):
        """Botões da aba Log (job selecionado) e barra do topo (todos os jobs)."""
        job = self._selected_job()
        if job is None:
            self._job_stop_btn.config(state=tk.DISABLED)
            self._job_close_btn.config(state=tk.DISABLED)
            self._log_label.set("")
        else:
            self._job_stop_btn.config(state=tk.NORMAL if job.running() else tk.DISABLED)
            self._job_close_btn.config(state=tk.DISABLED if job.running() else tk.NORMAL)
            if job.running():
                self._log_label.set(job.label)
            elif job.status == "stopped":
                self._log_label.set("interrompido")
            else:
                self._log_label.set(f"código {job.returncode}")
        running = self._running_jobs()
        self._stop_all_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        if not running:
            self._status_var.set("Pronto")
        elif len(running) == 1:
            self._status_var.set(f"▶  {running[0].label}")
        else:
            self._status_var.set(f"▶  {len(running)} em execução")

    def _refresh_llm_status(self):
        """Status do provedor escolhido no painel Pipeline, visto pelo servidor
        (fora da thread do Tk: checar o Ollama de lá é uma chamada HTTP)."""
        provider = self._llm_provider.get()
        if not CLIENT.connected:
            self._llm_status.set("sem servidor")
            return
        self._llm_status.set("verificando…")

        def _check():
            try:
                st = core.llm_status(provider)
                text = ("● " if st["ok"] else "⚠ ") + st["detail"] + " (no servidor)"
            except RemoteError as e:
                text = f"⚠ {e}"
            self.after(0, lambda: self._llm_provider.get() == provider and self._llm_status.set(text))
        threading.Thread(target=_check, daemon=True).start()

    def _refresh_llm_labels(self):
        """Nome do modelo local configurado no servidor, no rótulo do rádio."""
        try:
            self._llm_radios["local"].config(text=f"Local ({core.llm_local_model()})")
        except RemoteError:
            pass
        self._refresh_llm_status()

    def _launch(self, cmd: list, label: str = "", pause_rate: float = None,
                on_done=None, job: "Job" = None):
        """Roda ``cmd`` em paralelo aos demais, com log numa sub-aba própria.

        ``job`` reaproveita a sub-aba de um job existente (próximo item de um
        lote). ``on_done`` (opcional) roda na thread do Tk quando o processo
        termina — é o gancho de encadeamento do lote.
        """
        llm = self._llm_provider.get()
        if not CLIENT.connected:
            raise sr.Disconnected("Sem conexão com o servidor: o processo não foi iniciado.")
        if job is None and llm == "local":
            st = core.llm_status("local")
            if not st["ok"] and not messagebox.askyesno(
                    "LLM local indisponível",
                    f"{st['detail']}.\nIniciar mesmo assim? As chamadas à LLM vão falhar."):
                return
        if job is None:
            if any(j.label == label for j in self._running_jobs()):
                if not messagebox.askyesno(
                        "Já em execução",
                        f"'{label}' já está rodando.\nIniciar outro mesmo assim?"):
                    return
            job = self._new_job(label)
        else:
            job.status = "running"
            job.label = label   # no lote, o rótulo acompanha o item corrente
            self._log_nb.tab(job.frame, text=self._job_tab_text(job))
        job.on_done = on_done

        self._log_line(f"$ {' '.join(str(c) for c in cmd)}", "cmd", job)
        self._update_job_controls()

        # None = use checkbox value; caller can force 0.0 to disable pauses.
        if pause_rate is None:
            pause_rate = self._pause_rate_value()

        debug_ds = self._ds_debug_on.get()
        # Estilo da queima: vale para todo launch, inclusive o batch.
        box_opaque = self._burn_box_opaque_on.get()
        top_translation = self._burn_top_translation_on.get()
        multiline = self._burn_multiline_on.get()
        extract_audio = self._extract_audio_on.get()
        drive_upload = self._drive_upload_on.get()
        jid = job.id

        def _run():
            # Só os ajustes desta janela: o resto do ambiente (PATH, .env, chaves
            # da DeepSeek) é o do servidor, onde o processo roda. None = remover.
            env = {
                "BURN_PAUSE_RATE": f"{pause_rate}" if pause_rate > 0 else None,
                # Sempre explícito: sem a variável o process_chunks assume opaco.
                "BURN_BOX_OPAQUE": "1" if box_opaque else "0",
                "BURN_TOP_TRANSLATION": "1" if top_translation else "0",
                "BURN_MULTILINE": "1" if multiline else "0",
                "EXTRACT_AUDIO": "1" if extract_audio else "0",
                "DRIVE_UPLOAD": "1" if drive_upload else "0",
                "SUBRIM_LLM_PROVIDER": llm,
                "DEEPSEEK_DEBUG": "1" if debug_ds else None,
            }
            try:
                pid = CLIENT.proc_start(cmd, env, label)
            except RemoteError as e:
                self._log_q.put((jid, f"❌ Não foi possível iniciar no servidor: {e}", "error"))
                self.after(0, self._on_job_done, job, -1)
                return
            self._log_q.put((jid, f"(processo #{pid} no servidor)", "info"))
            self._follow(job, sr.RemoteProc(pid), threaded=False)

        threading.Thread(target=_run, daemon=True).start()

    def _follow(self, job: "Job", p, threaded: bool = True):
        """Acompanha o log de um processo do servidor na sub-aba do ``job``."""
        jid = job.id
        self._attached_procs.add(p.pid)

        def _run():
            with self._proc_lock:
                job.proc = p
                parar = job.stopped
            if parar:   # "Parar" clicado antes do processo começar
                p.terminate()
            for raw in p.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                lo = line.lower()
                # Os glifos ❌/⚠️/✅ são o vocabulário dos scripts do repo; sem
                # eles a saída do make_bundle sairia toda como "info".
                tag = (
                    "error"   if "❌" in line or any(k in lo for k in ("error", "erro", "exception", "traceback")) else
                    "warning" if "⚠️" in line or any(k in lo for k in ("warn", "aviso", "skip")) else
                    "success" if any(k in line for k in ("[OK]", "✓", "✅", "Done", "done", "DONE",
                                                          "Completo", "merged", "completed")) else
                    "info"
                )
                self._log_q.put((jid, line, tag))
            p.wait()
            self._attached_procs.discard(p.pid)
            try:
                CLIENT.proc_forget(p.pid)
            except RemoteError:
                pass
            sep = "─" * 70
            tag = "success" if p.returncode == 0 else "error"
            self._log_q.put((jid, sep, "info"))
            self._log_q.put((jid, f"Encerrado  (código {p.returncode})", tag))
            self.after(0, self._on_job_done, job, p.returncode)

        if threaded:
            threading.Thread(target=_run, daemon=True).start()
        else:
            _run()

    def _on_job_done(self, job: "Job", returncode: int):
        # Garante que as últimas linhas do processo entrem antes do status final.
        self._drain_log_q()
        with self._proc_lock:
            job.proc = None
        job.returncode = returncode
        job.status = ("stopped" if job.stopped
                      else "ok" if returncode == 0 else "error")
        # Encadeamento (próximo item do lote). Zera antes de chamar, senão um
        # on_done que dispara outro _launch se reencadearia sozinho.
        seguinte, job.on_done = job.on_done, None
        if seguinte and not job.stopped:
            try:
                seguinte()
            except Exception as e:  # noqa: BLE001
                self._log_line(f"Erro ao continuar depois do processo: {e}", "error", job)
        if job.id in self._jobs and not job.running():
            # Lote: o ✗ de um item não marca o lote todo; vale o último item.
            self._log_nb.tab(job.frame, text=self._job_tab_text(job))
        self._update_job_controls()
        self._refresh_assets()
        self._refresh_sources()

    def _stop_job(self, job: "Job"):
        # Parar interrompe o lote inteiro do job, não só o item em execução.
        if job.queue:
            self._log_line(f"⏹  Lote cancelado: {len(job.queue)} item(ns) não iniciado(s)",
                           "warning", job)
        job.queue = []
        with self._proc_lock:
            job.stopped = True
            if job.proc:
                job.proc.terminate()
        self._log_line("⏹  Processo interrompido pelo usuário", "warning", job)

    def _stop(self):
        job = self._selected_job()
        if job and job.running():
            self._stop_job(job)

    def _stop_all(self):
        for job in self._running_jobs():
            self._stop_job(job)

    def _close_job_tab(self):
        job = self._selected_job()
        if job is None or job.running():
            return
        self._log_nb.forget(job.frame)
        job.frame.destroy()
        self._jobs.pop(job.id, None)
        self._update_job_controls()

    def _on_close(self):
        """Os processos rodam no servidor: fechar a janela não precisa pará-los
        (ao reabrir, o acompanhamento é retomado). Só os itens de lote ainda não
        iniciados se perdem, porque a fila do lote mora aqui."""
        running = self._running_jobs()
        if running:
            nomes = "\n".join(f"  • {j.label}" for j in running[:10])
            fila = sum(len(j.queue) for j in running)
            aviso = (f"\n\n{fila} item(ns) de lote ainda não iniciado(s) não serão iniciados."
                     if fila else "")
            resp = messagebox.askyesnocancel(
                "Processos em execução",
                f"{len(running)} processo(s) em execução no servidor:\n{nomes}{aviso}\n\n"
                "Sim = fechar e deixar rodando no servidor\n"
                "Não = interromper todos e fechar\n"
                "Cancelar = voltar")
            if resp is None:
                return
            if resp is False:
                with self._proc_lock:
                    for j in running:
                        j.queue = []
                        j.stopped = True
                        if j.proc:
                            j.proc.terminate()
        tmp = getattr(self, "_col_audio_tmp", None)
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        self.destroy()

    # ── Logging ────────────────────────────────────────────────────────────────
    def _log_line(self, msg: str, tag: str = "info", job: "Job" = None):
        """Escreve na sub-aba do ``job`` ou, sem job, na sub-aba Geral."""
        txt = job.txt if job is not None and job.id in self._jobs else self._log_txt
        ts = datetime.now().strftime("%H:%M:%S")
        txt.config(state=tk.NORMAL)
        txt.insert(tk.END, f"[{ts}]  {msg}\n", tag)
        txt.config(state=tk.DISABLED)
        if self._autoscroll.get():
            txt.see(tk.END)

    def _clear_log(self):
        job = self._selected_job()
        txt = job.txt if job else self._log_txt
        txt.config(state=tk.NORMAL)
        txt.delete("1.0", tk.END)
        txt.config(state=tk.DISABLED)

    _RE_DIR   = re.compile(r"Processando diret[óo]rio:\s*(.+?)\s*$")
    _RE_CHUNK = re.compile(r"Gerando chunk\s+\d+/(\d+)")

    def _drain_log_q(self) -> bool:
        new_total = False
        try:
            while True:
                item = self._log_q.get_nowait()
                if len(item) == 3:
                    jid, msg, tag = item
                    job = self._jobs.get(jid)
                    self._log_line(msg, tag, job)
                    if job is not None:
                        new_total = self._scan_log_for_total(job, msg) or new_total
                else:
                    self._log_line(*item)
        except queue.Empty:
            pass
        return new_total

    def _poll_log(self):
        if self._drain_log_q():
            self._refresh_assets()
        self.after(80, self._poll_log)

    def _scan_log_for_total(self, job: "Job", msg: str) -> bool:
        """Extrai o total de chunks anunciado pelo pipeline (ex.: 'chunk 042/109').

        Retorna ``True`` quando descobre um total novo, para forçar refresh da tabela."""
        m = self._RE_DIR.search(msg)
        if m:
            job.current_asset = m.group(1).strip()
            return False
        m = self._RE_CHUNK.search(msg)
        if m and job.current_asset:
            total = int(m.group(1))
            if self._live_chunk_total.get(job.current_asset) != total:
                self._live_chunk_total[job.current_asset] = total
                return True
        return False

    # ── Auto-refresh ───────────────────────────────────────────────────────────
    def _schedule_refresh(self):
        def _tick():
            running = self._any_running()
            # Só a lista do modo visível: varrer os assets de vídeo enquanto o
            # modo Texto está na tela é I/O de disco que ninguém vê.
            if self._is_text_mode():
                self._refresh_texts()
            else:
                self._refresh_assets()
                if self._ds_auto.get():
                    self._ds_refresh()
            self.after(3000 if running else 12000, _tick)
        self.after(12000, _tick)


# ─── Dialog: Salvar coleção (Coleções) ──────────────────────────────────────────
class AddChannelDialog(tk.Toplevel):
    """Pop-up modal para adicionar um canal ao YouTube Monitor."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Adicionar canal")
        self.resizable(False, False)
        self.transient(app)

        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)

        self._url_var = tk.StringVar()
        self._name_var = tk.StringVar()
        self._prefix_var = tk.StringVar()
        self._enabled_var = tk.BooleanVar(value=True)
        self._name_edited = False

        ttk.Label(f, text="URL:").grid(row=0, column=0, sticky=tk.W, pady=3)
        url_e = ttk.Entry(f, textvariable=self._url_var, width=44)
        url_e.grid(row=0, column=1, sticky=tk.EW, pady=3)
        ttk.Label(f, text="Nome:").grid(row=1, column=0, sticky=tk.W, pady=3)
        name_e = ttk.Entry(f, textvariable=self._name_var)
        name_e.grid(row=1, column=1, sticky=tk.EW, pady=3)
        ttk.Label(f, text="Prefixo:").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(f, textvariable=self._prefix_var, width=18).grid(row=2, column=1, sticky=tk.W, pady=3)
        ttk.Checkbutton(f, text="Ativo", variable=self._enabled_var).grid(
            row=3, column=1, sticky=tk.W, pady=(4, 0))
        ttk.Label(f, text="O nome não pode ser alterado depois (identifica o canal no histórico).",
                  foreground="#888", font=("", 9)).grid(row=4, column=0, columnspan=2,
                                                        sticky=tk.W, pady=(8, 0))

        btns = ttk.Frame(f)
        btns.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(14, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Adicionar", command=self._ok).pack(side=tk.RIGHT)
        f.columnconfigure(1, weight=1)

        # Nome sugerido a partir do @handle da URL, até o usuário mexer nele.
        self._url_var.trace_add("write", self._suggest_name)
        name_e.bind("<Key>", lambda _e: setattr(self, "_name_touched", True))
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        url_e.focus_set()

    def _suggest_name(self, *_):
        if self._name_edited:
            return
        m = re.search(r"youtube\.com/@([^/?#]+)", self._url_var.get())
        self._name_var.set(ytm.sanitize_name(m.group(1)) if m else "")

    def _ok(self):
        url = self._url_var.get().strip()
        name = ytm.sanitize_name(self._name_var.get()) if self._name_var.get().strip() else ""
        prefix = self._prefix_var.get().strip()
        err = None
        if not url:
            err = "Informe a URL do canal."
        elif not name:
            err = "Informe o nome do canal."
        elif any(ch.get("name") == name for ch in self.app._ytm_cfg["channels"]):
            err = f"Já existe um canal chamado '{name}'."
        else:
            err = self.app._ytm_prefix_error(prefix)
        if err:
            messagebox.showwarning("Adicionar canal", err, parent=self)
            return
        if self.app._ytm_add_channel(name, url, prefix, self._enabled_var.get()):
            self.destroy()


class SaveCollectionDialog(tk.Toplevel):
    """Escolha do formato (original OU r36s) e do filtro de nota 0 antes de salvar.

    Substitui a confirmação simples de antes: como já mostra a contagem e o
    destino, confirmar duas vezes seria redundante.
    """

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Salvar coleção")
        # Largura travada (resizable False no eixo x), então quem resolve texto
        # longo é o wraplength dos labels — não o tamanho da janela.
        self.geometry("520x420")
        self.resizable(False, True)
        self.grab_set()
        self._wrap = 470   # largura útil: 520 - 2*18 de padding, com folga

        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text="Salvar coleção", font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Separator(f, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        self._mode = tk.StringVar(value=app._col_save_mode)
        ttk.Label(f, text="Formato:").pack(anchor=tk.W)
        ttk.Radiobutton(f, text="Original — resolução do vídeo",
                        variable=self._mode, value="original",
                        command=self._refresh).pack(anchor=tk.W, padx=(12, 0))
        ttk.Radiobutton(f, text="R36S — 640x480, legenda maior",
                        variable=self._mode, value="r36s",
                        command=self._refresh).pack(anchor=tk.W, padx=(12, 0))

        self._skip_zero = tk.BooleanVar(value=app._col_skip_zero)
        ttk.Checkbutton(f, text="Ignorar frases com nota 0",
                        variable=self._skip_zero,
                        command=self._refresh).pack(anchor=tk.W, pady=(10, 0))

        # Variantes de legenda: no ditado, os jogos 3 e 4 mostram a imagem que
        # esconde a resposta. Sem elas esses dois jogos não acontecem.
        self._variants = tk.BooleanVar(value=app._col_variants)
        ttk.Checkbutton(f, text="Gerar variantes de imagem (jogos 3 e 4 do ditado)",
                        variable=self._variants,
                        command=self._refresh).pack(anchor=tk.W, pady=(10, 0))

        # Ditado: NÃO ligado ao _refresh, que refaz duas passadas O(n) sobre os
        # matches (custa caro com dezenas de milhares). Este checkbox não muda a
        # contagem, só a linha de estimativa.
        self._make_bundle = tk.BooleanVar(value=app._col_make_bundle)
        self._bundle_chk = ttk.Checkbutton(f, text="Gerar também ditado",
                                           variable=self._make_bundle,
                                           command=self._refresh_bundle)
        self._bundle_chk.pack(anchor=tk.W, pady=(6, 0))
        self._bundle_info = tk.StringVar()
        ttk.Label(f, textvariable=self._bundle_info, foreground="#888",
                  font=("", 9), wraplength=self._wrap,
                  justify=tk.LEFT).pack(anchor=tk.W, padx=(20, 0))

        self._summary = tk.StringVar()
        # wraplength aqui é o conserto do texto cortado: sem ele o resumo com as
        # duas razões de descarte e contagens de 5 dígitos passava da largura e
        # era simplesmente truncado à direita.
        ttk.Label(f, textvariable=self._summary, wraplength=self._wrap,
                  justify=tk.LEFT).pack(anchor=tk.W, pady=(10, 0))
        self._dest = tk.StringVar()
        ttk.Label(f, textvariable=self._dest, foreground="#888",
                  font=("", 9), wraplength=self._wrap,
                  justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 0))

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        self._save_btn = ttk.Button(btns, text="Salvar", command=self._save)
        self._save_btn.pack(side=tk.RIGHT)

        self._refresh()

    def _refresh(self, _=None):
        """Recalcula contagem e destino conforme formato e filtro escolhidos."""
        cb = self.app._col_import()
        mode = self._mode.get()
        itens, motivos = self.app._col_save_items(self._skip_zero.get())

        if not itens:
            self._n_total = 0
            self._summary.set("Nada a salvar com esse filtro.")
            self._dest.set("Nenhuma frase da lista sobrou "
                           "(nota 0, sem texto chinês ou repetida).")
            self._save_btn.config(state=tk.DISABLED)
            self._refresh_bundle()
            return

        self._n_total = len(itens)   # o _refresh_bundle reusa sem repetir a varredura
        # Mesmo detalhamento do log: nota 0, "sem texto chinês" e repetida são
        # motivos diferentes e o rótulo não pode chamar os três de nota 0.
        extra = f"  (ignoradas: {', '.join(motivos)})" if motivos else ""
        # Com as variantes são três arquivos por frase, e o número que importa
        # para o disco é o de imagens, não o de frases.
        n_img = len(itens) * 3 if self._variants.get() else len(itens)
        imagens = (f"{len(itens)} frase(s), {n_img} imagens"
                   if n_img != len(itens) else f"{len(itens)} imagem(ns)")
        self._summary.set(f"{imagens} numa coleção{extra}")

        label = self.app._col_query or "coleção"
        nome = f"{cb.collection_folder_name(label, itens)}_{mode}"
        self._dest.set(f"→ warehouse/collections/{nome}")
        self._save_btn.config(state=tk.NORMAL)
        self._refresh_bundle()

    def _refresh_bundle(self, _=None):
        """Habilita/desabilita o ditado e mostra a estimativa do bundle.

        No formato Original o bundle não serve: as imagens são de resolução cheia
        e cada arquivo passaria dos 60 MB que o Chrome do Android aguenta.
        """
        if self._mode.get() == "original":
            self._bundle_chk.config(state=tk.DISABLED)
            self._bundle_info.set("Só no formato R36S — no Original cada arquivo "
                                  "passaria de 60 MB e o Chrome do celular não abre.")
            return

        self._bundle_chk.config(state=tk.NORMAL)
        if not self._make_bundle.get() or not getattr(self, "_n_total", 0):
            self._bundle_info.set("")
            return

        # Medido nas coleções r36s reais: ~60 KB por imagem em base64 e ~6 ms
        # para re-encodar. Serve para o passo de minutos e gigabytes não ser
        # uma surpresa depois de clicar em Salvar.
        n = self._n_total
        arquivos = -(-n // 150)          # ceil
        gb = n * 60 / 1024 / 1024
        minutos = n * 0.006 / 60
        self._bundle_info.set(
            f"≈ {arquivos} arquivo(s) em dictation/, ~{gb:.1f} GB, ~{max(1, round(minutos))} min")

    def _save(self):
        mode, skip_zero = self._mode.get(), self._skip_zero.get()
        # Checkbox desabilitado no Tk MANTÉM o valor da variável, então marcar no
        # R36S e trocar para Original geraria o bundle sem isto.
        make_bundle = self._make_bundle.get() and mode != "original"
        variants = self._variants.get()
        self.destroy()
        self.app._col_save_run(mode, skip_zero, make_bundle, variants)


# ─── Dialog: Restaurar do HD externo (Warehouse) ───────────────────────────────
class RestoreDialog(tk.Toplevel):
    """Lista o que está no HD externo, agrupado e sanfonado como a lista do
    Warehouse, para escolher o que trazer de volta. Serve ao warehouse
    (episódios) e aos assets (material bruto) — quem chama passa como varrer,
    medir e restaurar.

    ``scan()`` roda numa thread e devolve ``{nome: status}``; itens com status
    "Já no computador" aparecem em cinza e são ignorados (restaurá-los
    sobrescreveria o local, que pode ser mais novo). ``size(nome)`` dá os
    bytes no HD e ``run(plan, delete_src)`` executa com
    ``plan = [(nome, bytes)]``."""

    def __init__(self, app: App, hd: Path, title: str, scan, size, run,
                 local_root: Path, onde: str):
        super().__init__(app)
        self.app = app
        self.hd = hd
        self._scan, self._size, self._run = scan, size, run
        self._local_root, self._onde = local_root, onde
        self.title(title)
        self.geometry("640x600")
        self.minsize(460, 380)
        self.transient(app)
        self.grab_set()
        self._status: dict = {}   # asset -> status no HD (ou "Já no computador")

        f = ttk.Frame(self, padding=12)
        f.pack(fill=tk.BOTH, expand=True)
        ttk.Label(f, text=f"{title} — {hd}",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))

        lf = ttk.Frame(f)
        lf.pack(fill=tk.BOTH, expand=True)
        t = ttk.Treeview(lf, columns=("status",), show="tree headings",
                         selectmode="extended")
        t.heading("#0",     text="Nome",          anchor=tk.W)
        t.heading("status", text="Status no HD",  anchor=tk.CENTER)
        t.column("#0",     width=360, anchor=tk.W,      stretch=True)
        t.column("status", width=180, anchor=tk.CENTER, stretch=False)
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        t.tag_configure("ok",       foreground="#27AE60")
        t.tag_configure("archived", foreground="#2980B9")
        t.tag_configure("missing",  foreground="#E74C3C")
        t.tag_configure("local",    foreground="#999")
        t.tag_configure("group",    font=("", 12, "bold"))
        t.bind("<<TreeviewSelect>>", lambda _: self._update_btn())
        t.insert("", tk.END, iid="__loading__", text="Carregando…", values=("",))
        self._tree = t

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(10, 0))
        self._count = tk.StringVar(value="")
        ttk.Label(btns, textvariable=self._count, foreground="#888").pack(side=tk.LEFT)
        self._restore_btn = ttk.Button(btns, text="Restaurar...", state=tk.DISABLED,
                                       command=self._restore)
        self._restore_btn.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Fechar", command=self.destroy).pack(side=tk.RIGHT, padx=4)

        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        """Varre o HD fora da thread da UI — o disco externo pode ser lento."""
        try:
            status, err = self._scan(), None
        except OSError as e:
            status, err = {}, e
        try:
            self.after(0, lambda: self._fill(status, err))
        except (RuntimeError, tk.TclError):
            pass   # modal fechado durante a carga

    def _fill(self, status: dict, err):
        if not self.winfo_exists():
            return
        t = self._tree
        t.delete(*t.get_children())
        if err is not None:
            t.insert("", tk.END, text=f"Erro ao ler o HD: {err}", values=("",))
            return
        if not status:
            t.insert("", tk.END, text="(nenhum episódio no HD)", values=("",))
            return
        self._status = status
        tags = {"Completo": "ok", "Arquivado": "archived", "Só texto": "missing",
                "Só no HD": "ok", "Já no computador": "local"}
        for key, nome, stems in core.wh_group_list(list(status)):
            n_local = sum(1 for a in stems if status[a] == "Já no computador")
            n_hd = len(stems) - n_local
            resumo = " · ".join(x for x in (
                f"{n_hd} só no HD" if n_hd else "",
                f"{n_local} já local" if n_local else "") if x)
            gid = f"grp:{key or ''}"
            t.insert("", tk.END, iid=gid, text=f"{nome}  ({len(stems)})",
                     values=(resumo,), tags=("group",), open=False)
            for a in stems:
                t.insert(gid, tk.END, iid=a, text=_wh_readable_name(a),
                         values=(status[a],), tags=(tags[status[a]],))
        n_local = sum(1 for v in status.values() if v == "Já no computador")
        self._count.set(f"{len(status)} no HD · {len(status) - n_local} restaurável(is)")

    def _selected(self) -> list:
        """Assets restauráveis da seleção; um grupo vale todos os filhos."""
        t = self._tree
        sel = set(t.selection())
        out = []
        for gid in t.get_children():
            for a in t.get_children(gid):
                if (gid in sel or a in sel) and self._status.get(a) not in (
                        None, "Já no computador"):
                    out.append(a)
        return out

    def _update_btn(self):
        n = len(self._selected())
        self._restore_btn.config(text="Restaurar..." if n <= 1 else f"Restaurar {n}...",
                                 state=tk.NORMAL if n else tk.DISABLED)

    def _restore(self):
        assets = self._selected()
        if not assets:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            plan = [(a, self._size(a)) for a in assets]
            livre = core.disk_free(self._local_root)
        except OSError as e:
            self.config(cursor="")
            messagebox.showerror("Restaurar", f"Erro ao ler o HD:\n{e}", parent=self)
            return
        self.config(cursor="")
        total = sum(n for _, n in plan)
        if total > livre:
            messagebox.showerror(
                "Restaurar",
                f"Espaço insuficiente no computador: precisa de "
                f"{total / 1024**3:.2f} GB, livre {livre / 1024**3:.2f} GB.", parent=self)
            return
        resp = App._hd_ask_restore(self, plan, self._status, self._onde)
        if resp is None:
            return
        self.destroy()
        self._run(plan, resp)


# ─── Dialog: Asset Filter (Coleções) ────────────────────────────────────────────
class AssetFilterDialog(tk.Toplevel):
    """Pop-up de seleção de assets (checkboxes) para filtrar a busca de coleções.

    Agrupado por prefixo como a lista do Warehouse (``_wh_group_list``): cada
    grupo tem uma seta para recolher, um checkbox que marca/desmarca o grupo
    inteiro (parcial = estado "alternate") e um contador de marcados."""

    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Filtrar por assets")
        self.geometry("620x640")
        self.minsize(460, 420)
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
        ttk.Button(top, text="Expandir todos",
                   command=lambda: self._set_all_open(True)).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(top, text="Recolher todos",
                   command=lambda: self._set_all_open(False)).pack(side=tk.LEFT, padx=4)

        # Área rolável de checkboxes
        canvas_f = ttk.Frame(f)
        canvas_f.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(canvas_f, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_f, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        # O conteúdo acompanha a largura do Canvas (contador alinhado à direita).
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Scroll com mouse no Mac
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._wheel = _on_mousewheel
        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner.bind("<MouseWheel>", _on_mousewheel)

        self._vars = {}
        self._groups = []   # dicts: key, header, arrow, body, var, cb, count, stems
        self._bulk = False  # marcando um grupo inteiro: sincroniza só no fim
        for key, nome, stems in core.wh_group_list(assets):
            self._add_group(inner, key, nome, stems, current)

        if not assets:
            ttk.Label(inner, text="(nenhum base.txt no warehouse)",
                      foreground="#888").pack(anchor=tk.W)

        btns = ttk.Frame(f)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Cancelar", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Aplicar",  command=self._apply).pack(side=tk.RIGHT)

    def _add_group(self, parent, key, nome: str, stems: list, current):
        gid = key or ""
        g = {"key": gid, "stems": stems}
        header = ttk.Frame(parent)
        header.pack(fill=tk.X, pady=(2, 0))
        arrow = ttk.Label(header, width=2, cursor="hand2")
        arrow.pack(side=tk.LEFT)
        var = tk.BooleanVar()
        cb = ttk.Checkbutton(header, text=f"{nome}  ({len(stems)})", variable=var,
                             style="Group.TCheckbutton",
                             command=lambda: self._toggle_group_check(g))
        cb.pack(side=tk.LEFT)
        count = ttk.Label(header, foreground="#888")
        count.pack(side=tk.RIGHT, padx=(0, 6))
        body = ttk.Frame(parent)
        g.update(header=header, arrow=arrow, body=body, var=var, cb=cb, count=count)

        for stem in stems:
            checked = (current is None) or (stem in current)
            v = tk.BooleanVar(value=checked)
            v.trace_add("write", lambda *_: self._sync_group(g))
            self._vars[stem] = v
            c = ttk.Checkbutton(body, text=_wh_readable_name(stem), variable=v)
            c.pack(anchor=tk.W, padx=(36, 0), pady=1)
            c.bind("<MouseWheel>", self._wheel)

        for w in (header, arrow, cb, count, body):
            w.bind("<MouseWheel>", self._wheel)
        arrow.bind("<Button-1>", lambda _: self._set_open(g, not g.get("open")))
        self._groups.append(g)
        self._set_open(g, gid in self.app._col_filter_open)
        self._sync_group(g)

    def _set_open(self, g: dict, aberto: bool):
        g["open"] = aberto
        g["arrow"].config(text="▾" if aberto else "▸")
        if aberto:
            g["body"].pack(fill=tk.X, after=g["header"])
            self.app._col_filter_open.add(g["key"])
        else:
            g["body"].pack_forget()
            self.app._col_filter_open.discard(g["key"])

    def _set_all_open(self, aberto: bool):
        for g in self._groups:
            self._set_open(g, aberto)

    def _sync_group(self, g: dict):
        """Checkbox do grupo e contador a partir dos filhos."""
        if self._bulk:
            return
        n = sum(1 for s in g["stems"] if self._vars[s].get())
        total = len(g["stems"])
        g["var"].set(n == total)
        g["cb"].state(["alternate"] if 0 < n < total else ["!alternate"])
        g["count"].config(text=f"{n}/{total}")

    def _toggle_group_check(self, g: dict):
        # Parcial ou desmarcado → marca tudo; marcado → desmarca tudo.
        marcar = g["var"].get()
        self._bulk = True
        for s in g["stems"]:
            self._vars[s].set(marcar)
        self._bulk = False
        self._sync_group(g)

    def _set_all(self, valor: bool):
        self._bulk = True
        for v in self._vars.values():
            v.set(valor)
        self._bulk = False
        for g in self._groups:
            self._sync_group(g)

    def _select_all(self):
        self._set_all(True)

    def _clear_all(self):
        self._set_all(False)

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
        cmd = [SCRAPER_PY, str(REPO / "scrape_globoplay_episodes.py"),
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
        cmd = [PY, str(REPO / "video_fetcher.py"), self.series, ep]
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
    # Antes do Tk(): o Dock lê o nome do app quando o processo se registra.
    set_app_name(APP_NAME)
    app = App()
    app.mainloop()
