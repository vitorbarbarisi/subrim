#!/bin/sh
# Script de configuração inicial para Alpine Linux VM
# Execute este script após a instalação básica do Alpine

set -e

echo "🚀 Configurando Alpine Linux VM..."

# Atualizar sistema
echo "📦 Atualizando sistema..."
apk update && apk upgrade

# Instalar ferramentas essenciais
echo "📦 Instalando ferramentas essenciais..."
apk add bash vim git curl wget

# Instalar Python e ferramentas de desenvolvimento
echo "🐍 Instalando Python..."
apk add python3 py3-pip build-base

# Instalar Node.js (opcional)
echo "📦 Instalando Node.js..."
apk add nodejs npm

# Instalar Docker (opcional)
echo "🐳 Instalando Docker..."
apk add docker docker-compose
rc-service docker start
rc-update add docker

# Instalar e configurar sudo
echo "🔐 Configurando sudo..."
apk add sudo
if ! grep -q "%wheel ALL=(ALL) ALL" /etc/sudoers; then
    echo "%wheel ALL=(ALL) ALL" >> /etc/sudoers
fi

# Instalar e configurar SSH
echo "🔌 Configurando SSH..."
apk add openssh
rc-service sshd start
rc-update add sshd

# Configurar bash como shell padrão
echo "🐚 Configurando bash..."
if ! grep -q "/bin/bash" /etc/shells; then
    echo "/bin/bash" >> /etc/shells
fi

# Criar diretório para desenvolvimento
echo "📁 Criando diretórios..."
mkdir -p ~/dev ~/projects

echo ""
echo "✅ Configuração concluída!"
echo ""
echo "📋 Próximos passos:"
echo "   1. Criar usuário: adduser seuusuario"
echo "   2. Adicionar ao grupo wheel: adduser seuusuario wheel"
echo "   3. Configurar chave SSH (opcional)"
echo "   4. Reiniciar: reboot"
echo ""

