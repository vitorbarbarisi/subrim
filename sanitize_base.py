#!/usr/bin/env python3
"""
Sanitize Base - Limpa arquivos base.txt removendo erros e caracteres especiais

Usage: python3 sanitize_base.py <directory_name>
Example: python3 sanitize_base.py onibus133

O script:
1. Verifica se a word-api está funcionando (se não estiver, encerra com erro)
2. Encontra o arquivo base.txt ou *_zht_secs_base.txt no diretório assets/<directory_name>
3. Remove linhas específicas que contenham erro de tradução
4. Remove caracteres especiais da coluna chinesa (zht)
5. Integra com word-api para filtrar palavras por confidence_level
6. Salva o arquivo modificado no mesmo local

Linhas removidas:
- "Infelizmente, não há uma frase em chinês fornecida para eu extrair e traduzir..."
- "A frase fornecida é muito curta e não contém palavras chinesas para extrair..."
- "A frase fornecida está vazia, portanto, não há palavras para extrair e traduzir."
- Linhas onde a coluna chinesa contém apenas "♪" (sem conteúdo chinês)

Caracteres removidos da coluna chinesa:
- ♪ (notas musicais)
- … (reticências chinesas)
- 【】 (colchetes chineses)
- [] (colchetes simples)
- Caracteres alfanuméricos (A-Z, a-z, 0-9)
- Outros caracteres especiais problemáticos

Integração com word-api:
- Para cada palavra em mandarim nos pares de tradução:
  - Faz GET para http://localhost:7998/word-api/{palavra}
  - Se confidence_level == 3: remove a palavra do array
  - Se não existir: faz POST para adicionar com confidence_level = 1
- Palavras com confidence_level != 3 são mantidas no arquivo
"""

import sys
import argparse
import os
import requests
import json
import re
from pathlib import Path

# Frases específicas que indicam erro de tradução e devem ser removidas
ERROR_TRANSLATION_TEXTS = [
    "Infelizmente, não há uma frase em chinês fornecida para eu extrair e traduzir. Por favor, envie a frase em chinês tradicional para que eu possa ajudá-lo.",
    "A frase fornecida é muito curta e não contém palavras chinesas para extrair. Por favor, forneça uma frase em chinês tradicional para que eu possa realizar a extração conforme solicitado.",
    "A frase fornecida está vazia, portanto, não há palavras para extrair e traduzir."
]

# URL da word-api localhost
WORD_API_BASE_URL = "http://localhost:7998/word-api"


def check_word_api_health() -> bool:
    """
    Verifica se a word-api está funcionando.
    
    Returns:
        True se a API está funcionando, False caso contrário
    """
    try:
        print("🔍 Verificando status da word-api...", flush=True)
        response = requests.get(f"{WORD_API_BASE_URL}/health", timeout=5)
        
        if response.status_code == 200:
            print("✅ Word-api está funcionando", flush=True)
            return True
        else:
            print(f"❌ Word-api retornou status {response.status_code}", flush=True)
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao conectar com word-api: {e}", flush=True)
        return False
    except Exception as e:
        print(f"❌ Erro inesperado ao verificar word-api: {e}", flush=True)
        return False


def get_word_from_api(word: str) -> dict:
    """
    Faz GET para a word-api para verificar se a palavra existe.
    
    Args:
        word: Palavra em mandarim para verificar
        
    Returns:
        dict: Resposta da API ou None se erro
    """
    url = f"{WORD_API_BASE_URL}/{word}"
    try:
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None  # Palavra não encontrada
        else:
            print(
                f"❌ ERRO hanzi-api [GET {url}] status {response.status_code}: "
                f"{response.text}",
                flush=True,
            )
            return None

    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO hanzi-api [GET {url}]: {e}", flush=True)
        return None


def post_word_to_api(word: str, pinyin: str, translation: str, confidence_level: int = 1) -> bool:
    """
    Faz POST para a word-api para adicionar uma nova palavra.
    
    Args:
        word: Palavra em mandarim
        pinyin: Pinyin da palavra
        translation: Tradução da palavra
        confidence_level: Nível de confiança (padrão: 1)
        
    Returns:
        bool: True se sucesso, False caso contrário
    """
    url = f"{WORD_API_BASE_URL}/"
    try:
        data = {
            "word": word,
            "pinyin": pinyin,
            "translation": translation,
            "confidence_level": confidence_level
        }

        response = requests.post(url, json=data, timeout=5)

        if response.status_code in [200, 201]:
            print(f"   ✅ Palavra '{word}' adicionada à word-api")
            return True
        else:
            print(
                f"❌ ERRO hanzi-api [POST {url}] palavra '{word}' "
                f"status {response.status_code}: {response.text}",
                flush=True,
            )
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO hanzi-api [POST {url}] palavra '{word}': {e}", flush=True)
        return False


