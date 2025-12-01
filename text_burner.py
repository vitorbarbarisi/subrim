#!/usr/bin/env python3
"""
Text Burner - Processa TXTs com texto chinês e gera imagens PNG com pinyin e traduções

Usage: python3 text_burner.py <directory_name>
Example: python3 text_burner.py texto3

O script:
1. Procura por arquivo TXT no diretório assets/<directory_name>
2. Extrai linhas contendo caracteres chineses do TXT
3. Cria base.txt com essas linhas
4. Chama LLM para gerar pares de tradução para cada linha
5. Sanitiza usando word-api (remove palavras com confidence_level == 3)
6. Gera uma série de imagens .png com fundo preto na resolução compatível com r36s (640x480).
   Cada imagem corresponde a uma linha do base.txt. Ela renderiza os caracteres com o pinyin
   e a tradução do array, semelhante ao que o process_chunks faz com o video, só que agora nas imagens.
7. É idempotente - continua de onde parou se base.txt já existir

Formato do base.txt:
- Uma linha por linha do TXT que contém caracteres chineses
- Formato: linha_original\tpares_json

Formato dos pares:
- Array JSON: ["palavra (pinyin): tradução", ...]

Exemplo de saída nas imagens:
nǐ hǎo
你好
olá
"""

import sys
import argparse
import os
import json
import re
import time
from pathlib import Path
from typing import List, Tuple, Dict

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ Erro: PIL (Pillow) não encontrado. Instale com: pip install Pillow")
    sys.exit(1)

# Importar funções do processor.py
from processor import (
    _get_api_provider, _retry_api_call, _call_maritaca_pairs, _call_deepseek_pairs,
    _call_deepseek_translate_to_pt, load_dotenv
)

# Importar funções do sanitize_base.py (opcional)
try:
    from sanitize_base import (
        check_word_api_health, get_word_from_api, post_word_to_api,
        extract_pairs_from_translation, process_word_api_integration
    )
    SANITIZE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  Aviso: sanitize_base não disponível: {e}")
    SANITIZE_AVAILABLE = False
    # Define funções stub
    def check_word_api_health():
        return False
    def extract_pairs_from_translation(pairs_str):
        return []
    def process_word_api_integration(pairs):
        return pairs

# Load .env immediately when module is imported
load_dotenv()

# URL da word-api localhost
WORD_API_BASE_URL = "http://localhost:7998/word-api"

# R36S resolution
R36S_WIDTH = 640
R36S_HEIGHT = 480


def extract_text_from_txt(txt_path: Path) -> list[str]:
    """
    Extrai linhas de um arquivo TXT.
    
    Args:
        txt_path: Caminho para o arquivo TXT
        
    Returns:
        list: Lista de linhas do texto extraído
    """
    lines = []
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
    except Exception as e:
        print(f"❌ Erro ao ler arquivo TXT: {e}")
        sys.exit(1)
    
    return lines


def contains_chinese_characters(text: str) -> bool:
    """
    Verifica se o texto contém caracteres chineses.
    
    Args:
        text: Texto para verificar
        
    Returns:
        bool: True se contém caracteres chineses
    """
    # Range de caracteres chineses: CJK Unified Ideographs
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    return bool(chinese_pattern.search(text))


