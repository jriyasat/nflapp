#!/usr/bin/env python3
"""
# Pre‑commit hook to detect grading‑logic anti‑patterns.
Run manually with: python scripts/check_grading_patterns.py

Checks for:
1. market_spread = -float(r["spread_line"]) followed by home_cov = result - market_spread (sign‑flip bug)
2. market.get('spread') when predictor only emits home_spread
3. Use of 'clv' variable name that might be mis‑labeled (should be avg_edge)
"""

import os
import re
import sys

def find_py_files(root):
    """Yield all .py files under root."""
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.endswith('.py'):
                yield os.path.join(dirpath, f)

def check_sign_flip(content, path):
    """Detect the sign-flip bug pattern."""
    lines = content.split('\n')
    errors = []
    for i, line in enumerate(lines):
        if 'market_spread = -float(r["spread_line"])' in line:
            # Look ahead a few lines for home_cov using market_spread
            for j in range(i, min(i+5, len(lines))):
                if 'home_cov' in lines[j] and 'market_spread' in lines[j]:
                    # Check if it's the buggy formula
                    if 'result' in lines[j] and '-' in lines[j] and 'market_spread' in lines[j]:
                        errors.append(f'{path}:{i+1}: possible sign-flip: {line.strip()}\n  -> {lines[j].strip()}')
    return errors

def check_market_get_spread(content, path):
    """Detect market.get('spread') which returns None."""
    pattern = r'market\.get\(["\']spread["\']\)'
    matches = re.finditer(pattern, content)
    errors = []
    for m in matches:
        # Context line
        line_no = content[:m.start()].count('\n') + 1
        line = content.split('\n')[line_no-1]
        errors.append(f'{path}:{line_no}: market.get("spread") used (predictor only emits home_spread)')
    return errors

def check_clv_variable(content, path):
    """Warn about 'clv' variable that might be mislabeled."""
    # Look for assignment clv = ... mean()
    pattern = r'\bclv\s*=\s*[^;]+\.mean\(\)'
    matches = re.finditer(pattern, content)
    errors = []
    for m in matches:
        line_no = content[:m.start()].count('\n') + 1
        line = content.split('\n')[line_no-1]
        errors.append(f'{path}:{line_no}: clv variable defined as mean edge (rename to avg_edge?)')
    return errors

def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    all_errors = []
    
    for py_path in find_py_files(root):
        # Skip virtual environments and .git
        if '/.venv/' in py_path or '/.git/' in py_path:
            continue
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            continue
        
        all_errors.extend(check_sign_flip(content, py_path))
        all_errors.extend(check_market_get_spread(content, py_path))
        all_errors.extend(check_clv_variable(content, py_path))
    
    if all_errors:
        print('\n❌ Grading‑logic anti‑patterns detected:\n')
        for err in all_errors:
            print(err)
        print('\nPlease fix before committing.')
        sys.exit(1)
    else:
        print('✅ No grading‑logic anti‑patterns found.')
        sys.exit(0)

if __name__ == '__main__':
    main()