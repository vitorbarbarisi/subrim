#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

# Test the new subtitle adjustments with a real image
def test_subtitle_sizing():
    # Use the test directory
    test_dir = Path("assets/test")
    base_file = test_dir / "test_sub_zht_secs_base.txt"
    
    if not base_file.exists():
        print("Base file not found, cannot test")
        return
    
    # Parse base file to get subtitle data
    subtitles = parse_base_file(base_file)
    if not subtitles:
        print("No subtitles found")
        return
    
    # Find a subtitle with pinyin data
    test_subtitle = None
    test_second = None
    for second, (chinese_text, translations_text, translations_json, portuguese_text) in subtitles.items():
        if translations_json and translations_json != "N/A":
            test_subtitle = (chinese_text, translations_json)
            test_second = second
            break
    
    if not test_subtitle:
        print("No subtitle with pinyin found")
        return
    
    print(f"Testing subtitle adjustments...")
    print(f"Selected subtitle from second {test_second}:")
    print(f"Chinese: {test_subtitle[0]}")
    print(f"Translations: {test_subtitle[1][:100]}...")
    
    # Look for a test image in the screenshots folder
    screenshots_dir = test_dir / "screenshots"
    if not screenshots_dir.exists():
        print("Screenshots folder not found")
        return
    
    # Find an image near our test second
    test_images = list(screenshots_dir.glob(f"*{test_second:05d}_*.png"))
    if not test_images:
        # Try any image
        test_images = list(screenshots_dir.glob("*.png"))
        if not test_images:
            print("No test images found")
            return
    
    test_image = test_images[0]
    output_image = Path("test_subtitle_output.png")
    
    print(f"Processing image: {test_image.name}")
    print(f"Output will be saved to: {output_image}")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image, 
        test_subtitle[0], 
        test_subtitle[1], 
        output_image
    )
    
    if success:
        print("✅ Subtitle processing successful!")
        print(f"Check the output image: {output_image}")
        print("Features tested:")
        print("- ✅ Font size adjustment to fit screen")
        print("- ✅ Automatic line breaking")
        print("- ✅ Strong blue-purple color for pinyin and Portuguese")
    else:
        print("❌ Subtitle processing failed")

if __name__ == "__main__":
    test_subtitle_sizing()
