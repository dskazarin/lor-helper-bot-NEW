#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЛОР-Помощник - Telegram бот для управления приемом лекарств и отслеживания симптомов
Версия: 11.0.0 (Новая логика добавления)
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
        Boolean, BigInteger, Index, func, select, and_, or_, desc
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, scoped_session
    from sqlalchemy.pool import QueuePool
except ImportError:
    print("Устанавливаем SQLAlchemy...")
    os.system(f"{sys.executable} -m pip install sqlalchemy==2.0.23")
    from sqlalchemy import (
        create_engine, Column, Integer, String, DateTime, Text, 
        Boolean, BigInteger, Index, func, select, and_, or_, desc
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, scoped_session
    from sqlalchemy.pool import QueuePool

# ============== КОНФИГУРАЦИЯ ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "").split(",") if id]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Директории для данных
DATA_DIR = Path("/app/data")
BACKUP_DIR = Path("/app/backups")
LOG_DIR = Path("/app/logs")

for directory in [DATA_DIR, BACKUP_DIR, LOG_DIR]:
    os.makedirs(directory, exist_ok=True)

# Пути к базам данных
DB_PATH = DATA_DIR / "lor_reminder.db"
JOBS_DB_PATH = DATA_DIR / "apscheduler_jobs.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
JOB_STORE_URL = f"sqlite:///{JOBS_DB_PATH}"

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
    frequency = Column(Integer, nullable=False, default=1)  # количество раз в день
    times = Column(String(200), nullable=False)  # "08:00,20:00" или "08:00"
    reminder_minutes = Column(Integer, nullable=True)  # за сколько минут напомнить
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
    reminder_minutes = Column(Integer, default=120)  # за сколько минут напомнить
    repeat_type = Column(String(20), default='once')
    repeat_interval = Column(Integer, nullable=True)
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
    target = Column(String(50), nullable=False)  # 'all', 'active'
    total = Column(Integer, nullable=False)
    success = Column(Integer, nullable=False)
    failed = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(pytz.UTC))

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
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        from sqlalchemy import inspect
        inspector = inspect(engine)
        
        tables = inspector.get_table_names()
        
        if 'medicines' in tables:
            med_columns = [c['name'] for c in inspector.get_columns('medicines')]
            if 'frequency' not in med_columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN frequency INTEGER DEFAULT 1'))
                db.commit()
            if 'reminder_minutes' not in med_columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN reminder_minutes INTEGER'))
                db.commit()
            if 'paused_until' not in med_columns:
                db.execute(text('ALTER TABLE medicines ADD COLUMN paused_until DATETIME'))
                db.commit()
        
        if 'analyses' in tables:
            ana_columns = [c['name'] for c in inspector.get_columns('analyses')]
            if 'paused_until' not in ana_columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN paused_until DATETIME'))
                db.commit()
            if 'reminder_minutes' not in ana_columns:
                db.execute(text('ALTER TABLE analyses ADD COLUMN reminder_minutes INTEGER DEFAULT 120'))
                db.commit()
        
        if 'reminders' in tables:
            rem_columns = [c['name'] for c in inspector.get_columns('reminders')]
            if 'postponed_days' not in rem_columns:
                db.execute(text('ALTER TABLE reminders ADD COLUMN postponed_days INTEGER'))
                db.commit()
        
        if 'medicine_logs' in tables:
            log_columns = [c['name'] for c in inspector.get_columns('medicine_logs')]
            if 'is_planned' not in log_columns:
                db.execute(text('ALTER TABLE medicine_logs ADD COLUMN is_planned BOOLEAN DEFAULT 1'))
                db.commit()
            
    except Exception as e:
        log.error(f"Ошибка инициализации БД: {e}")
        db.rollback()
    finally:
        db.close()

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

# ============== ФУНКЦИИ ДЛЯ КНОПОК НАВИГАЦИИ ==============

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

def get_medicine_inline_keyboard(medicine_id: int):
    keyboard = [
        [
            InlineKeyboardButton("✅ Принял(а)", callback_data=f"take_{medicine_id}"),
            InlineKeyboardButton("📝 Комментарий", callback_data=f"comment_{medicine_id}"),
        ],
        [
            InlineKeyboardButton("⏸ Отложить", callback_data=f"postpone_medicine_{medicine_id}"),
            InlineKeyboardButton("⏸ Пауза курса", callback_data=f"pause_medicine_{medicine_id}"),
        ],
        [
            InlineKeyboardButton("❌ Пропустить", callback_data=f"skip_{medicine_id}"),
            InlineKeyboardButton("🗑️ Отменить", callback_data=f"cancel_medicine_{medicine_id}"),
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
            InlineKeyboardButton("⏸ Отложить", callback_data=f"postpone_analysis_{analysis_id}"),
            InlineKeyboardButton("🗑️ Отменить", callback_data=f"cancel_analysis_{analysis_id}"),
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

def get_frequency_keyboard(prefix: str):
    """Клавиатура для выбора количества раз в день."""
    keyboard = [
        [
            InlineKeyboardButton("1 раз", callback_data=f"{prefix}_freq_1"),
            InlineKeyboardButton("2 раза", callback_data=f"{prefix}_freq_2"),
            InlineKeyboardButton("3 раза", callback_data=f"{prefix}_freq_3"),
        ],
        [InlineKeyboardButton("⚙️ Свой вариант", callback_data=f"{prefix}_freq_custom")],
        [InlineKeyboardButton("🔙 Отмена", callback_data="start")],
        get_main_menu_button()
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

def get_minute_keyboard(hour: str, prefix: str, back_callback: str):
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
    
    keyboard.append([
        InlineKeyboardButton("🔙 К выбору часа", callback_data=back_callback),
        get_main_menu_button()[0]
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_reminder_keyboard(prefix: str, back_callback: str):
    """Клавиатура для выбора времени напоминания."""
    keyboard = [
        [
            InlineKeyboardButton("⏰ 15 мин", callback_data=f"{prefix}_remind_15"),
            InlineKeyboardButton("⏰ 30 мин", callback_data=f"{prefix}_remind_30"),
            InlineKeyboardButton("⏰ 1 час", callback_data=f"{prefix}_remind_60"),
        ],
        [
            InlineKeyboardButton("⏰ 2 часа", callback_data=f"{prefix}_remind_120"),
            InlineKeyboardButton("⏰ 3 часа", callback_data=f"{prefix}_remind_180"),
            InlineKeyboardButton("⏰ 6 часов", callback_data=f"{prefix}_remind_360"),
        ],
        [
            InlineKeyboardButton("⏰ 12 часов", callback_data=f"{prefix}_remind_720"),
            InlineKeyboardButton("⏰ 24 часа", callback_data=f"{prefix}_remind_1440"),
            InlineKeyboardButton("⚙️ Свое", callback_data=f"{prefix}_remind_custom"),
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data=back_callback)],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_simple_date_keyboard():
    """Простая клавиатура для выбора даты."""
    today = datetime.now()
    keyboard = []
    
    for i in range(3):
        d = today + timedelta(days=i)
        date_str = d.strftime('%d.%m.%Y')
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        keyboard.append([InlineKeyboardButton(
            f"{date_str} ({day_name})", 
            callback_data=f"analysis_date_{date_str}"
        )])
    
    keyboard.append([InlineKeyboardButton("📅 Своя дата", callback_data="analysis_date_custom")])
    keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data="start")])
    keyboard.append(get_main_menu_button())
    
    return InlineKeyboardMarkup(keyboard)

def get_symptom_list_keyboard(user_id: int, page: int = 0):
    """Клавиатура со списком симптомов для удаления."""
    db = get_db()
    try:
        symptoms = db.query(SymptomLog).filter(
            SymptomLog.user_id == user_id
        ).order_by(SymptomLog.created_at.desc()).limit(10).offset(page * 10).all()
        
        if not symptoms:
            return None
        
        keyboard = []
        for s in symptoms:
            local_time = utc_to_local(s.created_at, get_user_timezone(user_id))
            date_str = local_time.strftime('%d.%m %H:%M')
            text = f"{s.symptom} ({s.severity}/5) - {date_str}"
            keyboard.append([InlineKeyboardButton(
                f"❌ {text[:30]}...",
                callback_data=f"delete_symptom_{s.id}"
            )])
        
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"symptom_page_{page-1}"))
        if len(symptoms) == 10:
            nav.append(InlineKeyboardButton("➡️ Вперед", callback_data=f"symptom_page_{page+1}"))
        if nav:
            keyboard.append(nav)
        
        keyboard.append(get_main_menu_button())
        return InlineKeyboardMarkup(keyboard)
    finally:
        db.close()

