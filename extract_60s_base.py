#!/usr/bin/env python3
"""
Extract first 60 seconds of base.txt entries
"""

import re
from pathlib import Path

def extract_first_60s_base(base_file, output_file):
    """Extract first 60 seconds from base.txt file"""
    
    output_lines = []
    
    with open(base_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            # Split by tabs
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            
            # Extract begin timestamp (second column)
            begin_timestamp_str = parts[1].strip()
            
            # Extract seconds from begin timestamp (e.g., "26.880s" -> 26.880)
            begin_match = re.match(r'([\d.]+)s?', begin_timestamp_str)
            if not begin_match:
                continue
                
            begin_seconds = float(begin_match.group(1))
            
            # Only include entries that start within first 60 seconds
            if begin_seconds < 60.0:
                output_lines.append(line)
            else:
                # Stop processing once we go beyond 60 seconds
                break
    
    # Write output
    with open(output_file, 'w', encoding='utf-8') as f:
        for line in output_lines:
            f.write(line + '\n')
    
    print(f"Extracted {len(output_lines)} entries from first 60 seconds")
    return len(output_lines)

if __name__ == "__main__":
    base_input = "/Users/vitor.barbarisi/dev/subrim/assets/onibus152/capítulo de 25⧸03⧸2025 [13458287].zht-br_secs_base.txt"
    base_output = "/Users/vitor.barbarisi/dev/subrim/assets/test/test_60s_zht-br_secs_base.txt"
    
    extract_first_60s_base(base_input, base_output)
