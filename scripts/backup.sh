#!/bin/bash
# Ручной запуск бэкапа

echo "📦 Создание резервной копии..."
docker exec lor-helper-bot python -c "
import sqlite3
import shutil
import gzip
from datetime import datetime
import os

BACKUP_DIR = '/app/backups'
DATA_DIR = '/app/data'
os.makedirs(BACKUP_DIR, exist_ok=True)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_path = f'{BACKUP_DIR}/manual_{timestamp}'
os.makedirs(backup_path)

for db in ['lor_reminder.db', 'apscheduler_jobs.db']:
    src = f'{DATA_DIR}/{db}'
    if os.path.exists(src):
        dst = f'{backup_path}/{db}'
        shutil.copy2(src, dst)
        with open(dst, 'rb') as f_in:
            with gzip.open(f'{dst}.gz', 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(dst)
        print(f'✅ {db} сохранен')

print(f'✅ Бэкап создан: {backup_path}'
"