def put_word_translation(word: str, translation: str) -> bool:
    """
    Faz PUT para a word-api para adicionar uma nova tradução a uma palavra existente.

    Args:
        word: Palavra em mandarim (deve existir na word-api)
        translation: Tradução a ser adicionada

    Returns:
        bool: True se sucesso, False caso contrário
    """
    url = f"{WORD_API_BASE_URL}/{word}/translations"
    try:
        response = requests.put(url, json={"translation": translation}, timeout=5)

        if response.status_code in [200, 201]:
            print(f"   ➕ Tradução '{translation}' adicionada à palavra '{word}'")
            return True
        elif response.status_code == 404:
            print(
                f"❌ ERRO hanzi-api [PUT {url}] palavra '{word}' não encontrada (404): "
                f"{response.text}",
                flush=True,
            )
            return False
        else:
            print(
                f"❌ ERRO hanzi-api [PUT {url}] palavra '{word}' "
                f"status {response.status_code}: {response.text}",
                flush=True,
            )
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ ERRO hanzi-api [PUT {url}] palavra '{word}': {e}", flush=True)
        return False


def extract_existing_translations(api_response: dict) -> list:
    """
    Extrai as traduções existentes da resposta do GET da word-api.

    Lida com diferentes formatos possíveis: campo 'translations' (lista de
    strings ou de dicts com chave 'translation') e campo 'translation' singular.

    Args:
        api_response: Resposta JSON do GET da word-api

    Returns:
        list: Lista de traduções (strings) já cadastradas para a palavra
    """
    translations = []

    raw = api_response.get("translations")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                translations.append(item)
            elif isinstance(item, dict):
                value = item.get("translation")
                if isinstance(value, str):
                    translations.append(value)

    singular = api_response.get("translation")
    if isinstance(singular, str):
        translations.append(singular)

    return translations


def extract_pairs_from_translation(translation_text: str) -> list:
    """
    Extrai pares de palavras da coluna de tradução.
    
    Args:
        translation_text: Texto da coluna de tradução
        
    Returns:
        list: Lista de dicionários com word, pinyin, translation
    """
    pairs = []
    
    if not translation_text or translation_text.strip() == "":
        return pairs
    
    try:
        # Parse do JSON-like array
        import ast
        translation_list = ast.literal_eval(translation_text)
        
        if isinstance(translation_list, list):
            for item in translation_list:
                if not isinstance(item, str):
                    continue
                item = item.strip()
                if not item:
                    continue

                if ":" in item:
                    # Formato: "palavra (pinyin): tradução"
                    parts = item.split(":", 1)
                    word_part = parts[0].strip()
                    translation = parts[1].strip()
                else:
                    # Entrada só com a palavra (ex.: palavra dominada — sem pinyin/tradução).
                    # Mantemos para que continue buscável e renderize só o caractere.
                    word_part = item
                    translation = ""

                # Extrai palavra e pinyin
                pinyin_match = re.search(r'\(([^)]+)\)', word_part)
                if pinyin_match:
                    pinyin = pinyin_match.group(1)
                    word = word_part.replace(f"({pinyin})", "").strip()
                else:
                    word = word_part
                    pinyin = ""

                pairs.append({
                    "word": word,
                    "pinyin": pinyin,
                    "translation": translation,
                })
    except Exception as e:
        print(f"   ⚠️  Erro ao extrair pares de '{translation_text}': {e}")
    
    return pairs


