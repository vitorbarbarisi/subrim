#!/bin/sh
# Exibe um balão/caixa gráfica com "Olá" quando possível.
# Compatível com ARM; tenta várias ferramentas comuns e faz fallback para TUI.

# Melhor chance de encontrar um display
: "${DISPLAY:=:0}"
export DISPLAY

# Tenta zenity (GTK)
if command -v zenity >/dev/null 2>&1; then
  zenity --question --title="R36S Viewer" --text="Olá" --ok-label="OK" --cancel-label="Sair" --width=260 --height=140 2>/dev/null && exit 0
  exit 0
fi

# Tenta yad (GTK)
if command -v yad >/dev/null 2>&1; then
  yad --center --title="R36S Viewer" --text="Olá" --button=OK:0 --button=Sair:1 --width=260 --height=140 2>/dev/null
  exit 0
fi

# Tenta kdialog (Qt)
if command -v kdialog >/dev/null 2>&1; then
  kdialog --yesno "Olá" --yes-label OK --no-label Sair 2>/dev/null
  exit 0
fi

# Tenta notificação (libnotify)
if command -v notify-send >/dev/null 2>&1; then
  notify-send "R36S Viewer" "Olá" 2>/dev/null && exit 0
fi

# Tenta whiptail/dialog (TUI)
if command -v whiptail >/dev/null 2>&1; then
  whiptail --title "R36S Viewer" --yesno "Olá" 8 24 2>/dev/null
  exit 0
fi
if command -v dialog >/dev/null 2>&1; then
  dialog --title "R36S Viewer" --yesno "Olá" 8 24 2>/dev/null
  exit 0
fi

# Fallback simples
printf "Olá\n"
exit 0
