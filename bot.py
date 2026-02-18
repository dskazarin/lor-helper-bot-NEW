#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЛОР-Помощник - Telegram бот для управления приемом лекарств и отслеживания симптомов
Версия: 11.0.0 (Стабильная с автоматической миграцией)
Автор: Денис Казарин (врач-оториноларинголог)
"""

import asyncio
import logging
import logging.handlers
import os
import sys
import json
import re
import shutil
import gzip
import csv
import time
import traceback
import functools
import warnings
import signal
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from collections import defaultdict
from pathlib import Path
from io import StringIO, BytesIO
import pytz
import sqlite3
from dataclasses import dataclass, asdict

# ============== ОТКЛЮЧЕНИЕ ПРЕДУПРЕЖДЕНИЙ ==============
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', category=UserWarning)

# ============== ОПТИМИЗАЦИЯ EVENT LOOP ==============
try:
    import uvloop
    uvloop.install()
    print("✅ uvloop установлен и активен")
except ImportError:
    print("⚠️ uvloop не установлен, используем стандартный asyncio")

try:
    import nest_asyncio
    nest_asyncio.apply()
    print("✅ nest_asyncio применен")
except ImportError:
    print("⚠️ nest_asyncio не установлен, устанавливаем...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "nest_asyncio"])
    import nest_asyncio
    nest_asyncio.apply()
    print("✅ nest_asyncio установлен и применен")

# ============== УСТАНОВКА ЗАВИСИМОСТЕЙ ==============
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
        ConversationHandler, MessageHandler, filters, ContextTypes
    )
    from telegram.constants import ParseMode
    from telegram.error import RetryAfter, TimedOut, BadRequest, Conflict
except ImportError:
    print("Устанавливаем python-telegram-bot...")
    os.system(f"{sys.executable} -m pip install python-telegram-bot==20.3")
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler,
        ConversationHandler, MessageHandler, filters, ContextTypes
    )
    from telegram.constants import ParseMode
    from telegram.error import RetryAfter, TimedOut, BadRequest, Conflict

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.executors.asyncio import AsyncIOExecutor
    from apscheduler.jobstores.base import JobLookupError
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    print("Устанавливаем APScheduler...")
    os.system(f"{sys.executable} -m pip install apscheduler==3.10.4")
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.executors.asyncio import AsyncIOExecutor
    from apscheduler.jobstores.base import JobLookupError
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

try:
    from sqlalchemy import (
        create_engine, Column, Integer, String, DateTime, Text, 
        Boolean, BigInteger, Index, func, select, and_, or_, desc,
        inspect
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, scoped_session
    from sqlalchemy.pool import QueuePool
except ImportError:
    print("Устанавливаем SQLAlchemy...")
    os.system(f"{sys.executable} -m pip install sqlalchemy==2.0.23")
    from sqlalchemy import (
        create_engine, Column, Integer, String, DateTime, Text, 
        Boolean, BigInteger, Index, func, select, and_, or_, desc,
        inspect
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, scoped_session
    from sqlalchemy.pool import QueuePool

# ============== КОНФИГУРАЦИЯ ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8515765315:AAEufR-gJQUZCux_kC0yDfmHRZf2QLgacUk")
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "308780639").split(",") if id]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "308780639")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Директории для данных
DATA_DIR = Path("/app/data")
BACKUP_DIR = Path("/app/backups")
LOG_DIR = Path("/app/logs")

# Создаем директории
for directory in [DATA_DIR, BACKUP_DIR, LOG_DIR]:
    os.makedirs(directory, exist_ok=True)
    print(f"📁 Создана директория: {directory}")

# Пути к базам данных
DB_PATH = DATA_DIR / "lor_reminder.db"
JOBS_DB_PATH = DATA_DIR / "apscheduler_jobs.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
JOB_STORE_URL = f"sqlite:///{JOBS_DB_PATH}"

print(f"📁 База данных: {DB_PATH}")
print(f"📁 БД планировщика: {JOBS_DB_PATH}")

# Контакты клиник
KIT_CLINIC = {
    "name": "🏥 КИТ-клиника (Куркино)",
    "address": "125466, Москва, ул. Соколово-Мещерская, 16/114",
    "phone": "84957775580",
    "phone_display": "8 (495) 777-55-80",
    "site": "https://kit-clinic.ru/doctors/kazarin-denis-sergeevich/",
    "maps": "https://yandex.ru/maps/-/CPQZIPYD",
    "coords": "55.897085, 37.389648"
}

FAMILY_CLINIC = {
    "name": "🏥 Семейная клиника (Путилково)",
    "address": "Красногорск г.о., пгт Путилково, Спасо-Тушинский бульвар, д. 5",
    "phone": "84987317555",
    "phone_display": "8 (498) 731-75-55",
    "site": "https://klinika-bz.ru/speczialistyi/kazarin-denis-sergeevich",
    "maps": "https://yandex.ru/maps/-/CPEBA46u"
}

# Информация о враче
DOCTOR_INFO = """👨‍⚕️ Денис Сергеевич Казарин - врач-оториноларинголог

👶 Ведет прием детей с 0 лет и взрослых

🎓 Образование:
• 2001-2007: МГМСУ им. А.И. Евдокимова (Лечебное дело)
• 2007-2009: Ординатура, РМАПО (Оториноларингология)
• Доп. образование: Лазерная медицина (НПЦ лазерной медицины им. Скобелкина)

🏥 Принимает в клиниках:
• КИТ-клиника (Куркино)
• Семейная клиника (Путилково)

📱 Telegram:
• Канал: @KAZARIN_LOR
• Личный: @deniskazarin"""

# ============== СИСТЕМА ЛОГГИРОВАНИЯ ==============

class JsonFormatter(logging.Formatter):
    """Форматтер для JSON-логов."""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        
        if hasattr(record, 'user_id'):
            log_entry["user_id"] = record.user_id
        if hasattr(record, 'username'):
            log_entry["username"] = record.username
        
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info)
            }
        
        if hasattr(record, 'extra'):
            log_entry.update(record.extra)
        
        return json.dumps(log_entry, ensure_ascii=False)

class CustomFormatter(logging.Formatter):
    """Кастомный форматтер с цветами для консоли."""
    
    grey = "\x1b[38;21m"
    blue = "\x1b[38;5;39m"
    yellow = "\x1b[38;5;226m"
    red = "\x1b[38;5;196m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    
    def __init__(self, use_colors=True):
        super().__init__()
        self.use_colors = use_colors
        self.date_format = "%Y-%m-%d %H:%M:%S"
    
    def format(self, record):
        record.timestamp = datetime.fromtimestamp(record.created).strftime(self.date_format)
        record.user_info = f"[User:{record.user_id}]" if hasattr(record, 'user_id') else ""
        
        log_colors = {
            logging.DEBUG: self.grey,
            logging.INFO: self.blue,
            logging.WARNING: self.yellow,
            logging.ERROR: self.red,
            logging.CRITICAL: self.bold_red
        }
        color = log_colors.get(record.levelno, self.grey)
        
        formatted = f"{record.timestamp} - {record.user_info} - {record.levelname} - {record.getMessage()}"
        if self.use_colors:
            formatted = f"{color}{formatted}{self.reset}"
        
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        
        return formatted

def setup_logging():
    """Настройка многоуровневого логирования."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL))
    
    file_formatter = CustomFormatter(use_colors=False)
    console_formatter = CustomFormatter(use_colors=True)
    json_formatter = JsonFormatter()
    
    # Консоль
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(console_formatter)
    root_logger.addHandler(console)
    
    # DEBUG лог
    debug_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "debug.log",
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(file_formatter)
    root_logger.addHandler(debug_handler)
    
    # INFO лог
    info_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "info.log",
        maxBytes=10*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(file_formatter)
    root_logger.addHandler(info_handler)
    
    # ERROR лог
    error_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "error.log",
        maxBytes=10*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)
    
    # JSON лог
    json_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "bot.json",
        maxBytes=10*1024*1024,
        backupCount=2,
        encoding='utf-8'
    )
    json_handler.setLevel(logging.INFO)
    json_handler.setFormatter(json_formatter)
    root_logger.addHandler(json_handler)
    
    return root_logger

logger = setup_logging()

class ContextLogger:
    """Логгер с контекстом пользователя."""
    
    def __init__(self, logger):
        self.logger = logger
    
    def _add_context(self, extra: dict, update: Update = None):
        if update and update.effective_user:
            extra['user_id'] = update.effective_user.id
            extra['username'] = update.effective_user.username
            extra['first_name'] = update.effective_user.first_name
        return extra
    
    def debug(self, msg: str, update: Update = None, **kwargs):
        self.logger.debug(msg, extra=self._add_context(kwargs, update))
    
    def info(self, msg: str, update: Update = None, **kwargs):
        self.logger.info(msg, extra=self._add_context(kwargs, update))
    
    def warning(self, msg: str, update: Update = None, **kwargs):
        self.logger.warning(msg, extra=self._add_context(kwargs, update))
    
    def error(self, msg: str, update: Update = None, exc_info=False, **kwargs):
        self.logger.error(msg, extra=self._add_context(kwargs, update), exc_info=exc_info)
    
    def critical(self, msg: str, update: Update = None, **kwargs):
        self.logger.critical(msg, extra=self._add_context(kwargs, update))

