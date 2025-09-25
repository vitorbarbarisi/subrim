#!/usr/bin/env python3
"""
Script to fix markdown formatting in base files
Removes ```json and ``` markers from the pairs column
"""

import re
from pathlib import Path

def fix_markdown_in_base_file(file_path: Path) -> None:
    """Fix markdown formatting in a base file."""
    if not file_path.exists():
        print(f"Arquivo não encontrado: {file_path}")
        return
    
    print(f"Corrigindo arquivo: {file_path}")
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    fixed_lines = []
    changes_made = 0
    
    for line in lines:
        if not line.strip():
            fixed_lines.append(line)
            continue
            
        parts = line.split('\t')
        if len(parts) >= 5:  # Ensure we have at least 5 columns
            pairs_col = parts[4]  # Pairs column is the 5th column (index 4)
            
            # Check if the pairs column has markdown formatting
            if pairs_col.startswith('```json') and pairs_col.endswith('```'):
                # Remove ```json and ``` markers
                cleaned_pairs = pairs_col[7:-3].strip()
                parts[4] = cleaned_pairs
                changes_made += 1
            elif pairs_col.startswith('```') and pairs_col.endswith('```'):
                # Remove ``` markers
                cleaned_pairs = pairs_col[3:-3].strip()
                parts[4] = cleaned_pairs
                changes_made += 1
            
            fixed_lines.append('\t'.join(parts))
        else:
            fixed_lines.append(line)
    
    if changes_made > 0:
        # Write the fixed content back
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(fixed_lines))
        print(f"✅ Corrigidas {changes_made} linhas com formatação markdown")
    else:
        print("ℹ️  Nenhuma formatação markdown encontrada")

def main():
    """Main function to fix base files."""
    # Fix the specific file mentioned
    base_file = Path("assets/amor97/capítulo de 23⧸10⧸1995 [11667150].zht-br_secs_base.txt")
    fix_markdown_in_base_file(base_file)
    
    # Also check for other files that might have the same issue
    assets_dir = Path("assets")
    if assets_dir.exists():
        print("\n🔍 Verificando outros arquivos base...")
        for base_file in assets_dir.rglob("*_base.txt"):
            if base_file != base_file:  # Skip the one we already fixed
                fix_markdown_in_base_file(base_file)

if __name__ == "__main__":
    main()
