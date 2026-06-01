#!/usr/bin/env python3
"""
Convert SRT file from simplified Chinese to traditional Chinese.

Usage: python3 convert_srt_to_traditional.py <srt_file_path>
"""

import sys
from pathlib import Path

# Global flag to print warning only once
_opencc_warning_printed = False

def convert_simplified_to_traditional(text: str) -> str:
    """
    Convert simplified Chinese characters to traditional Chinese characters using OpenCC.
    """
    global _opencc_warning_printed
    try:
        import opencc
        converter = opencc.OpenCC('s2t')  # simplified to traditional
        return converter.convert(text)
    except ImportError:
        if not _opencc_warning_printed:
            print("⚠️ OpenCC não disponível, usando conversão básica")
            print("   Para conversão completa, instale: pip install opencc-python-reimplemented")
            _opencc_warning_printed = True
        # Fallback to basic conversion if OpenCC is not available
        conversions = {
            "组": "組", "什么": "什麼", "不会": "不會", "样": "樣", "湾": "灣",
            "来": "來", "这": "這", "个": "個", "说": "說", "还": "還",
            "过": "過", "时": "時", "为": "為", "发": "發", "现": "現",
            "对": "對", "应": "應", "经": "經", "没": "沒", "会": "會",
            "一个": "一個", "以后": "以後", "满足": "滿足", "要求": "要求",
            "怎样": "怎樣", "对待": "對待", "请听": "請聽", "从前": "從前",
            "家里": "家裡", "过得": "過得", "年": "年", "几": "幾"
        }
        result = text
        for simplified, traditional in conversions.items():
            result = result.replace(simplified, traditional)
        return result

def convert_srt_file(srt_path: Path) -> bool:
    """
    Convert SRT file from simplified to traditional Chinese.
    """
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split by double newlines to get subtitle blocks
        blocks = content.split('\n\n')
        srt_content = []
        
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 3:
                srt_content.append(block)
                continue
            
            # First line is index, second is timing, rest is text
            timing_line = lines[1]
            if '-->' not in timing_line:
                srt_content.append(block)
                continue
            
            # Convert Chinese text to traditional
            chinese_text = ' '.join(lines[2:]).strip()
            if chinese_text:
                traditional_text = convert_simplified_to_traditional(chinese_text)
                srt_content.append(f"{lines[0]}\n{timing_line}\n{traditional_text}")
            else:
                srt_content.append(block)
        
        # Write converted SRT file
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(srt_content))
        
        print(f"✅ Arquivo convertido: {srt_path.name}")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao converter arquivo: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("❌ Uso: python3 convert_srt_to_traditional.py <srt_file_path>")
        sys.exit(1)
    
    srt_path = Path(sys.argv[1])
    if not srt_path.exists():
        print(f"❌ Arquivo não encontrado: {srt_path}")
        sys.exit(1)
    
    if not srt_path.suffix == '.srt':
        print(f"⚠️ Aviso: Arquivo não é .srt: {srt_path}")
    
    success = convert_srt_file(srt_path)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

