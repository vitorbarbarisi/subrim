# R36S Viewer - Instalação no Windows

## Pré-requisitos

### 1. WSL2 (Windows Subsystem for Linux)
O R36S Viewer precisa ser compilado para ARM Linux. No Windows, usamos WSL2:

```cmd
# Execute como Administrador no PowerShell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

Reinicie o computador e instale Ubuntu da Microsoft Store.

### 2. Toolchain de Cross-compilation
No WSL Ubuntu, instale as ferramentas:
```bash
sudo apt-get update
sudo apt-get install gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf cmake build-essential
```

## Instalação Automática (Recomendado)

### Método 1: Script Completo
```cmd
# Execute no Windows (cmd ou PowerShell)
build_and_install_r36s.bat
```

Este script faz tudo automaticamente:
1. Compila o viewer para ARM
2. Cria o pacote de instalação
3. Instala no SD card do R36S

### Método 2: Passo a Passo

#### 1. Configure os drives do SD card
```cmd
config_windows.bat
```
Edite o arquivo para ajustar as letras dos drives (D:, F:, etc.)

#### 2. Compile o viewer
```cmd
build_for_r36s.bat
```

#### 3. Prepare o pacote
```cmd
prepare_r36s_package.bat
```

#### 4. Instale no SD card
```cmd
install_to_sd_card.bat
```

## Estrutura dos Arquivos Windows

```
subrim/
├── build_for_r36s.bat           # Compila para ARM via WSL
├── prepare_r36s_package.bat     # Cria pacote de instalação
├── install_to_sd_card.bat       # Instala no SD card
├── build_and_install_r36s.bat   # Script completo (tudo em um)
├── config_windows.bat           # Configuração de drives
├── drive_config.bat             # Configuração salva (gerado automaticamente)
├── build_for_r36s.sh           # Versão Unix (backup)
├── prepare_r36s_package.sh     # Versão Unix (backup)
└── install_to_sd_card.sh       # Versão Unix (backup)
```

## Configuração de Drives

O Windows monta o SD card do R36S como duas partições:

### Drives Padrão
- **R36S-OS**: `D:` (sistema operacional)
- **EASYROMS**: `F:` (ROMs e assets grandes)

### Personalizar Drives
1. Execute `config_windows.bat`
2. Edite as variáveis no início do arquivo:
   ```bat
   set R36S_OS_DRIVE=D:
   set EASYROMS_DRIVE=F:
   ```
3. Salve e execute novamente para verificar

## Processo de Compilação

### Como Funciona
1. **WSL2**: Scripts `.bat` chamam comandos Linux via `wsl`
2. **Cross-compilation**: GCC ARM compila para arquitetura do R36S
3. **CMake**: Configura o build para Linux ARM
4. **Make**: Compila o executável `r36s_viewer`

### Comandos WSL Executados
```bash
# Configuração do CMake
wsl cmake .. -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=arm -DCMAKE_C_COMPILER=arm-linux-gnueabihf-gcc

# Compilação
wsl make -j4
```

## Instalação no SD Card

### Estrutura Criada
```
D:\apps\r36s_viewer\              # R36S-OS partition
├── r36s_viewer                   # Executável ARM
├── launch_viewer.sh              # Script de inicialização
├── install_to_r36s.sh           # Instalador do sistema
├── uninstall.sh                 # Desinstalador
└── autostart.sh                 # Auto-start (opcional)

F:\r36s_viewer_assets\            # EASYROMS partition  
├── chaves001\                    # Episódios
├── chaves002\
└── ...
```

### Vantagens da Separação
- **Executável** na partição do sistema (rápido)
- **Assets** na partição de dados (não ocupa espaço do sistema)
- **Symlink** conecta os dois automaticamente

## Uso no R36S

### Instalação Final
No console R36S:
```bash
cd /apps/r36s_viewer
sudo ./install_to_r36s.sh
```

### Execução
```bash
# Menu de episódios
r36s_viewer

# Episódio específico  
r36s_viewer chaves001

# Modo debug (janela)
r36s_viewer --windowed
```

## Resolução de Problemas

### WSL não encontrado
```cmd
# Instale WSL2
wsl --install
# Reinicie e configure Ubuntu
```

### Toolchain ARM não encontrado
```bash
# No WSL Ubuntu
sudo apt-get update
sudo apt-get install gcc-arm-linux-gnueabihf g++-arm-linux-gnueabihf
```

### SD card não detectado
1. Verifique se o card está inserido
2. Execute `config_windows.bat` para verificar drives
3. Ajuste as letras dos drives conforme necessário

### Build falha
```cmd
# Limpe e tente novamente
rmdir /s build_r36s
build_for_r36s.bat
```

### Permissões no WSL
```bash
# Se der erro de permissão
sudo chmod +x /mnt/c/path/to/your/scripts
```

## Características do Windows

### Diferenças dos Scripts Unix
- **Extensão**: `.bat` em vez de `.sh`
- **Comandos**: `echo`, `set`, `if exist` em vez de bash
- **Paths**: Barras invertidas `\` em vez de `/`
- **Drives**: Letras (`D:`, `F:`) em vez de mount points
- **WSL**: Chama comandos Linux via `wsl bash -c`

### Vantagens
- **Nativo**: Roda diretamente no Windows
- **Automático**: Scripts detectam e configuram tudo
- **Flexível**: Suporta diferentes configurações de drive
- **Completo**: Inclui verificações e tratamento de erros

## Exemplo Completo de Uso

```cmd
# 1. Clone o projeto (se ainda não tiver)
git clone <repo> subrim
cd subrim

# 2. Configure drives (se necessário)
config_windows.bat

# 3. Execute instalação completa
build_and_install_r36s.bat

# 4. Insira SD card no R36S e execute:
#    sudo /apps/r36s_viewer/install_to_r36s.sh
#    r36s_viewer
```

Pronto! Seu viewer estará rodando no R36S com todos os episódios e legendas funcionando perfeitamente. 🎮✨
