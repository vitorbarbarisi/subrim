#!/usr/bin/env python3
"""
Script to extract words from base.txt file, count occurrences,
and output them sorted by count using a heap structure.
"""

import re
import heapq
import sys
import os
from collections import defaultdict
from typing import List, Tuple


def extract_words_from_pairs(pairs_str: str) -> List[str]:
    """
    Extract Chinese words from the pairs array string.
    
    Args:
        pairs_str: String containing the pairs array, e.g., 
                   '["真面目 (zhēn miàn mù): verdadeira face", ...]'
    
    Returns:
        List of Chinese words extracted from the pairs
    """
    words = []
    
    # Pattern to match: "word (pinyin): translation"
    # We want to extract the word part before " ("
    pattern = r'"([^"]+?)\s+\('
    
    matches = re.findall(pattern, pairs_str)
    words.extend(matches)
    
    return words


def parse_base_file(file_path: str) -> defaultdict:
    """
    Parse base.txt file and count word occurrences.
    
    Args:
        file_path: Path to the base.txt file
    
    Returns:
        Dictionary with words as keys and counts as values
    """
    word_count = defaultdict(int)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                # Split by tab to get the different parts
                parts = line.split('\t')
                
                # The pairs array should be in the 5th column (index 4)
                # Format: line_number, start_time, end_time, chinese_text, pairs_array, translation
                if len(parts) >= 5:
                    pairs_str = parts[4]
                    words = extract_words_from_pairs(pairs_str)
                    
                    for word in words:
                        word_count[word] += 1
                else:
                    print(f"Warning: Line {line_num} doesn't have expected format: {line[:50]}...", 
                          file=sys.stderr)
    
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)
    
    return word_count


def create_word_heap(word_count: defaultdict) -> List[Tuple[int, str]]:
    """
    Create a max-heap structure ordered by word count.
    
    Since Python's heapq is a min-heap, we use negative counts
    to simulate a max-heap (largest count first).
    
    Args:
        word_count: Dictionary with words and their counts
    
    Returns:
        List of tuples (-count, word) representing a max-heap
    """
    # Create heap with negative counts for max-heap behavior
    heap = [(-count, word) for word, count in word_count.items()]
    heapq.heapify(heap)
    
    return heap


def output_sorted_words(heap: List[Tuple[int, str]], output_file: str = None):
    """
    Output words sorted by count (descending order).
    
    Args:
        heap: Heap structure with (-count, word) tuples
        output_file: Optional output file path. If None, prints to stdout.
    """
    output_lines = []
    
    # Extract all items from heap in sorted order
    sorted_items = []
    heap_copy = heap.copy()
    
    while heap_copy:
        neg_count, word = heapq.heappop(heap_copy)
        count = -neg_count  # Convert back to positive
        sorted_items.append((count, word))
    
    # Sort by count descending (heap already gives us this, but let's be explicit)
    sorted_items.sort(reverse=True)
    
    # Format output
    for count, word in sorted_items:
        output_lines.append(f"{word}\t{count}")
    
    output_text = '\n'.join(output_lines)
    
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(output_text)
            print(f"Output written to '{output_file}'")
        except Exception as e:
            print(f"Error writing to file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(output_text)


def generate_output_filename(input_file: str) -> str:
    """
    Generate output filename based on input filename.
    Format: {base_name}_words_counted.txt
    
    Args:
        input_file: Path to input file
    
    Returns:
        Output file path with generated name
    """
    # Get directory and filename
    directory = os.path.dirname(input_file)
    filename = os.path.basename(input_file)
    
    # Remove extension
    base_name = os.path.splitext(filename)[0]
    
    # Remove _base suffix if present
    if base_name.endswith('_base'):
        base_name = base_name[:-5]  # Remove '_base'
    
    # Generate output filename
    output_filename = f"{base_name}_words_counted.txt"
    
    # Join with directory if it exists
    if directory:
        return os.path.join(directory, output_filename)
    else:
        return output_filename


def main():
    if len(sys.argv) < 2:
        print("Usage: python word_counter_heap.py <base.txt> [output.txt]")
        print("Example: python word_counter_heap.py warehouse/elvira_base.txt")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Generate output filename if not provided
    if output_file is None:
        output_file = generate_output_filename(input_file)
    
    print(f"Reading words from '{input_file}'...")
    word_count = parse_base_file(input_file)
    
    print(f"Found {len(word_count)} unique words.")
    print(f"Total word occurrences: {sum(word_count.values())}")
    
    print("Creating heap structure...")
    heap = create_word_heap(word_count)
    
    print("Outputting sorted words...")
    output_sorted_words(heap, output_file)


if __name__ == "__main__":
    main()

