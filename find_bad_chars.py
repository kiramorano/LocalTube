import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all non-ASCII characters that might cause issues
import re
# Find the script blocks
scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', content)

for i, script in enumerate(scripts):
    lines = script.split('\n')
    for j, line in enumerate(lines, 1):
        # Check for non-ASCII characters
        for ch in line:
            if ord(ch) > 127:
                code = hex(ord(ch))
                # Only flag problematic characters
                if code not in ['0x2014', '0x2013', '0x2018', '0x2019', '0x201c', '0x201d', '0x2026', '0xa0', '0xb7']:
                    pass  # Skip common ones
