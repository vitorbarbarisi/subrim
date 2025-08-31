#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

def test_light_purple_color():
    print("Testing light purple color for pinyin and Portuguese...")
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
    
    # Find a subtitle with translations
    test_subtitle = None
    test_second = None
    for second, (chinese_text, translations_text, translations_json, portuguese_text) in subtitles.items():
        if translations_json and len(translations_json) > 50:
            test_subtitle = (chinese_text, translations_json)
            test_second = second
            print(f"✅ Using test subtitle from second {test_second}:")
            print(f"   Chinese: {chinese_text}")
            break
    
    if not test_subtitle:
        print("❌ No suitable subtitle found")
        return
    
    # Look for a test image
    screenshots_dir = test_dir / "screenshots"
    if screenshots_dir.exists():
        test_images = list(screenshots_dir.glob("*.png"))[:1]
    else:
        test_images = list(Path("assets").rglob("*.png"))[:1]
    
    if not test_images:
        print("❌ No test images found")
        return
    
    test_image = test_images[0]
    output_image = Path("test_light_purple_output.png")
    
    print(f"\n🎨 Processing test image: {test_image.name}")
    print(f"   Expected result:")
    print(f"   🟣 Light purple color for pinyin and Portuguese (147, 112, 219)")
    print(f"   ⚫ Black borders around all text for visibility")
    print(f"   ⚪ White Chinese characters")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image,
        test_subtitle[0],
        test_subtitle[1],
        output_image
    )
    
    if success:
        print(f"\n✅ Light purple color test successful!")
        print(f"📸 Output saved to: {output_image}")
        print(f"\n📋 Verify the image has:")
        print(f"   🟣 Light purple pinyin text (medium slate blue)")
        print(f"   🟣 Light purple Portuguese text (medium slate blue)")
        print(f"   ⚫ Black borders around all text")
        print(f"   ⚪ White Chinese characters")
        print(f"   📏 Portuguese text wrapped within Chinese word width")
        print(f"\n🎨 Color reference: RGB(147, 112, 219) = #9370DB (Medium Slate Blue)")
        return True
    else:
        print("❌ Light purple color test failed")
        return False

if __name__ == "__main__":
    test_light_purple_color()
