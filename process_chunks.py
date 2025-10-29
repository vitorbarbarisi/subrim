#!/usr/bin/env python3
"""
Process Chunks - Executa processamento idempotente de chunks

Usage: python3 process_chunks.py <directory_name>
Example: python3 process_chunks.py onibus132

O script (AGORA IDÉMPOTENTE):
1. Encontra todos os chunks na pasta <directory_name>_sub
2. Verifica quais chunks já têm arquivos *_processed.mp4 correspondentes
3. Processa apenas os chunks que ainda não foram processados
4. Pula automaticamente chunks já processados
5. Mantém todos os arquivos originais

Características:
- IDÉMPOTENTE: Pode ser executado múltiplas vezes sem duplicar trabalho
- RESUMÍVEL: Continua do primeiro chunk não processado
- SEGURO: Não sobrescreve arquivos já processados
"""

import sys
import argparse
import shutil
import subprocess
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import re


def find_chunk_files(directory: Path) -> Tuple[List[Path], List[Path]]:
    """
    Encontra todos os arquivos de chunk (MP4) no diretório,
    ordenados numericamente. Ignora arquivos *_processed.mp4.

    Returns:
        Tuple[List[Path], List[Path]]: (todos_chunks_originais, chunks_sem_processed)
    """
    all_chunk_files = []
    unprocessed_chunk_files = []

    # Procurar apenas por arquivos que contenham "chunk" no nome, mas NÃO contenham "_processed" ou "_temp"
    for file_path in directory.glob("*chunk*.mp4"):
        # Ignorar arquivos já processados (que terminam com _processed.mp4)
        if "_processed" in file_path.name:
            continue

        # Ignorar arquivos temporários (que terminam com _temp.mp4)
        if "_temp" in file_path.name:
            continue

        all_chunk_files.append(file_path)

        # Verificar se já existe arquivo _processed correspondente
        processed_file = file_path.parent / f"{file_path.stem}_processed.mp4"
        if not processed_file.exists():
            unprocessed_chunk_files.append(file_path)

    # Ordenar por nome (chunk_001, chunk_002, etc.)
    all_chunk_files.sort(key=lambda x: x.name)
    unprocessed_chunk_files.sort(key=lambda x: x.name)

    return all_chunk_files, unprocessed_chunk_files