log = ContextLogger(logger)

def log_execution_time(func):
    """Декоратор для замера времени выполнения."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        update = next((a for a in args if isinstance(a, Update)), None)
        try:
            result = await func(*args, **kwargs)
            elapsed = (time.time() - start) * 1000
            log.info(f"{func.__name__} выполнен за {elapsed:.2f}ms", update=update)
            return result
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log.error(f"{func.__name__} упал за {elapsed:.2f}ms: {e}", update=update, exc_info=True)
            raise
    return wrapper

# ============== СИСТЕМА УВЕДОМЛЕНИЙ ОБ ОШИБКАХ ==============

class ErrorNotifier:
    """Отправляет уведомления об ошибках в Telegram."""
    
    def __init__(self, bot_token: str, admin_chat_id: str):
        self.bot_token = bot_token
        self.admin_chat_id = int(admin_chat_id) if admin_chat_id else None
        self.error_counts = defaultdict(int)
        self.last_reset = datetime.now()
        self.queue = asyncio.Queue()
        self.task = None
    
    async def start(self):
        if self.admin_chat_id:
            self.task = asyncio.create_task(self._processor())
            log.info("✅ Система уведомлений об ошибках запущена")
    
    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
    
    async def _processor(self):
        while True:
            try:
                if datetime.now() - self.last_reset > timedelta(hours=1):
                    self.error_counts.clear()
                    self.last_reset = datetime.now()
                
                error = await self.queue.get()
                key = error['type']
                self.error_counts[key] += 1
                
                if self.error_counts[key] <= 5:
                    await self._send(error)
                
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in notification processor: {e}")
    
    async def _send(self, error: dict):
        text = f"🚨 *Критическая ошибка!*\n\n"
        text += f"**Тип:** {error['type']}\n"
        text += f"**Время:** {error['timestamp']}\n"
        if 'user_id' in error:
            text += f"**Пользователь:** `{error['user_id']}`\n"
        text += f"\n**Сообщение:**\n```\n{error['message'][:500]}\n```\n"
        if 'traceback' in error:
            text += f"\n**Traceback:**\n```\n{error['traceback'][:1000]}\n```"
        
        import requests
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.admin_chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=5
            )
        except Exception as e:
            print(f"Failed to send notification: {e}")
    
    def notify(self, error_type: str, message: str, user_id: int = None, traceback: str = None):
        if not self.admin_chat_id:
            return
        try:
            self.queue.put_nowait({
                "type": error_type,
                "message": message,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "user_id": user_id,
                "traceback": traceback
            })
        except asyncio.QueueFull:
            print("Notification queue full")

error_notifier = None

# ============== СИСТЕМА РЕЗЕРВНОГО КОПИРОВАНИЯ ==============

class BackupManager:
    """Управление резервным копированием."""
    
    def __init__(self, db_path: Path, jobs_path: Path, backup_dir: Path, max_backups: int = 30):
        self.db_path = db_path
        self.jobs_path = jobs_path
        self.backup_dir = backup_dir
        self.max_backups = max_backups
        self.backup_dir.mkdir(exist_ok=True)
    
    def create_backup(self, backup_type: str = "auto") -> Optional[Path]:
        """Создание резервной копии."""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = self.backup_dir / f"{backup_type}_{timestamp}"
            backup_path.mkdir(exist_ok=True)
            
            stats = []
            
            if self.db_path.exists():
                dst = backup_path / "lor_reminder.db"
                shutil.copy2(self.db_path, dst)
                self._compress(dst)
                stats.append(f"БД: {self.db_path.stat().st_size / 1024:.1f}KB")
            
            if self.jobs_path.exists():
                dst = backup_path / "apscheduler_jobs.db"
                shutil.copy2(self.jobs_path, dst)
                self._compress(dst)
                stats.append(f"Jobs: {self.jobs_path.stat().st_size / 1024:.1f}KB")
            
            self._save_metadata(backup_path, backup_type, stats)
            self._cleanup_old()
            
            log.info(f"✅ {backup_type.upper()} бэкап создан: {timestamp} ({', '.join(stats)})")
            return backup_path
            
        except Exception as e:
            log.error(f"❌ Ошибка создания бэкапа: {e}")
            return None
    
    def _compress(self, file_path: Path):
        """Сжатие файла."""
        compressed = file_path.with_suffix('.db.gz')
        with open(file_path, 'rb') as f_in:
            with gzip.open(compressed, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        file_path.unlink()
    
    def _save_metadata(self, backup_path: Path, backup_type: str, stats: list):
        """Сохранение метаданных."""
        metadata = {
            "timestamp": backup_path.name.split('_')[1],
            "type": backup_type,
            "stats": stats,
            "files": [f.name for f in backup_path.glob("*.gz")],
            "db_size": self.db_path.stat().st_size if self.db_path.exists() else 0
        }
        with open(backup_path / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    def _cleanup_old(self):
        """Удаление старых бэкапов."""
        backups = sorted([d for d in self.backup_dir.iterdir() if d.is_dir()])
        while len(backups) > self.max_backups:
            shutil.rmtree(backups[0])
            log.info(f"🗑️ Удален старый бэкап: {backups[0].name}")
            backups = sorted([d for d in self.backup_dir.iterdir() if d.is_dir()])
    
    def get_backups(self) -> List[dict]:
        """Список всех бэкапов."""
        backups = []
        for backup_dir in sorted(self.backup_dir.iterdir(), reverse=True):
            if not backup_dir.is_dir():
                continue
            
            meta_path = backup_dir / "metadata.json"
            if meta_path.exists():
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            else:
                parts = backup_dir.name.split('_')
                meta = {
                    "timestamp": parts[1] if len(parts) > 1 else "unknown",
                    "type": parts[0] if parts else "unknown",
                    "stats": [],
                    "files": [f.name for f in backup_dir.glob("*.gz")]
                }
            
            total_size = sum(f.stat().st_size for f in backup_dir.glob("*")) / 1024
            meta["size_kb"] = total_size
            meta["name"] = backup_dir.name
            backups.append(meta)
        
        return backups
    
    def restore(self, backup_name: str) -> bool:
        """Восстановление из бэкапа."""
        backup_path = self.backup_dir / backup_name
        if not backup_path.exists():
            log.error(f"❌ Бэкап {backup_name} не найден")
            return False
        
        try:
            for gz_file in backup_path.glob("*.gz"):
                original = DATA_DIR / gz_file.stem
                with gzip.open(gz_file, 'rb') as f_in:
                    with open(original, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                log.info(f"✅ Восстановлен: {original.name}")
            return True
        except Exception as e:
            log.error(f"❌ Ошибка восстановления: {e}")
            return False

backup_manager = BackupManager(DB_PATH, JOBS_DB_PATH, BACKUP_DIR)

# ============== ДЕКОРАТОР АДМИНА ==============

def admin_only(func):
    """Декоратор для ограничения доступа администраторам."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("⛔ Доступ запрещен. Эта команда только для администраторов.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ============== МОДЕЛИ БАЗЫ ДАННЫХ ==============

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    last_activity = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    is_active = Column(Boolean, default=True)
    is_banned = Column(Boolean, default=False)
    ban_reason = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False)
    language = Column(String(10), default='ru')
    total_interactions = Column(Integer, default=0)
    
    __table_args__ = (
        Index('ix_users_status', 'is_active', 'is_banned'),
    )

class UserTimezone(Base):
    __tablename__ = 'user_timezones'
    user_id = Column(BigInteger, primary_key=True)
    timezone = Column(String(50), nullable=False, default='Europe/Moscow')
    created_at = Column(DateTime, default=lambda: datetime.now(pytz.UTC))

class Medicine(Base):
    __tablename__ = 'medicines'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    schedule = Column(String(200), nullable=False)  # время в формате "08:00" или "08:00,20:00"
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    user_timezone = Column(String(50), nullable=False)
    status = Column(String(20), default='active')
    course_type = Column(String(20), default='unlimited')
    course_days = Column(Integer, nullable=True)
    repeat_type = Column(String(20), default='none')
    repeat_days = Column(Integer, nullable=True)
    paused_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(pytz.UTC))
    
    __table_args__ = (
        Index('ix_medicines_user_status', 'user_id', 'status'),
    )

class Analysis(Base):
    __tablename__ = 'analyses'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    scheduled_date = Column(DateTime, nullable=False)
    scheduled_time = Column(String(10), nullable=False, default='12:00')
    repeat_type = Column(String(20), default='once')
    repeat_interval = Column(Integer, nullable=True)
    reminder_before = Column(Integer, default=120)  # в минутах
    notes = Column(Text, nullable=True)
    status = Column(String(20), default='pending')
    user_timezone = Column(String(50), nullable=False)
    paused_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(pytz.UTC))
    
    __table_args__ = (
        Index('ix_analyses_user_status', 'user_id', 'status'),
        Index('ix_analyses_scheduled_date', 'scheduled_date'),
    )

class Reminder(Base):
    __tablename__ = 'reminders'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    reminder_type = Column(String(20))
    item_id = Column(Integer, nullable=False)
    scheduled_time = Column(DateTime(timezone=True), nullable=False)
    user_timezone = Column(String(50), nullable=False)
    status = Column(String(20), default='pending')
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    postponed_until = Column(DateTime(timezone=True), nullable=True)
    postponed_days = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(pytz.UTC))
    
    __table_args__ = (
        Index('ix_reminders_status_time', 'status', 'scheduled_time'),
    )

