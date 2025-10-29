#!/usr/bin/env python3
"""
Word Fetcher Script

Este script lê o arquivo words.txt e cria TODOs para cada palavra encontrada.
"""

from itertools import pairwise
import os
from pathlib import Path
import cv2
from datetime import datetime


def read_words_file(file_path):
    """
    Lê o arquivo words.txt e retorna uma lista de palavras.
    
    Args:
        file_path (str): Caminho para o arquivo words.txt
        
    Returns:
        list: Lista de palavras encontradas no arquivo
    """
    words = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                word = line.strip()
                if word:  # Ignora linhas vazias
                    words.append(word)
    except FileNotFoundError:
        print(f"Erro: Arquivo {file_path} não encontrado.")
    except Exception as e:
        print(f"Erro ao ler o arquivo: {e}")
    
    return words


def capture_video_frame(video_path, timestamp_seconds, output_path, translation_text=""):
    """
    Captura um frame do vídeo no timestamp especificado e adiciona texto de tradução.
    
    Args:
        video_path (str): Caminho para o arquivo de vídeo
        timestamp_seconds (float): Timestamp em segundos
        output_path (str): Caminho onde salvar o frame capturado
        translation_text (str): Texto de tradução para sobrepor na imagem
        
    Returns:
        bool: True se a captura foi bem-sucedida, False caso contrário
    """
    try:
        # Abre o vídeo
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Erro: Não foi possível abrir o vídeo {video_path}")
            return False
        
        # Obtém o FPS do vídeo
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            print(f"Erro: Não foi possível obter o FPS do vídeo {video_path}")
            cap.release()
            return False
        
        # Calcula o número do frame correspondente ao timestamp
        frame_number = int(fps * timestamp_seconds)
        
        # Define o frame a ser capturado
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        
        # Lê o frame
        ret, frame = cap.read()
        if not ret:
            print(f"Erro: Não foi possível capturar o frame no timestamp {timestamp_seconds}s")
            cap.release()
            return False
        
        # Fecha o vídeo
        cap.release()
        
        # Adiciona texto de tradução se fornecido
        if translation_text and translation_text.strip() != "N/A":
            frame = add_translation_text(frame, translation_text)
        
        # Salva o frame como PNG
        cv2.imwrite(output_path, frame)
        print(f"Screenshot salvo: {output_path}")
        return True
        
    except Exception as e:
        print(f"Erro ao capturar frame: {e}")
        return False


def normalize_pinyin(pinyin):
    """
    Remove caracteres especiais (acentos/tons) do pinyin para uso em nomes de arquivo.
    
    Args:
        pinyin (str): String com pinyin contendo acentos
        
    Returns:
        str: Pinyin sem acentos/tons, apenas letras básicas
    """
    # Mapeamento de caracteres especiais para versões básicas
    char_replacements = {
        'ā': 'a', 'á': 'a', 'ǎ': 'a', 'à': 'a',
        'ē': 'e', 'é': 'e', 'ě': 'e', 'è': 'e',
        'ī': 'i', 'í': 'i', 'ǐ': 'i', 'ì': 'i',
        'ō': 'o', 'ó': 'o', 'ǒ': 'o', 'ò': 'o',
        'ū': 'u', 'ú': 'u', 'ǔ': 'u', 'ù': 'u',
        'ǖ': 'ü', 'ǘ': 'ü', 'ǚ': 'ü', 'ǜ': 'ü',
        'Ā': 'A', 'Á': 'A', 'Ǎ': 'A', 'À': 'A',
        'Ē': 'E', 'É': 'E', 'Ě': 'E', 'È': 'E',
        'Ī': 'I', 'Í': 'I', 'Ǐ': 'I', 'Ì': 'I',
        'Ō': 'O', 'Ó': 'O', 'Ǒ': 'O', 'Ò': 'O',
        'Ū': 'U', 'Ú': 'U', 'Ǔ': 'U', 'Ù': 'U',
        'Ǖ': 'Ü', 'Ǘ': 'Ü', 'Ǚ': 'Ü', 'Ǜ': 'Ü'
    }
    
    normalized = pinyin
    for old_char, new_char in char_replacements.items():
        normalized = normalized.replace(old_char, new_char)
    
    return normalized


def extract_pinyin(word, pairs_column):
    """
    Extrai o pinyin de uma palavra chinesa da coluna pairs.
    
    Args:
        word (str): Palavra chinesa
        pairs_column (str): Coluna pairs com formato ["palavra (pinyin): tradução"]
        
    Returns:
        str: Pinyin da palavra ou palavra original se não encontrado
    """
    import re
    
    # Encontra todas as palavras entre colchetes e aspas
    word_matches = re.findall(r'"([^"]+)"', pairs_column)
    
    for match in word_matches:
        # Extrai apenas a parte da palavra (antes do espaço e parênteses)
        word_part = match.split()[0] if match.split() else match
        if word_part == word:
            # Procura por pinyin entre parênteses
            pinyin_match = re.search(r'\(([^)]+)\)', match)
            if pinyin_match:
                return pinyin_match.group(1)
    
    return word  # Retorna a palavra original se não encontrar pinyin

