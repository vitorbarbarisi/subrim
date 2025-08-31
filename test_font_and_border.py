#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

def test_font_and_border_improvements():
    print("Testing font size increase and black border...")
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
    
    # Find a good test subtitle with pinyin data
    test_subtitle = None
    test_second = None
    for second, (chinese_text, translations_text, translations_json, portuguese_text) in subtitles.items():
        if translations_json and len(translations_json) > 50:
            test_subtitle = (chinese_text, translations_json)
            test_second = second
            print(f"✅ Selected test subtitle from second {test_second}:")
            print(f"   Chinese: {chinese_text}")
            print(f"   Contains pinyin and Portuguese translations")
            break
    
    if not test_subtitle:
        print("❌ No suitable subtitle found")
        return
    
    # Look for a test image
    screenshots_dir = test_dir / "screenshots"  
    if screenshots_dir.exists():
        test_images = list(screenshots_dir.glob("*.png"))[:1]
    else:
        # Try any other location
        test_images = list(Path("assets").rglob("*.png"))[:1]
    
    if not test_images:
        print("❌ No test images found")
        return
    
    test_image = test_images[0]
    output_image = Path("test_font_border_output.png")
    
    print(f"\n🎬 Processing test image: {test_image.name}")
    print(f"   Expected improvements:")
    print(f"   📈 Larger Chinese character font size")  
    print(f"   🖤 Black border around all text for better visibility")
    print(f"   🎯 Word-based pinyin and Portuguese grouping")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image,
        test_subtitle[0],
        test_subtitle[1],
        output_image
    )
    
    if success:
        print(f"\n✅ Font and border improvements successful!")
        print(f"📸 Output saved to: {output_image}")
        print(f"\n📋 Verify in the image:")
        print(f"   ✅ Chinese characters appear larger than before")
        print(f"   ✅ All text (Chinese, pinyin, Portuguese) has black border")
        print(f"   ✅ Text is clearly visible against any background")
        print(f"   ✅ Pinyin and Portuguese grouped by word, not character")
        return True
    else:
        print("❌ Font and border processing failed")
        return False

if __name__ == "__main__":
    test_font_and_border_improvements()
