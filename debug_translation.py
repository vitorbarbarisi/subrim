#!/usr/bin/env python3
"""
Debug script to test translation parsing and identify quote issues
"""

import re
from pathlib import Path

def parse_pinyin_translations(translation_list_str: str) -> list[tuple[str, str, str]]:
    """
    Parse the translation list string to extract Chinese characters, pinyin, and Portuguese translations.

    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'

    Returns:
        List of tuples (chinese_chars, pinyin, portuguese_translation)
        Example: [("三", "sān", "três"), ("號", "hào", "número"), ("碼頭", "mǎ tóu", "cais")]
    """
    print(f"Input: {translation_list_str}")
    
    try:
        # Clean and parse the list
        translation_list_str = translation_list_str.strip()
        if not translation_list_str.startswith('[') or not translation_list_str.endswith(']'):
            return []

        # Remove brackets and split by quotes
        content = translation_list_str[1:-1]  # Remove [ and ]
        print(f"Content after removing brackets: {content}")

        # Split by ", " but keep the quotes
        import re
        items = re.findall(r'"([^"]*)"', content)
        print(f"Items found: {items}")

        result = []
        for item in items:
            # Parse format: "三 (sān): três"
            # Extract Chinese characters, pinyin, and Portuguese translation
            match = re.match(r'^([^\s\(]+)\s*\(([^)]+)\)\s*:\s*(.+)$', item)
            if match:
                chinese_chars = match.group(1).strip()
                pinyin = match.group(2).strip()
                portuguese = match.group(3).strip()
                result.append((chinese_chars, pinyin, portuguese))
                print(f"Parsed: '{chinese_chars}' -> '{pinyin}' -> '{portuguese}'")
            else:
                # Fallback: try to extract just Chinese chars if format doesn't match
                chinese_match = re.match(r'^([^\s\(]+)', item)
                if chinese_match:
                    chinese_chars = chinese_match.group(1)
                    result.append((chinese_chars, "", ""))  # Empty pinyin/portuguese
                    print(f"Fallback: '{chinese_chars}' -> '' -> ''")

        return result

    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções com pinyin: {e}")
        return []


def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter using double quotes."""
    print(f"BEFORE ESCAPE: '{text}'")
    
    if not text or not isinstance(text, str):
        return ""
    
    # Remove any null bytes that could cause issues
    text = text.replace('\x00', '')
    
    # Strip whitespace and check if empty
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
    # NOTE: Single quotes, colons, and parentheses don't need escaping when using double quotes
    
    print(f"AFTER ESCAPE: '{text}'")
    return text


def test_translation_parsing():
    """Test translation parsing with sample data from base.txt"""
    
    # Sample translation string from base.txt
    sample_translation = '["認真的 (rèn zhēn de): sério", "我 (wǒ): eu", "超愛 (chāo ài): amo muito", "這個 (zhè ge): este", "造型 (zào xíng): visual", "兄弟 (xiōng dì): mano"]'
    
    print("="*60)
    print("TESTING TRANSLATION PARSING")
    print("="*60)
    
    # Parse translations
    word_data = parse_pinyin_translations(sample_translation)
    
    print(f"\nParsed {len(word_data)} words:")
    for i, (chinese, pinyin, portuguese) in enumerate(word_data, 1):
        print(f"{i:2d}. Chinese: '{chinese}' | Pinyin: '{pinyin}' | Portuguese: '{portuguese}'")
    
    print("\n" + "="*60)
    print("TESTING FFMPEG ESCAPING")
    print("="*60)
    
    # Test escaping for each part
    for i, (chinese, pinyin, portuguese) in enumerate(word_data, 1):
        print(f"\n--- Word {i} ---")
        print(f"Chinese: '{chinese}'")
        escaped_chinese = escape_ffmpeg_text(chinese)
        
        print(f"Pinyin: '{pinyin}'")
        escaped_pinyin = escape_ffmpeg_text(pinyin)
        
        print(f"Portuguese: '{portuguese}'")
        escaped_portuguese = escape_ffmpeg_text(portuguese)
        
        # Show what would appear in FFmpeg command
        print(f"FFmpeg Chinese: text=\"{escaped_chinese}\"")
        print(f"FFmpeg Pinyin: text=\"{escaped_pinyin}\"")
        print(f"FFmpeg Portuguese: text=\"{escaped_portuguese}\"")


if __name__ == "__main__":
    test_translation_parsing()
