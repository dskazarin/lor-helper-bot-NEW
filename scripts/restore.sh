#!/bin/bash
# Восстановление из последнего бэкапа

LATEST=$(ls -td /app/backups/* | head -1)
echo "🔄 Восстановление из $LATEST..."

docker exec lor-helper-bot python -c "
import gzip
import shutil
import os
from pathlib import Path

backup = '$LATEST'
data_dir = '/app/data'

for gz in Path(backup).glob('*.gz'):
    with gzip.open(gz, 'rb') as f_in:
        with open(f'{data_dir}/{gz.stem}', 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    print(f'✅ {gz.stem} восстановлен'
"

echo "✅ Восстановление завершено!"
