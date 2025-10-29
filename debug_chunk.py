#!/usr/bin/env python3
"""
Debug script to test chunk processing
"""

import sys
from pathlib import Path
from process_chunks import parse_base_file, create_ffmpeg_drawtext_filters, get_video_info

def debug_chunk():
    # Test with first chunk
    chunk_path = Path("assets/onibus149_sub/Capítulo de 21⧸03⧸2025 [13448699]_chromecast_chunk_001.mp4")
    base_path = Path("assets/onibus149_sub/Capítulo de 21⧸03⧸2025 [13448699]_chromecast_chunk_001_base.txt")
    
    print("🔍 Debugging chunk processing...")
    print(f"📁 Chunk: {chunk_path}")
    print(f"📄 Base: {base_path}")
    
    # Check if files exist
    if not chunk_path.exists():
        print(f"❌ Chunk file not found: {chunk_path}")
        return
    if not base_path.exists():
        print(f"❌ Base file not found: {base_path}")
        return
    
    # Parse base file
    print("\n📖 Parsing base file...")
    subtitles = parse_base_file(base_path)
    print(f"📝 Found {len(subtitles)} subtitles")
    
    if not subtitles:
        print("❌ No subtitles found")
        return
    
    # Show first few subtitles
    print("\n📋 First 3 subtitles:")
    for i, (begin_time, subtitle_data) in enumerate(sorted(subtitles.items())[:3]):
        chinese_text, translations_text, translations_json, portuguese_text, duration = subtitle_data
        print(f"  {i+1}. {begin_time:.3f}s: '{chinese_text}' -> '{portuguese_text}'")
    
    # Get video info
    print("\n📐 Getting video info...")
    try:
        video_width, video_height, video_duration = get_video_info(chunk_path)
        print(f"📐 Dimensions: {video_width}x{video_height}")
        print(f"⏱️  Duration: {video_duration:.2f}s")
    except Exception as e:
        print(f"❌ Error getting video info: {e}")
        return
    
    # Create drawtext filters
    print("\n🎨 Creating drawtext filters...")
    try:
        drawtext_filters = create_ffmpeg_drawtext_filters(subtitles, video_width, video_height)
        print(f"🔧 Generated filters: {len(drawtext_filters.split(';')) if ';' in drawtext_filters else 1} parts")
        print(f"📏 Filter length: {len(drawtext_filters)} characters")
        
        # Show first part of filter
        if len(drawtext_filters) > 200:
            print(f"🔍 First 200 chars: {drawtext_filters[:200]}...")
        else:
            print(f"🔍 Full filter: {drawtext_filters}")
            
    except Exception as e:
        print(f"❌ Error creating drawtext filters: {e}")
        import traceback
        traceback.print_exc()
        return
    
    print("\n✅ Debug completed successfully!")

if __name__ == "__main__":
    debug_chunk()
