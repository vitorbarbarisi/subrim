#!/bin/bash
# Script para configurar e abrir VM Linux no UTM

set -e

VM_NAME="Alpine Linux"
ISO_PATH="$HOME/Downloads/vm_isos/alpine-standard.iso"
UTM_APP="/Applications/UTM.app"

echo "🚀 Configurando VM Linux..."

# Verificar se ISO existe
if [ ! -f "$ISO_PATH" ]; then
    echo "❌ ISO não encontrada em: $ISO_PATH"
    exit 1
fi

echo "✅ ISO encontrada: $ISO_PATH"
echo ""

# Abrir UTM
echo "📱 Abrindo UTM..."
open "$UTM_APP"

echo ""
echo "✅ UTM aberto!"
echo ""
echo "📋 Instruções para criar a VM:"
echo "   1. No UTM, clique em 'Create a New Virtual Machine'"
echo "   2. Escolha 'Virtualize' → 'Linux'"
echo "   3. Selecione 'Use an existing boot ISO image'"
echo "   4. Escolha o arquivo: $ISO_PATH"
echo "   5. Configure:"
echo "      - RAM: 2GB (mínimo) ou 4GB (recomendado)"
echo "      - CPU: 2-4 cores"
echo "      - Disco: 20GB (mínimo) ou 40GB (recomendado)"
echo "   6. Clique em 'Save' e depois 'Play'"
echo ""
echo "💡 Após iniciar, execute 'setup-alpine' para instalar"
echo ""

