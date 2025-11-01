from pathlib import Path
path = Path('app/bot/keyboards/admin.py')
for idx, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
    if 'Mark as paid' in line and 'timeline' in ''.join(path.read_text(encoding='utf-8').splitlines()[idx-5:idx+5]):
        print(f"{path}:{idx} -> {line.strip()}")
    if 'Notify delivered' in line and 'timeline' in ''.join(path.read_text(encoding='utf-8').splitlines()[idx-5:idx+5]):
        print(f"{path}:{idx} -> {line.strip()}")
