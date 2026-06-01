#!/bin/sh
# Script completo para montar SD card na VM Alpine Linux

echo "🔍 Verificando dispositivos disponíveis..."
echo ""

# Instalar ferramentas necessárias
echo "📦 Instalando ferramentas..."
apk add --no-cache util-linux dosfstools exfat-utils ntfs-3g 2>/dev/null || true

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "📋 PASSO 1: Conectar SD Card à VM"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "No UTM (no Mac):"
echo "  1. Com a VM rodando, clique no ícone USB na barra superior"
echo "  2. Selecione o SD card da lista"
echo "  3. O dispositivo será conectado à VM"
echo ""
echo "Pressione ENTER quando o SD card estiver conectado..."
read dummy

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "📋 PASSO 2: Identificar o Dispositivo"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Listar dispositivos de bloco
echo "💾 Dispositivos de bloco disponíveis:"
if command -v lsblk >/dev/null 2>&1; then
    lsblk
else
    echo "Instalando lsblk..."
    apk add --no-cache util-linux
    lsblk
fi

echo ""
echo "📦 Dispositivos em /dev:"
ls -lh /dev/sd* /dev/mmcblk* /dev/nvme* 2>/dev/null | head -20

echo ""
echo "🔍 Verificando partições:"
fdisk -l 2>/dev/null | grep -E "^/dev|Disk /dev" | head -20 || echo "Execute como root: fdisk -l"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "📋 PASSO 3: Montar o SD Card"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Detectar dispositivo automaticamente
SD_DEVICE=""
SD_PARTITION=""

# Tentar detectar automaticamente (geralmente /dev/sdb ou /dev/mmcblk0)
for dev in /dev/sdb /dev/sdc /dev/mmcblk0 /dev/mmcblk1; do
    if [ -b "$dev" ]; then
        # Verificar se tem partições
        if [ -b "${dev}1" ]; then
            SD_PARTITION="${dev}1"
            SD_DEVICE="$dev"
            break
        elif [ -b "$dev" ]; then
            SD_DEVICE="$dev"
            break
        fi
    fi
done

if [ -z "$SD_PARTITION" ] && [ -z "$SD_DEVICE" ]; then
    echo "⚠️  Não foi possível detectar automaticamente o SD card"
    echo ""
    echo "Por favor, informe o dispositivo manualmente:"
    echo "  Exemplos: /dev/sdb1, /dev/sdc1, /dev/mmcblk0p1"
    echo ""
    read -p "Digite o dispositivo (ou Enter para pular): " manual_device
    
    if [ -n "$manual_device" ]; then
        SD_PARTITION="$manual_device"
    else
        echo "❌ Nenhum dispositivo especificado"
        exit 1
    fi
fi

# Usar partição se encontrada, senão usar dispositivo
MOUNT_DEVICE="${SD_PARTITION:-$SD_DEVICE}"

if [ -z "$MOUNT_DEVICE" ]; then
    echo "❌ Nenhum dispositivo encontrado"
    exit 1
fi

echo "✅ Dispositivo detectado: $MOUNT_DEVICE"
echo ""

# Detectar tipo de filesystem
echo "🔍 Detectando tipo de filesystem..."
FS_TYPE=$(blkid -s TYPE -o value "$MOUNT_DEVICE" 2>/dev/null || echo "unknown")

if [ "$FS_TYPE" = "unknown" ] || [ -z "$FS_TYPE" ]; then
    echo "⚠️  Tipo de filesystem não detectado automaticamente"
    echo ""
    echo "Tipos comuns:"
    echo "  - vfat (FAT32)"
    echo "  - exfat (ExFAT)"
    echo "  - ntfs (NTFS)"
    echo "  - ext4 (Linux)"
    echo ""
    read -p "Digite o tipo de filesystem (ou Enter para tentar auto-detectar): " manual_fs
    FS_TYPE="${manual_fs:-auto}"
fi

echo "📁 Tipo de filesystem: $FS_TYPE"
echo ""

# Criar ponto de montagem
MOUNT_POINT="/mnt/sdcard"
mkdir -p "$MOUNT_POINT"

echo "📂 Ponto de montagem: $MOUNT_POINT"
echo ""

# Montar
echo "🔧 Montando dispositivo..."
MOUNT_OPTIONS=""

case "$FS_TYPE" in
    vfat|msdos)
        MOUNT_OPTIONS="-o uid=1000,gid=1000,umask=0002"
        ;;
    exfat)
        MOUNT_OPTIONS="-o uid=1000,gid=1000,umask=0002"
        if ! command -v mount.exfat >/dev/null 2>&1; then
            echo "Instalando suporte ExFAT..."
            apk add --no-cache exfat-utils
        fi
        ;;
    ntfs)
        MOUNT_OPTIONS="-o uid=1000,gid=1000,umask=0002"
        if ! command -v mount.ntfs >/dev/null 2>&1; then
            echo "Instalando suporte NTFS..."
            apk add --no-cache ntfs-3g
        fi
        ;;
    auto|unknown)
        # Tentar montar sem especificar tipo
        MOUNT_OPTIONS="-o uid=1000,gid=1000,umask=0002"
        ;;
esac

if mount $MOUNT_OPTIONS "$MOUNT_DEVICE" "$MOUNT_POINT" 2>/dev/null; then
    echo "✅ SD card montado com sucesso!"
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "📋 PASSO 4: Acessar o Conteúdo"
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    echo "📂 Conteúdo do SD card:"
    echo ""
    ls -lh "$MOUNT_POINT" | head -20
    echo ""
    echo "💡 O SD card está montado em: $MOUNT_POINT"
    echo ""
    echo "📋 Comandos úteis:"
    echo "  - Ver conteúdo: ls -lh $MOUNT_POINT"
    echo "  - Copiar arquivo: cp arquivo.txt $MOUNT_POINT/"
    echo "  - Desmontar: umount $MOUNT_POINT"
    echo ""
else
    echo "❌ Erro ao montar o dispositivo"
    echo ""
    echo "Tentando como root..."
    if [ "$(id -u)" != "0" ]; then
        echo "Execute como root:"
        echo "  sudo mount $MOUNT_OPTIONS $MOUNT_DEVICE $MOUNT_POINT"
        echo ""
        echo "Ou tente montar manualmente:"
        echo "  mount -t $FS_TYPE $MOUNT_OPTIONS $MOUNT_DEVICE $MOUNT_POINT"
    else
        mount $MOUNT_OPTIONS "$MOUNT_DEVICE" "$MOUNT_POINT"
    fi
fi