def get_postpone_keyboard(item_type: str, item_id: int):
    """Клавиатура для выбора срока откладывания."""
    keyboard = [
        [
            InlineKeyboardButton("5 дней", callback_data=f"postpone_{item_type}_{item_id}_5"),
            InlineKeyboardButton("10 дней", callback_data=f"postpone_{item_type}_{item_id}_10"),
        ],
        [
            InlineKeyboardButton("15 дней", callback_data=f"postpone_{item_type}_{item_id}_15"),
            InlineKeyboardButton("30 дней", callback_data=f"postpone_{item_type}_{item_id}_30"),
        ],
        [
            InlineKeyboardButton("⚙️ Свой вариант", callback_data=f"postpone_{item_type}_{item_id}_custom"),
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_{item_type}_{item_id}"),
            get_main_menu_button()[0]
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============== АДМИН-КЛАВИАТУРЫ ==============

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
        [InlineKeyboardButton("🔍 Поиск по ID", callback_data="admin_users_search")],
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
        [InlineKeyboardButton("👥 Действия пользователей", callback_data="admin_logs_users")],
        [InlineKeyboardButton("⏱ Медленные запросы", callback_data="admin_logs_slow")],
        [InlineKeyboardButton("📁 Скачать файлы логов", callback_data="admin_logs_files")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_backups_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔄 Создать бэкап", callback_data="admin_backup_create")],
        [InlineKeyboardButton("📋 Список бэкапов", callback_data="admin_backup_list")],
        [InlineKeyboardButton("⚙️ Настройки бэкапов", callback_data="admin_backup_settings")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")],
        get_main_menu_button()
    ]
    return InlineKeyboardMarkup(keyboard)

# ============== СОСТОЯНИЯ CONVERSATION HANDLER ==============
(
    MEDICINE_NAME, MEDICINE_FREQUENCY, MEDICINE_TIME, MEDICINE_REMINDER, MEDICINE_CONFIRM,
    ANALYSIS_NAME, ANALYSIS_DATE, ANALYSIS_TIME, ANALYSIS_REMINDER, ANALYSIS_CONFIRM,
    SYMPTOM_TEXT, SYMPTOM_SEVERITY,
    MEDICINE_COMMENT, MEDICINE_DOSAGE, MEDICINE_EXTRA_REASON,
    POSTPONE_MEDICINE, POSTPONE_ANALYSIS,
    PAUSE_MEDICINE, PAUSE_ANALYSIS,
    EXTRA_MEDICINE_SELECT,
    ADMIN_BROADCAST_MESSAGE, ADMIN_BROADCAST_CONFIRM,
    ADMIN_USER_SEARCH
) = range(23)

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
            
            if error_notifier:
                error_notifier.notify(
                    "NEW_USER",
                    f"Новый пользователь: {user.first_name} (ID: {user.id})"
                )
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
    is_new = await register_user(update)
    
    if is_new:
        text = f"""👋 Здравствуйте, {update.effective_user.first_name}!

Я ЛОР-Помощник — персональный медицинский бот, созданный врачом-оториноларингологом Денисом Казариным.

👶 Врач ведет прием детей с 0 лет и взрослых

📖 Быстрый старт:
1️⃣ Добавьте лекарство - нажмите кнопку "💊 Добавить лекарство"
2️⃣ Укажите сколько раз в день
3️⃣ Выберите время приема
4️⃣ Укажите за сколько напомнить

🩺 Для анализов - аналогично

📊 Отслеживайте самочувствие - кнопка "📊 Самочувствие"

❓ Если что-то непонятно - зайдите в раздел "👨‍⚕️ О враче" и нажмите "❓ Помощь"

Выберите действие в меню ниже:"""
    else:
        text = f"""👋 С возвращением, {update.effective_user.first_name}!

Чем могу помочь сегодня?

Выберите действие в меню ниже:"""
    
    await update.message.reply_text(text, reply_markup=get_start_keyboard(), parse_mode=None)
    log.info("✅ /start обработан", update=update)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    text = """❓ Как очистить историю переписки

Чтобы удалить всю переписку с ботом и вернуться на главную:

1️⃣ В правом верхнем углу нажмите на свой профиль
2️⃣ В меню выберите пункт "Еще" (или "More")
3️⃣ Прокрутите вниз и нажмите "Удалить переписку" (или "Delete chat")

✅ После этого откроется начальная страница бота
💾 Все ваши сохраненные данные останутся без изменений

👇 Нажмите синюю кнопку START внизу чтобы вернуться к боту"""

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

# ============== ДОБАВЛЕНИЕ ЛЕКАРСТВА ==============

async def add_medicine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления лекарства."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    context.user_data['medicine'] = {}
    
    await query.edit_message_text(
        "💊 *Добавление лекарства*\n\nШаг 1/5: Введите название лекарства",
        parse_mode=None
    )
    return MEDICINE_NAME

async def add_medicine_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия лекарства."""
    context.user_data['medicine']['name'] = update.message.text
    
    await update.message.reply_text(
        "Шаг 2/5: Сколько раз в день принимать?",
        reply_markup=get_frequency_keyboard("med"),
        parse_mode=None
    )
    return MEDICINE_FREQUENCY

async def add_medicine_frequency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор количества приемов в день."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        if query.data == "med_freq_custom":
            await query.edit_message_text(
                "Введите количество раз в день (от 1 до 10):",
                parse_mode=None
            )
            return MEDICINE_FREQUENCY
        
        freq = int(query.data.replace("med_freq_", ""))
        context.user_data['medicine']['frequency'] = freq
        context.user_data['medicine']['times'] = []
        
        await query.edit_message_text(
            f"Шаг 3/5: Выберите час для приема №1 из {freq}",
            reply_markup=get_hour_keyboard("med_time", "start"),
            parse_mode=None
        )
        return MEDICINE_TIME
    else:
        try:
            freq = int(update.message.text.strip())
            if freq < 1 or freq > 10:
                raise ValueError
            context.user_data['medicine']['frequency'] = freq
            context.user_data['medicine']['times'] = []
            
            await update.message.reply_text(
                f"Шаг 3/5: Выберите час для приема №1 из {freq}",
                reply_markup=get_hour_keyboard("med_time", "start"),
                parse_mode=None
            )
            return MEDICINE_TIME
        except:
            await update.message.reply_text("❌ Введите число от 1 до 10")
            return MEDICINE_FREQUENCY

async def add_medicine_time_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часа для времени приема."""
    query = update.callback_query
    await query.answer()
    
    hour = query.data.replace("med_time_hour_", "")
    context.user_data['medicine']['temp_hour'] = hour
    
    await query.edit_message_text(
        f"Вы выбрали час {hour}. Теперь выберите минуты:",
        reply_markup=get_minute_keyboard(hour, "med_time", "med_time_back"),
        parse_mode=None
    )
    return MEDICINE_TIME

async def add_medicine_time_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор минуты для времени приема."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("med_time_minute_", "")
    hour, minute = data.split('_')
    time_str = f"{hour}:{minute}"
    
    context.user_data['medicine']['times'].append(time_str)
    
    current = len(context.user_data['medicine']['times'])
    total = context.user_data['medicine']['frequency']
    
    if current < total:
        await query.edit_message_text(
            f"Шаг 3/5: Выберите час для приема №{current+1} из {total}",
            reply_markup=get_hour_keyboard("med_time", "start"),
            parse_mode=None
        )
        return MEDICINE_TIME
    else:
        # Все времена выбраны
        times_str = ", ".join(context.user_data['medicine']['times'])
        
        await query.edit_message_text(
            f"Шаг 4/5: За сколько напомнить?\n\nВыбранное время: {times_str}",
            reply_markup=get_reminder_keyboard("med", "start"),
            parse_mode=None
        )
        return MEDICINE_REMINDER

async def add_medicine_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор времени напоминания."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        if query.data == "med_remind_custom":
            await query.edit_message_text(
                "Введите количество минут (от 1 до 1440):",
                parse_mode=None
            )
            return MEDICINE_REMINDER
        
        minutes = int(query.data.replace("med_remind_", ""))
        context.user_data['medicine']['reminder_minutes'] = minutes
    else:
        try:
            minutes = int(update.message.text.strip())
            if minutes < 1 or minutes > 1440:
                raise ValueError
            context.user_data['medicine']['reminder_minutes'] = minutes
        except:
            await update.message.reply_text("❌ Введите число от 1 до 1440")
            return MEDICINE_REMINDER
    
    med = context.user_data['medicine']
    times_str = ", ".join(med['times'])
    
    text = f"""✅ *Проверьте данные:*

💊 Название: {med['name']}
📊 Приемов в день: {med['frequency']}
⏰ Время: {times_str}
⏰ Напомнить за: {med['reminder_minutes']} мин.

Всё верно?"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Записать", callback_data="confirm_medicine"),
            InlineKeyboardButton("✏️ Редактировать", callback_data="add_medicine"),
        ],
        get_main_menu_button()
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    return MEDICINE_CONFIRM

async def add_medicine_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение добавления лекарства."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    med = context.user_data['medicine']
    tz = get_user_timezone(user_id)
    
    db = get_db()
    try:
        times_str = ",".join(med['times'])
        
        medicine = Medicine(
            user_id=user_id,
            name=med['name'],
            frequency=med['frequency'],
            times=times_str,
            reminder_minutes=med['reminder_minutes'],
            start_date=datetime.now(pytz.UTC),
            user_timezone=tz,
            course_type='unlimited'
        )
        db.add(medicine)
        db.flush()
        
        # Создаем напоминания на каждый прием
        now = datetime.now(pytz.timezone(tz))
        
        for time_str in med['times']:
            h, m = map(int, time_str.split(':'))
            scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if scheduled < now:
                scheduled += timedelta(days=1)
            
            reminder = Reminder(
                user_id=user_id,
                reminder_type='medicine',
                item_id=medicine.id,
                scheduled_time=scheduled.astimezone(pytz.UTC),
                user_timezone=tz
            )
            db.add(reminder)
            db.flush()
            
            # Если указано напоминание заранее
            if med['reminder_minutes'] and med['reminder_minutes'] > 0:
                remind_time = scheduled - timedelta(minutes=med['reminder_minutes'])
                if remind_time > datetime.now(pytz.UTC):
                    reminder2 = Reminder(
                        user_id=user_id,
                        reminder_type='medicine',
                        item_id=medicine.id,
                        scheduled_time=remind_time.astimezone(pytz.UTC),
                        user_timezone=tz
                    )
                    db.add(reminder2)
                    db.flush()
                    
                    scheduler.scheduler.add_job(
                        send_reminder_job,
                        trigger=DateTrigger(run_date=remind_time.astimezone(pytz.UTC)),
                        id=f"medicine_{reminder2.id}",
                        args=[reminder2.id],
                        replace_existing=True
                    )
            
            scheduler.scheduler.add_job(
                send_reminder_job,
                trigger=DateTrigger(run_date=scheduled.astimezone(pytz.UTC)),
                id=f"medicine_{reminder.id}",
                args=[reminder.id],
                replace_existing=True
            )
        
        db.commit()
        
        keyboard = [
            [InlineKeyboardButton("📋 Список лекарств", callback_data="list_medicines")],
            [InlineKeyboardButton("➕ Добавить еще", callback_data="add_medicine")],
            get_main_menu_button()
        ]
        
        await query.edit_message_text(
            f"✅ Лекарство '{med['name']}' добавлено!\nНапоминания настроены.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
        
        log.info(f"✅ Лекарство добавлено: {med['name']}", update=update)
        
    except Exception as e:
        db.rollback()
        log.error(f"Ошибка добавления лекарства: {e}", update=update, exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при добавлении лекарства",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END

# ============== ДОБАВЛЕНИЕ АНАЛИЗА ==============

async def add_analysis_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления анализа."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    context.user_data['analysis'] = {}
    
    await query.edit_message_text(
        "🩺 *Добавление анализа/исследования*\n\nШаг 1/5: Введите название",
        parse_mode=None
    )
    return ANALYSIS_NAME

async def add_analysis_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия анализа."""
    context.user_data['analysis']['name'] = update.message.text
    
    await update.message.reply_text(
        "Шаг 2/5: Выберите дату:",
        reply_markup=get_simple_date_keyboard(),
        parse_mode=None
    )
    return ANALYSIS_DATE

async def add_analysis_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор даты анализа."""
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
        
        date_str = query.data.replace("analysis_date_", "")
        try:
            date = datetime.strptime(date_str, '%d.%m.%Y')
            date = pytz.timezone(tz).localize(date.replace(hour=12))
            context.user_data['analysis']['date'] = date
        except:
            await query.edit_message_text("❌ Неверный формат даты")
            return ANALYSIS_DATE
    else:
        try:
            date = datetime.strptime(update.message.text.strip(), '%d.%m.%Y')
            date = pytz.timezone(tz).localize(date.replace(hour=12))
            context.user_data['analysis']['date'] = date
        except:
            await update.message.reply_text("❌ Неверный формат. Используйте ДД.ММ.ГГГГ")
            return ANALYSIS_DATE
    
    await (update.callback_query or update.message).reply_text(
        "Шаг 3/5: Выберите час:",
        reply_markup=get_hour_keyboard("ana", "analysis_date_back"),
        parse_mode=None
    )
    return ANALYSIS_TIME

async def add_analysis_time_hour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часа для анализа."""
    query = update.callback_query
    await query.answer()
    
    hour = query.data.replace("ana_hour_", "")
    context.user_data['analysis']['temp_hour'] = hour
    
    await query.edit_message_text(
        f"Вы выбрали час {hour}. Выберите минуты:",
        reply_markup=get_minute_keyboard(hour, "ana", "ana_hour_back"),
        parse_mode=None
    )
    return ANALYSIS_TIME

async def add_analysis_time_minute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор минуты для анализа."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.replace("ana_minute_", "")
    hour, minute = data.split('_')
    time_str = f"{hour}:{minute}"
    context.user_data['analysis']['time'] = time_str
    
    await query.edit_message_text(
        "Шаг 4/5: За сколько напомнить?",
        reply_markup=get_reminder_keyboard("ana", "analysis_time_back"),
        parse_mode=None
    )
    return ANALYSIS_REMINDER

async def add_analysis_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор времени напоминания."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        if query.data == "ana_remind_custom":
            await query.edit_message_text(
                "Введите количество минут (от 1 до 43200):",
                parse_mode=None
            )
            return ANALYSIS_REMINDER
        
        minutes = int(query.data.replace("ana_remind_", ""))
        context.user_data['analysis']['reminder_minutes'] = minutes
    else:
        try:
            minutes = int(update.message.text.strip())
            if minutes < 1 or minutes > 43200:
                raise ValueError
            context.user_data['analysis']['reminder_minutes'] = minutes
        except:
            await update.message.reply_text("❌ Введите число от 1 до 43200")
            return ANALYSIS_REMINDER
    
    ana = context.user_data['analysis']
    date = ana['date'].strftime('%d.%m.%Y')
    
    text = f"""✅ *Проверьте данные:*

🩺 Название: {ana['name']}
📅 Дата: {date}
⏰ Время: {ana['time']}
⏰ Напомнить за: {ana['reminder_minutes']} мин.

Всё верно?"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Записать", callback_data="confirm_analysis"),
            InlineKeyboardButton("✏️ Редактировать", callback_data="add_analysis"),
        ],
        get_main_menu_button()
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    return ANALYSIS_CONFIRM

async def add_analysis_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение добавления анализа."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    ana = context.user_data['analysis']
    tz = get_user_timezone(user_id)
    
    db = get_db()
    try:
        h, m = map(int, ana['time'].split(':'))
        dt = ana['date'].replace(hour=h, minute=m)
        
        analysis = Analysis(
            user_id=user_id,
            name=ana['name'],
            scheduled_date=dt,
            scheduled_time=ana['time'],
            reminder_minutes=ana['reminder_minutes'],
            user_timezone=tz
        )
        db.add(analysis)
        db.flush()
        
        # Напоминание
        remind_time = dt - timedelta(minutes=ana['reminder_minutes'])
        if remind_time > datetime.now(pytz.UTC):
            reminder = Reminder(
                user_id=user_id,
                reminder_type='analysis',
                item_id=analysis.id,
                scheduled_time=remind_time,
                user_timezone=tz
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
        
        keyboard = [
            [InlineKeyboardButton("📋 Список анализов", callback_data="list_analyses")],
            [InlineKeyboardButton("➕ Добавить еще", callback_data="add_analysis")],
            get_main_menu_button()
        ]
        
        await query.edit_message_text(
            f"✅ Анализ '{ana['name']}' добавлен!\nНапоминание настроено.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
        
        log.info(f"✅ Анализ добавлен: {ana['name']}", update=update)
        
    except Exception as e:
        db.rollback()
        log.error(f"Ошибка добавления анализа: {e}", update=update, exc_info=True)
        await query.edit_message_text(
            "❌ Ошибка при добавлении анализа",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END

# ============== ЭКСТРЕННЫЙ ПРИЕМ ==============

async def extra_medicine_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало экстренного приема."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        medicines = db.query(Medicine).filter(
            Medicine.user_id == user_id,
            Medicine.status == 'active'
        ).all()
        
        if not medicines:
            text = "💊 У вас нет активных лекарств. Сначала добавьте лекарство."
            keyboard = [
                [InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")],
                get_main_menu_button()
            ]
        else:
            text = "💊 Выберите лекарство, которое приняли:"
            keyboard = []
            for m in medicines:
                keyboard.append([InlineKeyboardButton(m.name, callback_data=f"extra_select_{m.id}")])
            keyboard.append([InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")])
            keyboard.append(get_main_menu_button())
        
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
            return EXTRA_MEDICINE_SELECT
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
            return EXTRA_MEDICINE_SELECT
    finally:
        db.close()

async def extra_medicine_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор лекарства для экстренного приема."""
    query = update.callback_query
    await query.answer()
    
    med_id = int(query.data.replace("extra_select_", ""))
    context.user_data['extra'] = {'medicine_id': med_id}
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_dosage")]])
    
    await query.edit_message_text(
        "💊 Укажите принятую дозу (например: 1 таблетка):",
        reply_markup=keyboard,
        parse_mode=None
    )
    return MEDICINE_DOSAGE

async def extra_medicine_dosage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение дозы."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        context.user_data['extra']['dosage'] = None
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_comment")]])
        await query.edit_message_text(
            "📝 Добавьте комментарий:",
            reply_markup=keyboard,
            parse_mode=None
        )
    else:
        if update.message.text == "/skip":
            context.user_data['extra']['dosage'] = None
        else:
            context.user_data['extra']['dosage'] = update.message.text
        
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Пропустить", callback_data="skip_comment")]])
        await update.message.reply_text(
            "📝 Добавьте комментарий:",
            reply_markup=keyboard,
            parse_mode=None
        )
    return MEDICINE_COMMENT

async def extra_medicine_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение комментария и завершение."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "skip_comment":
            comment = None
        else:
            comment = None
    else:
        if update.message.text == "/skip":
            comment = None
        else:
            comment = update.message.text
    
    user_id = update.effective_user.id
    med_id = context.user_data['extra']['medicine_id']
    dosage = context.user_data['extra'].get('dosage')
    
    db = get_db()
    try:
        medicine = db.query(Medicine).filter_by(id=med_id).first()
        if not medicine:
            await (update.callback_query or update.message).reply_text("❌ Лекарство не найдено")
            return ConversationHandler.END
        
        log_entry = MedicineLog(
            medicine_id=med_id,
            user_id=user_id,
            status='extra',
            dosage=dosage,
            comment=comment,
            is_planned=False,
            course_info=f"{medicine.course_type} ({medicine.course_days or '∞'} дн.)"
        )
        db.add(log_entry)
        db.commit()
        
        text = f"✅ Прием {medicine.name} зафиксирован!"
        if dosage:
            text += f"\n💊 Доза: {dosage}"
        if comment:
            text += f"\n📝 Комментарий: {comment}"
        
        keyboard = [
            [InlineKeyboardButton("👨‍⚕️ Записаться к врачу", callback_data="about")],
            get_main_menu_button()
        ]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
        
    except Exception as e:
        log.error(f"Ошибка экстренного приема: {e}", update=update, exc_info=True)
        await (update.callback_query or update.message).reply_text("❌ Ошибка")
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END

# ============== КОММЕНТАРИИ К ЛЕКАРСТВАМ ==============

async def medicine_comment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало комментария."""
    query = update.callback_query
    await query.answer()
    
    med_id = int(query.data.replace("comment_", ""))
    context.user_data['comment'] = {'medicine_id': med_id}
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤒 Новый симптом", callback_data=f"comment_symptom_{med_id}")],
        [InlineKeyboardButton("⚠️ Побочное действие", callback_data=f"comment_side_{med_id}")],
        [InlineKeyboardButton("📝 Обычный комментарий", callback_data=f"comment_normal_{med_id}")],
        get_main_menu_button()
    ])
    
    await query.edit_message_text(
        "📝 Выберите тип комментария:",
        reply_markup=keyboard,
        parse_mode=None
    )
    return MEDICINE_COMMENT

async def medicine_comment_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор типа комментария."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    med_id = int(parts[2])
    ctype = parts[1]
    
    context.user_data['comment'] = {
        'medicine_id': med_id,
        'type': ctype
    }
    
    await query.edit_message_text(
        "📝 Введите текст комментария:",
        parse_mode=None
    )
    return MEDICINE_COMMENT

async def medicine_comment_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение комментария."""
    comment = update.message.text
    user_id = update.effective_user.id
    data = context.user_data.get('comment', {})
    med_id = data.get('medicine_id')
    
    if not med_id:
        await update.message.reply_text("❌ Ошибка. Начните заново.")
        return ConversationHandler.END
    
    db = get_db()
    try:
        last = db.query(MedicineLog).filter(
            MedicineLog.medicine_id == med_id,
            MedicineLog.user_id == user_id
        ).order_by(MedicineLog.taken_at.desc()).first()
        
        if last:
            last.comment = comment
            db.commit()
        
        # Если это новый симптом, переходим к добавлению симптома
        if data.get('type') == 'symptom':
            context.user_data['symptom_from_medicine'] = {
                'comment': comment,
                'medicine_id': med_id
            }
            await update.message.reply_text(
                "🩺 Опишите симптом:",
                parse_mode=None
            )
            return SYMPTOM_TEXT
        
        await update.message.reply_text(
            "✅ Комментарий сохранен!",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
        
    except Exception as e:
        log.error(f"Ошибка сохранения комментария: {e}", update=update, exc_info=True)
        await update.message.reply_text("❌ Ошибка")
    finally:
        db.close()
        if 'comment' in context.user_data:
            del context.user_data['comment']
    
    return ConversationHandler.END

# ============== САМОЧУВСТВИЕ ==============

async def mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оценка настроения."""
    text = "📊 Как вы себя чувствуете сегодня?\n\nОцените по 5-балльной шкале:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_mood_keyboard(), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=get_mood_keyboard(), parse_mode=None)

async def mood_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение оценки настроения."""
    query = update.callback_query
    await query.answer()
    
    score = int(query.data.replace("mood_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        mood = MoodLog(user_id=user_id, mood_score=score)
        db.add(mood)
        db.commit()
        
        # Проверка на ухудшение
        recent = db.query(MoodLog).filter(
            MoodLog.user_id == user_id
        ).order_by(MoodLog.created_at.desc()).limit(2).all()
        
        if len(recent) == 2 and all(m.mood_score <= 2 for m in recent):
            keyboard = [
                [
                    InlineKeyboardButton("👨‍⚕️ Записаться", callback_data="about"),
                    InlineKeyboardButton("✅ Отметить визит", callback_data="doctor_visited"),
                ],
                get_main_menu_button()
            ]
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ Зафиксировано ухудшение самочувствия два дня подряд. Рекомендуется обратиться к врачу.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        texts = {1: "😢 Очень плохо", 2: "🙁 Плохо", 3: "😐 Нормально", 4: "🙂 Хорошо", 5: "😊 Отлично"}
        local = utc_to_local(mood.created_at, get_user_timezone(user_id))
        
        keyboard = [
            [InlineKeyboardButton("🩺 Отметить симптомы", callback_data="symptoms")],
            get_main_menu_button()
        ]
        
        await query.edit_message_text(
            f"✅ {texts[score]}\n📅 {local.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=None
        )
    finally:
        db.close()

async def doctor_visited(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отметка о визите к врачу."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        visit = DoctorVisitLog(user_id=user_id, notes="Посещение врача")
        db.add(visit)
        db.commit()
        
        await query.edit_message_text(
            "✅ Визит к врачу отмечен!\n\nХорошо, что вы обратились к специалисту.",
            reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
            parse_mode=None
        )
    finally:
        db.close()

# ============== СИМПТОМЫ ==============

async def symptoms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление симптома."""
    text = "🩺 Какие симптомы вас беспокоят?\n\nВведите симптом текстом:"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="mood")],
                [InlineKeyboardButton("🗑️ Управление симптомами", callback_data="manage_symptoms")],
                get_main_menu_button()
            ]),
            parse_mode=None
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="mood")],
                [InlineKeyboardButton("🗑️ Управление симптомами", callback_data="manage_symptoms")],
                get_main_menu_button()
            ]),
            parse_mode=None
        )
    return SYMPTOM_TEXT

async def symptom_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текст симптома."""
    context.user_data['symptom'] = update.message.text
    
    keyboard = [
        [
            InlineKeyboardButton("1 🔴 Минимальная", callback_data="severity_1"),
            InlineKeyboardButton("2 🟠 Легкая", callback_data="severity_2"),
        ],
        [
            InlineKeyboardButton("3 🟡 Умеренная", callback_data="severity_3"),
            InlineKeyboardButton("4 🟢 Сильная", callback_data="severity_4"),
        ],
        [
            InlineKeyboardButton("5 🔵 Максимальная", callback_data="severity_5"),
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="mood"),
            get_main_menu_button()[0]
        ]
    ]
    
    await update.message.reply_text(
        "🩺 Оцените тяжесть симптома (1-5):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )
    return SYMPTOM_SEVERITY

async def symptom_severity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение симптома."""
    query = update.callback_query
    await query.answer()
    
    severity = int(query.data.replace("severity_", ""))
    
    # Проверяем, пришли ли мы из комментария к лекарству
    if 'symptom_from_medicine' in context.user_data:
        symptom = context.user_data['symptom']
        from_medicine = context.user_data['symptom_from_medicine']
        del context.user_data['symptom_from_medicine']
    else:
        symptom = context.user_data.get('symptom', 'Не указан')
        from_medicine = None
    
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        log_entry = SymptomLog(
            user_id=user_id,
            symptom=symptom,
            severity=severity
        )
        db.add(log_entry)
        db.commit()
        
        local = utc_to_local(log_entry.created_at, get_user_timezone(user_id))
        
        texts = {
            1: "1️⃣ Минимальная (🔴)",
            2: "2️⃣ Легкая (🟠)",
            3: "3️⃣ Умеренная (🟡)",
            4: "4️⃣ Сильная (🟢)",
            5: "5️⃣ Максимальная (🔵)"
        }
        
        if from_medicine:
            # Возвращаемся к напоминанию о лекарстве
            med_id = from_medicine['medicine_id']
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 К лекарству", callback_data=f"back_to_medicine_{med_id}"),
                get_main_menu_button()[0]
            ]])
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить еще", callback_data="symptoms")],
                [InlineKeyboardButton("🗑️ Управление симптомами", callback_data="manage_symptoms")],
                get_main_menu_button()
            ])
        
        await query.edit_message_text(
            f"✅ Симптом зафиксирован:\n\n🤒 {symptom}\n📊 {texts[severity]}\n📅 {local.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=keyboard,
            parse_mode=None
        )
        
    finally:
        db.close()
        context.user_data.pop('symptom', None)
    
    return ConversationHandler.END

async def manage_symptoms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление симптомами (удаление)."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    page = int(context.user_data.get('symptom_page', 0))
    
    keyboard = get_symptom_list_keyboard(user_id, page)
    if not keyboard:
        await query.edit_message_text("📭 Нет симптомов для удаления")
        return
    
    await query.edit_message_text(
        "🗑️ *Выберите симптом для удаления:*",
        reply_markup=keyboard,
        parse_mode=None
    )

async def delete_symptom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление симптома."""
    query = update.callback_query
    await query.answer()
    
    symptom_id = int(query.data.replace("delete_symptom_", ""))
    user_id = update.effective_user.id
    
    db = get_db()
    try:
        symptom = db.query(SymptomLog).filter_by(id=symptom_id, user_id=user_id).first()
        if symptom:
            db.delete(symptom)
            db.commit()
            await query.edit_message_text("✅ Симптом удален!")
        else:
            await query.edit_message_text("❌ Симптом не найден")
    finally:
        db.close()
    
    await manage_symptoms_callback(update, context)

# ============== ОТКЛАДЫВАНИЕ АНАЛИЗОВ ==============

async def postpone_analysis_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало откладывания анализа."""
    query = update.callback_query
    await query.answer()
    
    analysis_id = int(query.data.replace("postpone_analysis_", ""))
    context.user_data['postpone'] = {'analysis_id': analysis_id}
    
    await query.edit_message_text(
        "⏸ На сколько дней отложить анализ?",
        reply_markup=get_postpone_keyboard("analysis", analysis_id),
        parse_mode=None
    )
    return POSTPONE_ANALYSIS

async def postpone_analysis_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора дней откладывания."""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        
        if query.data == "postpone_analysis_custom":
            await query.edit_message_text("Введите количество дней (от 1 до 365):")
            return POSTPONE_ANALYSIS
        
        parts = query.data.split('_')
        days = int(parts[3])
        await process_analysis_postpone(query, context, days)
    else:
        try:
            days = int(update.message.text.strip())
            if days < 1 or days > 365:
                raise ValueError
            await process_analysis_postpone(update.message, context, days)
        except:
            await update.message.reply_text("❌ Введите число от 1 до 365")
            return POSTPONE_ANALYSIS
    
    return ConversationHandler.END

async def process_analysis_postpone(obj, context: ContextTypes.DEFAULT_TYPE, days: int):
    """Обработка откладывания анализа."""
    analysis_id = context.user_data['postpone']['analysis_id']
    user_id = obj.from_user.id
    
    db = get_db()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if not analysis:
            await obj.reply_text("❌ Анализ не найден")
            return
        
        reminder = db.query(Reminder).filter(
            Reminder.item_id == analysis_id,
            Reminder.reminder_type == 'analysis',
            Reminder.status == 'sent'
        ).order_by(Reminder.scheduled_time.desc()).first()
        
        if reminder:
            reminder.status = 'postponed'
            reminder.postponed_until = datetime.now(pytz.UTC) + timedelta(days=days)
            reminder.postponed_days = days
            
            log_entry = AnalysisLog(
                analysis_id=analysis_id,
                user_id=user_id,
                status='postponed',
                notes=f"Отложено на {days} дн."
            )
            db.add(log_entry)
            db.commit()
            
            local_date = utc_to_local(reminder.postponed_until, get_user_timezone(user_id))
            text = f"✅ Анализ {analysis.name} отложен на {days} дней.\nНапоминание возобновится {local_date.strftime('%d.%m.%Y')}."
            
            keyboard = [
                [InlineKeyboardButton("📋 Список анализов", callback_data="list_analyses")],
                get_main_menu_button()
            ]
            
            if hasattr(obj, 'edit_message_text'):
                await obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await obj.reply_text("❌ Активное напоминание не найдено")
            
    except Exception as e:
        log.error(f"Ошибка откладывания анализа: {e}", exc_info=True)
        await obj.reply_text("❌ Ошибка")
    finally:
        db.close()
        context.user_data.pop('postpone', None)

async def cancel_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена анализа."""
    query = update.callback_query
    await query.answer()
    
    analysis_id = int(query.data.replace("cancel_analysis_", ""))
    
    db = get_db()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if analysis:
            analysis.status = 'cancelled'
            for r in db.query(Reminder).filter(
                Reminder.item_id == analysis_id,
                Reminder.reminder_type == 'analysis',
                Reminder.status.in_(['pending', 'sent'])
            ):
                r.status = 'cancelled'
                try:
                    scheduler.scheduler.remove_job(f"analysis_{r.id}")
                except:
                    pass
            db.commit()
            
            await query.edit_message_text(
                f"✅ Анализ {analysis.name} удален",
                reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
                parse_mode=None
            )
    finally:
        db.close()

async def analysis_notes_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заметки к анализу."""
    query = update.callback_query
    await query.answer()
    
    analysis_id = int(query.data.replace("analysis_notes_", ""))
    context.user_data['analysis_notes_id'] = analysis_id
    
    await query.edit_message_text(
        "📝 Введите заметки к анализу:",
        parse_mode=None
    )
    return ANALYSIS_CONFIRM

async def analysis_notes_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение заметок к анализу."""
    notes = update.message.text
    analysis_id = context.user_data.get('analysis_notes_id')
    
    db = get_db()
    try:
        analysis = db.query(Analysis).filter_by(id=analysis_id).first()
        if analysis:
            analysis.notes = notes
            db.commit()
            await update.message.reply_text(
                "✅ Заметки сохранены!",
                reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
                parse_mode=None
            )
    finally:
        db.close()
        context.user_data.pop('analysis_notes_id', None)
    
    return ConversationHandler.END

# ============== НАПОМИНАНИЯ ==============

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
            
            if medicine.paused_until and medicine.paused_until > datetime.now(pytz.UTC):
                reminder.status = 'postponed'
                reminder.postponed_until = medicine.paused_until
                db.commit()
                return
            
            text = f"💊 *Время принять лекарство!*\n\n{medicine.name}"
            keyboard = get_medicine_inline_keyboard(medicine.id)
            
        elif reminder.reminder_type == 'analysis':
            analysis = db.query(Analysis).filter_by(id=reminder.item_id).first()
            if not analysis or analysis.status != 'pending':
                reminder.status = 'cancelled'
                db.commit()
                return
            
            if analysis.paused_until and analysis.paused_until > datetime.now(pytz.UTC):
                reminder.status = 'postponed'
                reminder.postponed_until = analysis.paused_until
                db.commit()
                return
            
            date = analysis.scheduled_date
            if date.tzinfo is None:
                date = pytz.UTC.localize(date)
            local = utc_to_local(date, analysis.user_timezone)
            
            text = f"🩺 *Напоминание об анализе!*\n\n{analysis.name}\n📅 {local.strftime('%d.%m.%Y')} в {analysis.scheduled_time}"
            if analysis.notes:
                text += f"\n\n📝 Заметки: {analysis.notes}"
            
            keyboard = get_analysis_inline_keyboard(analysis.id)
        else:
            return
        
        for attempt in range(3):
            try:
                await rate_limiter.acquire(user_id)
                await application.bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=None
                )
                reminder.status = 'sent'
                reminder.retry_count = attempt + 1
                db.commit()
                log.info(f"✅ Напоминание {reminder_id} отправлено {user_id}")
                return
                
            except (RetryAfter, TimedOut) as e:
                reminder.retry_count = attempt + 1
                reminder.last_error = str(e)
                db.commit()
                log.warning(f"⚠️ Попытка {attempt+1} для {reminder_id} не удалась: {e}")
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
            except Exception as e:
                reminder.status = 'failed'
                reminder.last_error = str(e)
                db.commit()
                log.error(f"❌ Ошибка отправки {reminder_id}: {e}")
                return
        
        reminder.status = 'failed'
        db.commit()
        
    except Exception as e:
        log.error(f"❌ Критическая ошибка в send_reminder_job: {e}")
    finally:
        db.close()

# ============== ОБРАБОТЧИКИ ПРИЕМА ==============

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
            is_planned=True,
            course_info=f"{med.course_type} ({med.course_days or '∞'} дн.)"
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
        log_entry = AnalysisLog(
            analysis_id=ana_id,
            user_id=user_id,
            status='completed'
        )
        db.add(log_entry)
        
        ana = db.query(Analysis).filter_by(id=ana_id).first()
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
            f"✅ Отлично! Сдача анализа {ana.name} отмечена.",
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
        log_entry = AnalysisLog(
            analysis_id=ana_id,
            user_id=user_id,
            status='skipped'
        )
        db.add(log_entry)
        
        ana = db.query(Analysis).filter_by(id=ana_id).first()
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

# ============== СПИСКИ ==============

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
            keyboard = [[InlineKeyboardButton("💊 Добавить лекарство", callback_data="add_medicine")], get_main_menu_button()]
        else:
            text = "📋 Ваши лекарства:\n\n"
            keyboard = []
            for i, m in enumerate(medicines, 1):
                if m.paused_until and m.paused_until > datetime.now(pytz.UTC):
                    pause = f" (пауза до {utc_to_local(m.paused_until, m.user_timezone).strftime('%d.%m')})"
                else:
                    pause = ""
                times_str = m.times.replace(",", ", ")
                text += f"{i}. {m.name}{pause}\n   ⏰ {times_str} ({m.frequency} раз/день)\n"
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
            keyboard = [[InlineKeyboardButton("🩺 Добавить анализ", callback_data="add_analysis")], get_main_menu_button()]
        else:
            text = "📋 Запланированные анализы:\n\n"
            keyboard = []
            now = datetime.now(pytz.UTC)
            for i, a in enumerate(analyses, 1):
                if a.scheduled_date.tzinfo is None:
                    date = pytz.UTC.localize(a.scheduled_date)
                else:
                    date = a.scheduled_date
                local = utc_to_local(date, a.user_timezone)
                days = (date - now).days
                status = "🔴 Просрочен" if days < 0 else "🟡 Сегодня" if days == 0 else f"🟢 Через {days} дн."
                text += f"{i}. {a.name}\n   📅 {local.strftime('%d.%m.%Y')} в {a.scheduled_time} - {status}\n"
                text += f"   ⏰ Напомнить за {a.reminder_minutes} мин.\n"
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

# ============== СТАТИСТИКА ==============

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда статистики."""
    text = "📈 *Статистика*\n\nВыберите тип статистики:"
    
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
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

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
            ).order_by(MoodLog.created_at.desc()).all()
            
            symptoms = db.query(SymptomLog).filter(
                SymptomLog.user_id == user_id,
                SymptomLog.created_at >= week_ago
            ).order_by(SymptomLog.created_at.desc()).all()
            
            meds = db.query(MedicineLog).filter(
                MedicineLog.user_id == user_id,
                MedicineLog.taken_at >= week_ago
            ).order_by(MedicineLog.taken_at.desc()).all()
            
            avg_mood = sum(m.mood_score for m in mood) / len(mood) if mood else 0
            
            text = f"""📊 *Статистика за неделю*

😊 *Настроение:* {len(mood)} записей, среднее {avg_mood:.1f}/5
🩺 *Симптомы:* {len(symptoms)} записей
💊 *Лекарства:* {len([m for m in meds if m.status in ['taken', 'extra']])} приемов, {len([m for m in meds if m.status == 'skipped'])} пропусков"""
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
                parse_mode=None
            )
            
        elif query.data == "stats_mood":
            mood = db.query(MoodLog).filter(
                MoodLog.user_id == user_id
            ).order_by(MoodLog.created_at.desc()).limit(30).all()
            
            if not mood:
                await query.edit_message_text("📊 Нет данных о настроении")
                return
            
            text = "📈 *Детальная статистика настроения:*\n\n"
            for m in mood[:20]:
                local = utc_to_local(m.created_at, tz)
                emoji = "😢" if m.mood_score <=2 else "😐" if m.mood_score==3 else "😊"
                text += f"{local.strftime('%d.%m %H:%M')}: {emoji} {m.mood_score}/5"
                if m.comment:
                    text += f" ({m.comment})"
                text += "\n"
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
                parse_mode=None
            )
            
        elif query.data == "stats_symptoms":
            symptoms = db.query(SymptomLog).filter(
                SymptomLog.user_id == user_id
            ).order_by(SymptomLog.created_at.desc()).all()
            
            if not symptoms:
                await query.edit_message_text("📊 Нет данных о симптомах")
                return
            
            text = "🩺 *Детальная статистика симптомов:*\n\n"
            for s in symptoms[:15]:
                local = utc_to_local(s.created_at, tz)
                text += f"{local.strftime('%d.%m %H:%M')}: {s.symptom} ({s.severity}/5)"
                if s.comment:
                    text += f" - {s.comment}"
                text += "\n"
            
            keyboard = [
                [InlineKeyboardButton("🗑️ Управление симптомами", callback_data="manage_symptoms")],
                get_main_menu_button()
            ]
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=None
            )
            
        elif query.data == "stats_medicine":
            meds = db.query(MedicineLog).filter(
                MedicineLog.user_id == user_id
            ).order_by(MedicineLog.taken_at.desc()).all()
            
            if not meds:
                await query.edit_message_text("📊 Нет данных о лекарствах")
                return
            
            planned = [m for m in meds if m.is_planned and m.status in ['taken', 'extra']]
            unplanned = [m for m in meds if not m.is_planned and m.status in ['taken', 'extra']]
            skipped = [m for m in meds if m.status == 'skipped']
            
            text = f"""💊 *Детальная статистика лекарств*

📅 *Всего приемов:* {len(meds)}
✅ *Запланированные:* {len(planned)}
➕ *Внеплановые:* {len(unplanned)}
❌ *Пропущено:* {len(skipped)}

*Последние приемы:*\n"""
            
            for m in meds[:10]:
                local = utc_to_local(m.taken_at, tz)
                status = "✅" if m.status in ['taken', 'extra'] else "❌"
                plan = "📅" if m.is_planned else "➕"
                text += f"{local.strftime('%d.%m %H:%M')}: {status}{plan} "
                medicine = db.query(Medicine).filter_by(id=m.medicine_id).first()
                name = medicine.name if medicine else "Неизвестно"
                text += f"{name}"
                if m.dosage:
                    text += f" ({m.dosage})"
                if m.comment:
                    text += f"\n   📝 {m.comment[:50]}"
                text += "\n"
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
                parse_mode=None
            )
            
    finally:
        db.close()

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
        active_week = db.query(User).filter(
            User.last_activity >= datetime.now(pytz.UTC) - timedelta(days=7)
        ).count()
        total_medicines = db.query(Medicine).count()
        active_medicines = db.query(Medicine).filter(Medicine.status == 'active').count()
        total_analyses = db.query(Analysis).count()
        today_actions = db.query(AdminLog).filter(
            AdminLog.created_at >= datetime.now(pytz.UTC) - timedelta(days=1)
        ).count()
        
        text = f"""📊 *Статистика бота*

👥 *Пользователи:*
• Всего: {total_users}
• Активных сегодня: {active_today}
• Активных за неделю: {active_week}

💊 *Лекарства:*
• Всего: {total_medicines}
• Активных: {active_medicines}

🩺 *Анализы:*
• Всего: {total_analyses}

📈 *Активность:*
• Действий сегодня: {today_actions}
• В среднем: {today_actions/max(total_users,1):.1f}"""
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]]),
            parse_mode=None
        )
    finally:
        db.close()

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
        lines = f.readlines()[-20:]
    
    if not lines:
        await query.edit_message_text("✅ Ошибок не обнаружено!")
        return
    
    text = "🚨 *Последние ошибки:*\n\n"
    for line in reversed(lines[-10:]):
        if len(line) > 200:
            line = line[:200] + "..."
        text += f"`{line.strip()}`\n"
    
    text += f"\n📊 Всего ошибок: {len(lines)}"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin_logs_errors")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_logs")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

