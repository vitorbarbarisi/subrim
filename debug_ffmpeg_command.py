#!/usr/bin/env python3
"""
Debug script to analyze FFmpeg command generation and identify quote issues
"""

import re
from pathlib import Path

def parse_pinyin_translations(translation_list_str: str) -> list[tuple[str, str, str]]:
    """Parse translation list"""
    try:
        translation_list_str = translation_list_str.strip()
        if not translation_list_str.startswith('[') or not translation_list_str.endswith(']'):
            return []

        content = translation_list_str[1:-1]
        items = re.findall(r'"([^"]*)"', content)

        result = []
        for item in items:
            match = re.match(r'^([^\s\(]+)\s*\(([^)]+)\)\s*:\s*(.+)$', item)
            if match:
                chinese_chars = match.group(1).strip()
                pinyin = match.group(2).strip()
                portuguese = match.group(3).strip()
                result.append((chinese_chars, pinyin, portuguese))
            else:
                chinese_match = re.match(r'^([^\s\(]+)', item)
                if chinese_match:
                    chinese_chars = chinese_match.group(1)
                    result.append((chinese_chars, "", ""))

        return result

    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções com pinyin: {e}")
        return []

def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter using double quotes."""
    if not text or not isinstance(text, str):
        return ""
    
    text = text.replace('\x00', '')
    text = text.strip()
    if not text:
        return ""
    
    # Escape special characters for FFmpeg (using double quotes strategy)
    text = text.replace('\\', '\\\\')  # Backslash
    text = text.replace('"', '\\"')    # Double quote (since we'll use double quotes)
    text = text.replace('[', '\\[')    # Left bracket
    text = text.replace(']', '\\]')    # Right bracket
    text = text.replace('%', '\\%')    # Percent sign
    text = text.replace(';', '\\;')    # Semicolon
    text = text.replace(',', '\\,')    # Comma (critical for FFmpeg parsing)
    
    return text

def analyze_base_file_entry():
    """Analyze a single entry from base.txt"""
    
    # Sample entry from our test file
    sample_entry = """1	0.000s	4.460s	[卡卡] 終究是怎麼回事,對吧,紫羅蘭女士,我帶著呢。	["卡卡 (kǎ kǎ): Caca", "終究 (zhōng jiū): afinal", "是 (shì): ser", "怎麼 (zěn me): como", "回事 (huí shì): situação", "對吧 (duì ba): certo", "紫羅蘭 (zǐ luó lán): violeta", "女士 (nǚ shì): senhora", "我 (wǒ): eu", "帶著 (dài zhe): carregando", "呢 (ne): partícula modal"]	[CACÁ] AFINAL DE CONTAS, NÉ, DONA VIOLETA, EU CARREGO"""
    
    print("="*80)
    print("ANÁLISE DE ENTRADA DO BASE.TXT")
    print("="*80)
    
    parts = sample_entry.split('\t')
    
    chinese_text = parts[3].strip()
    translations_text = parts[4].strip()
    portuguese_text = parts[5].strip()
    
    print(f"Chinese Text: {chinese_text}")
    print(f"Translations JSON: {translations_text}")
    print(f"Portuguese Text: {portuguese_text}")
    
    print("\n" + "-"*60)
    print("PARSING TRANSLATIONS")
    print("-"*60)
    
    # Parse translations
    word_data = parse_pinyin_translations(translations_text)
    
    print(f"Parsed {len(word_data)} words:")
    for i, (chinese, pinyin, portuguese) in enumerate(word_data, 1):
        print(f"{i:2d}. '{chinese}' | '{pinyin}' | '{portuguese}'")
    
    print("\n" + "-"*60)
    print("FFMPEG ESCAPING AND COMMAND GENERATION")
    print("-"*60)
    
    # Clean Chinese text
    clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '').replace('"', '').replace('"', '')
    
    print(f"Clean Chinese: {clean_chinese}")
    
    # Group characters into words
    display_items = []
    remaining_text = clean_chinese
    
    while remaining_text:
        found_word = False
        for chinese_word, word_pinyin, word_portuguese in sorted(word_data, key=lambda x: len(x[0]), reverse=True):
            if remaining_text.startswith(chinese_word):
                display_items.append((chinese_word, word_pinyin, word_portuguese))
                remaining_text = remaining_text[len(chinese_word):]
                found_word = True
                break
        if not found_word:
            char = remaining_text[0]
            display_items.append((char, "", ""))
            remaining_text = remaining_text[1:]
    
    print(f"\nDisplay items: {len(display_items)}")
    for i, (chinese, pinyin, portuguese) in enumerate(display_items, 1):
        print(f"{i:2d}. Chinese: '{chinese}' | Pinyin: '{pinyin}' | Portuguese: '{portuguese}'")
    
    print("\n" + "-"*60)
    print("SAMPLE FFMPEG COMMANDS THAT WOULD BE GENERATED")
    print("-"*60)
    
    for i, (chinese_word, word_pinyin, word_portuguese) in enumerate(display_items[:3], 1):  # Just first 3
        print(f"\n--- Word {i}: '{chinese_word}' ---")
        
        # Escape texts
        chinese_escaped = escape_ffmpeg_text(chinese_word)
        pinyin_escaped = escape_ffmpeg_text(word_pinyin) if word_pinyin else ""
        portuguese_escaped = escape_ffmpeg_text(word_portuguese) if word_portuguese else ""
        
        print(f"Original: '{chinese_word}' -> Escaped: '{chinese_escaped}'")
        print(f"Original: '{word_pinyin}' -> Escaped: '{pinyin_escaped}'")
        print(f"Original: '{word_portuguese}' -> Escaped: '{portuguese_escaped}'")
        
        # Simulate FFmpeg command generation
        if chinese_escaped:
            chinese_filter = f'drawtext=text="{chinese_escaped}":x=100:y=100:fontfile=font.ttc:fontsize=48:fontcolor=white'
            print(f"Chinese Filter: {chinese_filter}")
        
        if pinyin_escaped:
            pinyin_filter = f'drawtext=text="{pinyin_escaped}":x=100:y=50:fontfile=font.ttc:fontsize=32:fontcolor=purple'
            print(f"Pinyin Filter: {pinyin_filter}")
            
        if portuguese_escaped:
            portuguese_filter = f'drawtext=text="{portuguese_escaped}":x=100:y=150:fontfile=font.ttf:fontsize=24:fontcolor=yellow'
            print(f"Portuguese Filter: {portuguese_filter}")

if __name__ == "__main__":
    analyze_base_file_entry()