class MedicineLog(Base):
    __tablename__ = 'medicine_logs'
    id = Column(Integer, primary_key=True)
    medicine_id = Column(Integer, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    status = Column(String(20))  # taken, skipped, postponed, extra
    dosage = Column(String(50), nullable=True)
    comment = Column(Text, nullable=True)
    taken_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    error_details = Column(Text, nullable=True)
    course_info = Column(Text, nullable=True)
    is_planned = Column(Boolean, default=True)

class AnalysisLog(Base):
    __tablename__ = 'analysis_logs'
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    status = Column(String(20))
    completed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    notes = Column(Text, nullable=True)

class MoodLog(Base):
    __tablename__ = 'mood_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    mood_score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))

class SymptomLog(Base):
    __tablename__ = 'symptom_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    symptom = Column(String(100), nullable=False)
    severity = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))

class DoctorVisitLog(Base):
    __tablename__ = 'doctor_visits'
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    visit_date = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    notes = Column(Text, nullable=True)

class AdminLog(Base):
    __tablename__ = 'admin_logs'
    id = Column(Integer, primary_key=True)
    admin_id = Column(BigInteger, nullable=False)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    target_user = Column(BigInteger, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))
    
    __table_args__ = (
        Index('ix_admin_logs_admin', 'admin_id'),
        Index('ix_admin_logs_time', 'created_at'),
    )

class BroadcastLog(Base):
    __tablename__ = 'broadcast_logs'
    id = Column(Integer, primary_key=True)
    admin_id = Column(BigInteger, nullable=False)
    message = Column(Text, nullable=False)
    target = Column(String(50), nullable=False)
    total = Column(Integer, nullable=False)
    success = Column(Integer, nullable=False)
    failed = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))

# ============== ФУНКЦИЯ МИГРАЦИИ БАЗЫ ДАННЫХ ==============

def migrate_database():
    """Автоматическое добавление недостающих колонок."""
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        
        # Миграция таблицы medicines
        if 'medicines' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('medicines')]
            
            # Проверяем и добавляем все необходимые колонки
            if 'course_type' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN course_type VARCHAR(20) DEFAULT "unlimited"'))
                log.info("✅ Добавлена колонка course_type в medicines")
            
            if 'course_days' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN course_days INTEGER'))
                log.info("✅ Добавлена колонка course_days в medicines")
            
            if 'repeat_type' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN repeat_type VARCHAR(20) DEFAULT "none"'))
                log.info("✅ Добавлена колонка repeat_type в medicines")
            
            if 'repeat_days' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN repeat_days INTEGER'))
                log.info("✅ Добавлена колонка repeat_days в medicines")
            
            if 'paused_until' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN paused_until DATETIME'))
                log.info("✅ Добавлена колонка paused_until в medicines")
            
            if 'end_date' not in columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN end_date DATETIME'))
                log.info("✅ Добавлена колонка end_date в medicines")
        
        # Миграция таблицы analyses
        if 'analyses' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('analyses')]
            
            if 'repeat_interval' not in columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN repeat_interval INTEGER'))
                log.info("✅ Добавлена колонка repeat_interval в analyses")
            
            if 'reminder_before' not in columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN reminder_before INTEGER DEFAULT 120'))
                log.info("✅ Добавлена колонка reminder_before в analyses")
            
            if 'scheduled_time' not in columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN scheduled_time VARCHAR(10) DEFAULT "12:00"'))
                log.info("✅ Добавлена колонка scheduled_time в analyses")
            
            if 'paused_until' not in columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN paused_until DATETIME'))
                log.info("✅ Добавлена колонка paused_until в analyses")
            
            if 'notes' not in columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN notes TEXT'))
                log.info("✅ Добавлена колонка notes в analyses")
        
        # Миграция таблицы reminders
        if 'reminders' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('reminders')]
            
            if 'postponed_days' not in columns:
                db.execute(text('ALTER TABLE reminders ADD COLUMN postponed_days INTEGER'))
                log.info("✅ Добавлена колонка postponed_days в reminders")
            
            if 'postponed_until' not in columns:
                db.execute(text('ALTER TABLE reminders ADD COLUMN postponed_until DATETIME'))
                log.info("✅ Добавлена колонка postponed_until в reminders")
            
            if 'retry_count' not in columns:
                db.execute(text('ALTER TABLE reminders ADD COLUMN retry_count INTEGER DEFAULT 0'))
                log.info("✅ Добавлена колонка retry_count в reminders")
            
            if 'last_error' not in columns:
                db.execute(text('ALTER TABLE reminders ADD COLUMN last_error TEXT'))
                log.info("✅ Добавлена колонка last_error в reminders")
        
        # Миграция таблицы medicine_logs
        if 'medicine_logs' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('medicine_logs')]
            
            if 'is_planned' not in columns:
                db.execute(text('ALTER TABLE medicine_logs ADD COLUMN is_planned BOOLEAN DEFAULT 1'))
                log.info("✅ Добавлена колонка is_planned в medicine_logs")
            
            if 'dosage' not in columns:
                db.execute(text('ALTER TABLE medicine_logs ADD COLUMN dosage VARCHAR(50)'))
                log.info("✅ Добавлена колонка dosage в medicine_logs")
            
            if 'comment' not in columns:
                db.execute(text('ALTER TABLE medicine_logs ADD COLUMN comment TEXT'))
                log.info("✅ Добавлена колонка comment в medicine_logs")
            
            if 'course_info' not in columns:
                db.execute(text('ALTER TABLE medicine_logs ADD COLUMN course_info TEXT'))
                log.info("✅ Добавлена колонка course_info в medicine_logs")
        
        # Миграция таблицы users
        if 'users' in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns('users')]
            
            if 'is_admin' not in columns:
                db.execute(text('ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0'))
                log.info("✅ Добавлена колонка is_admin в users")
            
            if 'language' not in columns:
                db.execute(text('ALTER TABLE users ADD COLUMN language VARCHAR(10) DEFAULT "ru"'))
                log.info("✅ Добавлена колонка language в users")
            
            if 'total_interactions' not in columns:
                db.execute(text('ALTER TABLE users ADD COLUMN total_interactions INTEGER DEFAULT 0'))
                log.info("✅ Добавлена колонка total_interactions в users")
        
        db.commit()
        log.info("✅ Миграция базы данных завершена успешно")
        
    except Exception as e:
        log.error(f"❌ Ошибка при миграции БД: {e}")
        db.rollback()
    finally:
        db.close()

# ============== СОЕДИНЕНИЕ С БД ==============

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    """Инициализация базы данных."""
    # Создаем таблицы
    Base.metadata.create_all(bind=engine)
    log.info("✅ Таблицы созданы/проверены")
    
    # Запускаем миграцию
    migrate_database()

init_db()

def get_db():
    """Получение сессии БД."""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

# ============== RATE LIMITER ==============

class RateLimiter:
    def __init__(self, global_rate: int = 30, per_user_rate: int = 1):
        self.global_semaphore = asyncio.Semaphore(global_rate)
        self.per_user_rate = per_user_rate
        self.user_last_message = defaultdict(float)
    
    async def acquire(self, user_id: Optional[int] = None):
        await self.global_semaphore.acquire()
        if user_id:
            now = time.time()
            last = self.user_last_message[user_id]
            if now - last < self.per_user_rate:
                await asyncio.sleep(self.per_user_rate - (now - last))
            self.user_last_message[user_id] = now

rate_limiter = RateLimiter()

# ============== ПЛАНИРОВЩИК ==============

class PersistentScheduler:
    def __init__(self):
        jobstores = {'default': SQLAlchemyJobStore(url=JOB_STORE_URL)}
        executors = {'default': AsyncIOExecutor()}
        job_defaults = {
            'coalesce': True,
            'max_instances': 3,
            'misfire_grace_time': 3600
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=pytz.UTC
        )
    
    def start(self):
        self.scheduler.start()
        log.info("SCHEDULER - Планировщик запущен")
    
    def shutdown(self):
        self.scheduler.shutdown()
        log.info("SCHEDULER - Планировщик остановлен")
    
    async def restore_reminders(self):
        db = get_db()
        try:
            now = datetime.now(pytz.UTC)
            pending = db.query(Reminder).filter(
                Reminder.status == 'pending',
                Reminder.scheduled_time > now
            ).all()
            
            for reminder in pending:
                job_id = f"{reminder.reminder_type}_{reminder.id}"
                try:
                    self.scheduler.remove_job(job_id)
                except JobLookupError:
                    pass
                
                self.scheduler.add_job(
                    send_reminder_job,
                    trigger=DateTrigger(run_date=reminder.scheduled_time),
                    id=job_id,
                    args=[reminder.id],
                    replace_existing=True
                )
            
            log.info(f"RESTORE - Восстановлено {len(pending)} напоминаний")
            return len(pending)
        finally:
            db.close()

scheduler = PersistentScheduler()

# ============== ФУНКЦИИ ДЛЯ РАБОТЫ С ЧАСОВЫМИ ПОЯСАМИ ==============

