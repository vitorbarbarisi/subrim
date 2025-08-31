#!/usr/bin/env python3
"""
Video Screenshot Extractor
Extracts 7 screenshots per second from MP4 videos in the assets folder.

Usage: python3 video_screenshoter.py <folder_name>
Example: python3 video_screenshoter.py death_becomes_her

Output format: {segundo_em_5_digitos}_{frame}.png
"""

import os
import sys
import cv2
import argparse
from pathlib import Path


def find_mp4_file(assets_folder):
    """Find the first MP4 file in the specified assets folder."""
    mp4_files = list(assets_folder.glob("*.mp4"))
    if not mp4_files:
        raise FileNotFoundError(f"No MP4 file found in {assets_folder}")
    
    if len(mp4_files) > 1:
        print(f"Warning: Multiple MP4 files found. Using: {mp4_files[0].name}")
    
    return mp4_files[0]


def extract_screenshots(video_path, output_folder, frames_per_second=7):
    """
    Extract screenshots from video at specified frame rate.
    
    Args:
        video_path: Path to the MP4 video file
        output_folder: Path to save screenshots
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
            print(f"Saved: {filename}")
            
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
        
        # Create output folder for screenshots
        output_folder = video_folder / "screenshots"
        
        # Extract screenshots
        extract_screenshots(mp4_file, output_folder)
        
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

