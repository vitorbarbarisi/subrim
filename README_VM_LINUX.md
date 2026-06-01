# 🐧 Guia: VM Linux Leve no Mac

Este guia explica como configurar uma máquina virtual Linux leve no macOS usando UTM (gratuito e open source).

## 📋 Opções de Software de Virtualização

### 1. UTM (Recomendado - Gratuito)
- ✅ Gratuito e open source
- ✅ Interface simples e moderna
- ✅ Boa performance no Mac
- ✅ Suporta Apple Silicon (M1/M2/M3) e Intel

### 2. VirtualBox (Alternativa Gratuita)
- ✅ Gratuito
- ⚠️ Performance inferior ao UTM
- ⚠️ Pode ter problemas no Mac com Apple Silicon

### 3. Parallels (Pago)
- ✅ Melhor performance
- ❌ Requer licença paga

## 🚀 Instalação com UTM

### Passo 1: Instalar UTM

```bash
# Via Homebrew (recomendado)
brew install --cask utm

# Ou baixe diretamente do site:
# https://mac.getutm.app/
```

### Passo 2: Baixar ISO Linux Leve

**Opções de distribuições leves:**

1. **Alpine Linux** (Mais leve - ~130MB)
   - Download: https://www.alpinelinux.org/downloads/
   - ISO: `alpine-standard-x.x.x-x86_64.iso` (para Intel) ou `alpine-standard-x.x.x-aarch64.iso` (para Apple Silicon)

2. **Lubuntu** (Ubuntu leve - ~2GB)
   - Download: https://lubuntu.me/downloads/
   - Interface gráfica completa

3. **Xubuntu** (Ubuntu com XFCE - ~2GB)
   - Download: https://xubuntu.org/download/
   - Interface gráfica moderna

### Passo 3: Criar VM no UTM

1. Abra o UTM
2. Clique em "Create a New Virtual Machine"
3. Escolha "Virtualize" → "Linux"
4. Selecione "Use an existing boot ISO image"
5. Escolha o arquivo ISO baixado
6. Configure:
   - **RAM**: 2GB (mínimo) a 4GB (recomendado)
   - **CPU**: 2-4 cores
   - **Disco**: 20GB (mínimo) a 40GB (recomendado)
7. Clique em "Save" e depois "Play"

## 🐧 Configuração Rápida: Alpine Linux

### Instalação Inicial

1. Ao iniciar a VM, digite `root` (sem senha)
2. Execute:
```bash
setup-alpine
```

3. Siga o assistente:
   - Keyboard: `us` (ou `br-abnt2` para teclado brasileiro)
   - Hostname: escolha um nome
   - Network: `eth0`
   - IP: `dhcp` (automático)
   - DNS: `none` (usa DHCP)
   - Timezone: `America/Sao_Paulo`
   - Proxy: `none`
   - NTP: `chrony`
   - SSH: `openssh`
   - Disk: `sda` → `sys` (instalação completa)
   - Erase disk: `y`

4. Após reiniciar, faça login como `root`

### Configuração Básica

```bash
# Atualizar sistema
apk update && apk upgrade

# Instalar ferramentas essenciais
apk add bash vim git curl wget

# Instalar Python e ferramentas de desenvolvimento
apk add python3 py3-pip build-base

# Instalar servidor SSH (se não instalou durante setup)
apk add openssh
rc-service sshd start
rc-update add sshd

# Criar usuário não-root
adduser meuusuario
# Adicionar ao grupo wheel (sudo)
adduser meuusuario wheel
```

### Habilitar Sudo

```bash
# Instalar sudo
apk add sudo

# Editar sudoers
visudo
# Descomentar a linha:
# %wheel ALL=(ALL) ALL
```

## 🐧 Configuração Rápida: Lubuntu/Xubuntu

### Instalação Inicial

1. Inicie a VM com o ISO
2. Escolha "Install Lubuntu/Xubuntu"
3. Siga o assistente gráfico
4. Configure usuário e senha
5. Aguarde a instalação

### Configuração Pós-Instalação

```bash
# Atualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar ferramentas essenciais
sudo apt install -y git curl wget vim build-essential

# Instalar Python e pip
sudo apt install -y python3 python3-pip python3-venv
```

## 🔧 Configurações Recomendadas da VM

### Recursos Mínimos Recomendados

- **RAM**: 2GB (Alpine) / 4GB (Lubuntu/Xubuntu)
- **CPU**: 2 cores
- **Disco**: 20GB
- **Rede**: NAT (padrão) ou Bridge (para acesso externo)

### Otimizações de Performance

1. **No UTM:**
   - Habilite "Use Hypervisor Framework" (Apple Silicon)
   - Aumente RAM se possível
   - Use disco virtual (não imagem física)

2. **Dentro da VM:**
   - Desabilite efeitos visuais desnecessários
   - Use ambiente gráfico leve (XFCE, LXDE)

## 📦 Script de Instalação Automática

Execute este script dentro da VM Alpine para instalar ferramentas comuns:

```bash
#!/bin/sh
# Instala ferramentas essenciais no Alpine Linux

apk update
apk add bash vim git curl wget python3 py3-pip build-base \
    openssh sudo docker docker-compose nodejs npm

# Configurar sudo para grupo wheel
echo "%wheel ALL=(ALL) ALL" >> /etc/sudoers

echo "✅ Instalação concluída!"
```

## 🌐 Compartilhamento de Arquivos

### Opção 1: SSH/SFTP
```bash
# No Mac, conecte via SFTP
sftp usuario@IP_DA_VM

# Ou use FileZilla/Transmit
```

### Opção 2: SMB/CIFS (Lubuntu/Xubuntu)
```bash
# Instalar servidor Samba
sudo apt install samba

# Configurar compartilhamento
sudo nano /etc/samba/smb.conf
```

### Opção 3: Pastas Compartilhadas (UTM)
- UTM suporta compartilhamento de pastas
- Configure em Settings → Sharing → Directory Sharing

## 🔍 Verificar IP da VM

```bash
# Dentro da VM
ip addr show
# ou
ifconfig

# No Mac, descobrir IPs na rede
arp -a
```

## 🐛 Troubleshooting

### VM não inicia
- Verifique se a virtualização está habilitada no Mac
- Tente aumentar a RAM alocada
- Verifique se o ISO está correto para sua arquitetura (x86_64 vs aarch64)

### Performance lenta
- Aumente RAM e CPU alocados
- Desabilite aceleração gráfica 3D
- Use distribuição mais leve (Alpine)

### Problemas de rede
- Verifique configuração de rede (NAT vs Bridge)
- Teste ping: `ping 8.8.8.8`
- Verifique DNS: `nslookup google.com`

### Problemas com Apple Silicon
- Use ISOs aarch64 (ARM64)
- Habilite "Use Hypervisor Framework" no UTM
- Algumas distribuições podem não ter suporte completo

## 📚 Recursos Adicionais

- **UTM Documentation**: https://docs.getutm.app/
- **Alpine Linux Wiki**: https://wiki.alpinelinux.org/
- **Lubuntu Documentation**: https://manual.lubuntu.me/

## 💡 Dicas

1. **Backup**: Faça snapshots da VM antes de grandes mudanças
2. **SSH**: Configure chaves SSH para acesso sem senha
3. **Docker**: Alpine é ótimo para containers Docker
4. **Desenvolvimento**: Use VS Code Remote SSH para desenvolvimento remoto

