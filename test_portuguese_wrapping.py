#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

def test_portuguese_word_wrapping():
    print("Testing Portuguese word wrapping within Chinese word width...")
    print("=" * 65)
    
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
    
    # Find a subtitle with long Portuguese translations
    test_subtitle = None
    test_second = None
    for second, (chinese_text, translations_text, translations_json, portuguese_text) in subtitles.items():
        if translations_json and len(translations_json) > 100:  # Look for longer translations
            # Check if it has translations that might be long
            if "atua como protagonista" in translations_json or "simplesmente" in translations_json:
                test_subtitle = (chinese_text, translations_json)
                test_second = second
                print(f"✅ Found perfect test subtitle at second {test_second}:")
                print(f"   Chinese: {chinese_text}")
                print(f"   Contains long Portuguese translations that should wrap")
                break
    
    if not test_subtitle:
        # Fall back to any subtitle with translations
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
    output_image = Path("test_portuguese_wrapping_output.png")
    
    print(f"\n🎬 Processing test image: {test_image.name}")
    print(f"   Expected result:")
    print(f"   📝 Long Portuguese translations should break into multiple lines")
    print(f"   📏 Each Portuguese line should fit within its Chinese word width")
    print(f"   🎯 All lines should be centered under the Chinese word")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image,
        test_subtitle[0],
        test_subtitle[1],
        output_image
    )
    
    if success:
        print(f"\n✅ Portuguese word wrapping successful!")
        print(f"📸 Output saved to: {output_image}")
        print(f"\n📋 Check the image to verify:")
        print(f"   ✅ Long Portuguese words are broken into multiple lines")
        print(f"   ✅ Portuguese text doesn't extend beyond Chinese word width")
        print(f"   ✅ Multi-line Portuguese text is centered under each word") 
        print(f"   ✅ Text has proper spacing and black borders")
        print(f"\n💡 Example expected layout:")
        print(f"   zhǔ yǎn")
        print(f"   主演")
        print(f"   atua como")
        print(f"   protagonista")
        return True
    else:
        print("❌ Portuguese word wrapping processing failed")
        return False

if __name__ == "__main__":
    test_portuguese_word_wrapping()