@admin_only
async def admin_backup_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание бэкапа."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔄 Создаю резервную копию...")
    backup_path = backup_manager.create_backup("manual")
    
    if backup_path:
        await query.edit_message_text(
            f"✅ Бэкап успешно создан!\n\n📁 Путь: `{backup_path.name}`",
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
    keyboard = []
    
    for backup in backups[:10]:
        try:
            date = datetime.strptime(backup['timestamp'], '%Y%m%d_%H%M%S')
            date_str = date.strftime('%d.%m.%Y %H:%M')
        except:
            date_str = backup['timestamp']
        
        emoji = {'auto': '🤖', 'manual': '👤', 'pre_update': '🔄'}.get(backup['type'], '📦')
        text += f"{emoji} {date_str} - {backup['size_kb']:.0f} KB\n"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {date_str}",
            callback_data=f"admin_backup_info_{backup['name']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_backups")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )

@admin_only
async def admin_backup_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о бэкапе."""
    query = update.callback_query
    await query.answer()
    
    backup_name = query.data.replace("admin_backup_info_", "")
    backups = backup_manager.get_backups()
    backup = next((b for b in backups if b['name'] == backup_name), None)
    
    if not backup:
        await query.edit_message_text("❌ Бэкап не найден")
        return
    
    try:
        date = datetime.strptime(backup['timestamp'], '%Y%m%d_%H%M%S')
        date_str = date.strftime('%d.%m.%Y %H:%M:%S')
    except:
        date_str = backup['timestamp']
    
    type_names = {'auto': '🤖 Автоматический', 'manual': '👤 Ручной', 'pre_update': '🔄 Пред-обновление'}
    type_display = type_names.get(backup['type'], f'📦 {backup["type"]}')
    
    text = f"""📁 *Информация о бэкапе*