def get_user_timezone(user_id: int) -> str:
    db = get_db()
    try:
        user_tz = db.query(UserTimezone).filter_by(user_id=user_id).first()
        return user_tz.timezone if user_tz else 'Europe/Moscow'
    finally:
        db.close()

def set_user_timezone(user_id: int, timezone: str):
    db = get_db()
    try:
        user_tz = db.query(UserTimezone).filter_by(user_id=user_id).first()
        if user_tz:
            user_tz.timezone = timezone
        else:
            user_tz = UserTimezone(user_id=user_id, timezone=timezone)
            db.add(user_tz)
        db.commit()
    finally:
        db.close()

def local_to_utc(local_time_str: str, tz: str, base: datetime = None) -> datetime:
    if base is None:
        base = datetime.now(pytz.timezone(tz))
    
    h, m = map(int, local_time_str.split(':'))
    local = base.replace(hour=h, minute=m, second=0, microsecond=0)
    if not local.tzinfo:
        local = pytz.timezone(tz).localize(local)
    
    return local.astimezone(pytz.UTC)

def local_to_utc_safe(local_time_str: str, tz: str, base: datetime = None) -> datetime:
    utc = local_to_utc(local_time_str, tz, base)
    if utc < datetime.now(pytz.UTC):
        utc += timedelta(days=1)
        log.info("Время приема скорректировано на следующий день")
    return utc

def utc_to_local(utc: datetime, tz: str) -> datetime:
    if utc.tzinfo is None:
        utc = pytz.UTC.localize(utc)
    return utc.astimezone(pytz.timezone(tz))

def parse_date(date_str: str, tz: str) -> Optional[datetime]:
    try:
        fmts = ['%d.%m.%Y', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%y', '%Y-%m-%d']
        for fmt in fmts:
            try:
                dt = datetime.strptime(date_str, fmt).replace(hour=12)
                return pytz.timezone(tz).localize(dt)
            except:
                continue
    except:
        pass
    return None

def check_existing_analysis(user_id: int, date: datetime, time: str) -> bool:
    db = get_db()
    try:
        if date.tzinfo is None:
            date = pytz.UTC.localize(date)
        exists = db.query(Analysis).filter(
            Analysis.user_id == user_id,
            Analysis.status == 'pending',
            func.date(Analysis.scheduled_date) == func.date(date),
            Analysis.scheduled_time == time
        ).first()
        return exists is not None
    finally:
        db.close()

# ============== КЛАВИАТУРЫ ==============

def get_main_menu_button():
    return [InlineKeyboardButton("🏠 Главная", callback_data="start")]

def get_start_keyboard():
    keyboard = [
        [InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")],
        [InlineKeyboardButton("📋 Список лекарств", callback_data="list_medicines")],
        [InlineKeyboardButton("💊 Принять препарат", callback_data="extra_medicine")],
        [InlineKeyboardButton("🩺 Добавить анализ/исследование", callback_data="add_analysis")],
        [InlineKeyboardButton("📋 Список анализов/исследований", callback_data="list_analyses")],
        [InlineKeyboardButton("📊 Самочувствие", callback_data="mood")],
        [InlineKeyboardButton("📈 Статистика", callback_data="stats")],
        [InlineKeyboardButton("👨‍⚕️ О враче", callback_data="about")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_about_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Telegram канал", url="https://t.me/KAZARIN_LOR")],
        [InlineKeyboardButton("👨‍⚕️ Мой Telegram", url="https://t.me/deniskazarin")],
        [InlineKeyboardButton("🏥 КИТ-клиника", url=KIT_CLINIC['site'])],
        [
            InlineKeyboardButton("📞 Позвонить в КИТ", callback_data="phone_kit"),
            InlineKeyboardButton("🗺️ Карты КИТ", url=KIT_CLINIC['maps'])
        ],
        [InlineKeyboardButton("🏥 Семейная клиника", url=FAMILY_CLINIC['site'])],
        [
            InlineKeyboardButton("📞 Позвонить в Семейную", callback_data="phone_family"),
            InlineKeyboardButton("🗺️ Карты Семейной", url=FAMILY_CLINIC['maps'])
        ],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="start"),
            get_main_menu_button()[0]
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_hour_keyboard(prefix: str, back_callback: str):
    """Клавиатура для выбора часа."""
    keyboard = []
    hours = list(range(0, 24))
    row = []
    for h in hours:
        row.append(InlineKeyboardButton(f"{h:02d}", callback_data=f"{prefix}_hour_{h:02d}"))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=back_callback)])
    keyboard.append(get_main_menu_button())
    
    return InlineKeyboardMarkup(keyboard)

def get_minute_keyboard(prefix: str, hour: str, back_callback: str):
    """Клавиатура для выбора минуты."""
    keyboard = []
    minutes = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]
    row = []
    for m in minutes:
        row.append(InlineKeyboardButton(f"{m:02d}", callback_data=f"{prefix}_minute_{hour}_{m:02d}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 К выбору часа", callback_data=back_callback)])
    keyboard.append(get_main_menu_button())
    
    return InlineKeyboardMarkup(keyboard)

def get_simple_date_keyboard():
    """Простая клавиатура для выбора даты."""
    today = datetime.now()
    keyboard = []
    
    for i in range(3):
        date = today + timedelta(days=i)
        date_str = date.strftime('%d.%m.%Y')
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][date.weekday()]
        keyboard.append([InlineKeyboardButton(
            f"{date_str} ({day_name})", 
            callback_data=f"analysis_date_{date_str}"
        )])
    
    keyboard.append([InlineKeyboardButton("📅 Своя дата", callback_data="analysis_date_custom")])
    keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data="start")])
    keyboard.append(get_main_menu_button())
    
    return InlineKeyboardMarkup(keyboard)

