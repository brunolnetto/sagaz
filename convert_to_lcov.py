#!/usr/bin/env python3
"""Convert coverage.json to LCOV format."""

import json
from pathlib import Path

def json_to_lcov(coverage_json_file, output_file):
    """Convert coverage.json to LCOV format."""
    
    with open(coverage_json_file) as f:
        data = json.load(f)
    
    lines = []
    lines.append("TN:Sagaz Coverage Report")
    
    files = data.get('files', {})
    
    for file_path, file_data in files.items():
        # Skip non-Python files and test files
        if not file_path.endswith('.py') or '/test' in file_path:
            continue
            
        lines.append(f"SF:{file_path}")
        
        # Add line coverage data
        executed_lines = file_data.get('executed_lines', [])
        missing_lines = file_data.get('missing_lines', [])
        
        for line_num in sorted(set(executed_lines + missing_lines)):
            is_executed = line_num in executed_lines
            line_count = 1 if is_executed else 0
            lines.append(f"DA:{line_num},{line_count}")
        
        # Calculate summary for this file
        total_lines = len(set(executed_lines + missing_lines))
        covered_lines = len(executed_lines)
        
        if total_lines > 0:
            lines.append(f"LH:{covered_lines}")
            lines.append(f"LF:{total_lines}")
        
        lines.append("end_of_record")
    
    # Write LCOV file
    with open(output_file, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ LCOV report created: {output_file}")
    print(f"📊 Files: {len(files)}")
    
    with open(output_file) as f:
        content = f.read()
        print(f"📄 File size: {len(content)} bytes")

if __name__ == '__main__':
    json_to_lcov('coverage.json', 'coverage.lcov')