def add_translation_text(frame, translation_text):
    """
    Adiciona texto de tradução na parte superior do frame.
    
    Args:
        frame: Frame do vídeo (numpy array)
        translation_text (str): Texto de tradução para adicionar
        
    Returns:
        Frame com texto sobreposto
    """
    try:
        # Configurações do texto - usando fonte mais robusta para caracteres especiais
        font = cv2.FONT_HERSHEY_DUPLEX
        font_scale = 0.8
        color = (255, 255, 255)  # Branco
        thickness = 2
        line_type = cv2.LINE_AA
        
        # Obtém dimensões do frame
        height, width = frame.shape[:2]
        
        # Processa o texto para melhor compatibilidade com caracteres especiais
        processed_text = translation_text.replace('♪', '').replace('<i>', '').replace('</i>', '').strip()
        
        # Converte caracteres problemáticos para versões compatíveis com OpenCV
        char_replacements = {
            'ã': 'a', 'á': 'a', 'à': 'a', 'â': 'a', 'ä': 'a',
            'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
            'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
            'ó': 'o', 'ò': 'o', 'ô': 'o', 'ö': 'o',
            'ú': 'u', 'ù': 'u', 'û': 'u', 'ü': 'u',
            'ç': 'c', 'ñ': 'n',
            'Ã': 'A', 'Á': 'A', 'À': 'A', 'Â': 'A', 'Ä': 'A',
            'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E',
            'Í': 'I', 'Ì': 'I', 'Î': 'I', 'Ï': 'I',
            'Ó': 'O', 'Ò': 'O', 'Ô': 'O', 'Ö': 'O',
            'Ú': 'U', 'Ù': 'U', 'Û': 'U', 'Ü': 'U',
            'Ç': 'C', 'Ñ': 'N'
        }
        
        # Aplica as substituições
        for old_char, new_char in char_replacements.items():
            processed_text = processed_text.replace(old_char, new_char)
        
        # Se o texto for muito longo, quebra em linhas
        max_chars_per_line = 60
        if len(processed_text) > max_chars_per_line:
            words = processed_text.split()
            lines = []
            current_line = ""
            
            for word in words:
                if len(current_line + " " + word) <= max_chars_per_line:
                    if current_line:
                        current_line += " " + word
                    else:
                        current_line = word
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
        else:
            lines = [processed_text]
        
        # Calcula a altura total do texto (múltiplas linhas)
        line_height = 30
        total_text_height = len(lines) * line_height
        
        # Posição inicial do texto (centralizado na parte superior)
        start_y = total_text_height + 20
        
        # Desenha cada linha do texto
        for i, line in enumerate(lines):
            # Calcula o tamanho da linha
            (text_width, text_height), baseline = cv2.getTextSize(line, font, font_scale, thickness)
            
            # Posição da linha (centralizada)
            x = (width - text_width) // 2
            y = start_y - (len(lines) - 1 - i) * line_height
            
            # Adiciona uma sombra preta atrás do texto para melhor legibilidade
            cv2.putText(frame, line, (x + 2, y + 2), font, font_scale, (0, 0, 0), thickness + 1, line_type)
            
            # Adiciona o texto branco
            cv2.putText(frame, line, (x, y), font, font_scale, color, thickness, line_type)
        
        return frame
        
    except Exception as e:
        print(f"Erro ao adicionar texto: {e}")
        return frame


def find_corresponding_video(base_file_path):
    """
    Encontra o arquivo de vídeo correspondente ao arquivo base.
    
    Args:
        base_file_path (Path): Caminho do arquivo *_base.txt
        
    Returns:
        Path: Caminho do arquivo de vídeo correspondente, ou None se não encontrado
    """
    # Remove o sufixo '_base.txt' para obter o nome base
    base_name = base_file_path.stem.replace('_base', '')
    parent_dir = base_file_path.parent
    
    # Procura por arquivos .mp4 que começam com o nome base
    # Exemplo: amor100_base.txt -> amor100*.mp4 (encontra amor100_chromecast_merged.mp4)
    video_matches = list(parent_dir.glob(f"{base_name}*.mp4"))
    
    if video_matches:
        # Retorna o primeiro match encontrado
        return video_matches[0]
    else:
        print(f"Vídeo correspondente não encontrado para: {base_name}")
        return None


