#!/usr/bin/env python3
"""
Script para criar configuração de VM Alpine Linux no UTM
"""

import os
import plistlib
import subprocess
from pathlib import Path

# Configurações da VM
VM_NAME = "Alpine Linux"
ISO_PATH = os.path.expanduser("~/Downloads/vm_isos/alpine-standard.iso")
VM_DIR = os.path.expanduser("~/Library/Containers/com.utmapp.UTM/Data/Documents")
RAM_GB = 2
CPU_CORES = 2
DISK_SIZE_GB = 20

def create_vm_config():
    """Cria o arquivo de configuração da VM"""
    
    # Criar diretório se não existir
    vm_path = Path(VM_DIR) / f"{VM_NAME}.utm"
    vm_path.mkdir(parents=True, exist_ok=True)
    
    # Configuração da VM
    config = {
        "name": VM_NAME,
        "architecture": "arm64",
        "memory": RAM_GB * 1024 * 1024 * 1024,  # Em bytes
        "cpuCount": CPU_CORES,
        "bootUefi": True,
        "networkEnabled": True,
        "networkMode": "shared",
        "drives": [
            {
                "imageType": "cd",
                "interface": "ide",
                "removable": True,
                "imageURL": {
                    "Bookmark": None,  # Será preenchido pelo UTM
                    "Path": ISO_PATH
                }
            },
            {
                "imageType": "disk",
                "interface": "virtio",
                "removable": False,
                "size": DISK_SIZE_GB * 1024 * 1024 * 1024,  # Em bytes
                "imageURL": {
                    "Bookmark": None,
                    "Path": str(vm_path / "disk.qcow2")
                }
            }
        ],
        "display": {
            "consoleOnly": False,
            "consoleFont": "Menlo",
            "consoleFontSize": 12,
            "consoleTheme": "Default",
            "consoleCursorBlink": True,
            "consoleResizeCommand": "",
            "displayCard": "virtio-ramfb",
            "displayFitScreen": True,
            "displayUpscale": True,
            "displayDownscale": True
        },
        "input": {
            "keyboard": True,
            "pointing": True
        },
        "sound": {
            "enabled": False
        },
        "sharing": {
            "clipboardEnabled": True,
            "directoryEnabled": False
        }
    }
    
    # Salvar configuração
    config_path = vm_path / "config.plist"
    with open(config_path, 'wb') as f:
        plistlib.dump(config, f)
    
    print(f"✅ Configuração da VM criada em: {vm_path}")
    return vm_path

def main():
    # Verificar se ISO existe
    if not os.path.exists(ISO_PATH):
        print(f"❌ ISO não encontrada em: {ISO_PATH}")
        print("   Execute o download primeiro!")
        return
    
    print(f"🚀 Criando VM: {VM_NAME}")
    print(f"   ISO: {ISO_PATH}")
    print(f"   RAM: {RAM_GB}GB")
    print(f"   CPU: {CPU_CORES} cores")
    print(f"   Disco: {DISK_SIZE_GB}GB")
    print()
    
    vm_path = create_vm_config()
    
    print()
    print("✅ VM criada com sucesso!")
    print()
    print("📋 Próximos passos:")
    print("   1. Abra o UTM (Applications/UTM.app)")
    print(f"   2. A VM '{VM_NAME}' deve aparecer na lista")
    print("   3. Clique em 'Play' para iniciar")
    print("   4. Siga a instalação do Alpine Linux")
    print()
    print("💡 Dica: Execute 'setup-alpine' após iniciar a VM")

if __name__ == "__main__":
    main()

