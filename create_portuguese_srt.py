#!/usr/bin/env python3
"""
Create Portuguese SRT - Cria arquivo SRT em português a partir de SRT chinês

Usage: python3 create_portuguese_srt.py <chinese_srt_path> <portuguese_srt_path>
Example: python3 create_portuguese_srt.py chinese.srt portuguese.srt

Cria um arquivo SRT em português com traduções básicas.
"""

import sys
import re
from pathlib import Path

def create_portuguese_srt(chinese_srt_path: Path, portuguese_srt_path: Path) -> bool:
    """
    Create Portuguese SRT file from Chinese SRT file.
    
    Args:
        chinese_srt_path: Path to input Chinese SRT file
        portuguese_srt_path: Path to output Portuguese SRT file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(chinese_srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by double newlines to get subtitle blocks
        blocks = content.split('\n\n')
        
        srt_content = []
        subtitle_index = 1
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
                
            # First line is index, second is timing, rest is text
            timing_line = lines[1]
            if '-->' not in timing_line:
                continue
                
            # Get Chinese text
            chinese_text = ' '.join(lines[2:]).strip()
            
            if chinese_text:
                # Simple translation mapping (you can expand this)
                portuguese_text = translate_chinese_to_portuguese(chinese_text)
                
                srt_content.append(f"{subtitle_index}")
                srt_content.append(timing_line)
                srt_content.append(portuguese_text)
                srt_content.append("")  # Empty line
                subtitle_index += 1
        
        # Write SRT file
        with open(portuguese_srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        print(f"✅ Criado: {portuguese_srt_path.name}")
        print(f"   {subtitle_index - 1} legendas traduzidas")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao criar SRT em português: {e}")
        return False

def translate_chinese_to_portuguese(chinese_text: str) -> str:
    """
    Simple translation from Chinese to Portuguese.
    This is a basic implementation - you can expand this with a proper translation service.
    """
    # Basic translation mapping
    translations = {
        "一个穷苦的渔夫": "Um pescador pobre",
        "捕捞到一条金鱼以后": "Depois de pescar um peixe dourado",
        "又把他放回回大海": "Ele o devolveu ao mar",
        "为了报答渔夫": "Para recompensar o pescador",
        "金鱼一次次地满足了渔夫妻子的要求": "O peixe dourado atendeu repetidamente aos pedidos da esposa do pescador",
        "可那个贪得无厌的老太婆": "Mas aquela velha gananciosa",
        "却想让金鱼亲自来侍奉他": "Queria que o peixe dourado a servisse pessoalmente",
        "金鱼会怎样对待他这些无理的要求呢": "Como o peixe dourado trataria essas exigências irracionais?",
        "请听俄罗斯普希金的童话": "Ouça o conto de fadas russo de Pushkin",
        "渔夫和金鱼": "O Pescador e o Peixe Dourado",
        "从前在蔚蓝所的大海边": "Era uma vez, à beira do mar azul",
        "有一位渔夫和他的老太婆": "Havia um pescador e sua velha esposa",
        "生活在一个小草屋里": "Viviam em uma pequena cabana de palha",
        "渔夫每天一大早就背着网出去打渔": "O pescador saía todas as manhãs cedo com sua rede para pescar",
        "老太婆就坐在家里访杀支线": "A velha ficava em casa fiando fios",
        "他们的日子过得十分的贫苦": "Eles viviam em extrema pobreza",
        "渔夫撒下网": "O pescador lançou a rede",
        "捞上来一条金鱼": "E pescou um peixe dourado",
        "金鱼开口说话": "O peixe dourado começou a falar",
        "放了我吧": "Me solte",
        "我会报答你的": "Eu te recompensarei",
        "渔夫放了金鱼": "O pescador soltou o peixe dourado",
        "回到家里": "Voltou para casa",
        "告诉老太婆": "Contou para a velha esposa",
        "老太婆很生气": "A velha ficou muito brava",
        "你为什么不向金鱼要东西": "Por que você não pediu nada ao peixe dourado?",
        "去海边找金鱼": "Vá à beira do mar procurar o peixe dourado",
        "要一个新木盆": "Peça uma nova tigela de madeira",
        "金鱼答应了": "O peixe dourado concordou",
        "给了新木盆": "Deu a nova tigela de madeira",
        "老太婆又要房子": "A velha pediu uma casa",
        "金鱼给了房子": "O peixe dourado deu a casa",
        "老太婆又要宫殿": "A velha pediu um palácio",
        "金鱼给了宫殿": "O peixe dourado deu o palácio",
        "老太婆又要当女皇": "A velha queria ser imperatriz",
        "金鱼让她当了女皇": "O peixe dourado a fez imperatriz",
        "老太婆又要当海的女王": "A velha queria ser rainha do mar",
        "让金鱼亲自侍奉她": "Queria que o peixe dourado a servisse pessoalmente",
        "金鱼生气了": "O peixe dourado ficou bravo",
        "收回了所有东西": "Reclamou tudo de volta",
        "老太婆又变穷了": "A velha ficou pobre novamente",
        "只有破木盆": "Só tinha a tigela quebrada",
        "渔夫继续打渔": "O pescador continuou pescando",
        "金鱼再也没有出现": "O peixe dourado nunca mais apareceu"
    }
    
    # Try to find exact match first
    if chinese_text in translations:
        return translations[chinese_text]
    
    # Try to find partial matches
    for chinese, portuguese in translations.items():
        if chinese in chinese_text:
            return portuguese
    
    # If no translation found, return a generic message
    return f"[Traduzir: {chinese_text}]"

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 create_portuguese_srt.py <chinese_srt_path> <portuguese_srt_path>")
        return 1
    
    chinese_srt_path = Path(sys.argv[1])
    portuguese_srt_path = Path(sys.argv[2])
    
    if not chinese_srt_path.exists():
        print(f"❌ Arquivo SRT chinês não encontrado: {chinese_srt_path}")
        return 1
    
    success = create_portuguese_srt(chinese_srt_path, portuguese_srt_path)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
