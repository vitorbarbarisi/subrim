"""Define o nome que o macOS mostra para o app rodando (tooltip do Dock, menu).

Um `python subrim_manager.py` puro se registra no Dock como "Python", porque
esse é o CFBundleName do bundle do framework Python de onde ele roda. O Tk não
tem API para isso — o nome precisa ser aplicado no dicionário de info do bundle
via a ponte Objective-C.

O momento importa: chame ANTES do primeiro Tk(). O Dock lê o nome quando o
processo se registra, o que o Tk dispara na inicialização; aplicar depois deixa
o tooltip desatualizado.

Tudo aqui degrada para no-op fora do macOS ou sem o pyobjc instalado — o ícone
do Dock (iconphoto) funciona de qualquer forma. Para habilitar o nome:
    pip install pyobjc-framework-Cocoa
"""
import sys


def set_app_name(name: str) -> bool:
    """True se o nome foi aplicado, False se não suportado nesta plataforma."""
    if sys.platform != "darwin":
        return False
    try:
        from Foundation import NSBundle
    except ImportError:
        return False

    try:
        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is None:
            return False
        info["CFBundleName"] = name
        info["CFBundleDisplayName"] = name
        return True
    except Exception as e:  # puramente cosmético — nunca travar o start por isso
        print(f"Nome do app não aplicado: {e}")
        return False