def create_base_file(txt_path: Path, base_path: Path, resume: bool = False) -> bool:
    """
    Cria o arquivo base.txt com linhas contendo caracteres chineses.
    
    Args:
        txt_path: Caminho para o arquivo TXT
        base_path: Caminho para o arquivo base.txt
        resume: Se True, continua de onde parou se base.txt já existir
        
    Returns:
        bool: True se sucesso
    """
    print(f"📖 Extraindo texto do arquivo: {txt_path.name}")
    
    # Extrai texto do arquivo
    all_lines = extract_text_from_txt(txt_path)
    print(f"📊 Total de linhas extraídas: {len(all_lines)}")
    
    # Filtra linhas com caracteres chineses
    chinese_lines = [line for line in all_lines if contains_chinese_characters(line)]
    print(f"🔤 Linhas com caracteres chineses: {len(chinese_lines)}")
    
    if not chinese_lines:
        print("❌ Nenhuma linha com caracteres chineses encontrada no TXT")
        return False
    
    # Verifica se deve continuar de onde parou
    existing_lines = []
    if resume and base_path.exists():
        try:
            with open(base_path, 'r', encoding='utf-8') as f:
                existing_content = f.read().strip()
                if existing_content:
                    existing_lines = existing_content.split('\n')
                    print(f"📝 Arquivo base existente encontrado com {len(existing_lines)} linhas")
        except Exception as e:
            print(f"⚠️  Erro ao ler arquivo base existente: {e}")
    
    # Abre arquivo para escrita (append se resumindo)
    mode = 'a' if resume and existing_lines else 'w'
    
    with open(base_path, mode, encoding='utf-8') as f:
        # Se não está resumindo, escreve todas as linhas
        if not resume or not existing_lines:
            for line in chinese_lines:
                f.write(f"{line}\n")
            print(f"✅ Arquivo base criado com {len(chinese_lines)} linhas")
        else:
            # Se está resumindo, só adiciona linhas novas
            existing_texts = {line.split('\t')[0] for line in existing_lines if '\t' in line}
            new_lines = [line for line in chinese_lines if line not in existing_texts]
            
            if new_lines:
                for line in new_lines:
                    f.write(f"{line}\n")
                print(f"✅ Adicionadas {len(new_lines)} linhas novas ao arquivo base")
            else:
                print("ℹ️  Nenhuma linha nova para adicionar")
    
    return True


def process_base_with_llm(base_path: Path, force_provider: str | None = None) -> bool:
    """
    Processa o arquivo base.txt chamando LLM para gerar pares de tradução.
    
    Args:
        base_path: Caminho para o arquivo base.txt
        force_provider: Força uso de provider específico ('maritaca' ou 'deepseek')
        
    Returns:
        bool: True se sucesso
    """
    print(f"🤖 Processando base.txt com LLM...")
    
    try:
        # Lê o arquivo base
        with open(base_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Processa cada linha
        processed_lines = []
        pairs_cache = {}
        
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            # Se a linha já tem pares (formato: texto\tpares_json ou texto\tpares_json\ttradução), verifica se tem tradução
            if '\t' in line:
                parts = line.split('\t')
                # Se já tem 3 colunas (texto, pares, tradução), mantém como está
                if len(parts) >= 3:
                    processed_lines.append(line)
                    continue
                # Se tem apenas 2 colunas (texto, pares), precisa adicionar tradução
                elif len(parts) == 2:
                    chinese_text = parts[0]
                    pairs_str = parts[1]
                    # Gera tradução completa
                    try:
                        provider = force_provider if force_provider else "deepseek"
                        if provider == "deepseek":
                            translation = _retry_api_call(_call_deepseek_translate_to_pt, chinese_text)
                        else:
                            # Para maritaca, usa deepseek para tradução também (não há função específica)
                            translation = _retry_api_call(_call_deepseek_translate_to_pt, chinese_text)
                        processed_lines.append(f"{chinese_text}\t{pairs_str}\t{translation}")
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"   ⚠️  Erro ao gerar tradução para linha {i}: {e}, mantendo sem tradução")
                        processed_lines.append(line)
                    continue
            
            print(f"   🔄 Processando linha {i}/{len(lines)}: {line[:50]}...")
            
            # Gera pares e tradução usando LLM
            try:
                # Usa deepseek como padrão, a menos que force_provider seja especificado
                provider = force_provider if force_provider else "deepseek"
                if provider == "maritaca":
                    pairs_str = _retry_api_call(_call_maritaca_pairs, line)
                else:
                    # Default é deepseek
                    pairs_str = _retry_api_call(_call_deepseek_pairs, line)
                
                # Gera tradução completa da linha
                if provider == "deepseek":
                    translation = _retry_api_call(_call_deepseek_translate_to_pt, line)
                else:
                    # Para maritaca, usa deepseek para tradução também
                    translation = _retry_api_call(_call_deepseek_translate_to_pt, line)
                
                # Adiciona linha com pares e tradução
                processed_lines.append(f"{line}\t{pairs_str}\t{translation}")
                
                # Pequena pausa entre chamadas
                time.sleep(0.1)
                
            except Exception as e:
                print(f"   ❌ Erro ao processar linha {i}: {e}")
                # Adiciona linha sem pares e sem tradução em caso de erro
                processed_lines.append(f"{line}\t[]\t")
        
        # Salva arquivo processado
        with open(base_path, 'w', encoding='utf-8') as f:
            for line in processed_lines:
                f.write(f"{line}\n")
        
        print(f"✅ Base.txt processado com LLM")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao processar base.txt com LLM: {e}")
        return False