def get_medicine_inline_keyboard(medicine_id: int):
    keyboard = [
        [
            InlineKeyboardButton("✅ Принял(а)", callback_data=f"take_{medicine_id}"),
            InlineKeyboardButton("📝 Комментарий", callback_data=f"comment_{medicine_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустить", callback_data=f"skip_{medicine_id}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_medicine_{medicine_id}"),
        ],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_analysis_inline_keyboard(analysis_id: int):
    keyboard = [
        [
            InlineKeyboardButton("✅ Сдал(а)", callback_data=f"analysis_take_{analysis_id}"),
            InlineKeyboardButton("📝 Заметки", callback_data=f"analysis_notes_{analysis_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустить", callback_data=f"analysis_skip_{analysis_id}"),
            InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_analysis_{analysis_id}"),
        ],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_mood_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("1 😢", callback_data="mood_1"),
            InlineKeyboardButton("2 🙁", callback_data="mood_2"),
            InlineKeyboardButton("3 😐", callback_data="mood_3"),
            InlineKeyboardButton("4 🙂", callback_data="mood_4"),
            InlineKeyboardButton("5 😊", callback_data="mood_5"),
        ],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_timezone_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Москва (UTC+3)", callback_data="tz_Europe/Moscow"),
            InlineKeyboardButton("СПб (UTC+3)", callback_data="tz_Europe/Moscow"),
        ],
        [
            InlineKeyboardButton("Калининград (UTC+2)", callback_data="tz_Europe/Kaliningrad"),
            InlineKeyboardButton("Самара (UTC+4)", callback_data="tz_Europe/Samara"),
        ],
        [
            InlineKeyboardButton("Екатеринбург (UTC+5)", callback_data="tz_Asia/Yekaterinburg"),
            InlineKeyboardButton("Омск (UTC+6)", callback_data="tz_Asia/Omsk"),
        ],
        [
            InlineKeyboardButton("Красноярск (UTC+7)", callback_data="tz_Asia/Krasnoyarsk"),
            InlineKeyboardButton("Иркутск (UTC+8)", callback_data="tz_Asia/Irkutsk"),
        ],
        [get_main_menu_button()[0]]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_stats_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 За неделю", callback_data="stats_week"),
            InlineKeyboardButton("📊 За месяц", callback_data="stats_month"),
        ],
        [
            InlineKeyboardButton("📊 За все время", callback_data="stats_all"),
            InlineKeyboardButton("📊 Настроение", callback_data="stats_mood"),
        ],
        [
            InlineKeyboardButton("📊 Симптомы", callback_data="stats_symptoms"),
            InlineKeyboardButton("💊 Лекарства", callback_data="stats_medicine"),
        ],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("📈 Логи активности", callback_data="admin_logs")],
        [InlineKeyboardButton("🚫 Бан-лист", callback_data="admin_bans")],
        [InlineKeyboardButton("📨 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📁 Бэкапы", callback_data="admin_backups")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_settings")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_users_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Список пользователей", callback_data="admin_users_list")],
        [InlineKeyboardButton("🚫 Заблокированные", callback_data="admin_users_banned")],
        [InlineKeyboardButton("👑 Администраторы", callback_data="admin_users_admins")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_logs_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Последние ошибки", callback_data="admin_logs_errors")],
        [InlineKeyboardButton("📊 Статистика за день", callback_data="admin_logs_today")],
        [InlineKeyboardButton("📁 Скачать файлы логов", callback_data="admin_logs_files")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_backups_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔄 Создать бэкап", callback_data="admin_backup_create")],
        [InlineKeyboardButton("📋 Список бэкапов", callback_data="admin_backup_list")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

# ============== СОСТОЯНИЯ CONVERSATION HANDLER ==============

(
    MEDICINE_NAME, 
    MEDICINE_TIME_HOUR, 
    MEDICINE_TIME_MINUTE,
    MEDICINE_CONFIRM,
    ANALYSIS_NAME, 
    ANALYSIS_DATE,
    ANALYSIS_TIME_HOUR, 
    ANALYSIS_TIME_MINUTE,
    ANALYSIS_CONFIRM,
    SYMPTOM_TEXT, 
    SYMPTOM_SEVERITY,
    EXTRA_MEDICINE_SELECT,
    ADMIN_BROADCAST_MESSAGE,
    ADMIN_BROADCAST_CONFIRM
) = range(14)

# ============== ОБРАБОТЧИКИ КОМАНД ==============

async def register_user(update: Update) -> bool:
    """Регистрация пользователя."""
    user = update.effective_user
    db = get_db()
    try:
        existing = db.query(User).filter_by(user_id=user.id).first()
        if not existing:
            new_user = User(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            db.add(new_user)
            db.commit()
            log.info(f"🎉 Новый пользователь: {user.first_name} (@{user.username})", update=update)
            return True
        else:
            existing.last_activity = datetime.now(pytz.UTC)
            existing.total_interactions += 1
            if user.username:
                existing.username = user.username
            db.commit()
            return False
    finally:
        db.close()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    await register_user(update)
    
    text = f"""👋 Здравствуйте, {update.effective_user.first_name}!

Я ЛОР-Помощник — персональный медицинский бот.

👶 Врач ведет прием детей с 0 лет и взрослых

📖 *Возможности:*
• 💊 Напоминания о лекарствах
• 🩺 Напоминания об анализах
• 📊 Отслеживание самочувствия
• 📈 Статистика

Выберите действие в меню ниже:"""
    
    await update.message.reply_text(text, reply_markup=get_start_keyboard(), parse_mode=None)
    log.info("✅ /start обработан", update=update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    text = """❓ *Помощь*

• /start - Главное меню
• /admin - Панель администратора (только для админов)

Чтобы очистить историю: нажмите на профиль → Еще → Удалить переписку"""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_about_keyboard(), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=get_about_keyboard(), parse_mode=None)
    log.info("✅ /help обработан", update=update)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /about."""
    text = DOCTOR_INFO + f"""

📍 КИТ-клиника:
{KIT_CLINIC['address']}
📞 {KIT_CLINIC['phone_display']}

📍 Семейная клиника:
{FAMILY_CLINIC['address']}
📞 {FAMILY_CLINIC['phone_display']}"""

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_about_keyboard(), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=get_about_keyboard(), parse_mode=None)
    log.info("✅ /about обработан", update=update)

# ============== АДМИН-КОМАНДЫ ==============

@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора."""
    await update.message.reply_text(
        "🔐 *Панель администратора*\n\nВыберите раздел:",
        reply_markup=get_admin_panel_keyboard(),
        parse_mode=None
    )
    log.info(f"🔐 Админ-панель открыта", update=update)

@admin_only
async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика бота."""
    query = update.callback_query
    await query.answer()
    
    db = get_db()
    try:
        total_users = db.query(User).count()
        active_today = db.query(User).filter(
            User.last_activity >= datetime.now(pytz.UTC) - timedelta(days=1)
        ).count()
        total_medicines = db.query(Medicine).filter(Medicine.status == 'active').count()
        total_analyses = db.query(Analysis).filter(Analysis.status == 'pending').count()
        
        text = f"""📊 *Статистика бота*

👥 *Пользователи:* {total_users}
📊 *Активных сегодня:* {active_today}
💊 *Активных лекарств:* {total_medicines}
🩺 *Запланированных анализов:* {total_analyses}"""
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]),
            parse_mode=None
        )
    finally:
        db.close()

@admin_only
async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление пользователями."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "👥 *Управление пользователями*\n\nВыберите действие:",
        reply_markup=get_admin_users_keyboard(),
        parse_mode=None
    )

@admin_only
async def admin_users_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей."""
    query = update.callback_query
    await query.answer()
    
    db = get_db()
    try:
        users = db.query(User).order_by(User.registered_at.desc()).limit(10).all()
        
        text = "📋 *Последние 10 пользователей:*\n\n"
        for u in users:
            date = u.registered_at.strftime('%d.%m.%Y')
            name = u.first_name or u.username or str(u.user_id)
            text += f"• {name} (ID: {u.user_id}) - {date}\n"
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_users")]]),
            parse_mode=None
        )
    finally:
        db.close()

@admin_only
async def admin_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр логов."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📈 *Просмотр логов*\n\nВыберите действие:",
        reply_markup=get_admin_logs_keyboard(),
        parse_mode=None
    )

@admin_only
async def admin_logs_errors_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Последние ошибки."""
    query = update.callback_query
    await query.answer()
    
    error_log = LOG_DIR / "error.log"
    if not error_log.exists():
        await query.edit_message_text("📭 Файл с ошибками пока пуст")
        return
    
    with open(error_log, 'r', encoding='utf-8') as f:
        lines = f.readlines()[-10:]
    
    if not lines:
        await query.edit_message_text("✅ Ошибок не обнаружено!")
        return
    
    text = "🚨 *Последние ошибки:*\n\n"
    for line in lines:
        if len(line) > 150:
            line = line[:150] + "..."
        text += f"`{line.strip()}`\n"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_logs")]]),
        parse_mode=None
    )

@admin_only
async def admin_backups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление бэкапами."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📁 *Управление бэкапами*\n\nВыберите действие:",
        reply_markup=get_admin_backups_keyboard(),
        parse_mode=None
    )

@admin_only
async def admin_backup_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание бэкапа."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔄 Создаю резервную копию...")
    backup_path = backup_manager.create_backup("manual")
    
    if backup_path:
        await query.edit_message_text(
            f"✅ Бэкап успешно создан!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_backups")]]),
            parse_mode=None
        )
    else:
        await query.edit_message_text("❌ Ошибка при создании бэкапа")

@admin_only
async def admin_backup_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список бэкапов."""
    query = update.callback_query
    await query.answer()
    
    backups = backup_manager.get_backups()
    
    if not backups:
        await query.edit_message_text("📭 Нет сохраненных бэкапов")
        return
    
    text = "📋 *Доступные бэкапы:*\n\n"
    for backup in backups[:5]:
        try:
            date = datetime.strptime(backup['timestamp'], '%Y%m%d_%H%M%S')
            date_str = date.strftime('%d.%m.%Y %H:%M')
        except:
            date_str = backup['timestamp']
        
        emoji = {'auto': '🤖', 'manual': '👤'}.get(backup['type'], '📦')
        text += f"{emoji} {date_str} - {backup['size_kb']:.0f} KB\n"
    
    text += f"\nВсего: {len(backups)} бэкапов"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_backups")]]),
        parse_mode=None
    )

# ============== ОБРАБОТЧИКИ ДОБАВЛЕНИЯ ЛЕКАРСТВ ==============

async def add_medicine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления лекарства."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    await query.edit_message_text(
        "💊 *Добавление лекарства*\n\nШаг 1/4: Введите название лекарства",
        parse_mode=None
    )
    return MEDICINE_NAME

async def add_medicine_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия."""
    context.user_data['medicine'] = {'name': update.message.text}
    
    await update.message.reply_text(
        "Шаг 2/4: Выберите час приема:",
        reply_markup=get_hour_keyboard("med", "start"),
        parse_mode=None
    )
    return MEDICINE_TIME_HOUR

async def add_medicine_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часа."""
    query = update.callback_query
    await query.answer()
    
    hour = query.data.replace("med_hour_", "")
    context.user_data['medicine']['hour'] = hour
    
    await query.edit_message_text(
        f"Вы выбрали час {hour}. Выберите минуты:",
        reply_markup=get_minute_keyboard("med", hour, "med_hour_back"),
        parse_mode=None
    )
    return MEDICINE_TIME_MINUTE

