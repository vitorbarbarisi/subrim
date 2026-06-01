# 📋 Guia: Montar SD Card na VM

## Passo 1: Conectar SD Card à VM

No **UTM** (no Mac):
1. Com a VM rodando, clique no **ícone USB** na barra superior da janela da VM
2. Selecione o **SD card** da lista de dispositivos USB
3. O dispositivo será conectado à VM

## Passo 2: Identificar o Dispositivo na VM

Execute na VM:

```bash
# Listar dispositivos de bloco
lsblk

# Ou ver dispositivos em /dev
ls -lh /dev/sd* /dev/mmcblk*

# Ver partições (como root)
fdisk -l
```

O SD card geralmente aparece como:
- `/dev/sdb` ou `/dev/sdb1` (primeira partição)
- `/dev/sdc` ou `/dev/sdc1`
- `/dev/mmcblk0` ou `/dev/mmcblk0p1`

## Passo 3: Instalar Ferramentas (Alpine Linux)

```bash
# Instalar ferramentas necessárias
apk add util-linux dosfstools exfat-utils ntfs-3g
```

## Passo 4: Montar o SD Card

### Para ExFAT/FAT32:

```bash
# Criar ponto de montagem
mkdir -p /mnt/sdcard

# Montar (substitua /dev/sdb1 pelo seu dispositivo)
mount -t exfat /dev/sdb1 /mnt/sdcard

# Ou para FAT32
mount -t vfat /dev/sdb1 /mnt/sdcard
```

### Para NTFS:

```bash
mount -t ntfs-3g /dev/sdb1 /mnt/sdcard
```

### Auto-detectar tipo:

```bash
mount /dev/sdb1 /mnt/sdcard
```

## Passo 5: Acessar o Conteúdo

```bash
# Ver conteúdo
ls -lh /mnt/sdcard

# Navegar
cd /mnt/sdcard

# Copiar arquivo
cp /caminho/arquivo.txt /mnt/sdcard/

# Ver espaço usado
df -h /mnt/sdcard
```

## Desmontar

```bash
umount /mnt/sdcard
```

## Script Completo (Copie e Cole na VM)

```bash
#!/bin/sh
# Detectar e montar SD card automaticamente

# Instalar ferramentas
apk add --no-cache util-linux dosfstools exfat-utils ntfs-3g

# Listar dispositivos
echo "Dispositivos disponíveis:"
lsblk

# Detectar SD card (geralmente /dev/sdb1 ou /dev/sdc1)
SD_DEVICE=""
for dev in /dev/sdb1 /dev/sdc1 /dev/mmcblk0p1; do
    if [ -b "$dev" ]; then
        SD_DEVICE="$dev"
        break
    fi
done

if [ -z "$SD_DEVICE" ]; then
    echo "SD card não detectado automaticamente"
    echo "Execute: lsblk para ver dispositivos"
    exit 1
fi

echo "Montando $SD_DEVICE..."

# Criar ponto de montagem
mkdir -p /mnt/sdcard

# Tentar montar
if mount "$SD_DEVICE" /mnt/sdcard 2>/dev/null; then
    echo "✅ SD card montado em /mnt/sdcard"
    echo ""
    echo "Conteúdo:"
    ls -lh /mnt/sdcard
else
    echo "❌ Erro ao montar. Tente manualmente:"
    echo "  mount -t exfat $SD_DEVICE /mnt/sdcard"
    echo "  ou"
    echo "  mount -t vfat $SD_DEVICE /mnt/sdcard"
fi
```

## Troubleshooting

### Dispositivo não aparece
- Verifique se conectou o SD card no UTM (ícone USB)
- Execute `dmesg | tail` para ver logs do sistema
- Verifique se o SD card está inserido no Mac

### Erro "mount: unknown filesystem type 'exfat'"
```bash
apk add exfat-utils
```

### Erro "Permission denied"
Execute como root:
```bash
sudo mount /dev/sdb1 /mnt/sdcard
```

### Ver tipo de filesystem
```bash
blkid /dev/sdb1
```

