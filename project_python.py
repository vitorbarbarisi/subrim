"""Relança o script num Python que tenha os módulos de que ele precisa.

O ``python3`` do Homebrew muda de versão sozinho num ``brew upgrade`` (ex.: foi
para o 3.15, sem Tk nem as dependências do projeto). Em vez de quebrar, o
script chama ``ensure("tkinter")`` antes desses imports: se o Python atual não
os tem, procura outra versão instalada que tenha e se troca por ela (execv).
Só stdlib, seguro importar no topo.
"""
import os
import shutil
import subprocess
import sys

CANDIDATES = ("python3.15", "python3.14", "python3.13", "python3.12")
_GUARD = "SUBRIM_PY_REEXEC"  # evita relançar em loop


def _has(modules: tuple[str, ...]) -> bool:
    try:
        for m in modules:
            __import__(m)
    except ImportError:
        return False
    return True


def ensure(*modules: str) -> None:
    if _has(modules) or os.environ.get(_GUARD):
        return
    here = os.path.realpath(sys.executable)
    probe = "import sys\nfor m in sys.argv[1:]: __import__(m)"
    for name in CANDIDATES:
        exe = shutil.which(name)
        if not exe or os.path.realpath(exe) == here:
            continue
        if subprocess.run([exe, "-c", probe, *modules], capture_output=True).returncode == 0:
            print(f"↪ {os.path.basename(sys.executable)} sem {', '.join(modules)}; "
                  f"relançando com {name}", file=sys.stderr)
            os.environ[_GUARD] = "1"
            os.execv(exe, [exe, os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    # Nenhum serve: segue e deixa o import original falhar com a mensagem dele.