def process_word_api_integration(pairs: list) -> list:
    """
    Processa integração com word-api para cada palavra nos pares.
    
    Args:
        pairs: Lista de pares de palavras
        
    Returns:
        list: Lista de pares filtrada (palavras com confidence_level == 3 removidas)
    """
    filtered_pairs = []
    
    for pair in pairs:
        word = pair["word"]
        pinyin = pair["pinyin"]
        translation = pair["translation"]
        
        # Pula palavras vazias ou inválidas
        if not word or word.strip() == "":
            continue
        
        print(f"   🔍 Verificando palavra: '{word}'")
        
        # Consulta a word-api
        api_response = get_word_from_api(word)
        
        if api_response is None:
            # Palavra não encontrada, adiciona à word-api
            print(f"   📝 Palavra '{word}' não encontrada, adicionando...")
            post_word_to_api(word, pinyin, translation, confidence_level=1)
            filtered_pairs.append(pair)
        else:
            # Palavra encontrada, verifica confidence_level
            confidence_level = api_response.get("confidence_level", 0)
            
            # Garante que confidence_level seja int (pode vir como string da API)
            try:
                confidence_level = int(confidence_level)
            except (ValueError, TypeError):
                confidence_level = 0
            
            if confidence_level == 3:
                print(f"   ⭐ Palavra '{word}' dominada (confidence_level == 3) — "
                      "mantida no array sem pinyin/tradução")
                # Mantém a palavra (buscável e posicionada na queima), mas sem
                # pinyin nem tradução — o aprendiz já domina, então não recebe ajuda.
                filtered_pairs.append({"word": word, "pinyin": "", "translation": ""})
            else:
                print(f"   ✅ Palavra '{word}' mantida (confidence_level == {confidence_level})")

                # Se a tradução da LLM não estiver entre as traduções já
                # cadastradas, adiciona via PUT.
                existing = extract_existing_translations(api_response)
                normalized = {t.strip().lower() for t in existing}
                if translation.strip().lower() not in normalized:
                    put_word_translation(word, translation)

                filtered_pairs.append(pair)
    
    return filtered_pairs


def sanitize_chinese_text(text: str) -> str:
    """
    Remove caracteres especiais do texto chinês.

    Args:
        text: Texto chinês a ser limpo

    Returns:
        Texto chinês sem caracteres especiais
    """
    if not text:
        return text

    # Caracteres a serem removidos
    chars_to_remove = ['【', '】', '[', ']', '{', '\1c&HFF8000&', '}',
        'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
        'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
        '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
        'Á', 'É', 'Í', 'Ó', 'Ú', 'Ã', 'Õ', 'Ç', 'À', 'È', 'Ì', 'Ò', 'Ù', 'Â', 'Ê', 'Î', 'Ô', 'Û', 'Ã', 'Õ', 'Ç', 'À', 'È', 'Ì', 'Ò', 'Ù', 'Â', 'Ê', 'Î', 'Ô', 'Û',
        'á', 'é', 'í', 'ó', 'ú', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û',
        'â', 'ê', 'î', 'ô', 'û', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û',
        'â', 'ê', 'î', 'ô', 'û', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û', 'ã', 'õ', 'ç', 'à', 'è', 'ì', 'ò', 'ù', 'â', 'ê', 'î', 'ô', 'û',
    ]

    # Remove os caracteres especiais
    for char in chars_to_remove:
        text = text.replace(char, '')

    return text.strip()


