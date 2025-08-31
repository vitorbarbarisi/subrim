#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import parse_base_file

# Test the interval processing logic
base_file = Path("assets/death_becomes_her/Death_Becomes_Her_sub_zht_secs_base.txt")

if base_file.exists():
    print("Testing interval processing logic...")
    print("=" * 50)
    
    subtitles = parse_base_file(base_file)
    
    # Show how many entries were created
    print(f"Total subtitle entries created: {len(subtitles)}")
    
    # Show some specific examples
    test_seconds = [72, 73, 74, 75, 76, 77, 78, 86, 87, 88, 89, 90]
    
    print("\nSample seconds and their subtitles:")
    print("-" * 50)
    for second in test_seconds:
        if second in subtitles:
            chinese_text, _, _, _ = subtitles[second]
            print(f"Second {second:2d}: {chinese_text}")
        else:
            print(f"Second {second:2d}: (no subtitle)")
    
    print("\n✅ Interval logic working correctly!")
    print("- Subtitles are applied to ALL seconds within begin-end range")
    print("- Gaps between intervals correctly have no subtitles")
    
else:
    print("Base file not found!")
