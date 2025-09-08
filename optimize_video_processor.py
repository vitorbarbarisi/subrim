#!/usr/bin/env python3
"""
Script para otimizar o video_subtitle_printer_all_in_one.py
Aplica duas otimizações:
1. Preset 'medium' -> 'fast' (velocidade)
2. Batch size 25 -> 10 (estabilidade)
"""

def optimize_video_processor():
    file_path = "video_subtitle_printer_all_in_one.py"
    
    print("🔧 Aplicando otimizações ao video_subtitle_printer_all_in_one.py...")
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Apply optimizations
    changes_made = []
    
    # 1. Change batch size from 25 to 10
    old_batch = "batch_size = 25  # Process 25 subtitles at a time to avoid extremely long filter chains"
    new_batch = "batch_size = 10  # Process 10 subtitles at a time to avoid extremely long filter chains (optimized)"
    if old_batch in content:
        content = content.replace(old_batch, new_batch)
        changes_made.append("✅ Batch size: 25 → 10 legendas por lote")
    
    # 2. Change preset from medium to fast (both occurrences)
    old_preset = "'-preset', 'medium',"
    new_preset = "'-preset', 'fast',    # Changed from 'medium' to 'fast' for better speed"
    
    # Count occurrences
    preset_count = content.count(old_preset)
    if preset_count > 0:
        content = content.replace(old_preset, new_preset)
        changes_made.append(f"✅ FFmpeg preset: 'medium' → 'fast' ({preset_count} locais)")
    
    # Write the updated file
    if changes_made:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("\n🎉 Otimizações aplicadas com sucesso!")
        for change in changes_made:
            print(f"   {change}")
        
        print(f"\n📊 Benefícios esperados:")
        print(f"   ⚡ Velocidade: ~30-50% mais rápido")
        print(f"   💾 Tamanho: Arquivos ligeiramente maiores (mas muito menos que CRF 18)")
        print(f"   🔧 Estabilidade: Menos filtros por comando, mais confiável")
        print(f"   📦 Lotes: 744 legendas = ~75 lotes de 10 cada (vs 30 lotes de 25)")
        
    else:
        print("⚠️  Nenhuma mudança necessária - arquivo já otimizado")

if __name__ == "__main__":
    optimize_video_processor()
