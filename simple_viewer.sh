#!/bin/bash
# Simples "transpilação" da lógica do r36s_viewer.c para shell.
# Objetivo: escolher um diretório em assets/ e exibir as imagens em tela cheia
# usando um viewer disponível (feh/sxiv/fbi). Sem sobreposição de legendas.

set -euo pipefail

# WSL helper: if running under WSL without WSLg and DISPLAY not set, try to set it for X server on Windows
if grep -qi microsoft /proc/version 2>/dev/null; then
  if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    ns=$(grep -m1 nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}')
    if [ -n "$ns" ]; then
      export DISPLAY="$ns:0"
      export LIBGL_ALWAYS_INDIRECT=1
    fi
  fi
fi

ASSETS_ROOT="assets"

die() { echo "ERROR: $*" >&2; exit 1; }

# Detectar viewer disponível
choose_viewer() {
  if command -v feh >/dev/null 2>&1; then echo feh; return; fi
  if command -v nsxiv >/dev/null 2>&1; then echo nsxiv; return; fi
  if command -v sxiv >/dev/null 2>&1; then echo sxiv; return; fi
  if command -v fbi >/dev/null 2>&1; then echo fbi; return; fi
  echo none
}

# Mostrar menu com whiptail/dialog, senão fallback via stdin
choose_directory() {
  local choices
  mapfile -t choices < <(find "$ASSETS_ROOT" -mindepth 1 -maxdepth 1 -type d | sort)
  [ ${#choices[@]} -gt 0 ] || die "Nenhum diretório em $ASSETS_ROOT"

  # Tentar whiptail
  if command -v whiptail >/dev/null 2>&1; then
    local opts=()
    local i=1
    for d in "${choices[@]}"; do opts+=("$i" "${d#${ASSETS_ROOT}/}"); ((i++)); done
    local sel
    sel=$(whiptail --title "Escolha um diretório" --menu "assets/" 20 60 12 "${opts[@]}" 3>&1 1>&2 2>&3) || exit 1
    echo "${choices[$((sel-1))]}"
    return
  fi

  # Tentar dialog
  if command -v dialog >/dev/null 2>&1; then
    local opts=()
    local i=1
    for d in "${choices[@]}"; do opts+=("$i" "${d#${ASSETS_ROOT}/}"); ((i++)); done
    local sel
    sel=$(dialog --title "Escolha um diretório" --menu "assets/" 20 60 12 "${opts[@]}" 3>&1 1>&2 2>&3) || exit 1
    echo "${choices[$((sel-1))]}"
    return
  fi

  # Fallback por stdin
  echo "Diretórios em $ASSETS_ROOT:" >&2
  local idx=1
  for d in "${choices[@]}"; do echo "  $idx) ${d#${ASSETS_ROOT}/}" >&2; ((idx++)); done
  read -rp "Escolha (número): " n
  [[ "$n" =~ ^[0-9]+$ ]] || die "Entrada inválida"
  (( n>=1 && n<=${#choices[@]} )) || die "Fora de faixa"
  echo "${choices[$((n-1))]}"
}

# Executar viewer
run_viewer() {
  local dir="$1"
  local viewer; viewer=$(choose_viewer)
  [ "$viewer" != none ] || die "Instale feh, sxiv ou fbi para visualizar imagens"

  mapfile -t imgs < <(find "$dir" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.bmp' \) | sort)
  [ ${#imgs[@]} -gt 0 ] || die "Sem imagens em ${dir}"

  case "$viewer" in
    feh)
      # Tela cheia, zoom automático, setas para navegar
      exec feh -F -Z -Y --auto-rotate --start-at "${imgs[0]}" "${imgs[@]}"
      ;;
    nsxiv)
      # nsxiv (fork do sxiv) – tela cheia (-f), pré-carrega (-a)
      exec nsxiv -f -a "${imgs[@]}"
      ;;
    sxiv)
      # Tela cheia (-f), pré-carrega (-a)
      exec sxiv -f -a "${imgs[@]}"
      ;;
    fbi)
      # Framebuffer console; requer tty. Navegação com setas
      exec fbi -t 5 -a "${imgs[@]}"
      ;;
  esac
}

main() {
  mkdir -p "$ASSETS_ROOT"
  local chosen
  if [ $# -ge 1 ]; then
    chosen="$ASSETS_ROOT/$1"
    [ -d "$chosen" ] || die "Diretório não encontrado: $chosen"
  else
    chosen=$(choose_directory) || exit 1
  fi
  run_viewer "$chosen"
}

main "$@"