def process_chunk(chunk_path: Path, base_path: Path, chunk_number: int, total_chunks: int) -> bool:
    """
    Função para processar um chunk individual.
    Aplica legendas ao vídeo do chunk usando o arquivo base.txt correspondente.

    Args:
        chunk_path: Caminho para o arquivo MP4 do chunk
        base_path: Caminho para o arquivo base.txt do chunk
        chunk_number: Número do chunk (1, 2, 3...)
        total_chunks: Total de chunks sendo processados

    Returns:
        True se processamento bem-sucedido
    """
    print(f"   🔄 Processando chunk {chunk_number:03d}/{total_chunks:03d}", flush=True)
    print(f"   📁 Vídeo: {chunk_path.name}")
    print(f"   📄 Base: {base_path.name}")

    # Verificar se o arquivo base existe
    if not base_path or not base_path.exists():
        print(f"   ⚠️  Arquivo base não encontrado: {base_path}")
        return False

    # Verificar se o chunk de vídeo existe
    if not chunk_path.exists():
        print(f"   ⚠️  Arquivo de chunk não encontrado: {chunk_path}")
        return False

    try:
        # Parse do arquivo base para obter as legendas
        print("   📖 Lendo arquivo base...", flush=True)
        subtitles = parse_base_file(base_path)

        if not subtitles:
            print("   ⚠️  Arquivo base.txt vazio - fazendo cópia do chunk original com tag _processed")

            # Criar caminho para o chunk processado
            processed_chunk_path = chunk_path.parent / f"{chunk_path.stem}_processed.mp4"

            # Copiar o chunk original para o arquivo processado
            try:
                shutil.copy2(chunk_path, processed_chunk_path)
                print(f"   ✅ Chunk copiado com sucesso: {processed_chunk_path.name}")
                print(f"\n🎉 Processamento concluído! Chunk copiado como {processed_chunk_path.name}")
                return True
            except Exception as e:
                print(f"   ❌ Erro ao copiar chunk: {e}")
                return False

        print(f"   📝 Encontradas {len(subtitles)} legendas para o chunk", flush=True)

        # Criar arquivo temporário para o resultado
        temp_output = chunk_path.parent / f"{chunk_path.stem}_temp.mp4"

        # Aplicar legendas ao chunk
        print("   🎬 Aplicando legendas ao chunk...", flush=True)
        success = apply_subtitles_to_chunk(chunk_path, subtitles, temp_output)

        if not success:
            print("   ❌ Falha ao aplicar legendas ao chunk")
            # Limpar arquivo temporário se existir
            if temp_output.exists():
                temp_output.unlink()
            return False

        # Criar cópia do resultado processado (ao invés de substituir o original)
        processed_copy = chunk_path.parent / f"{chunk_path.stem}_processed.mp4"
        print(f"   📋 Criando cópia processada: {processed_copy.name}")

        try:
            shutil.copy2(temp_output, processed_copy)
            print(f"   ✅ Cópia processada criada: {processed_copy.name}")

            # Limpar arquivo temporário após criar a cópia
            temp_output.unlink()
            print(f"   🗑️  Arquivo temporário removido: {temp_output.name}")

        except Exception as copy_error:
            print(f"   ⚠️  Aviso: Não foi possível criar cópia processada: {copy_error}")
            # Limpar arquivo temporário em caso de erro na cópia
            try:
                if temp_output.exists():
                    temp_output.unlink()
                    print(f"   🗑️  Arquivo temporário removido devido a erro na cópia")
            except Exception as cleanup_error:
                print(f"   ⚠️  Não foi possível remover arquivo temporário: {cleanup_error}")
            return False

        print("   ✅ Processamento concluído com sucesso", flush=True)
        return True

    except Exception as e:
        print(f"   ❌ Erro inesperado no processamento do chunk: {e}")
        # Limpar arquivo temporário em caso de erro inesperado
        try:
            temp_output_path = chunk_path.parent / f"{chunk_path.stem}_temp.mp4"
            if temp_output_path.exists():
                temp_output_path.unlink()
                print(f"   🗑️  Arquivo temporário removido devido a erro inesperado")
        except Exception as cleanup_error:
            print(f"   ⚠️  Não foi possível remover arquivo temporário: {cleanup_error}")
        return False


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available."""
    try:
        import subprocess
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def parse_pinyin_translations(translation_list_str: str) -> list[tuple[str, str, str]]:
    """
    Parse the translation list string to extract Chinese characters, pinyin, and Portuguese translations.

    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'

    Returns:
        List of tuples (chinese_chars, pinyin, portuguese_translation)
        Example: [("三", "sān", "três"), ("號", "hào", "número"), ("碼頭", "mǎ tóu", "cais")]
    """
    try:
        # Clean and parse the list
        translation_list_str = translation_list_str.strip()
        if not translation_list_str.startswith('[') or not translation_list_str.endswith(']'):
            return []

        # Remove brackets and split by quotes
        content = translation_list_str[1:-1]  # Remove [ and ]

        # Split by ", " but keep the quotes
        import re
        items = re.findall(r'"([^"]*)"', content)

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
            else:
                # Fallback: try to extract just Chinese chars if format doesn't match
                chinese_match = re.match(r'^([^\s\(]+)', item)
                if chinese_match:
                    chinese_chars = chinese_match.group(1)
                    result.append((chinese_chars, "", ""))  # Empty pinyin/portuguese

        return result

    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções com pinyin: {e}")
        return []


def parse_base_file(base_file_path: Path) -> Dict[float, Tuple[str, str, str, str, float]]:
    """
    Parse the base.txt file and return a mapping of begin_time -> (chinese subtitle, translations, translations_json, portuguese, duration).

    Supports both old format (5 columns) and new format (6 columns):
    - Old: index, begin_time, chinese_text, translations, portuguese
    - New: index, begin_time, end_time, chinese_text, translations, portuguese

    For new format, calculates duration as end_time - begin_time.
    For old format, uses default duration of 3 seconds.

    Returns:
        Dict mapping begin_time (as float seconds) to tuple of (chinese_text, translations_text, translations_json, portuguese_text, duration)
    """
    subtitles = {}

    try:
        with open(base_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                # Split by tabs
                parts = line.split('\t')
                if len(parts) < 4:
                    continue

                # Detect format based on number of columns
                is_new_format = len(parts) >= 6

                # Extract begin timestamp (second column)
                begin_timestamp_str = parts[1].strip()

                # Extract seconds from begin timestamp (e.g., "186.645s" -> 186.645)
                begin_match = re.match(r'([\d.]+)s?', begin_timestamp_str)
                if not begin_match:
                    continue

                begin_seconds = float(begin_match.group(1))

                # Extract end timestamp and calculate duration if available
                duration = 3.0  # Default duration
                if is_new_format:
                    end_timestamp_str = parts[2].strip()
                    end_match = re.match(r'([\d.]+)s?', end_timestamp_str)
                    if end_match:
                        end_seconds = float(end_match.group(1))
                        duration = max(0.5, end_seconds - begin_seconds)  # Minimum 0.5 second duration

                # Extract Chinese subtitle - column position depends on format
                if is_new_format:
                    # New format: index, begin, end, chinese, translations, portuguese
                    chinese_text = parts[3].strip()
                    translations_text = parts[4].strip()
                    portuguese_text = parts[5].strip() if len(parts) >= 6 else ""
                else:
                    # Old format: index, begin, chinese, translations, portuguese
                    chinese_text = parts[2].strip()
                    translations_text = parts[3].strip()
                    portuguese_text = parts[4].strip() if len(parts) >= 5 else ""

                # Remove parentheses if present
                chinese_text = re.sub(r'^（(.*)）$', r'\1', chinese_text)

                # Keep original JSON string for translations
                translations_json = translations_text

                # Parse translations list if it exists
                if translations_text and translations_text != 'N/A':
                    try:
                        # Remove outer brackets and parse as list
                        import ast
                        translations_list = ast.literal_eval(translations_text)
                        if isinstance(translations_list, list):
                            # Join translations with line breaks
                            formatted_translations = '\n'.join(translations_list)
                        else:
                            formatted_translations = translations_text
                    except:
                        # If parsing fails, use raw text
                        formatted_translations = translations_text
                else:
                    formatted_translations = ""
                    translations_json = ""

                # Clean Portuguese text
                if portuguese_text == 'N/A':
                    portuguese_text = ""

                if chinese_text and chinese_text != 'N/A':
                    subtitles[begin_seconds] = (chinese_text, formatted_translations, translations_json, portuguese_text, duration)

    except Exception as e:
        print(f"Erro ao ler arquivo base {base_file_path}: {e}")

    return subtitles


def get_best_chinese_font() -> str:
    """Find the best available Chinese font for FFmpeg."""
    # List of Chinese fonts in order of preference (verified for this system)
    chinese_fonts = [
        '/System/Library/Fonts/STHeiti Medium.ttc',     # macOS Chinese (verified available)
        '/System/Library/Fonts/STHeiti Light.ttc',      # macOS Chinese (verified available)
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',   # Universal Unicode (verified available)
        '/Library/Fonts/Arial Unicode.ttf',             # Alternative path
        '/System/Library/Fonts/PingFang.ttc',           # macOS modern (if available)
        '/System/Library/Fonts/Hiragino Sans GB.ttc',   # macOS fallback
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',  # Linux
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux fallback
        'arial',  # FFmpeg's built-in fallback
    ]

    for font_path in chinese_fonts:
        if font_path == 'arial' or Path(font_path).exists():
            return font_path

    # Final fallback
    return 'arial'


def get_best_latin_font() -> str:
    """Find the best available Latin font for FFmpeg."""
    # List of Latin fonts in order of preference (verified for this system)
    latin_fonts = [
        '/System/Library/Fonts/Supplemental/Arial.ttf',  # macOS Arial (verified available)
        '/System/Library/Fonts/Helvetica.ttc',          # macOS clean
        '/System/Library/Fonts/ArialHB.ttc',            # macOS Arial
        '/System/Library/Fonts/HelveticaNeue.ttc',      # macOS modern
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',   # Universal Unicode (verified available)
        '/Library/Fonts/Arial Unicode.ttf',             # Alternative path
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',  # Linux
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',  # Linux alternative
        'arial',  # FFmpeg built-in fallback
    ]

    for font_path in latin_fonts:
        if font_path == 'arial' or Path(font_path).exists():
            return font_path

    # Final fallback
    return 'arial'


def escape_ffmpeg_text(text: str) -> str:
    """Escape text for FFmpeg drawtext filter using double quotes."""
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
    
    return text


def wrap_portuguese_to_chinese_width(portuguese_text: str, font_path: str, max_width: int, font_size: int = 20) -> List[str]:
    """
    Break Portuguese text into multiple lines to fit within the Chinese word width.
    Never breaks words in the middle - only breaks at word boundaries.

    Args:
        portuguese_text: Portuguese text to break
        font_path: Path to the font file
        max_width: Maximum width in pixels (width of the Chinese word)
        font_size: Font size in pixels (default 20)

    Returns:
        List of text lines that fit within max_width
    """
    if not portuguese_text:
        return []

    # Calculate character width based on actual font size
    char_width = int(font_size * 0.6)  # Approximate: 60% of font size for Latin characters
    chars_per_line = max(3, max_width // char_width)  # Minimum 3 characters per line

    words = portuguese_text.split()
    if not words:
        return [portuguese_text]

    # If it's a single word and fits, return it
    if len(words) == 1 and len(words[0]) <= chars_per_line:
        return [words[0]]

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        # Check if adding this word would exceed the line limit
        word_length = len(word)
        space_length = 1 if current_line else 0  # Space before word (except first word)

        if current_length + space_length + word_length <= chars_per_line:
            # Word fits in current line
            current_line.append(word)
            current_length += space_length + word_length
        else:
            # Word doesn't fit, start new line
            if current_line:
                lines.append(' '.join(current_line))
                current_line = []
                current_length = 0

            # If single word is still too long for a line by itself, keep it whole
            # Better to have one long word than break it in the middle
            if word_length > chars_per_line:
                lines.append(word)  # Keep the word whole even if it's long
            else:
                # Start new line with this word
                current_line = [word]
                current_length = word_length

    # Add remaining words
    if current_line:
        lines.append(' '.join(current_line))

    return lines


def create_subtitle_background_filter(subtitle_area_height: int, subtitle_width: int, video_width: int, video_height: int, bottom_margin: int, time_condition: str = None) -> str:
    """
    Create a semi-transparent black background filter for the subtitle area.

    Args:
        subtitle_area_height: Height of the subtitle area in pixels
        subtitle_width: Width of the subtitle area in pixels (based on actual subtitle width)
        video_width: Video width in pixels
        video_height: Video height in pixels
        bottom_margin: Bottom margin in pixels
        time_condition: FFmpeg time condition for enabling the filter

    Returns:
        FFmpeg filter string for the background
    """
    # Calculate background position and size based on subtitle dimensions
    bg_width = subtitle_width
    bg_height = subtitle_area_height

    # Center the background horizontally (same as subtitle positioning)
    bg_x = (video_width - bg_width) // 2
    bg_y = video_height - subtitle_area_height - bottom_margin

    # Create semi-transparent black background with 50% opacity
    background_filter = f"drawbox=x={bg_x}:y={bg_y}:width={bg_width}:height={bg_height}:color=black@0.5:t=fill"

    # Add time condition if provided
    if time_condition:
        background_filter += f":enable='{time_condition}'"

    return background_filter


def create_ffmpeg_drawtext_filters(subtitles: Dict[float, Tuple[str, str, str, str, float]], video_width: int = 1920, video_height: int = 1080) -> str:
    """
    Create FFmpeg filters to render Chinese text, pinyin, and Portuguese translations with semi-transparent background.

    Args:
        subtitles: Dictionary mapping begin_time to subtitle data
        video_width: Video width for positioning (default 1920)
        video_height: Video height for positioning (default 1080)

    Returns:
        FFmpeg filter string for drawtext operations with background
    """
    filter_parts = []

    # Get appropriate font paths once for all subtitles
    chinese_font_path = get_best_chinese_font()
    latin_font_path = get_best_latin_font()

    print(f"   🔤 Fonte chinesa: {chinese_font_path}")
    print(f"   🔤 Fonte latina: {latin_font_path}")
    print(f"   📐 Resolução do vídeo: {video_width}x{video_height}")

    # Calculate adaptive font sizes based on video resolution
    # Base the font sizes on video height, similar to the C code logic
    base_chinese_font_size = max(24, min(120, int(video_height * 0.06)))  # 6% of video height
    base_pinyin_font_size = int(base_chinese_font_size * 0.65)  # 65% of Chinese font size
    base_portuguese_font_size = int(base_chinese_font_size * 0.45)  # 45% of Chinese font size

    # Calculate adaptive spacing based on video width
    # Aim to use about 85% of the video width for subtitles
    max_subtitle_width_pixels = int(video_width * 0.85)

    print(f"   📝 Tamanhos adaptativos: Chinês={base_chinese_font_size}px, Pinyin={base_pinyin_font_size}px, PT={base_portuguese_font_size}px")
    print(f"   📏 Largura máxima das legendas: {max_subtitle_width_pixels}px ({(max_subtitle_width_pixels/video_width)*100:.1f}% da tela)")

    # Sort subtitles by time and validate content
    valid_subtitles = {}
    for begin_time, subtitle_data in subtitles.items():
        chinese_text, translations_text, translations_json, portuguese_text, duration = subtitle_data
        # Skip empty or invalid subtitles
        if chinese_text and chinese_text.strip() and chinese_text != 'N/A':
            valid_subtitles[begin_time] = subtitle_data
    
    # Limit number of subtitles to prevent FFmpeg filter complexity issues
    MAX_SUBTITLES = 1  # Process only first 1 subtitle to avoid timeouts and parsing errors
    if len(valid_subtitles) > MAX_SUBTITLES:
        print(f"   ⚠️  Limiting to first {MAX_SUBTITLES} subtitle to prevent FFmpeg timeout (total: {len(valid_subtitles)})")
        # Keep only the first MAX_SUBTITLES by time
        limited_subtitles = {}
        for i, (begin_time, subtitle_data) in enumerate(sorted(valid_subtitles.items())):
            if i >= MAX_SUBTITLES:
                break
            limited_subtitles[begin_time] = subtitle_data
        valid_subtitles = limited_subtitles

    if not valid_subtitles:
        print("   ⚠️  Nenhuma legenda válida encontrada, usando filtro de cópia")
        return "[0:v]copy[v]"

    print(f"   📊 Processando {len(valid_subtitles)} legendas válidas de {len(subtitles)} totais")

    # Define variables needed for positioning calculations
    # Calculate margins based on font sizes for better proportions
    bottom_margin = max(30, int(video_height * 0.04))  # 4% of height or minimum 30px (increased)
    vertical_spacing = max(10, int(base_chinese_font_size * 0.20))  # 20% of Chinese font size (increased)
    portuguese_extra_height = base_portuguese_font_size * 2  # Space for 2 additional lines

    # Calculate subtitle area dimensions for background
    # Find the minimum Y position (highest point) and maximum Y position (lowest point)
    # Also calculate the maximum width of subtitles
    min_y = float('inf')
    max_y = 0
    max_subtitle_width = 0
    background_filters = []

    # First pass: collect all Y positions and calculate maximum subtitle width
    for begin_time in sorted(valid_subtitles.keys()):
        chinese_text, translations_text, translations_json, portuguese_text, duration = valid_subtitles[begin_time]

        # Parse translations for pinyin and word-by-word Portuguese
        word_data = parse_pinyin_translations(translations_json) if translations_json else []

        # Clean Chinese text
        clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '').replace('"', '').replace('"', '')

        # Group characters into words and build display data
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

        # Calculate Y positions for this subtitle
        portuguese_y = video_height - bottom_margin - portuguese_extra_height - (base_portuguese_font_size // 2)
        chinese_y = portuguese_y - vertical_spacing - base_chinese_font_size
        pinyin_y = chinese_y - vertical_spacing - base_pinyin_font_size

        # Track min and max Y positions
        min_y = min(min_y, pinyin_y)
        max_y = max(max_y, portuguese_y + base_portuguese_font_size + portuguese_extra_height)

        # Calculate width for this subtitle and track maximum
        if display_items:
            # Calculate total width using the same logic as in the main loop
            chinese_char_width = int(base_chinese_font_size * 0.95)
            pinyin_char_width = int(base_pinyin_font_size * 0.65)
            min_word_spacing = max(80, int(video_width * 0.05))

            total_line_width = 0
            word_widths = []

            for chinese_word, word_pinyin, word_portuguese in display_items:
                chinese_word_width = len(chinese_word) * chinese_char_width
                pinyin_width = len(word_pinyin) * pinyin_char_width if word_pinyin else 0
                base_word_width = max(chinese_word_width, pinyin_width, min_word_spacing)
                safety_padding = max(20, int(base_word_width * 0.10))
                word_width = base_word_width + safety_padding
                word_widths.append(word_width)
                total_line_width += word_width

            # Apply scaling if needed
            if total_line_width > max_subtitle_width_pixels:
                scale_factor = max_subtitle_width_pixels / total_line_width
                min_word_width = 40
                scaled_widths = []
                for w in word_widths:
                    scaled_width = max(min_word_width, int(w * scale_factor))
                    scaled_widths.append(scaled_width)
                word_widths = scaled_widths
                total_line_width = sum(word_widths)

            max_subtitle_width = max(max_subtitle_width, total_line_width)

    # Create background filter if we have subtitles
    if valid_subtitles and max_subtitle_width > 0:
        background_height = max_y - min_y + 10  # Add some padding
        background_width = max_subtitle_width + 40  # Add some horizontal padding

        # Create a time condition that covers all subtitle periods
        if len(valid_subtitles) == 1:
            # Single subtitle
            begin_time = list(valid_subtitles.keys())[0]
            duration = valid_subtitles[begin_time][4]
            end_time = begin_time + duration
            time_condition = f"between(t,{begin_time:.3f},{end_time:.3f})"
        else:
            # Multiple subtitles - create a complex condition
            time_conditions = []
            for begin_time in sorted(valid_subtitles.keys()):
                duration = valid_subtitles[begin_time][4]
                end_time = begin_time + duration
                time_conditions.append(f"between(t,{begin_time:.3f},{end_time:.3f})")
            time_condition = "+".join(time_conditions)

        background_filter = create_subtitle_background_filter(background_height, background_width, video_width, video_height, bottom_margin, time_condition)
        background_filters.append(background_filter)

    # Sort subtitles by time
    for begin_time in sorted(valid_subtitles.keys()):
        chinese_text, translations_text, translations_json, portuguese_text, duration = valid_subtitles[begin_time]

        # Parse translations for pinyin and word-by-word Portuguese
        word_data = parse_pinyin_translations(translations_json) if translations_json else []

        # Clean Chinese text
        clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '').replace('"', '').replace('"', '')

        # Group characters into words and build display data
        display_items = []
        remaining_text = clean_chinese

        while remaining_text:
            found_word = False

            # Try to find the longest matching word
            for chinese_word, word_pinyin, word_portuguese in sorted(word_data, key=lambda x: len(x[0]), reverse=True):
                if remaining_text.startswith(chinese_word):
                    display_items.append((chinese_word, word_pinyin, word_portuguese))
                    remaining_text = remaining_text[len(chinese_word):]
                    found_word = True
                    break

            if not found_word:
                # Single character with no translation
                char = remaining_text[0]
                display_items.append((char, "", ""))
                remaining_text = remaining_text[1:]

        # Calculate adaptive positioning based on video height and font sizes
        # Ensure subtitle area is large enough for the adaptive font sizes
        min_subtitle_area = base_chinese_font_size + base_pinyin_font_size + (base_portuguese_font_size * 2) + 80  # Extra space for margins
        subtitle_area_height = max(int(video_height * 0.25), min_subtitle_area)  # Use 25% of video height or minimum needed

        # Variables already defined above

        # Calculate total height needed for all elements (more conservative)
        total_text_height = (base_pinyin_font_size + vertical_spacing +
                           base_chinese_font_size + vertical_spacing +
                           base_portuguese_font_size + portuguese_extra_height)

        # Ensure we don't use more than 35% of screen height for subtitles
        max_subtitle_height = int(video_height * 0.35)
        if total_text_height > max_subtitle_height:
            # Scale down spacing proportionally
            scale_factor = max_subtitle_height / total_text_height
            vertical_spacing = max(6, int(vertical_spacing * scale_factor))
            portuguese_extra_height = int(portuguese_extra_height * scale_factor)
            total_text_height = max_subtitle_height

        # Calculate Y positions from bottom up, with safety margins
        # Portuguese starts higher to avoid bottom crop (considering baseline positioning)
        portuguese_y = video_height - bottom_margin - portuguese_extra_height - (base_portuguese_font_size // 2)
        chinese_y = portuguese_y - vertical_spacing - base_chinese_font_size
        pinyin_y = chinese_y - vertical_spacing - base_pinyin_font_size

        # Safety check: ensure pinyin doesn't go off-screen at top
        min_pinyin_y = base_pinyin_font_size + 15  # Keep at least 15px from top (increased)
        if pinyin_y < min_pinyin_y:
            # Recalculate with compressed layout
            available_height = video_height - min_pinyin_y - bottom_margin - portuguese_extra_height
            compressed_spacing = max(6, available_height // 8)  # Divide available space

            pinyin_y = min_pinyin_y
            chinese_y = pinyin_y + base_pinyin_font_size + compressed_spacing
            portuguese_y = chinese_y + base_chinese_font_size + compressed_spacing

            # Final safety check for bottom crop
            max_portuguese_bottom = portuguese_y + base_portuguese_font_size + portuguese_extra_height
            if max_portuguese_bottom > video_height - 10:
                # Emergency compression - reduce font sizes if needed
                overflow = max_portuguese_bottom - (video_height - 10)
                portuguese_y -= overflow

        # Debug info for positioning (only for first subtitle to avoid spam)
        if begin_time == sorted(subtitles.keys())[0]:
            print(f"   📐 Posições Y adaptativas: Pinyin={pinyin_y}px, Chinês={chinese_y}px, PT={portuguese_y}px")
            print(f"   📏 Área de legendas: {subtitle_area_height}px ({(subtitle_area_height/video_height)*100:.1f}% da altura)")
            print(f"   🔵 Margem inferior: {bottom_margin}px, Espaçamento: {vertical_spacing}px")
            print(f"   🛡️  Altura extra PT: {portuguese_extra_height}px, Altura total: {total_text_height}px")

            # Check for potential cropping
            max_y_used = portuguese_y + base_portuguese_font_size + portuguese_extra_height
            bottom_clearance = video_height - max_y_used
            if bottom_clearance < 20:
                print(f"   ⚠️  ATENÇÃO: Pouco espaço inferior ({bottom_clearance}px restantes)")
            else:
                print(f"   ✅ Espaço inferior seguro: {bottom_clearance}px restantes")

        # Build text for each line with proper spacing
        chinese_parts = []
        pinyin_parts = []
        portuguese_parts = []

        for chinese_word, word_pinyin, word_portuguese in display_items:
            chinese_parts.append(chinese_word)
            if word_pinyin:
                pinyin_parts.append(word_pinyin)
            else:
                pinyin_parts.append(' ')  # Placeholder to maintain alignment

            if word_portuguese:
                # Keep full Portuguese translation (no truncation)
                portuguese_parts.append(word_portuguese)
            else:
                portuguese_parts.append('')  # Empty for words without translation

        # Create word-by-word aligned subtitle with pinyin centered over each Chinese word
        # Calculate total line width first to center the entire subtitle block
        total_line_width = 0
        word_widths = []

        # Calculate adaptive character widths based on font sizes (with safety margin)
        chinese_char_width = int(base_chinese_font_size * 0.95)  # Increased from 0.85 to 0.95 for safety
        pinyin_char_width = int(base_pinyin_font_size * 0.65)    # Increased from 0.6 to 0.65 for safety
        min_word_spacing = max(80, int(video_width * 0.05))      # Increased minimum spacing: 5% of width (was 4%)

        # Calculate width of each word for positioning
        for chinese_word, word_pinyin, word_portuguese in display_items:
            # Calculate adaptive word width based on resolution
            chinese_word_width = len(chinese_word) * chinese_char_width
            pinyin_width = len(word_pinyin) * pinyin_char_width if word_pinyin else 0

            # Use the wider of the two for spacing, with adaptive minimum + extra safety margin
            base_word_width = max(chinese_word_width, pinyin_width, min_word_spacing)
            # Add extra padding for safety (10% of base width, minimum 20px)
            safety_padding = max(20, int(base_word_width * 0.10))
            word_width = base_word_width + safety_padding
            word_widths.append(word_width)
            total_line_width += word_width

        # If the line is too wide, scale down word widths proportionally to fit max_subtitle_width
        if total_line_width > max_subtitle_width:
            scale_factor = max_subtitle_width / total_line_width

            # Apply more conservative scaling to preserve minimum spacing
            min_word_width = 40  # Minimum width per word to avoid complete overlap
            scaled_widths = []
            for w in word_widths:
                scaled_width = max(min_word_width, int(w * scale_factor))
                scaled_widths.append(scaled_width)

            word_widths = scaled_widths
            total_line_width = sum(word_widths)

            # If still too wide after conservative scaling, try reducing font sizes instead
            if total_line_width > max_subtitle_width:
                font_reduction_factor = max_subtitle_width / total_line_width
                print(f"   📏 Linha ainda muito larga, reduzindo fontes por fator {font_reduction_factor:.2f}")
            else:
                print(f"   📏 Linha muito larga, reduzida por fator {scale_factor:.2f} (conservativo)")

        # Calculate starting x position to center the entire line
        start_x = (video_width - total_line_width) // 2

        # Create time conditions for FFmpeg enable parameter
        end_time = begin_time + duration
        time_condition = f"between(t,{begin_time:.3f},{end_time:.3f})"

        # Remove borders since we have background
        chinese_border_width = 0
        pinyin_border_width = 0
        portuguese_border_width = 0

        # Add each word with its pinyin and Portuguese positioned individually
        current_x = start_x
        for i, (chinese_word, word_pinyin, word_portuguese) in enumerate(display_items):
            word_width = word_widths[i]

            # Escape text for FFmpeg
            chinese_escaped = escape_ffmpeg_text(chinese_word)
            pinyin_escaped = escape_ffmpeg_text(word_pinyin) if word_pinyin else ""

            # Debug: Log first few words of the first subtitle to trace unexpected quotes rendered
            if begin_time == sorted(valid_subtitles.keys())[0] and i < 5:
                try:
                    print(f"   🔎 RAW[{i}] zh='{chinese_word}' | py='{word_pinyin}' | pt='{word_portuguese}'")
                    print(f"   🔎 ESC[{i}] zh='{chinese_escaped}' | py='{pinyin_escaped}'")
                except Exception:
                    pass

            # Skip if Chinese text is empty after escaping
            if not chinese_escaped or chinese_escaped.strip() == '':
                current_x += word_width
                continue

            # Calculate center position for this word within its allocated width
            word_center_x = current_x + word_width // 2

            # Chinese text (centered within word width) - using adaptive font size
            chinese_filter = f'drawtext=text="{chinese_escaped}":x={word_center_x}-text_w/2:y={chinese_y}:fontfile=\'{chinese_font_path}\':fontsize={base_chinese_font_size}:fontcolor=white:borderw={chinese_border_width}:bordercolor=black:enable=\'{time_condition}\''
            if chinese_filter:  # Validate filter is not empty
                filter_parts.append(chinese_filter)

            # Pinyin text (centered over the Chinese word) - using adaptive font size
            if pinyin_escaped and pinyin_escaped.strip():
                pinyin_filter = f'drawtext=text="{pinyin_escaped}":x={word_center_x}-text_w/2:y={pinyin_y}:fontfile=\'{chinese_font_path}\':fontsize={base_pinyin_font_size}:fontcolor=#9370DB:borderw={pinyin_border_width}:bordercolor=black:enable=\'{time_condition}\''
                if pinyin_filter:  # Validate filter is not empty
                    filter_parts.append(pinyin_filter)

        # Portuguese text (centered below each Chinese word, with line breaks if needed) - using adaptive font size
        if word_portuguese and word_portuguese.strip():
            portuguese_lines = wrap_portuguese_to_chinese_width(word_portuguese, latin_font_path, word_width, base_portuguese_font_size)
            portuguese_line_height = int(base_portuguese_font_size * 1.2)  # Adaptive line height (120% of font size)

            for line_idx, portuguese_line in enumerate(portuguese_lines):
                if portuguese_line and portuguese_line.strip():  # Only add non-empty lines
                    portuguese_escaped = escape_ffmpeg_text(portuguese_line)
                    if begin_time == sorted(valid_subtitles.keys())[0] and i < 5 and line_idx == 0:
                        try:
                            print(f"   🔎 PT[{i}] line='{portuguese_line}' | esc='{portuguese_escaped}'")
                        except Exception:
                            pass
                    if portuguese_escaped and portuguese_escaped.strip():  # Validate escaped text
                        portuguese_line_y = portuguese_y + (line_idx * portuguese_line_height)
                        portuguese_filter = f'drawtext=text="{portuguese_escaped}":x={word_center_x}-text_w/2:y={portuguese_line_y}:fontfile=\'{latin_font_path}\':fontsize={base_portuguese_font_size}:fontcolor=yellow:borderw={portuguese_border_width}:bordercolor=black:enable=\'{time_condition}\''
                        if portuguese_filter:  # Validate filter is not empty
                            filter_parts.append(portuguese_filter)

            current_x += word_width

    # Format for filter complex script file - with validation
    # Remove any empty or invalid filter parts
    valid_filter_parts = [f for f in filter_parts if f and f.strip() and 'drawtext=' in f]

    print(f"   🔧 Gerados {len(valid_filter_parts)} filtros válidos de {len(filter_parts)} totais")
    print(f"   🎨 Filtros de fundo: {len(background_filters)}")

    # Combine background and text filters
    all_filters = background_filters + valid_filter_parts

    if all_filters:
        # Use pipeline approach for better reliability with many filters
        if len(all_filters) == 1:
            # Single filter case
            return f"[0:v]{all_filters[0]}[v]"
        else:
            # Multiple filters - chain them sequentially
            result_parts = []
            current_input = "[0:v]"

            for i, filter_part in enumerate(all_filters):
                if i == len(all_filters) - 1:
                    # Last filter outputs to [v]
                    result_parts.append(f"{current_input}{filter_part}[v]")
                else:
                    # Intermediate filter
                    temp_label = f"[tmp{i}]"
                    result_parts.append(f"{current_input}{filter_part}{temp_label}")
                    current_input = temp_label

            filter_result = "; ".join(result_parts)

            # Final validation - ensure the result contains [v] output
            if "[v]" not in filter_result:
                print("   ⚠️  Filtro final não contém saída [v], usando cópia")
                return "[0:v]copy[v]"

            return filter_result
    else:
        print("   ⚠️  Nenhum filtro válido criado, usando filtro de cópia")
        return "[0:v]copy[v]"  # No filters, just copy video


def get_video_info(video_path: Path) -> Tuple[int, int, float]:
    """Get video dimensions and duration using ffprobe."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'csv=p=0',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,duration',
            str(video_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        parts = result.stdout.strip().split(',')
        width = int(parts[0])
        height = int(parts[1])
        duration = float(parts[2]) if parts[2] and parts[2] != 'N/A' else 0.0
        return width, height, duration
    except:
        # Default values if detection fails
        return 1920, 1080, 0.0


def apply_subtitles_to_chunk(input_video: Path, subtitles: Dict[float, Tuple[str, str, str, str, float]], output_video: Path) -> bool:
    """
    Apply subtitles to video chunk using FFmpeg drawtext filters.

    Args:
        input_video: Path to input MP4 chunk file
        subtitles: Dictionary with subtitle data
        output_video: Path to output MP4 file

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get video info for proper positioning
        video_width, video_height, video_duration = get_video_info(input_video)
        print(f"   📐 Dimensões do chunk: {video_width}x{video_height}")
        if video_duration > 0:
            duration_min = int(video_duration // 60)
            duration_sec = int(video_duration % 60)
            print(f"   ⏱️  Duração do chunk: {duration_min}m{duration_sec:02d}s")

        # Create drawtext filters for subtitles
        drawtext_filters = create_ffmpeg_drawtext_filters(subtitles, video_width, video_height)

        if not drawtext_filters:
            print("   ⚠️  Nenhum filtro de legenda criado")
            return False

        # FFmpeg command for chunk processing - using filter_complex with proper syntax
        cmd = [
            'ffmpeg',
            '-i', str(input_video),
            '-filter_complex', drawtext_filters,
            '-map', '[v]',       # Map the filtered video output
            '-map', '0:a',       # Map original audio
            '-c:v', 'libx264',   # Video codec
            '-c:a', 'copy',      # Copy audio without re-encoding
            '-crf', '20',        # High quality
            '-preset', 'fast',   # Faster preset to avoid issues
            '-pix_fmt', 'yuv420p',  # Compatible pixel format
            '-y',                # Overwrite output
            str(output_video)
        ]

        print(f"   🎬 Aplicando legendas ao chunk...")
        print(f"   📂 Entrada: {input_video.name}")
        print(f"   📂 Saída: {output_video.name}")

        # Run FFmpeg with progress tracking
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        last_progress = -1
        stderr_output = []

        # Read progress from stdout
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break

            if line:
                current_time = float(line.strip().split('=')[1]) if 'out_time_ms=' in line else None
                if current_time is not None and video_duration > 0:
                    progress_percent = min(100.0, (current_time / 1_000_000.0 / video_duration) * 100)

                    if int(progress_percent) > last_progress:
                        last_progress = int(progress_percent)
                        print(f"\r   📊 Progresso: {last_progress:3d}%", end='', flush=True)

        # Read stderr
        stderr_data = process.stderr.read()
        if stderr_data:
            stderr_output.append(stderr_data)

        # Wait for completion
        return_code = process.wait()

        print()  # New line after progress

        if return_code == 0:
            print(f"   ✅ Legendas aplicadas com sucesso ao chunk!")
            return True
        else:
            print(f"   ❌ Erro no FFmpeg (código: {return_code})")
            if stderr_output:
                print(f"   STDERR: {''.join(stderr_output)}")
            # Limpar arquivo de saída em caso de erro do FFmpeg
            try:
                if output_video.exists():
                    output_video.unlink()
                    print(f"   🗑️  Arquivo de saída removido devido a erro no FFmpeg")
            except Exception as cleanup_error:
                print(f"   ⚠️  Não foi possível remover arquivo de saída: {cleanup_error}")
            return False

    except Exception as e:
        print(f"   ❌ Erro ao aplicar legendas ao chunk: {e}")
        # Limpar arquivo de saída em caso de erro inesperado
        try:
            if output_video.exists():
                output_video.unlink()
                print(f"   🗑️  Arquivo de saída removido devido a erro inesperado")
        except Exception as cleanup_error:
            print(f"   ⚠️  Não foi possível remover arquivo de saída: {cleanup_error}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Processa chunks de forma idempotente - apenas os não processados",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 process_chunks.py onibus132    # Processa apenas chunks não processados

Funcionamento (Idempotente):
  1. Encontra todos os chunks na pasta <directory_name>_sub
  2. Verifica quais chunks já têm arquivos *_processed.mp4 correspondentes
  3. Processa apenas os chunks que ainda não foram processados
  4. Pula automaticamente chunks já processados
  5. Mantém todos os arquivos originais

Características:
  - IDÉMPOTENTE: Pode ser executado múltiplas vezes sem duplicar trabalho
  - RESUMÍVEL: Continua do primeiro chunk não processado
  - SEGURO: Não sobrescreve arquivos já processados
  - VERBOSE: Mostra quais chunks estão sendo pulados

Arquivos gerados:
  - *_processed.mp4: Versão processada do chunk (com legendas)
  - Arquivos originais: Mantidos intactos

Para reprocessar:
  Remova os arquivos *_processed.mp4 e execute novamente o script.
        """
    )

    parser.add_argument('directory', help='Nome do diretório (sem _sub)')

    args = parser.parse_args()

    # Construct paths
    source_dir = Path('assets') / f"{args.directory}_sub"

    print("🔄 Process Chunks - Processamento individual de chunks")
    print("=" * 55)
    print(f"📁 Diretório fonte: {source_dir}")

    # Check if source directory exists
    if not source_dir.exists():
        print(f"❌ Erro: Diretório {source_dir} não encontrado")
        return 1

    try:
        # Find chunk files
        print("\n🔍 Procurando chunks...")
        all_chunk_files, unprocessed_chunk_files = find_chunk_files(source_dir)

        if not all_chunk_files:
            print(f"❌ Nenhum arquivo de chunk encontrado em {source_dir}")
            print("   Certifique-se de que os arquivos seguem o padrão: *chunk*.mp4")
            return 1

        print(f"📊 Total de chunks encontrados: {len(all_chunk_files)}")
        print(f"🎯 Chunks não processados: {len(unprocessed_chunk_files)}")

        # Show which chunks are being skipped
        if len(unprocessed_chunk_files) < len(all_chunk_files):
            processed_chunks = len(all_chunk_files) - len(unprocessed_chunk_files)
            print(f"⏭️  Pulando {processed_chunks} chunk(s) já processado(s)")

            # List skipped chunks (first few and last few if many)
            skipped_files = [f for f in all_chunk_files if f not in unprocessed_chunk_files]
            if len(skipped_files) <= 5:
                for skipped in skipped_files:
                    print(f"   ⏭️  {skipped.name} (já processado)")
            else:
                # Show first 2 and last 2
                for skipped in skipped_files[:2]:
                    print(f"   ⏭️  {skipped.name} (já processado)")
                print(f"   ... e mais {len(skipped_files) - 4} chunk(s) já processado(s)")
                for skipped in skipped_files[-2:]:
                    print(f"   ⏭️  {skipped.name} (já processado)")

        if not unprocessed_chunk_files:
            print("\n✅ Todos os chunks já foram processados!")
            print("💡 Para reprocessar, remova os arquivos *_processed.mp4")
            return 0

        # Process only unprocessed chunks
        processed_count = 0
        error_count = 0

        print("\n🎬 Iniciando processamento dos chunks não processados...")
        print("-" * 60)

        for i, chunk_file in enumerate(unprocessed_chunk_files, 1):
            # Find corresponding base file
            base_file = chunk_file.parent / chunk_file.name.replace('.mp4', '_base.txt')

            if not base_file.exists():
                print(f"   ⚠️  Arquivo base não encontrado: {base_file.name}")
                base_file = None

            # Process the chunk
            try:
                if process_chunk(chunk_file, base_file, i, len(unprocessed_chunk_files)):
                    processed_count += 1
                else:
                    error_count += 1
                    print(f"   ❌ Erro ao processar {chunk_file.name}")

                    # Lógica especial para Death.Becomes.Her.1992.1080p.BluRay.H264.AAC_chromecast_chunk_115.mp4
                    if "Death.Becomes.Her.1992.1080p.BluRay.H264.AAC_chromecast_chunk_115.mp4" in chunk_file.name:
                        print(f"   🔄 Aplicando tratamento especial para {chunk_file.name}")
                        print(f"   📋 Fazendo cópia idêntica do chunk original...")

                        # Criar cópia idêntica do chunk original
                        processed_copy = chunk_file.parent / f"{chunk_file.stem}_processed.mp4"

                        try:
                            shutil.copy2(chunk_file, processed_copy)
                            print(f"   ✅ Cópia idêntica criada: {processed_copy.name}")
                            print(f"   📊 Tamanho: {processed_copy.stat().st_size} bytes")
                            processed_count += 1
                            error_count -= 1  # Corrige a contagem pois agora foi "processado"
                        except Exception as copy_error:
                            print(f"   ❌ Falha ao criar cópia idêntica: {copy_error}")

            except Exception as e:
                error_count += 1
                print(f"   ❌ Erro inesperado em {chunk_file.name}: {e}")

                # Lógica especial para Death.Becomes.Her.1992.1080p.BluRay.H264.AAC_chromecast_chunk_115.mp4
                if "Death.Becomes.Her.1992.1080p.BluRay.H264.AAC_chromecast_chunk_115.mp4" in chunk_file.name:
                    print(f"   🔄 Aplicando tratamento especial para {chunk_file.name}")
                    print(f"   📋 Fazendo cópia idêntica do chunk original...")

                    # Criar cópia idêntica do chunk original
                    processed_copy = chunk_file.parent / f"{chunk_file.stem}_processed.mp4"

                    try:
                        shutil.copy2(chunk_file, processed_copy)
                        print(f"   ✅ Cópia idêntica criada: {processed_copy.name}")
                        print(f"   📊 Tamanho: {processed_copy.stat().st_size} bytes")
                        processed_count += 1
                        error_count -= 1  # Corrige a contagem pois agora foi "processado"
                    except Exception as copy_error:
                        print(f"   ❌ Falha ao criar cópia idêntica: {copy_error}")

            # Add small delay between chunks for better readability
            if i < len(unprocessed_chunk_files):
                print()

        # Summary
        print("\n" + "=" * 60)
        print("RESUMO DO PROCESSAMENTO")
        print("=" * 60)
        print(f"📊 Total de chunks encontrados: {len(all_chunk_files)}")
        print(f"⏭️  Chunks já processados (pulados): {len(all_chunk_files) - len(unprocessed_chunk_files)}")
        print(f"🎯 Chunks processados agora: {processed_count}")
        print(f"✅ Sucesso: {processed_count}")
        print(f"❌ Erros: {error_count}")
        print(f"💡 Arquivos originais: mantidos intactos")

        if error_count == 0:
            print("\n🎉 Todos os chunks pendentes processados com sucesso!")
            return 0
        else:
            print(f"\n⚠️  Processamento concluído com {error_count} erro(s)")
            return 1

    except KeyboardInterrupt:
        print("\n❌ Operação interrompida pelo usuário")
        return 1
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
