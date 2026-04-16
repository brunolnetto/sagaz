#!/usr/bin/env python3
"""Convert coverage.json to Codacy format."""

import json
import sys

def coverage_json_to_cobertura(coverage_json_file, output_file):
    """Convert coverage.json to basic coverage report for Codacy."""
    
    with open(coverage_json_file) as f:
        data = json.load(f)
    
    # Extract coverage summary
    total_coverage = data.get('totals', {}).get('percent_covered', 0)
    
    # Create a simple report that Codacy can understand
    report = {
        "coverage_percentage": total_coverage,
        "files_with_coverage": len(data.get('files', {})),
        "total_lines": data.get('totals', {}).get('num_statements', 0),
        "covered_lines": int(data.get('totals', {}).get('num_statements', 0) * total_coverage / 100),
    }
    
    # Write report
    with open(output_file, 'w') as f:
        # Codacy expects COBERTURA XML format or JSON report
        # For now, write the JSON summary
        f.write(json.dumps(report, indent=2))
    
    print(f"✅ Coverage report created: {output_file}")
    print(f"📊 Total Coverage: {total_coverage:.1f}%")
    print(f"📈 Files: {report['files_with_coverage']}")
    print(f"📝 Covered Lines: {report['covered_lines']} / {report['total_lines']}")

if __name__ == '__main__':
    coverage_json_to_cobertura('coverage.json', 'codacy_report.txt')
