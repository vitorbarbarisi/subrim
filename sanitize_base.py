#!/usr/bin/env python3
"""
Sanitize Base - Limpa arquivos base.txt removendo erros e caracteres especiais

Usage: python3 sanitize_base.py <directory_name>
Example: python3 sanitize_base.py onibus133

O script:
1. Encontra o arquivo base.txt ou *_zht_secs_base.txt no diretório assets/<directory_name>
2. Remove linhas específicas que contenham erro de tradução
3. Remove caracteres especiais da coluna chinesa (zht)
4. Salva o arquivo modificado no mesmo local

Linhas removidas:
- "Infelizmente, não há uma frase em chinês fornecida para eu extrair e traduzir..."

Caracteres removidos da coluna chinesa:
- ♪ (notas musicais)
- … (reticências chinesas)
- 【】 (colchetes chineses)
- [] (colchetes simples)
- Caracteres alfanuméricos (A-Z, a-z, 0-9)
- Outros caracteres especiais problemáticos
"""

import sys
import argparse
import os
from pathlib import Path

# Frase específica que indica erro de tradução e deve ser removida (apenas a parte chinesa)
ERROR_TRANSLATION_TEXT = "♪	Infelizmente, não há uma frase em chinês fornecida para eu extrair e traduzir. Por favor, envie a frase em chinês tradicional para que eu possa ajudá-lo.	♪"


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
    print(f"🔍 Lendo arquivo: {base_file_path.name}")

    try:
        # Lê todas as linhas do arquivo
        with open(base_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        print(f"📊 Encontradas {len(lines)} linhas")

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

            # Verifica se a coluna de traduções contém exatamente a frase de erro de tradução
            if len(parts) >= 5 and parts[4].strip() == ERROR_TRANSLATION_TEXT.strip():
                print(f"   🗑️  Linha {line_num}: removida (erro de tradução)")
                removed_count += 1
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

            # Reconstrói a linha com o texto chinês limpo
            parts[3] = sanitized_chinese
            processed_lines.append('\t'.join(parts))

        # Salva o arquivo modificado
        print(f"💾 Salvando arquivo modificado...")
        with open(base_file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(processed_lines) + '\n')

        print(f"✅ Processamento concluído!")
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
        # Procura por arquivos *_zht_secs_base.txt
        for file_path in source_dir.glob('*_zht_secs_base.txt'):
            base_file = file_path
            break

    print("🧹 Sanitize Base - Limpeza de caracteres especiais")
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

    print(f"📄 Arquivo base encontrado: {base_file.name}")

    # Processa o arquivo
    if process_base_file(base_file):
        print("\n🎉 Sanitização concluída com sucesso!")
        return 0
    else:
        print("\n❌ Erro durante a sanitização")
        return 1


if __name__ == "__main__":
    sys.exit(main())
