#!/bin/sh
# Script para montar SD card na VM Alpine Linux

echo "🔍 Procurando dispositivos de bloco..."
echo ""

# Listar todos os dispositivos de bloco
echo "📦 Dispositivos disponíveis:"
lsblk 2>/dev/null || blkid 2>/dev/null || echo "Instalando lsblk..."
apk add --no-cache util-linux 2>/dev/null || true
lsblk

echo ""
echo "💾 Dispositivos de bloco em /dev:"
ls -lh /dev/sd* /dev/mmcblk* /dev/nvme* 2>/dev/null | head -20

echo ""
echo "🔍 Verificando dispositivos USB conectados..."
dmesg | tail -30 | grep -i "usb\|sd\|mmc" || echo "Verifique os logs do sistema"

echo ""
echo "📋 Para montar um dispositivo:"
echo "   1. Identifique o dispositivo (ex: /dev/sdb1, /dev/mmcblk0p1)"
echo "   2. Crie um ponto de montagem: mkdir -p /mnt/sdcard"
echo "   3. Monte o dispositivo: mount /dev/sdb1 /mnt/sdcard"
echo ""
echo "💡 Dica: Use 'fdisk -l' ou 'lsblk' para ver partições"