async def add_medicine_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор минуты."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("med_minute_", "")
    hour, minute = data.split('_')
    time_str = f"{hour}:{minute}"
    context.user_data['medicine']['time'] = time_str
    
    med = context.user_data['medicine']
    text = f"""✅ *Проверьте данные:*

💊 Название: {med['name']}
⏰ Время: {time_str}

Всё верно?"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Добавить", callback_data="confirm_medicine"),
            InlineKeyboardButton("✏️ Заново", callback_data="add_medicine"),
        ],
        get_main_menu_button()
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )
    return MEDICINE_CONFIRM

async def add_medicine_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение добавления."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    med = context.user_data.get('medicine', {})
    
    if not med or 'name' not in med or 'time' not in med:
        await query.edit_message_text(
            "❌ Ошибка данных. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        return ConversationHandler.END
    
    db = get_db()
    try:
        # Сохраняем лекарство
        medicine = Medicine(
            user_id=user_id,
            name=med['name'],
            schedule=med['time'],
            start_date=datetime.now(pytz.UTC),
            user_timezone=get_user_timezone(user_id),
            course_type='unlimited'
        )
        db.add(medicine)
        db.flush()
        
        # Создаем напоминание на сегодня
        tz = pytz.timezone(get_user_timezone(user_id))
        now = datetime.now(tz)
        h, m = map(int, med['time'].split(':'))
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        
        # Если время уже прошло, переносим на завтра
        if scheduled < now:
            scheduled += timedelta(days=1)
        
        reminder = Reminder(
            user_id=user_id,
            reminder_type='medicine',
            item_id=medicine.id,
            scheduled_time=scheduled.astimezone(pytz.UTC),
            user_timezone=get_user_timezone(user_id)
        )
        db.add(reminder)
        db.commit()
        
        # Планируем задание
        scheduler.scheduler.add_job(
            send_reminder_job,
            trigger=DateTrigger(run_date=scheduled.astimezone(pytz.UTC)),
            id=f"medicine_{reminder.id}",
            args=[reminder.id],
            replace_existing=True
        )
        
        await query.edit_message_text(
            f"✅ Лекарство '{med['name']}' добавлено!\nНапоминание в {med['time']}",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        log.info(f"✅ Лекарство добавлено: {med['name']}", update=update)
        
    except Exception as e:
        db.rollback()
        log.error(f"❌ Ошибка добавления лекарства: {e}", update=update, exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при добавлении лекарства",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END

# ============== ОБРАБОТЧИКИ ДОБАВЛЕНИЯ АНАЛИЗОВ ==============

async def add_analysis_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления анализа."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    await query.edit_message_text(
        "🩺 *Добавление анализа/исследования*\n\nШаг 1/4: Введите название",
        parse_mode=None
    )
    return ANALYSIS_NAME

async def add_analysis_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия."""
    context.user_data['analysis'] = {'name': update.message.text}
    
    await update.message.reply_text(
        "Шаг 2/4: Выберите дату:",
        reply_markup=get_simple_date_keyboard(),
        parse_mode=None
    )
    return ANALYSIS_DATE

async def add_analysis_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор даты."""
    user_id = update.effective_user.id
    tz = get_user_timezone(user_id)
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        if query.data == "analysis_date_custom":
            await query.edit_message_text(
                "Введите дату в формате ДД.ММ.ГГГГ:",
                parse_mode=None
            )
            return ANALYSIS_DATE
        
        if query.data == "analysis_date_back":
            return await add_analysis_start(update, context)
        
        date_str = query.data.replace("analysis_date_", "")
        try:
            date = datetime.strptime(date_str, '%d.%m.%Y')
            date = pytz.timezone(tz).localize(date.replace(hour=12))
            context.user_data['analysis']['date'] = date
        except:
            await query.edit_message_text("❌ Неверный формат даты")
            return ANALYSIS_DATE
    else:
        date = parse_date(update.message.text.strip(), tz)
        if not date:
            await update.message.reply_text("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")
            return ANALYSIS_DATE
        context.user_data['analysis']['date'] = date
    
    # Переходим к выбору времени
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Шаг 3/4: Выберите час:",
            reply_markup=get_hour_keyboard("ana", "analysis_date_back"),
            parse_mode=None
        )
    else:
        await update.message.reply_text(
            "Шаг 3/4: Выберите час:",
            reply_markup=get_hour_keyboard("ana", "analysis_date_back"),
            parse_mode=None
        )
    return ANALYSIS_TIME_HOUR

async def add_analysis_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часа."""
    query = update.callback_query
    await query.answer()
    
    hour = query.data.replace("ana_hour_", "")
    context.user_data['analysis']['hour'] = hour
    
    await query.edit_message_text(
        f"Вы выбрали час {hour}. Выберите минуты:",
        reply_markup=get_minute_keyboard("ana", hour, "ana_hour_back"),
        parse_mode=None
    )
    return ANALYSIS_TIME_MINUTE

