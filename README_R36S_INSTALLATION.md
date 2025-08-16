# R36S Viewer - Guia de Instalação Completo

## Visão Geral

O R36S Viewer é uma aplicação SDL2 que permite visualizar imagens com legendas sincronizadas no console R36S. Ele suporta navegação por controle, exibição de legendas em múltiplas línguas e reprodução automática baseada em timestamps.

## Estrutura do SD Card R36S

Seu SD card tem duas partições:
- **R36S-OS V50 16GB (D:)** - Sistema operacional e aplicações
- **EASYROMS (F:)** - ROMs e arquivos de mídia grandes

## Passos de Instalação

### 1. Preparação no Computador

```bash
# 1. Compile para ARM (arquitetura do R36S)
./build_for_r36s.sh

# 2. Prepare o pacote de instalação
./prepare_r36s_package.sh

# 3. Conecte o SD card do R36S ao computador
# Certifique-se que ambas as partições estão montadas

# 4. Instale diretamente no SD card
./install_to_sd_card.sh
```

### 2. Estrutura Instalada no SD Card

```
R36S-OS V50 16GB/
├── apps/
│   └── r36s_viewer/
│       ├── r36s_viewer              # Executável principal
│       ├── launch_viewer.sh         # Script de inicialização
│       ├── install_to_r36s.sh       # Instalador do sistema
│       ├── uninstall.sh             # Desinstalador
│       ├── autostart.sh             # Auto-inicialização (opcional)
│       └── r36s_viewer.desktop      # Entrada do menu

EASYROMS/
└── r36s_viewer_assets/              # Assets (imagens e legendas)
    ├── chaves001/
    ├── chaves002/
    └── ...
```

### 3. Instalação no R36S

Conecte-se ao R36S via SSH ou use o terminal:

```bash
# Navegue até o diretório da aplicação
cd /apps/r36s_viewer

# Opção 1: Instalação completa no sistema
sudo ./install_to_r36s.sh

# Opção 2: Execução direta (sem instalação)
./launch_viewer.sh
```

### 4. Uso da Aplicação

#### Inicialização

```bash
# Menu de episódios disponíveis
r36s_viewer

# Episódio específico
r36s_viewer chaves001

# Diretório customizado
r36s_viewer /path/to/images

# Modo janela (para debug)
r36s_viewer --windowed
```

#### Controles do R36S

| Botão | Função |
|-------|--------|
| **D-pad/Analógico** | Navegação no menu |
| **A (Confirmar)** | Próxima imagem |
| **B (Voltar)** | Imagem anterior |
| **X** | Próxima imagem (alternativo) |
| **Y** | Imagem anterior (alternativo) |
| **Start** | Alternar exibição de legendas |
| **Select** | Alternar menu/sair |
| **L1/L2** | Navegação rápida (5 imagens) |
| **R1/R2** | Navegação rápida (5 imagens) |

#### Funcionalidades

- **Menu de Episódios**: Lista automática de pastas em `/assets/`
- **Legendas Multilínguas**: Suporte para PT, ES, ENG, ZHT
- **Reprodução Sincronizada**: Baseada em timestamps dos arquivos base
- **Zoom e Ajuste**: Modo cover (preenche tela) e fit (mantém proporção)
- **Auto-pause**: Para em imagens com legendas
- **Navegação Rápida**: Pulo de múltiplas imagens

## Estrutura de Assets

Para cada episódio, organize assim:

```
assets/chaves001/
├── 0001.png                    # Imagens numeradas
├── 0002.png
├── ...
├── chaves_sub_pt.xml          # Legendas português
├── chaves_sub_es.xml          # Legendas espanhol  
├── chaves_sub_zht.xml         # Legendas chinês tradicional
├── chavzht_sub_zht_secs.xml   # Legendas processadas
└── chavzht_sub_zht_secs_base.txt  # Timestamps
```

## Resolução de Problemas

### SDL2 não encontrado
```bash
# No R36S, instale as dependências
sudo apt-get update
sudo apt-get install libsdl2-dev libsdl2-image-dev libsdl2-ttf-dev
```

### Tela preta
```bash
# Configure o driver de vídeo
export SDL_VIDEODRIVER=fbcon
export SDL_FBDEV=/dev/fb0
./launch_viewer.sh
```

### Assets não encontrados
```bash
# Verifique os symlinks
ls -la /apps/r36s_viewer/assets
# Deve apontar para /storage/roms/r36s_viewer_assets
```

### Performance
- Assets grandes ficam na partição EASYROMS
- Executável fica na partição do sistema
- Use imagens PNG otimizadas (max 1920x1080)

## Personalização

### Auto-inicialização
```bash
# Para iniciar automaticamente no boot
sudo cp /apps/r36s_viewer/autostart.sh /etc/autostart/
```

### Configuração de Tela
```bash
# Edite launch_viewer.sh para ajustar resolução
export SDL_VIDEO_X11_FORCE_EGL=1
export SDL_VIDEODRIVER=x11
```

## Desinstalação

```bash
cd /apps/r36s_viewer
sudo ./uninstall.sh
```

## Suporte Técnico

- **Logs**: Execute com `./launch_viewer.sh 2>&1 | tee viewer.log`
- **Debug**: Use `--windowed` para modo janela
- **Performance**: Monitor com `htop` durante execução

## Limitações

- Requer R36S com Linux/buildroot
- SDL2 deve estar disponível no sistema
- Resolução ótima: 640x480 (nativa do R36S)
- Formatos suportados: PNG, JPG
- Máximo recomendado: 2000 imagens por episódio