def main():
    """
    Função principal do script.
    """
    # Caminho para o arquivo words.txt (mesmo diretório do script)
    script_dir = Path(__file__).parent
    words_file = script_dir / "words.txt"
    
    print("Word Fetcher - Lendo palavras do arquivo words.txt")
    print("=" * 50)
    
    # Lê as palavras do arquivo
    words = read_words_file(words_file)
    
    if not words:
        print("Nenhuma palavra encontrada no arquivo words.txt")
        return
    
    print(f"Encontradas {len(words)} palavras:")
    for word in words:
        print(f"  - {word}")
    
    print()
    
    # Processa cada arquivo *_base.txt
    base_files = list(script_dir.glob("*_base.txt"))
    print(f"Encontrados {len(base_files)} arquivos base para processar:")
    
    # Cria diretório para screenshots com data atual
    current_date = datetime.now().strftime("%Y%m%d")
    screenshots_dir = script_dir / "screenshots" / f"screenshot{current_date}"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    
    for base_file in base_files:
        print(f"\nProcessando arquivo: {base_file.name}")
        print("-" * 50)
        
        # Encontra o vídeo correspondente
        video_path = find_corresponding_video(base_file)
        if not video_path:
            print(f"Pulando {base_file.name} - vídeo não encontrado")
            continue
        
        print(f"Vídeo correspondente: {video_path.name}")
        
        try:
            with open(base_file, 'r', encoding='utf-8') as file:
                matching_lines = []
                
                for line_num, line in enumerate(file, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Divide a linha em colunas (separadas por \t)
                    columns = line.split('\t')
                    if len(columns) < 5:
                        continue
                    
                    # Coluna 4 contém os pares de palavras (formato JSON-like)
                    pairs_column = columns[4]
                    
                    # Verifica se alguma palavra da lista está presente na coluna de pares
                    # Busca exata da palavra (não parcial)
                    for word_index, word in enumerate(words):
                        # Extrai as palavras individuais da coluna pairs
                        # Formato: ["palavra1 (pinyin): tradução", "palavra2 (pinyin): tradução"]
                        import re
                        # Encontra todas as palavras entre colchetes e aspas
                        word_matches = re.findall(r'"([^"]+)"', pairs_column)
                        
                        # Verifica se a palavra exata está presente
                        word_found = False
                        for match in word_matches:
                            # Extrai apenas a parte da palavra (antes do espaço e parênteses)
                            word_part = match.split()[0] if match.split() else match
                            if word_part == word:
                                word_found = True
                                break
                        
                        if word_found:
                            # Extrai os tempos begin e end (colunas 1 e 2) e tradução (última coluna)
                            try:
                                begin_time = float(columns[1].replace('s', ''))
                                end_time = float(columns[2].replace('s', ''))
                                avg_time = (begin_time + end_time) / 2
                                
                                # Extrai a tradução da última coluna
                                translation = columns[-1] if len(columns) > 5 else "N/A"
                                
                                # Extrai o pinyin da palavra
                                pinyin = extract_pinyin(word, pairs_column)
                                
                                matching_lines.append({
                                    'line_num': line_num,
                                    'word': word,
                                    'pinyin': pinyin,
                                    'word_index': word_index,
                                    'begin': begin_time,
                                    'end': end_time,
                                    'avg_time': avg_time,
                                    'translation': translation,
                                    'line': line
                                })
                                break  # Evita duplicatas se a palavra aparecer múltiplas vezes na mesma linha
                            except (ValueError, IndexError):
                                continue
                
                # Exibe os resultados e captura screenshots
                if matching_lines:
                    print(f"Encontradas {len(matching_lines)} linhas com palavras da lista:")
                    
                    for i, match in enumerate(matching_lines):
                        print(f"  Linha {match['line_num']}: '{match['word']}' - "
                              f"Tempo médio: {match['avg_time']:.3f}s "
                              f"({match['begin']:.3f}s - {match['end']:.3f}s)")
                        print(f"    Texto: {match['line'][:100]}...")
                        print(f"    Tradução: {match['translation']}")
                        
                        # Captura screenshot
                        asset_name = base_file.stem.replace('_base', '')
                        # Inclui o pinyin no nome do arquivo (sem caracteres especiais)
                        pinyin_normalized = normalize_pinyin(match['pinyin'])
                        pinyin_clean = pinyin_normalized.replace(' ', '_').replace(':', '').replace('(', '').replace(')', '')
                        screenshot_name = f"{match['word_index'] + 1}_{pinyin_clean}_line{match['line_num']:04d}_{asset_name}.png"
                        screenshot_path = screenshots_dir / screenshot_name
                        
                        # Screenshot com tradução sobreposta
                        capture_video_frame(str(video_path), match['avg_time'], str(screenshot_path), match['translation'])
                        
                        print()
                else:
                    print("Nenhuma linha encontrada com as palavras da lista.")
                    
        except Exception as e:
            print(f"Erro ao processar arquivo {base_file.name}: {e}")
    print("=" * 50)
    print("Script concluído!")


if __name__ == "__main__":
    main()
