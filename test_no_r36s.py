#!/usr/bin/env python3

from pathlib import Path
from subtitle_printer_all_in_one import add_pinyin_subtitle_to_image, parse_base_file

def test_no_r36s_resizing():
    print("Testing subtitle script without R36S resizing...")
    print("=" * 55)
    
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
    output_image = Path("test_no_r36s_output.png")
    
    print(f"\n🖼️  Processing test image: {test_image.name}")
    
    # Get original image size for comparison
    from PIL import Image
    with Image.open(test_image) as img:
        original_size = img.size
        print(f"   📏 Original image size: {original_size[0]}x{original_size[1]}")
    
    print(f"   Expected result:")
    print(f"   📏 Output should maintain original image dimensions")
    print(f"   🚫 No R36S resizing (640x480)")
    print(f"   🟣 Light purple pinyin and Portuguese text")
    print(f"   📝 Subtitles applied directly to original image")
    
    # Test the subtitle function
    success = add_pinyin_subtitle_to_image(
        test_image,
        test_subtitle[0],
        test_subtitle[1],
        output_image
    )
    
    if success:
        # Check output size
        with Image.open(output_image) as output_img:
            output_size = output_img.size
            
        print(f"\n✅ No R36S resizing test successful!")
        print(f"📸 Output saved to: {output_image}")
        print(f"📏 Original size: {original_size[0]}x{original_size[1]}")
        print(f"📏 Output size:   {output_size[0]}x{output_size[1]}")
        
        if original_size == output_size:
            print(f"✅ Perfect! Image dimensions preserved (no R36S resizing)")
        else:
            print(f"⚠️  Warning: Image dimensions changed")
            
        print(f"\n📋 Verify the image:")
        print(f"   ✅ Original image dimensions maintained")
        print(f"   🟣 Light purple pinyin and Portuguese text") 
        print(f"   📏 Portuguese text wrapped within Chinese word width")
        print(f"   ⚫ Black borders around all text")
        
        return True
    else:
        print("❌ No R36S resizing test failed")
        return False

if __name__ == "__main__":
    test_no_r36s_resizing()
