#!/usr/bin/env python3
"""
Video Screenshot Extractor with Subtitles
Extracts 7 screenshots per second from MP4 videos in the assets folder and adds subtitles from base.txt.

Usage: python3 video_screenshoter_r36s.py <folder_name>
Example: python3 video_screenshoter_r36s.py test

Output format: {segundo_em_5_digitos}_{frame}.png (with subtitles added)
"""

import os
import sys
import cv2
import argparse
import re
from pathlib import Path
from typing import Dict, Tuple, List, Optional

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ Erro: PIL (Pillow) não encontrado. Instale com: pip install Pillow")
    sys.exit(1)

# Import sanitize functions
try:
    from sanitize_base import process_base_file, check_word_api_health
    SANITIZE_AVAILABLE = True
except ImportError:
    SANITIZE_AVAILABLE = False

# R36S resolution
R36S_WIDTH = 640
R36S_HEIGHT = 480


def find_mp4_file(assets_folder):
    """Find the first MP4 file in the specified assets folder."""
    mp4_files = list(assets_folder.glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError(f"No MP4 file found in {assets_folder}")
    
    if len(mp4_files) > 1:
        print(f"Warning: Multiple MP4 files found. Using: {mp4_files[0].name}")
    
    return mp4_files[0]


def find_base_file(assets_folder):
    """Find the base.txt file in the specified assets folder."""
    base_files = list(assets_folder.glob("*base.txt"))
    if not base_files:
        return None
    
    if len(base_files) > 1:
        print(f"Warning: Multiple base.txt files found. Using: {base_files[0].name}")
    
    return base_files[0]


def get_chinese_font_path() -> str:
    """Find the best available Chinese font."""
    chinese_fonts = [
        '/System/Library/Fonts/STHeiti Medium.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    
    for font_path in chinese_fonts:
        if Path(font_path).exists():
            return font_path
    
    return 'arial'  # Fallback


def get_latin_font_path() -> str:
    """Find the best available Latin font."""
    latin_fonts = [
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        '/System/Library/Fonts/ArialHB.ttc',
        '/System/Library/Fonts/HelveticaNeue.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    
    for font_path in latin_fonts:
        if Path(font_path).exists():
            return font_path
    
    return 'arial'  # Fallback


def parse_pinyin_translations(translation_list_str: str) -> List[Tuple[str, str, str]]:
    """
    Parse the translation list string to extract Chinese characters, pinyin, and Portuguese translations.
    
    Args:
        translation_list_str: String like '["三 (sān): três", "號 (hào): número", "碼頭 (mǎ tóu): cais"]'
    
    Returns:
        List of tuples (chinese_chars, pinyin, portuguese_translation)
    """
    try:
        translation_list_str = translation_list_str.strip()
        if not translation_list_str.startswith('[') or not translation_list_str.endswith(']'):
            return []
        
        content = translation_list_str[1:-1]  # Remove [ and ]
        items = re.findall(r'"([^"]*)"', content)
        
        result = []
        for item in items:
            match = re.match(r'^([^\s\(]+)\s*\(([^)]+)\)\s*:\s*(.+)$', item)
            if match:
                chinese_chars = match.group(1).strip()
                pinyin = match.group(2).strip()
                portuguese = match.group(3).strip()
                result.append((chinese_chars, pinyin, portuguese))
            else:
                chinese_match = re.match(r'^([^\s\(]+)', item)
                if chinese_match:
                    chinese_chars = chinese_match.group(1)
                    result.append((chinese_chars, "", ""))
        
        return result
    except Exception as e:
        print(f"Erro ao fazer parsing da lista de traduções: {e}")
        return []


def parse_base_file(base_file_path: Path) -> Dict[int, Tuple[str, str, str]]:
    """
    Parse the base.txt file and return a mapping of second -> (chinese_text, translations_json, portuguese_text).
    
    Returns:
        Dict mapping second (as int) to tuple of (chinese_text, translations_json, portuguese_text)
    """
    subtitles = {}
    
    try:
        with open(base_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('\t')
                if len(parts) < 4:
                    continue
                
                # Detect format based on number of columns
                is_new_format = len(parts) >= 6
                
                # Extract begin timestamp (second column)
                begin_timestamp_str = parts[1].strip()
                begin_match = re.match(r'([\d.]+)s?', begin_timestamp_str)
                if not begin_match:
                    continue
                
                begin_seconds = float(begin_match.group(1))
                second = int(begin_seconds) + 1  # Convert to 1-based second number
                
                # Extract Chinese subtitle - column position depends on format
                if is_new_format:
                    chinese_text = parts[3].strip()
                    translations_text = parts[4].strip()
                    portuguese_text = parts[5].strip() if len(parts) >= 6 else ""
                else:
                    chinese_text = parts[2].strip()
                    translations_text = parts[3].strip()
                    portuguese_text = parts[4].strip() if len(parts) >= 5 else ""
                
                # Remove parentheses if present
                chinese_text = re.sub(r'^（(.*)）$', r'\1', chinese_text)
                
                # Clean Portuguese text
                if portuguese_text == 'N/A':
                    portuguese_text = ""
                
                if chinese_text and chinese_text != 'N/A':
                    subtitles[second] = (chinese_text, translations_text, portuguese_text)
    
    except Exception as e:
        print(f"Erro ao ler arquivo base {base_file_path}: {e}")
    
    return subtitles


def resize_image_for_r36s(img: Image.Image) -> Image.Image:
    """
    Resize image to R36S compatible resolution (640x480) while maintaining aspect ratio.
    Uses letterboxing (black bars) when needed to preserve original proportions.
    """
    target_width = R36S_WIDTH
    target_height = R36S_HEIGHT
    
    original_width, original_height = img.size
    original_aspect = original_width / original_height
    target_aspect = target_width / target_height
    
    if original_aspect > target_aspect:
        new_width = target_width
        new_height = int(target_width / original_aspect)
    else:
        new_height = target_height
        new_width = int(target_height * original_aspect)
    
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    final_img = Image.new('RGB', (target_width, target_height), (0, 0, 0))
    
    paste_x = (target_width - new_width) // 2
    paste_y = (target_height - new_height) // 2
    final_img.paste(resized_img, (paste_x, paste_y))
    
    return final_img


def wrap_portuguese_to_width(portuguese_text: str, font, max_width: int) -> List[str]:
    """Break Portuguese text into multiple lines to fit within max_width."""
    if not portuguese_text:
        return []
    
    words = portuguese_text.split()
    if not words:
        return [portuguese_text]
    
    lines = []
    current_line = []
    current_width = 0
    
    for word in words:
        word_width = font.getlength(word + ' ')
        
        if current_width + word_width <= max_width or not current_line:
            current_line.append(word)
            current_width += word_width
        else:
            lines.append(' '.join(current_line))
            current_line = [word]
            current_width = font.getlength(word + ' ')
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines


def split_chinese_into_lines(display_items: List[Tuple[str, str, str]], max_chars_per_line: int = 12) -> List[List[Tuple[str, str, str]]]:
    """
    Split Chinese display items into at most 2 lines based on character count.
    
    Args:
        display_items: List of (chinese_word, pinyin, portuguese) tuples
        max_chars_per_line: Maximum characters per line (default: 12)
    
    Returns:
        List of lines, each containing a list of display items
    """
    if not display_items:
        return []
    
    # Count total characters
    total_chars = sum(len(item[0]) for item in display_items)
    
    # If fits in one line, return as single line
    if total_chars <= max_chars_per_line:
        return [display_items]
    
    # Split into 2 lines - try to balance character count
    line1 = []
    line1_chars = 0
    target_chars = total_chars // 2
    
    for item in display_items:
        item_chars = len(item[0])
        # Add to line1 if it doesn't exceed target too much, or if line1 is empty
        if line1_chars + item_chars <= target_chars + 2 or not line1:
            line1.append(item)
            line1_chars += item_chars
        else:
            # Remaining items go to line2
            break
    
    line2 = display_items[len(line1):]
    
    return [line1, line2] if line2 else [line1]


def add_subtitles_to_frame(image_path: Path, chinese_text: str, translations_json: str, portuguese_text: str) -> bool:
    """
    Add subtitles to a frame image.
    
    Args:
        image_path: Path to the frame image
        chinese_text: Chinese subtitle text
        translations_json: JSON string with word-by-word translations
        portuguese_text: Portuguese translation text
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Open and resize image
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            new_img = resize_image_for_r36s(img)
            width, height = new_img.size
            draw = ImageDraw.Draw(new_img)
            
            # Get fonts
            chinese_font_path = get_chinese_font_path()
            latin_font_path = get_latin_font_path()
            
            # Font sizes for R36S (640x480)
            base_chinese_font_size = 36
            base_pinyin_font_size = int(base_chinese_font_size * 0.65)
            base_portuguese_font_size = int(base_chinese_font_size * 0.45)
            
            try:
                chinese_font = ImageFont.truetype(chinese_font_path, base_chinese_font_size)
                pinyin_font = ImageFont.truetype(chinese_font_path, base_pinyin_font_size)
                portuguese_font = ImageFont.truetype(latin_font_path, base_portuguese_font_size)
            except Exception as e:
                print(f"   ⚠️  Erro ao carregar fontes: {e}, usando fontes padrão")
                chinese_font = ImageFont.load_default()
                pinyin_font = ImageFont.load_default()
                portuguese_font = ImageFont.load_default()
            
            # Parse translations
            word_data = parse_pinyin_translations(translations_json) if translations_json else []
            
            # Clean Chinese text
            clean_chinese = chinese_text.replace(' ', '').replace('　', '').replace('（', '').replace('）', '').replace('.', '').replace('《', '').replace('》', '').replace('"', '').replace('"', '')
            
            # Group characters into words
            display_items = []
            remaining_text = clean_chinese
            
            while remaining_text:
                found_word = False
                for chinese_word, word_pinyin, word_portuguese in sorted(word_data, key=lambda x: len(x[0]), reverse=True):
                    if remaining_text.startswith(chinese_word):
                        display_items.append((chinese_word, word_pinyin, word_portuguese))
                        remaining_text = remaining_text[len(chinese_word):]
                        found_word = True
                        break
                if not found_word:
                    char = remaining_text[0]
                    display_items.append((char, "", ""))
                    remaining_text = remaining_text[1:]
            
            if not display_items:
                # No Chinese text to display, just save the resized image
                new_img.save(image_path, 'PNG')
                return True
            
            # Split Chinese into lines (max 2 lines, ~12 chars per line)
            chinese_lines = split_chinese_into_lines(display_items, max_chars_per_line=12)
            num_chinese_lines = len(chinese_lines)
            
            # Calculate spacing and positioning
            vertical_spacing = 12  # Increased from 8 for better readability
            bottom_margin = 30
            available_width = width - 40  # 20px padding on each side
            
            # Calculate word widths for each line
            chinese_char_width = int(base_chinese_font_size * 0.95)
            pinyin_char_width = int(base_pinyin_font_size * 0.65)
            min_word_spacing = 60
            
            all_line_widths = []
            all_word_widths_per_line = []
            max_line_width = 0
            
            for line_items in chinese_lines:
                word_widths = []
                total_line_width = 0
                
                for chinese_word, word_pinyin, word_portuguese in line_items:
                    chinese_word_width = len(chinese_word) * chinese_char_width
                    pinyin_width = len(word_pinyin) * pinyin_char_width if word_pinyin else 0
                    base_word_width = max(chinese_word_width, pinyin_width, min_word_spacing)
                    safety_padding = max(15, int(base_word_width * 0.10))
                    word_width = base_word_width + safety_padding
                    word_widths.append(word_width)
                    total_line_width += word_width
                
                # Scale down if too wide
                if total_line_width > available_width:
                    scale_factor = available_width / total_line_width
                    min_word_width = 40
                    word_widths = [max(min_word_width, int(w * scale_factor)) for w in word_widths]
                    total_line_width = sum(word_widths)
                
                all_line_widths.append(total_line_width)
                all_word_widths_per_line.append(word_widths)
                max_line_width = max(max_line_width, total_line_width)
            
            # Calculate Y positions from bottom
            # Height calculation: pinyin + spacing + chinese (1 or 2 lines) + spacing + portuguese
            chinese_line_height = base_chinese_font_size + vertical_spacing + base_pinyin_font_size
            chinese_total_height = chinese_line_height * num_chinese_lines + (vertical_spacing * (num_chinese_lines - 1))
            # Portuguese height: when 2 lines, both lines have portuguese, so we need space for both
            portuguese_extra_height = base_portuguese_font_size * 2
            if num_chinese_lines == 2:
                # For 2 lines: need space for portuguese of both lines
                # Line 1 portuguese is between the two chinese lines
                # Line 2 portuguese is at the bottom
                total_subtitle_height = base_pinyin_font_size + vertical_spacing + chinese_total_height + (vertical_spacing * 2) + (portuguese_extra_height * 2)
            else:
                total_subtitle_height = base_pinyin_font_size + vertical_spacing + chinese_total_height + vertical_spacing + portuguese_extra_height
            
            portuguese_y = height - bottom_margin - portuguese_extra_height - (base_portuguese_font_size // 2)
            chinese_bottom_y = portuguese_y - vertical_spacing - base_chinese_font_size
            
            # Calculate background box dimensions
            bg_width = max_line_width + 40  # Add padding
            bg_height = total_subtitle_height + 20  # Add padding
            bg_x = (width - bg_width) // 2
            bg_y = height - bottom_margin - bg_height
            
            # Draw semi-transparent background box
            # Create a temporary image with alpha channel for the box
            new_img_rgba = new_img.convert('RGBA')
            box_overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            box_draw = ImageDraw.Draw(box_overlay)
            # Draw semi-transparent black box (50% opacity = 128/255)
            box_draw.rectangle([bg_x, bg_y, bg_x + bg_width, bg_y + bg_height], fill=(0, 0, 0, 128))
            # Composite the overlay onto the main image
            new_img_rgba = Image.alpha_composite(new_img_rgba, box_overlay)
            new_img = new_img_rgba.convert('RGB')
            draw = ImageDraw.Draw(new_img)
            
            # Draw each line of Chinese text
            # Calculate Y positions for each line properly
            if num_chinese_lines == 2:
                # For 2 lines: calculate from bottom up
                # Line 2 (bottom): chinese + pinyin
                line2_chinese_y = chinese_bottom_y
                line2_pinyin_y = line2_chinese_y - vertical_spacing - base_pinyin_font_size
                line2_portuguese_y = line2_chinese_y + vertical_spacing + base_chinese_font_size + 4  # Extra spacing for portuguese
                
                # Line 1 (top): above line 2 with proper spacing
                # Space needed: pinyin + spacing + chinese + spacing between lines
                line_spacing = vertical_spacing * 3  # Extra spacing between the two chinese lines (increased from 2)
                line1_chinese_y = line2_pinyin_y - line_spacing - base_chinese_font_size
                line1_pinyin_y = line1_chinese_y - vertical_spacing - base_pinyin_font_size
                line1_portuguese_y = line1_chinese_y + vertical_spacing + base_chinese_font_size + 4  # Extra spacing for portuguese
            else:
                # Single line
                line1_chinese_y = chinese_bottom_y
                line1_pinyin_y = line1_chinese_y - vertical_spacing - base_pinyin_font_size
                line1_portuguese_y = portuguese_y
                line2_chinese_y = None
                line2_pinyin_y = None
                line2_portuguese_y = None
            
            for line_idx, (line_items, word_widths) in enumerate(zip(chinese_lines, all_word_widths_per_line)):
                line_width = all_line_widths[line_idx]
                start_x = (width - line_width) // 2
                current_x = start_x
                
                # Get Y positions for this line
                if num_chinese_lines == 2:
                    if line_idx == 1:  # Second line (bottom)
                        line_chinese_y = line2_chinese_y
                        line_pinyin_y = line2_pinyin_y
                        line_portuguese_y = line2_portuguese_y
                    else:  # First line (top)
                        line_chinese_y = line1_chinese_y
                        line_pinyin_y = line1_pinyin_y
                        line_portuguese_y = line1_portuguese_y
                else:
                    # Single line
                    line_chinese_y = line1_chinese_y
                    line_pinyin_y = line1_pinyin_y
                    line_portuguese_y = line1_portuguese_y
                
                # Draw each word in this line
                for i, (chinese_word, word_pinyin, word_portuguese) in enumerate(line_items):
                    word_width = word_widths[i]
                    word_center_x = current_x + word_width // 2
                    
                    # Pinyin (purple)
                    if word_pinyin:
                        pinyin_bbox = pinyin_font.getbbox(word_pinyin)
                        pinyin_text_width = pinyin_bbox[2] - pinyin_bbox[0]
                        pinyin_x = word_center_x - pinyin_text_width // 2
                        draw.text((pinyin_x, line_pinyin_y), word_pinyin, font=pinyin_font, fill=(147, 112, 219))
                    
                    # Chinese (white)
                    chinese_bbox = chinese_font.getbbox(chinese_word)
                    chinese_text_width = chinese_bbox[2] - chinese_bbox[0]
                    chinese_x = word_center_x - chinese_text_width // 2
                    draw.text((chinese_x, line_chinese_y), chinese_word, font=chinese_font, fill=(255, 255, 255))
                    
                    # Portuguese (yellow) with line breaks - render for all lines
                    if word_portuguese:
                        wrapped_lines = wrap_portuguese_to_width(word_portuguese, portuguese_font, word_width)
                        for pt_line_idx, line in enumerate(wrapped_lines):
                            if line and line.strip():
                                line_bbox = portuguese_font.getbbox(line)
                                line_width = line_bbox[2] - line_bbox[0]
                                line_x = word_center_x - line_width // 2
                                line_y = line_portuguese_y + (pt_line_idx * int(base_portuguese_font_size * 1.2))
                                draw.text((line_x, line_y), line, font=portuguese_font, fill=(255, 255, 0))
                    
                    current_x += word_width
            
            # Save the image
            new_img.save(image_path, 'PNG')
            return True
            
    except Exception as e:
        print(f"   ❌ Erro ao adicionar legendas ao frame {image_path}: {e}")
        return False


def extract_screenshots(video_path, output_folder, subtitles: Optional[Dict[int, Tuple[str, str, str]]] = None, frames_per_second=7):
    """
    Extract screenshots from video at specified frame rate and add subtitles.
    
    Args:
        video_path: Path to the MP4 video file
        output_folder: Path to save screenshots
        subtitles: Dictionary mapping second -> (chinese_text, translations_json, portuguese_text)
        frames_per_second: Number of frames to extract per second (default: 7)
    """
    # Open video file
    cap = cv2.VideoCapture(str(video_path))
    
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    
    print(f"Video: {video_path.name}")
    print(f"FPS: {fps:.2f}")
    print(f"Total frames: {total_frames}")
    print(f"Duration: {duration:.2f} seconds")
    print(f"Extracting {frames_per_second} frames per second...")
    if subtitles:
        print(f"Found {len(subtitles)} subtitle entries in base.txt")
    
    # Calculate frame interval
    frame_interval = fps / frames_per_second
    
    # Create output folder if it doesn't exist
    output_folder.mkdir(parents=True, exist_ok=True)
    
    frame_count = 0
    second = 1
    frame_in_second = 1
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Check if this frame should be extracted
        if frame_count >= (second - 1) * fps + (frame_in_second - 1) * frame_interval:
            # Generate filename: {segundo_em_5_digitos}_{frame}.png
            filename = f"{second:05d}_{frame_in_second}.png"
            output_path = output_folder / filename
            
            # Save the frame
            cv2.imwrite(str(output_path), frame)
            
            # Add subtitles if available for this second
            if subtitles and second in subtitles:
                chinese_text, translations_json, portuguese_text = subtitles[second]
                if add_subtitles_to_frame(output_path, chinese_text, translations_json, portuguese_text):
                    print(f"Saved with subtitles: {filename}")
                else:
                    print(f"Saved (subtitle error): {filename}")
            else:
                # Still resize to R36S even without subtitles
                try:
                    with Image.open(output_path) as img:
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        resized_img = resize_image_for_r36s(img)
                        resized_img.save(output_path, 'PNG')
                    print(f"Saved: {filename}")
                except Exception as e:
                    print(f"Saved (resize error): {filename} - {e}")
            
            frame_in_second += 1
            
            # Move to next second if we've extracted all frames for current second
            if frame_in_second > frames_per_second:
                second += 1
                frame_in_second = 1
        
        frame_count += 1
        
        # Stop if we've processed all seconds
        if second > duration:
            break
    
    cap.release()
    print(f"\nExtraction complete! Screenshots saved to: {output_folder}")


def main():
    """Main function to handle command line arguments and orchestrate screenshot extraction."""
    parser = argparse.ArgumentParser(
        description="Extract 7 screenshots per second from MP4 videos",
        epilog="Example: python3 video_screenshoter.py death_becomes_her"
    )
    parser.add_argument(
        "folder_name",
        help="Name of the folder inside assets/ containing the MP4 video"
    )
    
    args = parser.parse_args()
    
    # Setup paths
    script_dir = Path(__file__).parent
    assets_dir = script_dir / "assets"
    video_folder = assets_dir / args.folder_name
    
    # Check if assets folder exists
    if not assets_dir.exists():
        print(f"Error: Assets folder not found: {assets_dir}")
        sys.exit(1)
    
    # Check if specified folder exists
    if not video_folder.exists():
        print(f"Error: Folder not found: {video_folder}")
        print(f"Available folders in assets/:")
        for item in assets_dir.iterdir():
            if item.is_dir():
                print(f"  - {item.name}")
        sys.exit(1)
    
    try:
        # Find MP4 file in the folder
        mp4_file = find_mp4_file(video_folder)
        
        # Find base.txt file (optional)
        base_file = find_base_file(video_folder)
        subtitles = None
        if base_file:
            print(f"Found base.txt: {base_file.name}")
            
            # Sanitize base.txt before processing screenshots
            if not SANITIZE_AVAILABLE:
                print("❌ Error: sanitize_base module not available")
                print("   Please ensure sanitize_base.py is in the same directory")
                sys.exit(1)
            
            print("\n🧹 Sanitizing base.txt before processing screenshots...")
            if not check_word_api_health():
                print("❌ Error: Word-api unavailable")
                print("   Sanitization requires word-api to be running")
                sys.exit(1)
            
            if not process_base_file(base_file):
                print("❌ Error: Sanitization failed")
                sys.exit(1)
            
            print("✅ Base.txt sanitized successfully")
            
            subtitles = parse_base_file(base_file)
            if subtitles:
                print(f"Loaded {len(subtitles)} subtitle entries")
            else:
                print("Warning: base.txt found but no valid subtitles parsed")
        else:
            print("No base.txt found - screenshots will be extracted without subtitles")
        
        # Create output folder for screenshots
        output_folder = video_folder / "screenshots"
        
        # Extract screenshots with subtitles
        extract_screenshots(mp4_file, output_folder, subtitles)
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