def find_pairs_column(parts: list) -> int | None:
    """
    Encontra automaticamente a coluna que contém o array de pairs.
    Procura por uma coluna que comece com '[' e contenha o padrão de pairs.
    
    Args:
        parts: Lista de partes da linha dividida por tabs
        
    Returns:
        int: Índice da coluna com pairs, ou None se não encontrado
    """
    for i, part in enumerate(parts):
        part = part.strip()
        # Verifica se parece com um array de pairs:
        # - Começa com '['
        # - Contém o padrão ": " (dois pontos seguido de espaço, dentro ou fora das aspas)
        # - Contém '(' e ')' (pinyin entre parênteses) OU contém ": " que indica tradução
        if part.startswith('['):
            # Verifica se tem o padrão de pairs (palavra (pinyin): tradução)
            # Procura por ": " (dois pontos e espaço) que aparece após o pinyin
            if ': ' in part and ('(' in part or '"' in part):
                # Verifica se não é apenas um array simples como [texto] ou [SILÊNCIO]
                # Deve ter pelo menos um padrão que indique pairs
                if '(' in part and ')' in part:
                    return i
                # Ou se tem múltiplas aspas indicando array de strings
                elif part.count('"') >= 2:
                    return i
    return None


def sanitize_base_with_word_api(base_path: Path) -> bool:
    """
    Sanitiza o arquivo base.txt usando word-api.
    Detecta automaticamente a coluna que contém o array de pairs.
    
    Args:
        base_path: Caminho para o arquivo base.txt
        
    Returns:
        bool: True se sucesso
    """
    print(f"🧹 Sanitizando base.txt com word-api...")
    
    try:
        # Lê o arquivo base
        with open(base_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        processed_lines = []
        modified_count = 0
        removed_count = 0
        pairs_column = None  # Será detectado na primeira linha válida
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                processed_lines.append(line)
                continue
            
            # Divide a linha por tabs
            parts = line.split('\t')
            if len(parts) < 2:
                processed_lines.append(line)
                continue
            
            # Detecta a coluna de pairs na primeira linha válida
            if pairs_column is None:
                pairs_column = find_pairs_column(parts)
                if pairs_column is None:
                    print(f"   ⚠️  Não foi possível detectar coluna de pairs na linha {line_num}")
                    processed_lines.append(line)
                    continue
                else:
                    print(f"   🔍 Coluna de pairs detectada: coluna {pairs_column + 1} (índice {pairs_column})")
            
            # Verifica se a coluna existe
            if pairs_column >= len(parts):
                processed_lines.append(line)
                continue
            
            pairs_str = parts[pairs_column]
            
            # Processa pares com word-api
            if pairs_str and pairs_str != "[]":
                pairs = extract_pairs_from_translation(pairs_str)
                if pairs:
                    print(f"   📋 Linha {line_num}: {len(pairs)} pares encontrados")
                    filtered_pairs = process_word_api_integration(pairs)
                    print(f"   📋 Linha {line_num}: {len(filtered_pairs)} pares após filtro (removidos: {len(pairs) - len(filtered_pairs)})")
                    
                    if filtered_pairs:
                        # Reconstrói pares filtrados
                        new_pairs_parts = []
                        for pair in filtered_pairs:
                            if pair["pinyin"]:
                                new_pairs_parts.append(f'"{pair["word"]} ({pair["pinyin"]}): {pair["translation"]}"')
                            else:
                                new_pairs_parts.append(f'"{pair["word"]}: {pair["translation"]}"')
                        
                        new_pairs_str = "[" + ", ".join(new_pairs_parts) + "]"
                        
                        # Atualiza a coluna de pairs
                        parts[pairs_column] = new_pairs_str
                        
                        if new_pairs_str != pairs_str:
                            modified_count += 1
                            print(f"   ✅ Linha {line_num}: modificada ({len(pairs)} -> {len(filtered_pairs)} pares)")
                        else:
                            print(f"   ℹ️  Linha {line_num}: sem alterações ({len(pairs)} pares mantidos)")
                    else:
                        # Todos os pares foram removidos, pula a linha
                        removed_count += 1
                        print(f"   🗑️  Linha {line_num}: removida (todos os pares filtrados)")
                        continue
                else:
                    print(f"   ⚠️  Linha {line_num}: não foi possível extrair pares de '{pairs_str[:50]}...'")
            
            processed_lines.append('\t'.join(parts))
        
        # Salva arquivo sanitizado
        with open(base_path, 'w', encoding='utf-8') as f:
            for line in processed_lines:
                f.write(f"{line}\n")
        
        print(f"✅ Base.txt sanitizado com word-api")
        print(f"   📝 {modified_count} linhas modificadas")
        print(f"   🗑️  {removed_count} linhas removidas")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao sanitizar base.txt: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_chinese_font_path() -> str:
    """Find the best available Chinese font."""
    chinese_fonts = [
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    
    for font_path in chinese_fonts:
        if Path(font_path).exists():
            return font_path
    
    return 'arial'  # Fallback


def get_latin_font_path() -> str:
    """Find the best available Latin font."""
    latin_fonts = [
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/ArialHB.ttc',
        '/System/Library/Fonts/HelveticaNeue.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    
    for font_path in latin_fonts:
        if Path(font_path).exists():
            return font_path
    
    return 'arial'  # Fallback


def parse_pinyin_translations(translation_list_str: str) -> list[tuple[str, str, str]]:
    """
    Parse the translation list string to extract Chinese characters, pinyin, and Portuguese translations.
    
    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'
    
    Returns:
        List of tuples (chinese_chars, pinyin, portuguese_translation)
    """
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
        print(f"Erro ao fazer parsing da lista de traduções: {e}")
        return []


def wrap_portuguese_to_width(portuguese_text: str, font, max_width: int) -> List[str]:
    """
    Break Portuguese text into multiple lines to fit within max_width.
    Never breaks words in the middle - only breaks at word boundaries.
    """
    if not portuguese_text:
        return []
    
    words = portuguese_text.split()
    if not words:
        return [portuguese_text]
    
    lines = []
    current_line = []
    current_width = 0
    
    for word in words:
        word_width = font.getlength(word + ' ')
        
        if current_width + word_width <= max_width or not current_line:
            current_line.append(word)
            current_width += word_width
        else:
            lines.append(' '.join(current_line))
            current_line = [word]
            current_width = font.getlength(word + ' ')
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def render_image_with_lines(
    display_items: List[Tuple[str, str, str]],
    word_widths: List[int],
    lines_of_items: List[List[int]],
    output_path: Path,
    chinese_font_path: str,
    latin_font_path: str
) -> bool:
    """
    Renderiza uma imagem com até 3 linhas de palavras.
    
    Args:
        display_items: Lista de (chinese_word, pinyin, portuguese)
        word_widths: Lista de larguras de cada palavra
        lines_of_items: Lista de listas de índices de palavras por linha (máximo 3 linhas)
        output_path: Caminho para salvar a imagem
        chinese_font_path: Caminho da fonte chinesa
        latin_font_path: Caminho da fonte latina
        
    Returns:
        bool: True se sucesso
    """
    try:
        # Limita a 3 linhas
        if len(lines_of_items) > 3:
            lines_of_items = lines_of_items[:3]
        
        # Cria imagem com fundo preto
        img = Image.new('RGB', (R36S_WIDTH, R36S_HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Carrega fontes
        base_chinese_font_size = 48
        base_pinyin_font_size = int(base_chinese_font_size * 0.65)
        base_portuguese_font_size = int(base_chinese_font_size * 0.45)
        
        try:
            chinese_font = ImageFont.truetype(chinese_font_path, base_chinese_font_size)
            pinyin_font = ImageFont.truetype(chinese_font_path, base_pinyin_font_size)
            portuguese_font = ImageFont.truetype(latin_font_path, base_portuguese_font_size)
        except Exception as e:
            print(f"   ⚠️  Erro ao carregar fontes: {e}, usando fontes padrão")
            chinese_font = ImageFont.load_default()
            pinyin_font = ImageFont.load_default()
            portuguese_font = ImageFont.load_default()
        
        # Calcula espaçamento e posicionamento
        vertical_spacing = 10  # Espaçamento entre pinyin, chinês e português (reduzido)
        
        # Ajusta espaçamento entre linhas baseado no número de linhas
        num_lines = len(lines_of_items)
        if num_lines == 3:
            line_spacing = 10  # Espaçamento muito reduzido quando há 3 linhas
        elif num_lines == 2:
            line_spacing = 15  # Espaçamento médio para 2 linhas
        else:
            line_spacing = 25  # Espaçamento normal para 1 linha
        
        # Calcula altura de cada torre individualmente (pode variar)
        tower_heights = []
        for line_items in lines_of_items:
            max_portuguese_lines_for_line = 1
            for item_idx in line_items:
                _, _, word_portuguese = display_items[item_idx]
                if word_portuguese:
                    wrapped = wrap_portuguese_to_width(word_portuguese, portuguese_font, word_widths[item_idx])
                    max_portuguese_lines_for_line = max(max_portuguese_lines_for_line, len(wrapped))
            
            # Altura desta torre específica
            tower_height = base_pinyin_font_size + vertical_spacing + base_chinese_font_size + vertical_spacing + (base_portuguese_font_size * max_portuguese_lines_for_line)
            tower_heights.append(tower_height)
        
        # Altura total considerando múltiplas linhas
        total_height = sum(tower_heights) + (line_spacing * (len(lines_of_items) - 1))
        
        # Calcula margens dinamicamente para garantir que caiba
        available_height = R36S_HEIGHT
        if total_height > available_height:
            # Se não couber, reduz margens ao mínimo
            top_margin = 5
            bottom_margin = 5
        else:
            # Se couber, centraliza com margens proporcionais
            remaining_space = available_height - total_height
            top_margin = remaining_space // 2
            bottom_margin = remaining_space - top_margin
        
        start_y = top_margin
        
        # Desenha cada linha de palavras
        current_tower_y = start_y
        
        for line_idx, line_items in enumerate(lines_of_items):
            # Usa a altura específica desta torre
            tower_height = tower_heights[line_idx]
            
            # Calcula largura total desta linha
            line_width = sum(word_widths[i] for i in line_items)
            
            # Posição inicial X (centralizado)
            line_start_x = (R36S_WIDTH - line_width) // 2
            
            # Desenha cada palavra nesta linha
            current_x = line_start_x
            
            for item_idx in line_items:
                chinese_word, word_pinyin, word_portuguese = display_items[item_idx]
                word_width = word_widths[item_idx]
                word_center_x = current_x + word_width // 2
                
                # Pinyin (roxo)
                if word_pinyin:
                    pinyin_bbox = pinyin_font.getbbox(word_pinyin)
                    pinyin_text_width = pinyin_bbox[2] - pinyin_bbox[0]
                    pinyin_x = word_center_x - pinyin_text_width // 2
                    draw.text((pinyin_x, current_tower_y), word_pinyin, font=pinyin_font, fill=(147, 112, 219))  # #9370DB
                
                # Chinês (branco)
                chinese_bbox = chinese_font.getbbox(chinese_word)
                chinese_text_width = chinese_bbox[2] - chinese_bbox[0]
                chinese_x = word_center_x - chinese_text_width // 2
                chinese_y = current_tower_y + base_pinyin_font_size + vertical_spacing
                draw.text((chinese_x, chinese_y), chinese_word, font=chinese_font, fill=(255, 255, 255))
                
                # Português (amarelo)
                if word_portuguese:
                    portuguese_y = chinese_y + base_chinese_font_size + vertical_spacing
                    wrapped_lines = wrap_portuguese_to_width(word_portuguese, portuguese_font, word_width)
                    for line_idx_pt, line in enumerate(wrapped_lines):
                        line_bbox = portuguese_font.getbbox(line)
                        line_width = line_bbox[2] - line_bbox[0]
                        line_x = word_center_x - line_width // 2
                        line_y = portuguese_y + (line_idx_pt * int(base_portuguese_font_size * 1.2))
                        draw.text((line_x, line_y), line, font=portuguese_font, fill=(255, 255, 0))  # Amarelo
                
                current_x += word_width
            
            # Move para próxima linha de torres (exceto na última linha)
            if line_idx < len(lines_of_items) - 1:
                current_tower_y += tower_height + line_spacing
        
        # Salva imagem
        img.save(output_path, 'PNG')
        return True
        
    except Exception as e:
        print(f"   ❌ Erro ao renderizar imagem: {e}")
        return False


def render_translation_image(
    translation_text: str,
    output_path: Path,
    latin_font_path: str
) -> bool:
    """
    Renderiza uma imagem com a tradução completa em português.
    
    Args:
        translation_text: Texto da tradução em português
        output_path: Caminho para salvar a imagem
        latin_font_path: Caminho da fonte latina
        
    Returns:
        bool: True se sucesso
    """
    try:
        if not translation_text or not translation_text.strip():
            return False
        
        # Cria imagem com fundo preto
        img = Image.new('RGB', (R36S_WIDTH, R36S_HEIGHT), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Carrega fonte para português (tamanho maior para tradução completa)
        translation_font_size = 32
        try:
            translation_font = ImageFont.truetype(latin_font_path, translation_font_size)
        except Exception as e:
            print(f"   ⚠️  Erro ao carregar fonte: {e}, usando fonte padrão")
            translation_font = ImageFont.load_default()
        
        # Quebra o texto em múltiplas linhas
        max_width = int(R36S_WIDTH * 0.90)  # Usa 90% da largura
        wrapped_lines = wrap_portuguese_to_width(translation_text, translation_font, max_width)
        
        # Calcula altura total do texto
        line_height = int(translation_font_size * 1.3)
        total_height = len(wrapped_lines) * line_height
        
        # Centraliza verticalmente
        start_y = (R36S_HEIGHT - total_height) // 2
        
        # Desenha cada linha centralizada horizontalmente
        for i, line in enumerate(wrapped_lines):
            line_bbox = translation_font.getbbox(line)
            line_width = line_bbox[2] - line_bbox[0]
            line_x = (R36S_WIDTH - line_width) // 2
            line_y = start_y + (i * line_height)
            draw.text((line_x, line_y), line, font=translation_font, fill=(255, 255, 255))  # Branco
        
        # Salva imagem
        img.save(output_path, 'PNG')
        return True
        
    except Exception as e:
        print(f"   ❌ Erro ao renderizar imagem de tradução: {e}")
        return False


def generate_image_for_line(
    line_index: int,
    chinese_text: str,
    pairs_str: str,
    output_dir: Path,
    chinese_font_path: str,
    latin_font_path: str
) -> tuple[int, str]:
    """
    Gera uma ou mais imagens PNG para uma linha do base.txt.
    Limita a 3 linhas por imagem. Se não couber, cria novas imagens.
    
    Args:
        line_index: Índice da linha (para nome do arquivo)
        chinese_text: Texto chinês original
        pairs_str: String JSON com os pares de tradução
        output_dir: Diretório de saída
        chinese_font_path: Caminho da fonte chinesa
        latin_font_path: Caminho da fonte latina
        
    Returns:
        tuple[int, str]: (Número de imagens geradas, última letra usada)
    """
    try:
        # Parse pares de tradução
        word_data = parse_pinyin_translations(pairs_str) if pairs_str else []
        
        # Limpa texto chinês
        clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '').replace('"', '').replace('"', '')
        
        # Agrupa caracteres em palavras
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
        
        if not display_items:
            return (0, 'a')
        
        # Carrega fontes para calcular larguras
        base_chinese_font_size = 48
        base_pinyin_font_size = int(base_chinese_font_size * 0.65)
        base_portuguese_font_size = int(base_chinese_font_size * 0.45)
        
        try:
            chinese_font = ImageFont.truetype(chinese_font_path, base_chinese_font_size)
            pinyin_font = ImageFont.truetype(chinese_font_path, base_pinyin_font_size)
            portuguese_font = ImageFont.truetype(latin_font_path, base_portuguese_font_size)
        except Exception as e:
            print(f"   ⚠️  Erro ao carregar fontes: {e}, usando fontes padrão")
            chinese_font = ImageFont.load_default()
            pinyin_font = ImageFont.load_default()
            portuguese_font = ImageFont.load_default()
        
        # Calcula largura de cada palavra
        min_word_spacing = 80  # Espaçamento mínimo entre palavras
        word_widths = []
        for chinese_word, word_pinyin, word_portuguese in display_items:
            chinese_width = chinese_font.getlength(chinese_word)
            pinyin_width = pinyin_font.getlength(word_pinyin) if word_pinyin else 0
            word_width = max(chinese_width, pinyin_width, min_word_spacing)
            word_widths.append(word_width)
        
        # Distribui palavras em linhas
        max_subtitle_width = int(R36S_WIDTH * 0.90)  # Usa 90% da largura
        max_lines_per_image = 3  # Máximo de 3 linhas por imagem
        
        # Agrupa palavras em linhas
        all_lines_of_items = []
        current_line_items = []
        current_line_width = 0
        
        for i, item in enumerate(display_items):
            word_width = word_widths[i]
            
            # Se adicionar esta palavra ultrapassar a largura e já temos itens na linha
            if current_line_items and (current_line_width + word_width > max_subtitle_width):
                all_lines_of_items.append(current_line_items)
                current_line_items = [i]
                current_line_width = word_width
            else:
                current_line_items.append(i)
                current_line_width += word_width
        
        # Adiciona última linha
        if current_line_items:
            all_lines_of_items.append(current_line_items)
        
        # Divide em grupos de até 3 linhas por imagem
        images_generated = 0
        image_suffix_letter = 'a'  # Começa com 'a'
        
        for i in range(0, len(all_lines_of_items), max_lines_per_image):
            lines_for_this_image = all_lines_of_items[i:i + max_lines_per_image]
            
            # Cria nome do arquivo (sempre com sufixo)
            output_path = output_dir / f"line_{line_index:04d}_{image_suffix_letter}.png"
            
            # Renderiza imagem
            if render_image_with_lines(display_items, word_widths, lines_for_this_image, output_path, chinese_font_path, latin_font_path):
                images_generated += 1
                # Incrementa letra: a -> b -> c -> d -> etc.
                image_suffix_letter = chr(ord(image_suffix_letter) + 1)
        
        return (images_generated, image_suffix_letter)
        
    except Exception as e:
        print(f"   ❌ Erro ao gerar imagem para linha {line_index}: {e}")
        return (0, 'a')


def generate_images_from_base(base_path: Path, output_dir: Path) -> bool:
    """
    Gera imagens PNG para cada linha do base.txt.
    
    Args:
        base_path: Caminho para o arquivo base.txt
        output_dir: Diretório de saída para as imagens
        
    Returns:
        bool: True se sucesso
    """
    print(f"🖼️  Gerando imagens PNG...")
    
    # Cria diretório de saída
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Carrega fontes
    chinese_font_path = get_chinese_font_path()
    latin_font_path = get_latin_font_path()
    
    print(f"   🔤 Fonte chinesa: {chinese_font_path}")
    print(f"   🔤 Fonte latina: {latin_font_path}")
    
    try:
        # Lê o arquivo base
        with open(base_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        generated_count = 0
        skipped_count = 0
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or '\t' not in line:
                continue
            
            parts = line.split('\t')
            if len(parts) < 2:
                continue
            
            chinese_text = parts[0]
            pairs_str = parts[1]
            translation_text = parts[2] if len(parts) >= 3 else None
            
            # Verifica se a primeira imagem já existe (idempotente)
            first_image_path = output_dir / f"line_{line_num:04d}_a.png"
            if first_image_path.exists():
                # Verifica se precisa gerar imagem de tradução
                if translation_text and translation_text.strip():
                    # Descobre qual é a última letra usada procurando por imagens existentes
                    last_letter = 'a'
                    for letter in 'bcdefghijklmnopqrstuvwxyz':
                        check_path = output_dir / f"line_{line_num:04d}_{letter}.png"
                        if check_path.exists():
                            last_letter = letter
                        else:
                            break
                    
                    # Próxima letra para tradução
                    translation_letter = chr(ord(last_letter) + 1)
                    translation_path = output_dir / f"line_{line_num:04d}_{translation_letter}.png"
                    
                    if not translation_path.exists():
                        if render_translation_image(translation_text, translation_path, latin_font_path):
                            generated_count += 1
                            print(f"      ✅ Gerada imagem de tradução: line_{line_num:04d}_{translation_letter}.png")
                
                skipped_count += 1
                continue
            
            print(f"   🎨 Gerando imagem(s) {line_num}/{len(lines)}: {chinese_text[:30]}...")
            
            images_count, last_letter = generate_image_for_line(line_num, chinese_text, pairs_str, output_dir, chinese_font_path, latin_font_path)
            if images_count > 0:
                generated_count += images_count
                if images_count > 1:
                    print(f"      ✅ Geradas {images_count} imagens para esta linha")
                
                # Gera imagem de tradução se houver tradução completa
                if translation_text and translation_text.strip():
                    # Próxima letra na sequência
                    translation_letter = chr(ord(last_letter))
                    translation_path = output_dir / f"line_{line_num:04d}_{translation_letter}.png"
                    
                    if render_translation_image(translation_text, translation_path, latin_font_path):
                        generated_count += 1
                        print(f"      ✅ Gerada imagem de tradução: line_{line_num:04d}_{translation_letter}.png")
            else:
                print(f"   ⚠️  Falha ao gerar imagem para linha {line_num}")
        
        print(f"✅ Imagens geradas: {generated_count} novas, {skipped_count} já existentes")
        return True
        
    except Exception as e:
        print(f"❌ Erro ao gerar imagens: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Processa TXTs com texto chinês e gera imagens PNG com pinyin e traduções",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 text_burner.py texto3    # Processa assets/texto3/

Funcionamento:
  - Procura por arquivo TXT no diretório assets/<directory_name>
  - Extrai linhas contendo caracteres chineses
  - Cria base.txt com essas linhas
  - Chama LLM para gerar pares de tradução
  - Sanitiza usando word-api
  - Gera imagens PNG 640x480 com fundo preto
  - É idempotente - continua de onde parou se base.txt já existir
        """
    )
    
    parser.add_argument('directory', help='Nome do diretório dentro de assets/')
    
    # API provider selection
    api_group = parser.add_mutually_exclusive_group()
    api_group.add_argument(
        "-m", "--maritaca",
        action="store_true",
        help="Force use of Maritaca AI API (requires MARITACA_API_KEY)"
    )
    api_group.add_argument(
        "-d", "--deepseek",
        action="store_true",
        help="Force use of DeepSeek API (requires DEEPSEEK_API_KEY)"
    )
    
    args = parser.parse_args()
    
    # Determina provider forçado
    force_provider = None
    if args.maritaca:
        force_provider = "maritaca"
    elif args.deepseek:
        force_provider = "deepseek"
    
    # Constrói caminhos
    assets_root = Path(__file__).resolve().parent / "assets"
    source_dir = assets_root / args.directory
    
    print("🔥 Text Burner - Processador de TXTs com texto chinês")
    print("=" * 60)
    print(f"📁 Diretório: {source_dir}")
    
    # Verifica se o diretório existe
    if not source_dir.exists():
        print(f"❌ Erro: Diretório {source_dir} não encontrado")
        return 1
    
    # Procura por arquivo TXT
    txt_files = list(source_dir.glob("*.txt"))
    if not txt_files:
        print(f"❌ Erro: Nenhum arquivo TXT encontrado em {source_dir}")
        return 1
    
    if len(txt_files) > 1:
        print(f"⚠️  Múltiplos arquivos TXT encontrados, usando: {txt_files[0].name}")
    
    txt_path = txt_files[0]
    base_path = source_dir / "base.txt"
    output_dir = source_dir / "images"
    
    print(f"📄 Arquivo encontrado: {txt_path.name}")
    
    # 1. Cria arquivo base.txt
    print("\n📝 Passo 1: Criando base.txt...")
    if not create_base_file(txt_path, base_path, resume=True):
        return 1
    
    # 2. Processa com LLM
    print("\n🤖 Passo 2: Processando com LLM...")
    if not process_base_with_llm(base_path, force_provider):
        return 1
    
    # 3. Verifica word-api e sanitiza
    print("\n🧹 Passo 3: Sanitizando com word-api...")
    if not SANITIZE_AVAILABLE:
        print("⚠️  Sanitização não disponível (sanitize_base não importado), pulando")
    elif not check_word_api_health():
        print("⚠️  Word-api indisponível, pulando sanitização")
    else:
        if not sanitize_base_with_word_api(base_path):
            return 1
    
    # 4. Gera imagens PNG
    print("\n🖼️  Passo 4: Gerando imagens PNG...")
    if not generate_images_from_base(base_path, output_dir):
        return 1
    
    print("\n🎉 Processamento concluído com sucesso!")
    print(f"📝 Arquivo base: {base_path.name}")
    print(f"🖼️  Imagens: {output_dir.name}/")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