📌 *Имя:* `{backup_name}`
📊 *Тип:* {type_display}
🕐 *Дата:* {date_str}
📦 *Файлов:* {len(backup['files'])}
📈 *Размер:* {backup['size_kb']:.1f} KB"""

    if backup['stats']:
        text += "\n\n📋 *Состав:*\n" + "\n".join(f"• {s}" for s in backup['stats'])
    
    keyboard = [
        [
            InlineKeyboardButton("🔄 Восстановить", callback_data=f"admin_backup_restore_{backup_name}"),
            InlineKeyboardButton("📥 Скачать", callback_data=f"admin_backup_download_{backup_name}")
        ],
        [InlineKeyboardButton("🔙 К списку", callback_data="admin_backup_list")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )

@admin_only
async def admin_backup_restore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Восстановление из бэкапа."""
    query = update.callback_query
    await query.answer()
    
    backup_name = query.data.replace("admin_backup_restore_", "")
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, восстановить", callback_data=f"admin_backup_confirm_{backup_name}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"admin_backup_info_{backup_name}")
        ]
    ]
    
    await query.edit_message_text(
        f"⚠️ *Внимание!*\n\nВы уверены, что хотите восстановить данные из бэкапа `{backup_name}`?\nТекущие данные будут заменены!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )

@admin_only
async def admin_backup_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение восстановления."""
    query = update.callback_query
    await query.answer()
    
    backup_name = query.data.replace("admin_backup_confirm_", "")
    
    await query.edit_message_text("🔄 Восстанавливаю данные...")
    
    scheduler.scheduler.pause()
    success = backup_manager.restore(backup_name)
    
    if success:
        await query.edit_message_text(
            "✅ *Восстановление завершено!*\n\nПерезапускаю планировщик...",
            parse_mode=None
        )
        scheduler.scheduler.resume()
        await scheduler.restore_reminders()
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="✅ Бот успешно восстановлен!"
        )
    else:
        await query.edit_message_text("❌ Ошибка при восстановлении")

# ============== ЧАСОВЫЕ ПОЯСА ==============

async def set_timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка часового пояса."""
    user_id = update.effective_user.id
    current = get_user_timezone(user_id)
    
    text = f"🕒 Текущий часовой пояс: {current}\n\nВыберите новый:"
    
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
        get_main_menu_button()
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def timezone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка часового пояса."""
    query = update.callback_query
    await query.answer()
    
    tz = query.data.replace("tz_", "")
    user_id = update.effective_user.id
    
    set_user_timezone(user_id, tz)
    
    await query.edit_message_text(
        f"✅ Часовой пояс установлен: {tz}",
        reply_markup=InlineKeyboardMarkup([get_main_menu_button()]),
        parse_mode=None
    )

# ============== ОБРАБОТЧИК КНОПОК ==============

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик кнопок."""
    query = update.callback_query
    data = query.data
    
    # Навигация
    if data == "start":
        await start_callback(update, context)
    elif data == "back":
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
    elif data == "extra_medicine":
        await extra_medicine_start(update, context)
    elif data.startswith("extra_select_"):
        await extra_medicine_select(update, context)
    elif data == "skip_dosage":
        await extra_medicine_dosage(update, context)
    elif data == "skip_comment":
        await extra_medicine_comment(update, context)
    
    # Списки
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
    elif data == "doctor_visited":
        await doctor_visited(update, context)
    elif data == "symptoms":
        await symptoms_command(update, context)
    elif data.startswith("severity_"):
        await symptom_severity(update, context)
    
    # Симптомы
    elif data == "manage_symptoms":
        await manage_symptoms_callback(update, context)
    elif data.startswith("symptom_page_"):
        context.user_data['symptom_page'] = int(data.split('_')[-1])
        await manage_symptoms_callback(update, context)
    elif data.startswith("delete_symptom_"):
        await delete_symptom_callback(update, context)
    
    # Прием лекарств
    elif data.startswith("take_"):
        await medicine_take(update, context)
    elif data.startswith("skip_"):
        await medicine_skip(update, context)
    elif data.startswith("analysis_take_"):
        await analysis_take(update, context)
    elif data.startswith("analysis_skip_"):
        await analysis_skip(update, context)
    
    # Комментарии
    elif data.startswith("comment_"):
        if "symptom" in data or "side" in data or "normal" in data:
            await medicine_comment_type(update, context)
        else:
            await medicine_comment_start(update, context)
    
    # Откладывание анализов
    elif data.startswith("postpone_analysis_"):
        if "custom" in data:
            await postpone_analysis_days(update, context)
        elif data.count('_') == 3:
            await postpone_analysis_days(update, context)
        else:
            await postpone_analysis_start(update, context)
    elif data.startswith("cancel_analysis_"):
        await cancel_analysis(update, context)
    elif data.startswith("analysis_notes_"):
        await analysis_notes_start(update, context)
    
    # Часовые пояса
    elif data == "set_timezone":
        await set_timezone_command(update, context)
    elif data.startswith("tz_"):
        await timezone_callback(update, context)
    
    # Админ-панель
    elif data == "admin_panel":
        await admin_command(update, context)
    elif data == "admin_stats":
        await admin_stats_callback(update, context)
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
    elif data.startswith("admin_backup_info_"):
        await admin_backup_info_callback(update, context)
    elif data.startswith("admin_backup_restore_"):
        await admin_backup_restore_callback(update, context)
    elif data.startswith("admin_backup_confirm_"):
        await admin_backup_confirm_callback(update, context)
    
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
    elif data == "noop":
        await query.answer("Это информационная кнопка")
    else:
        await query.answer("Функция в разработке")

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    text = f"""👋 Здравствуйте, {user.first_name}!

Я ЛОР-Помощник — персональный медицинский бот, созданный врачом-оториноларингологом Денисом Казариным.

👶 Врач ведет прием детей с 0 лет и взрослых

🤖 Мои возможности:
• 💊 Напоминания о приеме лекарств
• 🩺 Напоминания об анализе
• 📊 Отслеживание самочувствия
• 📈 Статистика

Выберите действие:"""
    
    await query.edit_message_text(text, reply_markup=get_start_keyboard(), parse_mode=None)

# ============== ЕЖЕДНЕВНЫЕ ЗАДАЧИ ==============

async def daily_mood_check(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневный опрос в 21:00."""
    db = get_db()
    try:
        users = db.query(User).filter(User.is_active == True, User.is_banned == False).all()
        for u in users:
            try:
                tz = pytz.timezone(get_user_timezone(u.user_id))
                now = datetime.now(tz)
                if 20 <= now.hour <= 22:
                    await context.bot.send_message(
                        chat_id=u.user_id,
                        text="📊 Как вы себя чувствуете сегодня?\n\nОцените по 5-балльной шкале:",
                        reply_markup=get_mood_keyboard()
                    )
            except Exception as e:
                log.error(f"Ошибка опроса {u.user_id}: {e}")
    finally:
        db.close()

async def scheduled_backup(context: ContextTypes.DEFAULT_TYPE):
    """Плановый бэкап."""
    backup_manager.create_backup("auto")

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
        
        # Восстановление отложенных
        for rem in db.query(Reminder).filter(
            Reminder.status == 'postponed',
            Reminder.postponed_until.isnot(None),
            Reminder.postponed_until <= now
        ):
            rem.status = 'pending'
            rem.postponed_until = None
            scheduler.scheduler.add_job(
                send_reminder_job,
                trigger=DateTrigger(run_date=rem.scheduled_time),
                id=f"{rem.reminder_type}_{rem.id}",
                args=[rem.id],
                replace_existing=True
            )
            log.info(f"🔄 Восстановлено напоминание {rem.id}")
        
        db.commit()
        
        # Проверка планировщика
        pending = db.query(Reminder).filter(
            Reminder.status == 'pending',
            Reminder.scheduled_time > now
        ).all()
        
        pending_ids = {f"{r.reminder_type}_{r.id}" for r in pending}
        job_ids = {job.id for job in scheduler.scheduler.get_jobs()}
        
        # Восстановление пропущенных
        for job_id in pending_ids - job_ids:
            rid = int(job_id.split('_')[1])
            rem = db.query(Reminder).filter_by(id=rid).first()
            if rem and rem.scheduled_time > now:
                scheduler.scheduler.add_job(
                    send_reminder_job,
                    trigger=DateTrigger(run_date=rem.scheduled_time),
                    id=job_id,
                    args=[rid],
                    replace_existing=True
                )
                log.warning(f"🔄 Восстановлено задание {job_id}")
        
        # Удаление мертвых
        for job_id in job_ids - pending_ids:
            if job_id.startswith(('medicine_', 'analysis_')):
                try:
                    scheduler.scheduler.remove_job(job_id)
                    log.info(f"🗑️ Удалено мертвое задание {job_id}")
                except:
                    pass
        
        # Просроченные
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

# ============== ОТМЕНА ==============

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

# ============== СОЗДАНИЕ ПРИЛОЖЕНИЯ ==============

def create_application():
    """Создание приложения."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.scheduler = scheduler.scheduler
    
    # Команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("settimezone", set_timezone_command))
    app.add_handler(CommandHandler("mood", mood_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("list", list_medicines))
    app.add_handler(CommandHandler("list_medicines", list_medicines))
    app.add_handler(CommandHandler("list_analyses", list_analyses))
    app.add_handler(CommandHandler("extra", extra_medicine_start))
    app.add_handler(CommandHandler("admin", admin_command))
    
    # ConversationHandler для лекарств
    medicine_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_medicine_start, pattern="^add_medicine$")],
        states={
            MEDICINE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_medicine_name)],
            MEDICINE_FREQUENCY: [
                CallbackQueryHandler(add_medicine_frequency, pattern="^med_freq_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_medicine_frequency)
            ],
            MEDICINE_TIME: [
                CallbackQueryHandler(add_medicine_time_hour, pattern="^med_time_hour_"),
                CallbackQueryHandler(add_medicine_time_minute, pattern="^med_time_minute_"),
            ],
            MEDICINE_REMINDER: [
                CallbackQueryHandler(add_medicine_reminder, pattern="^med_remind_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_medicine_reminder)
            ],
            MEDICINE_CONFIRM: [CallbackQueryHandler(add_medicine_confirm, pattern="^confirm_medicine$")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
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
            ANALYSIS_TIME: [
                CallbackQueryHandler(add_analysis_time_hour, pattern="^ana_hour_"),
                CallbackQueryHandler(add_analysis_time_minute, pattern="^ana_minute_"),
            ],
            ANALYSIS_REMINDER: [
                CallbackQueryHandler(add_analysis_reminder, pattern="^ana_remind_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_analysis_reminder)
            ],
            ANALYSIS_CONFIRM: [CallbackQueryHandler(add_analysis_confirm, pattern="^confirm_analysis$")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
        name="add_analysis"
    )
    
    # ConversationHandler для симптомов
    symptom_conv = ConversationHandler(
        entry_points=[
            CommandHandler("symptoms", symptoms_command),
            CallbackQueryHandler(symptoms_command, pattern="^symptoms$")
        ],
        states={
            SYMPTOM_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, symptom_text)],
            SYMPTOM_SEVERITY: [CallbackQueryHandler(symptom_severity, pattern="^severity_")],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
        name="add_symptom"
    )
    
    # ConversationHandler для экстренного приема
    extra_conv = ConversationHandler(
        entry_points=[
            CommandHandler("extra", extra_medicine_start),
            CallbackQueryHandler(extra_medicine_start, pattern="^extra_medicine$")
        ],
        states={
            EXTRA_MEDICINE_SELECT: [CallbackQueryHandler(extra_medicine_select, pattern="^extra_select_")],
            MEDICINE_DOSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extra_medicine_dosage),
                CallbackQueryHandler(extra_medicine_dosage, pattern="^skip_dosage$")
            ],
            MEDICINE_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, extra_medicine_comment),
                CallbackQueryHandler(extra_medicine_comment, pattern="^skip_comment$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
        name="extra_medicine"
    )
    
    # ConversationHandler для комментариев
    comment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(medicine_comment_start, pattern="^comment_")],
        states={
            MEDICINE_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, medicine_comment_save),
                CallbackQueryHandler(medicine_comment_type, pattern="^comment_symptom_|^comment_side_|^comment_normal_")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
        name="comment_medicine"
    )
    
    # ConversationHandler для откладывания анализов
    postpone_analysis_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(postpone_analysis_start, pattern="^postpone_analysis_")],
        states={
            POSTPONE_ANALYSIS: [
                CallbackQueryHandler(postpone_analysis_days, pattern="^postpone_analysis_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, postpone_analysis_days)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CallbackQueryHandler(cancel, pattern="^cancel$")],
        name="postpone_analysis"
    )
    
    # Добавляем все обработчики
    app.add_handler(medicine_conv)
    app.add_handler(analysis_conv)
    app.add_handler(symptom_conv)
    app.add_handler(extra_conv)
    app.add_handler(comment_conv)
    app.add_handler(postpone_analysis_conv)
    
    # Обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Плановые задачи
    app.job_queue.run_repeating(integrity_check, interval=3600, first=10, name="integrity")
    app.job_queue.run_daily(daily_mood_check, time=datetime.strptime("21:00", "%H:%M").time(), name="daily_mood")
    app.job_queue.run_daily(scheduled_backup, time=datetime.strptime("03:00", "%H:%M").time(), name="daily_backup")
    
    return app

# ============== ЗАПУСК ==============

async def main():
    """Главная функция."""
    global application, error_notifier
    
    if BOT_TOKEN == "ВАШ_ТОКЕН_ЗДЕСЬ":
        print("\n" + "="*50)
        print("⚠️  ВНИМАНИЕ! Необходимо установить токен бота!")
        print("="*50)
        return
    
    print("🚀 Запуск ЛОР-Помощника...")
    print(f"📊 Версия: 11.0.0 (Новая логика)")
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
    print("💡 Отправьте /start в Telegram: @NEW_lor_helper_bot")
    print("⏎ Нажмите Ctrl+C для остановки")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Бот остановлен")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        if scheduler:
            scheduler.shutdown()
        if error_notifier:
            await error_notifier.stop()
        log.info("SHUTDOWN - Бот остановлен корректно")

# ============== ТОЧКА ВХОДА ==============

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
