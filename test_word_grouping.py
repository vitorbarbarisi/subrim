#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

# Test word grouping functionality
def test_word_grouping():
    print("Testing word-based pinyin and Portuguese grouping...")
    print("=" * 60)
    
    # Use the test directory
    test_dir = Path("assets/test")
    base_file = test_dir / "test_sub_zht_secs_base.txt"
    
    if not base_file.exists():
        print("❌ Base file not found, trying death_becomes_her...")
        test_dir = Path("assets/death_becomes_her")
        base_file = test_dir / "Death_Becomes_Her_sub_zht_secs_base.txt"
        if not base_file.exists():
            print("❌ No base file found")
            return
    
    # Parse base file
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("❌ No subtitles found")
        return
    
    # Find a good test subtitle
    test_subtitle = None
    test_second = None
    for second, (chinese_text, translations_text, translations_json, portuguese_text) in subtitles.items():
        if translations_json and len(translations_json) > 50:  # Find one with good data
            test_subtitle = (chinese_text, translations_json)
            test_second = second
            print(f"✅ Found test subtitle at second {test_second}:")
            print(f"   Chinese: {chinese_text}")
            print(f"   Translations: {translations_json[:150]}...")
            break
    
    if not test_subtitle:
        print("❌ No suitable subtitle found")
        return
    
    # Look for a test image
    screenshots_dir = test_dir / "screenshots"  
    if screenshots_dir.exists():
        test_images = list(screenshots_dir.glob("*.png"))[:1]  # Just get one image
    else:
        # Try any other location
        test_images = list(Path("assets").rglob("*.png"))[:1]
    
    if not test_images:
        print("❌ No test images found")
        return
    
    test_image = test_images[0]
    output_image = Path("test_word_grouping_output.png")
    
    print(f"\n🎬 Processing image: {test_image.name}")
    print(f"   Expected result: Pinyin and Portuguese should appear once per WORD")
    print(f"   Example: 'gē wǔ' above '歌舞' with 'canto e dança' below")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image,
        test_subtitle[0],
        test_subtitle[1],
        output_image
    )
    
    if success:
        print(f"\n✅ Word grouping processing successful!")
        print(f"📸 Output saved to: {output_image}")
        print(f"📋 Check the image to verify:")
        print(f"   - Pinyin appears once per word (not per character)")
        print(f"   - Portuguese appears once per word (not per character)")
        print(f"   - Words are properly spaced")
    else:
        print("❌ Word grouping processing failed")

if __name__ == "__main__":
    test_word_grouping()
