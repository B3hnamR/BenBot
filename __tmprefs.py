from pathlib import Path
for needle in ['Notify delivered','Order cancelled and recorded','admin:orders:timeline_status:']:
    text = Path('app/bot/keyboards/admin.py').read_text(encoding='utf-8')
    for idx, line in enumerate(text.splitlines(), 1):
        if needle in line:
            print(idx, line.strip())