async def add_analysis_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор минуты."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("ana_minute_", "")
    hour, minute = data.split('_')
    time_str = f"{hour}:{minute}"
    context.user_data['analysis']['time'] = time_str
    
    ana = context.user_data['analysis']
    date_str = ana['date'].strftime('%d.%m.%Y')
    
    text = f"""✅ *Проверьте данные:*

🩺 Название: {ana['name']}
📅 Дата: {date_str}
⏰ Время: {time_str}

Всё верно?"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Добавить", callback_data="confirm_analysis"),
            InlineKeyboardButton("✏️ Заново", callback_data="add_analysis"),
        ],
        get_main_menu_button()
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )
    return ANALYSIS_CONFIRM

async def add_analysis_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение добавления."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    ana = context.user_data.get('analysis', {})
    
    if not ana or 'name' not in ana or 'date' not in ana or 'time' not in ana:
        await query.edit_message_text(
            "❌ Ошибка данных. Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        return ConversationHandler.END
    
    db = get_db()
    try:
        h, m = map(int, ana['time'].split(':'))
        dt = ana['date'].replace(hour=h, minute=m)
        
        analysis = Analysis(
            user_id=user_id,
            name=ana['name'],
            scheduled_date=dt,
            scheduled_time=ana['time'],
            user_timezone=get_user_timezone(user_id)
        )
        db.add(analysis)
        db.flush()
        
        # Напоминание за 2 часа
        remind_time = dt - timedelta(hours=2)
        if remind_time > datetime.now(pytz.UTC):
            reminder = Reminder(
                user_id=user_id,
                reminder_type='analysis',
                item_id=analysis.id,
                scheduled_time=remind_time,
                user_timezone=get_user_timezone(user_id)
            )
            db.add(reminder)
            db.flush()
            
            scheduler.scheduler.add_job(
                send_reminder_job,
                trigger=DateTrigger(run_date=remind_time),
                id=f"analysis_{reminder.id}",
                args=[reminder.id],
                replace_existing=True
            )
        
        db.commit()
        
        await query.edit_message_text(
            f"✅ Анализ '{ana['name']}' добавлен!",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        log.info(f"✅ Анализ добавлен: {ana['name']}", update=update)
        
    except Exception as e:
        db.rollback()
        log.error(f"❌ Ошибка добавления анализа: {e}", update=update, exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при добавлении анализа",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END

# ============== ОБРАБОТЧИКИ СПИСКОВ ==============

async def list_medicines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список лекарств."""
    user_id = update.effective_user.id
    
    query = update.callback_query
    if query:
        await query.answer()
    
    db = get_db()
    try:
        medicines = db.query(Medicine).filter(
            Medicine.user_id == user_id,
            Medicine.status == 'active'
        ).order_by(Medicine.created_at.desc()).all()
        
        if not medicines:
            text = "📋 У вас нет активных лекарств"
            keyboard = [
                [InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")],
                get_main_menu_button()
            ]
        else:
            text = "📋 Ваши лекарства:\n\n"
            keyboard = []
            for i, m in enumerate(medicines, 1):
                text += f"{i}. {m.name}\n   ⏰ {m.schedule}\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {m.name}", callback_data=f"delete_medicine_{m.id}")])
            keyboard.append([InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")])
            keyboard.append(get_main_menu_button())
        
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    finally:
        db.close()

async def list_analyses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список анализов."""
    user_id = update.effective_user.id
    
    query = update.callback_query
    if query:
        await query.answer()
    
    db = get_db()
    try:
        analyses = db.query(Analysis).filter(
            Analysis.user_id == user_id,
            Analysis.status == 'pending'
        ).order_by(Analysis.scheduled_date.asc()).all()
        
        if not analyses:
            text = "📋 У вас нет запланированных анализов"
            keyboard = [
                [InlineKeyboardButton("🩺 Добавить анализ", callback_data="add_analysis")],
                get_main_menu_button()
            ]
        else:
            text = "📋 Запланированные анализы:\n\n"
            keyboard = []
            now = datetime.now(pytz.UTC)
            for i, a in enumerate(analyses, 1):
                local = utc_to_local(a.scheduled_date, a.user_timezone)
                text += f"{i}. {a.name}\n   📅 {local.strftime('%d.%m.%Y %H:%M')}\n"
                keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {a.name}", callback_data=f"delete_analysis_{a.id}")])
            keyboard.append([InlineKeyboardButton("🩺 Добавить анализ", callback_data="add_analysis")])
            keyboard.append(get_main_menu_button())
        
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    finally:
        db.close()

async def delete_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление лекарства."""
    query = update.callback_query
    await query.answer()
    
    med_id = int(query.data.replace("delete_medicine_", ""))
    
    db = get_db()
    try:
        med = db.query(Medicine).filter_by(id=med_id).first()
        if med:
            med.status = 'deleted'
            for r in db.query(Reminder).filter(
                Reminder.item_id == med_id,
                Reminder.reminder_type == 'medicine',
                Reminder.status.in_(['pending', 'sent'])
            ):
                r.status = 'cancelled'
                try:
                    scheduler.scheduler.remove_job(f"medicine_{r.id}")
                except:
                    pass
            db.commit()
            await query.edit_message_text(f"✅ Лекарство {med.name} удалено", reply_markup=InlineKeyboardMarkup([get_main_menu_button()]))
    finally:
        db.close()

async def delete_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление анализа."""
    query = update.callback_query
    await query.answer()
    
    ana_id = int(query.data.replace("delete_analysis_", ""))
    
    db = get_db()
    try:
        ana = db.query(Analysis).filter_by(id=ana_id).first()
        if ana:
            ana.status = 'cancelled'
            for r in db.query(Reminder).filter(
                Reminder.item_id == ana_id,
                Reminder.reminder_type == 'analysis',
                Reminder.status.in_(['pending', 'sent'])
            ):
                r.status = 'cancelled'
                try:
                    scheduler.scheduler.remove_job(f"analysis_{r.id}")
                except:
                    pass
            db.commit()
            await query.edit_message_text(f"✅ Анализ {ana.name} удален", reply_markup=InlineKeyboardMarkup([get_main_menu_button()]))
    finally:
        db.close()

# ============== ОБРАБОТЧИКИ САМОЧУВСТВИЯ ==============

async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оценка настроения."""
    text = "📊 Как вы себя чувствуете сегодня?\n\nОцените по 5-балльной шкале:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_mood_keyboard(), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=get_mood_keyboard(), parse_mode=None)

async def mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение оценки."""
    query = update.callback_query
    await query.answer()
    
    score = int(query.data.replace("mood_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        mood = MoodLog(user_id=user_id, mood_score=score)
        db.add(mood)
        db.commit()
        
        texts = {1: "😢 Очень плохо", 2: "🙁 Плохо", 3: "😐 Нормально", 4: "🙂 Хорошо", 5: "😊 Отлично"}
        local = utc_to_local(mood.created_at, get_user_timezone(user_id))
        
        await query.edit_message_text(
            f"✅ {texts[score]}\n📅 {local.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

# ============== ОБРАБОТЧИКИ СТАТИСТИКИ ==============

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда статистики."""
    text = "📈 *Статистика*\n\nВыберите тип статистики:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_stats_keyboard(), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=get_stats_keyboard(), parse_mode=None)

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора статистики."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    tz = get_user_timezone(user_id)
    db = get_db()
    
    try:
        if query.data == "stats_week":
            week_ago = datetime.now(pytz.UTC) - timedelta(days=7)
            
            mood = db.query(MoodLog).filter(
                MoodLog.user_id == user_id,
                MoodLog.created_at >= week_ago
            ).all()
            
            symptoms = db.query(SymptomLog).filter(
                SymptomLog.user_id == user_id,
                SymptomLog.created_at >= week_ago
            ).all()
            
            avg_mood = sum(m.mood_score for m in mood) / len(mood) if mood else 0
            
            text = f"""📊 *Статистика за неделю*

😊 Настроение: {len(mood)} записей, среднее {avg_mood:.1f}/5
🩺 Симптомы: {len(symptoms)} записей"""
            
        elif query.data == "stats_month":
            month_ago = datetime.now(pytz.UTC) - timedelta(days=30)
            
            mood = db.query(MoodLog).filter(
                MoodLog.user_id == user_id,
                MoodLog.created_at >= month_ago
            ).all()
            
            avg_mood = sum(m.mood_score for m in mood) / len(mood) if mood else 0
            
            text = f"""📊 *Статистика за месяц*

😊 Настроение: {len(mood)} записей, среднее {avg_mood:.1f}/5"""
            
        elif query.data == "stats_all":
            mood = db.query(MoodLog).filter(MoodLog.user_id == user_id).all()
            symptoms = db.query(SymptomLog).filter(SymptomLog.user_id == user_id).all()
            
            avg_mood = sum(m.mood_score for m in mood) / len(mood) if mood else 0
            
            text = f"""📊 *Вся статистика*

😊 Настроение: {len(mood)} записей, среднее {avg_mood:.1f}/5
🩺 Симптомы: {len(symptoms)} записей"""
            
        elif query.data == "stats_mood":
            mood = db.query(MoodLog).filter(
                MoodLog.user_id == user_id
            ).order_by(MoodLog.created_at.desc()).limit(10).all()
            
            if not mood:
                await query.edit_message_text("📊 Нет данных о настроении")
                return
            
            text = "📈 *Последние оценки настроения:*\n\n"
            for m in mood:
                local = utc_to_local(m.created_at, tz)
                emoji = "😢" if m.mood_score <=2 else "😐" if m.mood_score==3 else "😊"
                text += f"{local.strftime('%d.%m %H:%M')}: {emoji} {m.mood_score}/5\n"
            
        elif query.data == "stats_symptoms":
            symptoms = db.query(SymptomLog).filter(
                SymptomLog.user_id == user_id
            ).order_by(SymptomLog.created_at.desc()).limit(10).all()
            
            if not symptoms:
                await query.edit_message_text("📊 Нет данных о симптомах")
                return
            
            text = "🩺 *Последние симптомы:*\n\n"
            for s in symptoms:
                local = utc_to_local(s.created_at, tz)
                text += f"{local.strftime('%d.%m %H:%M')}: {s.symptom} ({s.severity}/5)\n"
            
        elif query.data == "stats_medicine":
            meds = db.query(MedicineLog).filter(
                MedicineLog.user_id == user_id
            ).order_by(MedicineLog.taken_at.desc()).limit(10).all()
            
            if not meds:
                await query.edit_message_text("📊 Нет данных о лекарствах")
                return
            
            text = "💊 *Последние приемы лекарств:*\n\n"
            for m in meds:
                local = utc_to_local(m.taken_at, tz)
                status = "✅" if m.status in ['taken', 'extra'] else "❌"
                plan = "📅" if m.is_planned else "➕"
                medicine = db.query(Medicine).filter_by(id=m.medicine_id).first()
                name = medicine.name if medicine else "Неизвестно"
                text += f"{local.strftime('%d.%m %H:%M')}: {status}{plan} {name}\n"
        else:
            text = "📈 Выберите тип статистики"
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        
    except Exception as e:
        log.error(f"STATS ERROR: {e}")
        await query.edit_message_text("❌ Ошибка при получении статистики")
    finally:
        db.close()

# ============== ОБРАБОТЧИКИ НАПОМИНАНИЙ ==============

async def send_reminder_job(reminder_id: int):
    """Отправка напоминания."""
    global application
    
    db = get_db()
    try:
        reminder = db.query(Reminder).filter_by(id=reminder_id).first()
        if not reminder or reminder.status != 'pending':
            return
        
        user_id = reminder.user_id
        
        if reminder.reminder_type == 'medicine':
            medicine = db.query(Medicine).filter_by(id=reminder.item_id).first()
            if not medicine or medicine.status != 'active':
                reminder.status = 'cancelled'
                db.commit()
                return
            
            text = f"💊 Время принять лекарство!\n\n{medicine.name}"
            keyboard = get_medicine_inline_keyboard(medicine.id)
            
        elif reminder.reminder_type == 'analysis':
            analysis = db.query(Analysis).filter_by(id=reminder.item_id).first()
            if not analysis or analysis.status != 'pending':
                reminder.status = 'cancelled'
                db.commit()
                return
            
            local = utc_to_local(analysis.scheduled_date, analysis.user_timezone)
            text = f"🩺 Напоминание об анализе!\n\n{analysis.name}\n📅 {local.strftime('%d.%m.%Y %H:%M')}"
            if analysis.notes:
                text += f"\n\n📝 Заметки: {analysis.notes}"
            
            keyboard = get_analysis_inline_keyboard(analysis.id)
        else:
            return
        
        await rate_limiter.acquire(user_id)
        await application.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=None
        )
        
        reminder.status = 'sent'
        db.commit()
        log.info(f"✅ Напоминание {reminder_id} отправлено {user_id}")
        
    except Exception as e:
        log.error(f"❌ Ошибка отправки {reminder_id}: {e}")
    finally:
        db.close()

async def medicine_take(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прием лекарства."""
    query = update.callback_query
    await query.answer()
    
    med_id = int(query.data.replace("take_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        med = db.query(Medicine).filter_by(id=med_id).first()
        log_entry = MedicineLog(
            medicine_id=med_id,
            user_id=user_id,
            status='taken',
            is_planned=True
        )
        db.add(log_entry)
        
        rem = db.query(Reminder).filter(
            Reminder.item_id == med_id,
            Reminder.reminder_type == 'medicine',
            Reminder.status == 'sent'
        ).order_by(Reminder.scheduled_time.desc()).first()
        if rem:
            rem.status = 'completed'
        
        db.commit()
        
        await query.edit_message_text(
            f"✅ Отлично! Прием {med.name} отмечен.",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

async def medicine_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск приема."""
    query = update.callback_query
    await query.answer()
    
    med_id = int(query.data.replace("skip_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        med = db.query(Medicine).filter_by(id=med_id).first()
        log_entry = MedicineLog(
            medicine_id=med_id,
            user_id=user_id,
            status='skipped',
            is_planned=True
        )
        db.add(log_entry)
        
        rem = db.query(Reminder).filter(
            Reminder.item_id == med_id,
            Reminder.reminder_type == 'medicine',
            Reminder.status == 'sent'
        ).order_by(Reminder.scheduled_time.desc()).first()
        if rem:
            rem.status = 'skipped'
        
        db.commit()
        
        await query.edit_message_text(
            f"❌ Прием {med.name} пропущен",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

async def analysis_take(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сдача анализа."""
    query = update.callback_query
    await query.answer()
    
    ana_id = int(query.data.replace("analysis_take_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        ana = db.query(Analysis).filter_by(id=ana_id).first()
        log_entry = AnalysisLog(
            analysis_id=ana_id,
            user_id=user_id,
            status='completed'
        )
        db.add(log_entry)
        
        if ana:
            ana.status = 'completed'
        
        rem = db.query(Reminder).filter(
            Reminder.item_id == ana_id,
            Reminder.reminder_type == 'analysis',
            Reminder.status == 'sent'
        ).order_by(Reminder.scheduled_time.desc()).first()
        if rem:
            rem.status = 'completed'
        
        db.commit()
        
        await query.edit_message_text(
            f"✅ Отлично! Анализ {ana.name} отмечен.",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

async def analysis_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск анализа."""
    query = update.callback_query
    await query.answer()
    
    ana_id = int(query.data.replace("analysis_skip_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        ana = db.query(Analysis).filter_by(id=ana_id).first()
        log_entry = AnalysisLog(
            analysis_id=ana_id,
            user_id=user_id,
            status='skipped'
        )
        db.add(log_entry)
        
        if ana:
            ana.status = 'skipped'
        
        rem = db.query(Reminder).filter(
            Reminder.item_id == ana_id,
            Reminder.reminder_type == 'analysis',
            Reminder.status == 'sent'
        ).order_by(Reminder.scheduled_time.desc()).first()
        if rem:
            rem.status = 'skipped'
        
        db.commit()
        
        await query.edit_message_text(
            f"❌ Анализ {ana.name} пропущен",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

# ============== ПРОВЕРКА ЦЕЛОСТНОСТИ ==============

async def integrity_check(context: ContextTypes.DEFAULT_TYPE):
    """Ежечасная проверка целостности."""
    db = get_db()
    try:
        now = datetime.now(pytz.UTC)
        
        # Восстановление пауз
        for med in db.query(Medicine).filter(
            Medicine.paused_until.isnot(None),
            Medicine.paused_until <= now,
            Medicine.status == 'active'
        ):
            med.paused_until = None
            log.info(f"🔄 Возобновлено лекарство {med.id}")
        
        for ana in db.query(Analysis).filter(
            Analysis.paused_until.isnot(None),
            Analysis.paused_until <= now,
            Analysis.status == 'pending'
        ):
            ana.paused_until = None
            log.info(f"🔄 Возобновлен анализ {ana.id}")
        
        db.commit()
        
        # Проверка просроченных
        overdue = db.query(Reminder).filter(
            Reminder.status == 'pending',
            Reminder.scheduled_time <= now
        ).all()
        
        for rem in overdue:
            rem.status = 'failed'
            rem.last_error = 'Overdue'
            log.warning(f"⚠️ Просроченное напоминание {rem.id}")
        
        db.commit()
        
    finally:
        db.close()

# ============== ОБРАБОТЧИК КНОПОК ==============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик кнопок."""
    query = update.callback_query
    data = query.data
    
    # Навигация
    if data == "start":
        await start_callback(update, context)
    elif data == "help":
        await help_command(update, context)
    elif data == "about":
        await about_command(update, context)
    elif data == "stats":
        await stats_command(update, context)
    elif data.startswith("stats_"):
        await stats_callback(update, context)
    
    # Основные функции
    elif data == "add_medicine":
        await add_medicine_start(update, context)
    elif data == "add_analysis":
        await add_analysis_start(update, context)
    elif data == "list_medicines":
        await list_medicines(update, context)
    elif data == "list_analyses":
        await list_analyses(update, context)
    elif data.startswith("delete_medicine_"):
        await delete_medicine(update, context)
    elif data.startswith("delete_analysis_"):
        await delete_analysis(update, context)
    
    # Самочувствие
    elif data == "mood":
        await mood_command(update, context)
    elif data.startswith("mood_"):
        await mood_callback(update, context)
    
    # Прием лекарств
    elif data.startswith("take_"):
        await medicine_take(update, context)
    elif data.startswith("skip_"):
        await medicine_skip(update, context)
    elif data.startswith("analysis_take_"):
        await analysis_take(update, context)
    elif data.startswith("analysis_skip_"):
        await analysis_skip(update, context)
    
    # Админ-панель
    elif data == "admin_panel":
        await admin_command(update, context)
    elif data == "admin_stats":
        await admin_stats_callback(update, context)
    elif data == "admin_users":
        await admin_users_callback(update, context)
    elif data == "admin_users_list":
        await admin_users_list_callback(update, context)
    elif data == "admin_logs":
        await admin_logs_callback(update, context)
    elif data == "admin_logs_errors":
        await admin_logs_errors_callback(update, context)
    elif data == "admin_backups":
        await admin_backups_callback(update, context)
    elif data == "admin_backup_create":
        await admin_backup_create_callback(update, context)
    elif data == "admin_backup_list":
        await admin_backup_list_callback(update, context)
    
    # Телефоны
    elif data == "phone_kit":
        await query.answer()
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"📞 Телефон КИТ-клиники: {KIT_CLINIC['phone_display']}\n\nНажмите на номер: {KIT_CLINIC['phone']}",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()])
        )
    elif data == "phone_family":
        await query.answer()
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"📞 Телефон Семейной клиники: {FAMILY_CLINIC['phone_display']}\n\nНажмите на номер: {FAMILY_CLINIC['phone']}",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()])
        )
    else:
        await query.answer("Функция в разработке")

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    await query.answer()
    
    text = f"""👋 Здравствуйте, {update.effective_user.first_name}!

Я ЛОР-Помощник — персональный медицинский бот.

👶 Врач ведет прием детей с 0 лет и взрослых

🤖 Мои возможности:
• 💊 Напоминания о лекарствах
• 🩺 Напоминания об анализах
• 📊 Отслеживание самочувствия
• 📈 Статистика

Выберите действие:"""
    
    await query.edit_message_text(text, reply_markup=get_start_keyboard(), parse_mode=None)

# ============== ПЛАНОВЫЕ ЗАДАЧИ ==============

async def scheduled_backup(context: ContextTypes.DEFAULT_TYPE):
    """Плановый бэкап."""
    backup_manager.create_backup("auto")

# ============== СОЗДАНИЕ ПРИЛОЖЕНИЯ ==============

def create_application():
    """Создание приложения."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.scheduler = scheduler.scheduler
    
    # Команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("admin", admin_command))
    
    # ConversationHandler для лекарств
    medicine_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_medicine_start, pattern="^add_medicine$")],
        states={
            MEDICINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_medicine_name)],
            MEDICINE_TIME_HOUR: [CallbackQueryHandler(add_medicine_hour, pattern="^med_hour_")],
            MEDICINE_TIME_MINUTE: [CallbackQueryHandler(add_medicine_minute, pattern="^med_minute_")],
            MEDICINE_CONFIRM: [CallbackQueryHandler(add_medicine_confirm, pattern="^confirm_medicine$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_medicine"
    )
    
    # ConversationHandler для анализов
    analysis_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_analysis_start, pattern="^add_analysis$")],
        states={
            ANALYSIS_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_analysis_name)],
            ANALYSIS_DATE: [
                CallbackQueryHandler(add_analysis_date, pattern="^analysis_date_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_analysis_date)
            ],
            ANALYSIS_TIME_HOUR: [CallbackQueryHandler(add_analysis_hour, pattern="^ana_hour_")],
            ANALYSIS_TIME_MINUTE: [CallbackQueryHandler(add_analysis_minute, pattern="^ana_minute_")],
            ANALYSIS_CONFIRM: [CallbackQueryHandler(add_analysis_confirm, pattern="^confirm_analysis$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_analysis"
    )
    
    # Добавляем обработчики
    app.add_handler(medicine_conv)
    app.add_handler(analysis_conv)
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Плановые задачи
    app.job_queue.run_repeating(integrity_check, interval=3600, first=10, name="integrity")
    app.job_queue.run_daily(scheduled_backup, time=datetime.strptime("03:00", "%H:%M").time(), name="daily_backup")
    
    return app

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции."""
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "❌ Операция отменена",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    else:
        await update.message.reply_text(
            "❌ Операция отменена",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    return ConversationHandler.END

# ============== ЗАПУСК ==============

async def main():
    """Главная функция."""
    global application, error_notifier
    
    if BOT_TOKEN == "8515765315:AAEufR-gJQUZCux_kC0yDfmHRZf2QLgacUk":
        print("\n" + "="*50)
        print("✅ Токен установлен")
        print("="*50)
    
    print("🚀 Запуск ЛОР-Помощника...")
    print(f"📁 Данные: {DATA_DIR}")
    print(f"📁 Бэкапы: {BACKUP_DIR}")
    print(f"📁 Логи: {LOG_DIR}")
    print("-" * 50)
    
    # Отключаем webhook
    print("🔄 Отключаем webhook...")
    import requests
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        print(f"✅ Webhook отключен: {r.json()}")
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
    
    # Инициализация уведомлений
    if ADMIN_CHAT_ID:
        error_notifier = ErrorNotifier(BOT_TOKEN, ADMIN_CHAT_ID)
        await error_notifier.start()
    
    # Создание приложения
    application = create_application()
    
    # Запуск планировщика
    scheduler.start()
    await scheduler.restore_reminders()
    
    # Создаем первый бэкап при старте
    if DB_PATH.exists():
        backup_manager.create_backup("auto")
    
    print("✅ Бот запущен и готов к работе!")
    print("📝 Логи пишутся в /app/logs")
    print("💡 Отправьте /start в Telegram")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        if scheduler:
            scheduler.shutdown()
        if error_notifier:
            await error_notifier.stop()
        log.info("SHUTDOWN - Бот остановлен")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