def process_base_file(base_file_path: Path) -> bool:
    """
    Processa o arquivo base.txt removendo caracteres especiais da coluna chinesa.

    Args:
        base_file_path: Caminho para o arquivo base.txt

    Returns:
        True se processamento bem-sucedido
    """
    print(f"🔍 Lendo arquivo: {base_file_path.name}", flush=True)

    try:
        # Lê todas as linhas do arquivo
        with open(base_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"📊 Encontradas {len(lines)} linhas", flush=True)

        # Processa cada linha
        processed_lines = []
        modified_count = 0
        removed_count = 0

        for line_num, line in enumerate(lines, 1):
            line = line.rstrip('\n\r')  # Remove quebras de linha

            if not line.strip():
                processed_lines.append(line)
                continue

            # Divide a linha por tabs
            parts = line.split('\t')

            # Verifica se a coluna chinesa (índice 2) contém apenas "♪"
            if len(parts) >= 3 and parts[2].strip() == "♪":
                print(f"   🗑️  Linha {line_num}: removida (coluna chinesa vazia - apenas ♪)")
                removed_count += 1
                continue
            
            # Verifica se a coluna de traduções (índice 4) contém alguma das frases de erro de tradução
            if len(parts) >= 5:
                translation_text = parts[4].strip()
                found_error = False
                for error_text in ERROR_TRANSLATION_TEXTS:
                    if translation_text == error_text.strip():
                        print(f"   🗑️  Linha {line_num}: removida (erro de tradução)")
                        removed_count += 1
                        found_error = True
                        break
                
                if found_error:
                    continue

            if len(parts) < 4:
                processed_lines.append(line)
                continue

            # A coluna chinesa é a 4ª (índice 3)
            original_chinese = parts[3]
            sanitized_chinese = sanitize_chinese_text(original_chinese)

            # Verifica se houve modificação
            if sanitized_chinese != original_chinese:
                print(f"   🔧 Linha {line_num}: '{original_chinese}' → '{sanitized_chinese}'")
                modified_count += 1

            # Processa integração com word-api se houver coluna de traduções
            if len(parts) >= 5:
                translation_text = parts[4].strip()
                if translation_text and translation_text not in ERROR_TRANSLATION_TEXTS:
                    print(f"   🔗 Processando word-api para linha {line_num}...")
                    
                    # Extrai pares de palavras da coluna de traduções
                    pairs = extract_pairs_from_translation(translation_text)
                    
                    if pairs:
                        # Processa integração com word-api
                        filtered_pairs = process_word_api_integration(pairs)
                        
                        # Reconstrói a coluna de traduções com pares filtrados
                        if filtered_pairs:
                            new_translation_parts = []
                            for pair in filtered_pairs:
                                if pair["pinyin"]:
                                    new_translation_parts.append(f'"{pair["word"]} ({pair["pinyin"]}): {pair["translation"]}"')
                                elif pair["translation"]:
                                    new_translation_parts.append(f'"{pair["word"]}: {pair["translation"]}"')
                                else:
                                    # Palavra dominada: só o caractere (sem ':' para não
                                    # grudar no parser; renderiza sem pinyin/tradução).
                                    new_translation_parts.append(f'"{pair["word"]}"')
                            
                            new_translation_text = "[" + ", ".join(new_translation_parts) + "]"
                            parts[4] = new_translation_text
                            
                            if new_translation_text != translation_text:
                                print(f"   🔄 Linha {line_num}: traduções filtradas pela word-api")
                                modified_count += 1
                        else:
                            # Todos os pares foram removidos, marca para remoção
                            print(f"   🗑️  Linha {line_num}: removida (todos os pares filtrados pela word-api)")
                            removed_count += 1
                            continue

            # Reconstrói a linha com o texto chinês limpo
            parts[3] = sanitized_chinese
            processed_lines.append('\t'.join(parts))

        # Salva o arquivo modificado
        print(f"💾 Salvando arquivo modificado...", flush=True)
        with open(base_file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(processed_lines) + '\n')

        print(f"✅ Processamento concluído!", flush=True)
        print(f"   📝 {modified_count} linhas modificadas")
        print(f"   🗑️  {removed_count} linhas removidas")
        print(f"   💾 Arquivo salvo: {base_file_path}")

        return True

    except Exception as e:
        print(f"❌ Erro ao processar arquivo: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Remove caracteres especiais da coluna chinesa do arquivo base.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 sanitize_base.py onibus133    # Processa assets/onibus133/base.txt

Funcionamento:
  - Encontra automaticamente o arquivo base.txt no diretório
  - Remove linhas com erro de tradução específico
  - Remove caracteres especiais como ♪, …, 【】, etc.
  - Remove também caracteres alfanuméricos (A-Z, a-z, 0-9)
  - Salva o arquivo modificado no mesmo local
  - Mostra quais linhas foram modificadas ou removidas
        """
    )

    parser.add_argument('directory', help='Nome do diretório (sem _sub)')

    args = parser.parse_args()

    # Constrói o caminho para o diretório
    source_dir = Path('assets') / args.directory

    # Procura pelo arquivo base (pode ser base.txt ou *_zht_secs_base.txt)
    base_file = None

    # Primeiro tenta encontrar base.txt
    if (source_dir / 'base.txt').exists():
        base_file = source_dir / 'base.txt'
    else:
        # Procura por arquivos *_zht*_secs_base.txt (com hífen ou underscore)
        for file_path in source_dir.glob('*zht*_secs_base.txt'):
            base_file = file_path
            break

    print("🧹 Sanitize Base - Limpeza de caracteres especiais", flush=True)
    print("=" * 55)
    print(f"📁 Diretório: {source_dir}")

    # Verifica se o diretório existe
    if not source_dir.exists():
        print(f"❌ Erro: Diretório {source_dir} não encontrado")
        return 1

    # Verifica se encontrou algum arquivo base
    if not base_file or not base_file.exists():
        print(f"❌ Erro: Arquivo base.txt ou *_zht_secs_base.txt não encontrado em {source_dir}")
        return 1

    print(f"📄 Arquivo base encontrado: {base_file.name}", flush=True)

    # Verifica se a word-api está funcionando antes de processar
    if not check_word_api_health():
        print("\n❌ Word-api está indisponível. Encerrando para evitar processamento com API down.")
        return 1

    # Processa o arquivo
    if process_base_file(base_file):
        print("\n🎉 Sanitização concluída com sucesso!")
        return 0
    else:
        print("\n❌ Erro durante a sanitização")
        return 1


if __name__ == "__main__":
    sys.exit(main())
