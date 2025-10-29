#!/usr/bin/env python3
"""
Test simple chunk processing with minimal filters
"""

import subprocess
from pathlib import Path

def test_simple_ffmpeg():
    chunk_path = Path("assets/onibus149_sub/Capítulo de 21⧸03⧸2025 [13448699]_chromecast_chunk_001.mp4")
    output_path = Path("test_output.mp4")
    
    print("🧪 Testing simple FFmpeg command...")
    
    # Simple FFmpeg command with just one drawtext filter
    cmd = [
        'ffmpeg',
        '-i', str(chunk_path),
        '-vf', 'drawtext=text="Test":x=100:y=100:fontsize=50:fontcolor=white',
        '-c:v', 'libx264',
        '-c:a', 'copy',
        '-t', '5',  # Only process 5 seconds
        '-y',
        str(output_path)
    ]
    
    print(f"🔧 Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(f"✅ FFmpeg exit code: {result.returncode}")
        if result.stderr:
            print(f"📝 stderr: {result.stderr[:500]}...")
        if result.stdout:
            print(f"📝 stdout: {result.stdout[:500]}...")
        
        if output_path.exists():
            print(f"✅ Output file created: {output_path}")
            output_path.unlink()  # Clean up
        else:
            print("❌ No output file created")
            
    except subprocess.TimeoutExpired:
        print("⏰ FFmpeg timed out after 30 seconds")
    except Exception as e:
        print(f"❌ Error running FFmpeg: {e}")

if __name__ == "__main__":
    test_simple_ffmpeg()
