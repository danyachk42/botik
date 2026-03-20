import os
import sqlite3
import time
import threading
import random
import re
import json
import logging
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import shutil
import traceback
import sys
from collections import defaultdict, deque

import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery, User

# Загружаем переменные окружения из .env (удобно локально).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ==================== ЛОГИРОВАНИЕ ====================
try:
    # Windows-консоль иногда бывает в cp1251, а в логах используются эмодзи.
    # Переводим stdout/stderr в UTF-8, чтобы `logging` не падал.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "spy_bot.log"),
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SpyBot")

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Создай файл .env рядом с main.py и укажи BOT_TOKEN=... "
        "(или задай переменную окружения BOT_TOKEN)."
    )
ADMIN_ID = 1244890626
BOT_USERNAME = "spionssbot"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML', skip_pending=True, threaded=True, num_threads=16)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "spy_bot (1).db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# ==================== ЛОКАЦИИ ====================
DEFAULT_LOCATIONS = [
    "Аэропорт", "Больница", "Библиотека", "Кинотеатр", "Ресторан",
    "Парикмахерская", "Супермаркет", "Полицейский участок", "Школа", "Университет",
    "Пляж", "Аквапарк", "Зоопарк", "Цирк", "Театр",
    "Стадион", "Фитнес-зал", "Кафе", "Отделение банка", "Почта",
    "Тюрьма", "Музей", "Концертный зал", "Автосалон", "АЗС",
    "Парк аттракционов", "Ледовый каток", "Пожарная часть", "Студия звукозаписи", "Радиостанция",
    "Космодром", "Подводная лодка", "Океанариум", "Полевой госпиталь", "Космический корабль",
    "Научная лаборатория", "Секретная база", "Деревня ведьм", "Пиратский корабль", "Гора Эверест",
    "Пустыня Сахара", "Джунгли Амазонки", "Антарктическая станция", "Действующий вулкан", "Средневековое подземелье",
    "Дворец фараона", "Замок графа Дракулы", "Голливуд", "Бродвей", "Стамбульский базар"
]

# ==================== ЦЕНЫ И ДЛИТЕЛЬНОСТИ ====================
VIP_PRICES = {'1m': 30, '3m': 100, '6m': 170, '1y': 380}
VIP_DURATIONS = {'1m': 30, '3m': 90, '6m': 180, '1y': 365}

# ==================== ТЕМЫ ====================
THEMES = {
    'default': {
        'emoji': '🕵️‍♂️',
        'join_phrase': '✅ Присоединиться',
        'settings_phrase': '⚙️ Настройки',
        'start_phrase': '▶️ Начать',
        'game_start': '🕵️‍♂️ Игра начинается!',
        'discussion_start': '💬 Начинается обсуждение!',
        'voting_start': '🗳️ Начинается голосование!',
        'round_text': '🔄 Раунд',
    },
    'winter': {
        'emoji': '❄️',
        'join_phrase': '❄️ Сесть у камина',
        'settings_phrase': '⚙️ Настроить игру',
        'start_phrase': '🎄 Начать игру',
        'game_start': '❄️ Зимняя игра начинается!',
        'discussion_start': '☃️ Начинается обсуждение!',
        'voting_start': '⛄ Начинается голосование!',
        'round_text': '❄️ Раунд',
    },
    'valentine': {
        'emoji': '💝',
        'join_phrase': '💕 Присоединиться',
        'settings_phrase': '💝 Настроить игру',
        'start_phrase': '💘 Начать игру',
        'game_start': '💝 Игра любви начинается!',
        'discussion_start': '💕 Начинается обсуждение!',
        'voting_start': '💗 Начинается голосование!',
        'round_text': '💘 Раунд',
    },
    'halloween': {
        'emoji': '🎃',
        'join_phrase': '👻 Войти в замок',
        'settings_phrase': '🎃 Настроить игру',
        'start_phrase': '👻 Начать игру',
        'game_start': '🎃 Хеллоуинская игра начинается!',
        'discussion_start': '👻 Начинается обсуждение!',
        'voting_start': '🦇 Начинается голосование!',
        'round_text': '🎃 Раунд',
    }
}

# ==================== КОНСТАНТЫ ====================
ROLE_CIVILIAN = 'civilian'
ROLE_SPY = 'spy'
SPY_RULES = {1: 3, 2: 5, 3: 7, 4: 9, 5: 11}
SPY_WIN_RULES = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}
DEFAULT_GAME_SETTINGS = {
    'discussion_time': 5,
    'voting_time': 2,
    'spies_count': 1,
    'guess_attempts': 3
}

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
processing_active = True
user_states = {}
game_sessions = {}
muted_users = defaultdict(lambda: {'until': None, 'count': 0})
game_timers = {}
active_games = {}
lock = threading.RLock()

# ==================== ФУНКЦИИ БД ====================
def get_db_connection():
    """Получение подключения к БД"""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA cache_size=10000')
        return conn
    except sqlite3.Error as e:
        logger.error(f"❌ Ошибка БД: {str(e)}")
        raise

def init_database():
    """Инициализация БД"""
    try:
        logger.info("🔄 Инициализация БД...")
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_vip BOOLEAN DEFAULT 0,
            vip_expires_at TEXT,
            games_played INTEGER DEFAULT 0,
            times_spy INTEGER DEFAULT 0,
            times_civilian INTEGER DEFAULT 0,
            stars_spent INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_active TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            username TEXT,
            bot_admin BOOLEAN DEFAULT 0,
            default_discussion_time INTEGER DEFAULT 5,
            default_voting_time INTEGER DEFAULT 2,
            default_spies_count INTEGER DEFAULT 1,
            default_guess_attempts INTEGER DEFAULT 3,
            theme TEXT DEFAULT 'default',
            created_at TEXT NOT NULL,
            last_active TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            creator_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            discussion_time INTEGER NOT NULL,
            voting_time INTEGER NOT NULL,
            spies_count INTEGER NOT NULL,
            guess_attempts INTEGER NOT NULL,
            location TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            winner TEXT,
            round_count INTEGER DEFAULT 1,
            message_id INTEGER,
            created_at TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS game_players (
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT,
            guessed_location BOOLEAN DEFAULT 0,
            alive BOOLEAN DEFAULT 1,
            voted BOOLEAN DEFAULT 0,
            guess_attempts_left INTEGER DEFAULT 3,
            eliminated_round INTEGER DEFAULT 0,
            PRIMARY KEY (game_id, user_id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS votes (
            vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            round_number INTEGER DEFAULT 1,
            voter_id INTEGER NOT NULL,
            voted_for_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS custom_locations (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            location_name TEXT NOT NULL,
            added_by INTEGER,
            added_at TEXT NOT NULL,
            UNIQUE(chat_id, location_name)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS vip_purchases (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            stars INTEGER NOT NULL,
            duration TEXT NOT NULL,
            purchased_at TEXT NOT NULL,
            operation_id TEXT UNIQUE
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
            game_id INTEGER PRIMARY KEY UNIQUE,
            chat_id INTEGER NOT NULL,
            current_round INTEGER DEFAULT 1,
            current_phase TEXT DEFAULT 'discussion',
            discussion_end_time TEXT,
            voting_end_time TEXT,
            spies_guessed_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS muted_players (
            mute_id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            muted_until TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        )''')

        # --- Мягкая миграция схемы (на случай старых/частично измененных БД) ---
        def ensure_column(table_name: str, column_name: str, column_def_sql: str):
            cols = [row[1] for row in cursor.execute(f'PRAGMA table_info({table_name})').fetchall()]
            if column_name in cols:
                return
            logger.warning(f"⚠️ В БД отсутствует колонка {table_name}.{column_name}. Добавляю...")
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_def_sql}')

        ensure_column('game_players', 'guessed_location', 'guessed_location BOOLEAN DEFAULT 0')
        ensure_column('game_players', 'alive', 'alive BOOLEAN DEFAULT 1')
        ensure_column('game_players', 'voted', 'voted BOOLEAN DEFAULT 0')
        ensure_column('game_players', 'guess_attempts_left', 'guess_attempts_left INTEGER DEFAULT 3')
        ensure_column('game_players', 'eliminated_round', 'eliminated_round INTEGER DEFAULT 0')
        ensure_column('active_sessions', 'discussion_end_time', 'discussion_end_time TEXT')
        ensure_column('active_sessions', 'voting_end_time', 'voting_end_time TEXT')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_games_chat_status ON games(chat_id, status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_players_game ON game_players(game_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_votes_game_round ON votes(game_id, round_number)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_vip ON users(is_vip, vip_expires_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_custom_locations_chat ON custom_locations(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_sessions_game ON active_sessions(game_id)')

        conn.commit()
        conn.close()

        add_default_locations()

        logger.info("✅ БД инициализирована успешно")
        return True

    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА инициализации БД: {str(e)}")
        logger.error(traceback.format_exc())
        return False

def add_default_locations():
    """Добавление локаций по умолчанию"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        for location in DEFAULT_LOCATIONS:
            try:
                cursor.execute('''INSERT OR IGNORE INTO custom_locations 
                    (chat_id, location_name, added_by, added_at) 
                    VALUES (?, ?, ?, ?)''', (0, location.strip(), ADMIN_ID, now))
            except:
                pass

        conn.commit()
        conn.close()
        logger.info(f"✅ Добавлено {len(DEFAULT_LOCATIONS)} локаций")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка добавления локаций: {str(e)}")
        return False

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def cleanup_chat_in_db(chat_id: int) -> None:
    """Удаляет пользователя/группу из БД, если Telegram запретил отправку (403/404/400).
    Это нужно, чтобы рассылки не теряли время на заблокировавших и чтобы данные со временем не устаревали.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE user_id = ?', (chat_id,))
        cursor.execute('DELETE FROM groups WHERE chat_id = ?', (chat_id,))
        conn.commit()
        conn.close()
    except Exception:
        # Не падаем, если БД недоступна
        pass

def safe_send_message(chat_id: int, text: str, reply_markup=None, parse_mode='HTML'):
    """Безопасная отправка сообщения с обработкой ошибок - ВОЗВРАЩАЕТ ОБЪЕКТ СООБЩЕНИЯ"""
    try:
        msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return msg
    except telebot.apihelper.ApiException as e:
        if e.result.status_code in (403, 404):
            logger.warning(f"⚠️ Невозможно отправить в {chat_id} (код {e.result.status_code}). Удаляю из БД...")
            cleanup_chat_in_db(chat_id)
            return None
        elif e.result.status_code == 400:
            logger.warning(f"⚠️ Ошибка 400 при отправке в {chat_id}: {str(e)}")
            return None
        else:
            logger.error(f"❌ Ошибка отправки сообщения в {chat_id}: {str(e)}")
            return None
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при отправке в {chat_id}: {str(e)}")
        return None

def safe_answer_callback(callback_id: str, text: str = None, show_alert: bool = False) -> bool:
    """Безопасный ответ на callback query"""
    try:
        bot.answer_callback_query(callback_id, text=text, show_alert=show_alert)
        return True
    except telebot.apihelper.ApiException as e:
        if e.result.status_code == 400:
            logger.warning(f"⚠️ Callback query истек: {callback_id}")
            return False
        else:
            logger.error(f"❌ Ошибка ответа на callback: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при ответе на callback: {str(e)}")
        return False

def safe_edit_message(chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode='HTML') -> bool:
    """Безопасное редактирование сообщения с обработкой ошибок"""
    try:
        bot.edit_message_text(
            text, 
            chat_id, 
            message_id, 
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except telebot.apihelper.ApiException as e:
        if "message is not modified" in str(e):
            logger.debug(f"ℹ️ Сообщение не изменилось, обновление пропущено")
            return True
        elif e.result.status_code == 400:
            logger.warning(f"⚠️ Ошибка 400 при редактировании: {str(e)}")
            return False
        else:
            logger.error(f"❌ Ошибка редактирования сообщения: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при редактировании: {str(e)}")
        return False

def parse_duration(duration_str: str) -> timedelta:
    """Парсинг длительности"""
    match = re.match(r'(\d+)([hdwmy])', duration_str.lower())
    if not match:
        raise ValueError("Неверный формат времени. Используйте: 1h, 1d, 1w, 1m, 1y")

    value, unit = int(match.group(1)), match.group(2)

    if unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    elif unit == 'w':
        return timedelta(weeks=value)
    elif unit == 'm':
        return timedelta(days=value * 30)
    elif unit == 'y':
        return timedelta(days=value * 365)
    else:
        raise ValueError("Неверный формат времени")

def get_user_profile_link(user_id: int, name: str = None) -> str:
    """Получение ссылки на профиль пользователя"""
    try:
        if not name:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT first_name, username FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                conn.close()
                if result:
                    name = result['first_name'] or result['username'] or f"User{user_id}"
                else:
                    name = f"User{user_id}"
            except:
                name = f"User{user_id}"

        name = str(name).replace('<', '').replace('>', '').replace('&', '&amp;').replace('"', '&quot;')
        return f'<a href="tg://user?id={user_id}">{name}</a>'
    except Exception as e:
        logger.error(f"❌ Ошибка создания ссылки: {str(e)}")
        return f"User{user_id}"

def check_bot_permissions(chat_id: int) -> bool:
    """Проверка прав бота в группе"""
    try:
        bot_me = bot.get_me()
        chat = bot.get_chat(chat_id)
        bot_member = bot.get_chat_member(chat_id, bot_me.id)

        if bot_member.status not in ['administrator', 'creator']:
            return False

        has_pin = getattr(bot_member, 'can_pin_messages', False)
        has_delete = getattr(bot_member, 'can_delete_messages', False)
        has_invite = getattr(bot_member, 'can_invite_users', False)
        has_restrict = getattr(bot_member, 'can_restrict_members', False)

        has_all = has_pin and has_delete and has_invite and has_restrict

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute('SELECT chat_id FROM groups WHERE chat_id = ?', (chat_id,))
            exists = cursor.fetchone()

            if exists:
                cursor.execute('''UPDATE groups SET bot_admin = ?, title = ?, username = ?, last_active = ? 
                    WHERE chat_id = ?''', (has_all, chat.title[:100] if chat.title else None, 
                    chat.username[:50] if chat.username else None, now, chat_id))
            else:
                cursor.execute('''INSERT INTO groups (chat_id, bot_admin, title, username, created_at, last_active) 
                    VALUES (?, ?, ?, ?, ?, ?)''', (chat_id, has_all, chat.title[:100] if chat.title else None, 
                    chat.username[:50] if chat.username else None, now, now))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"⚠️ Ошибка обновления информации о группе: {str(e)}")

        return has_all

    except Exception as e:
        logger.error(f"❌ ОШИБКА проверки прав в чате {chat_id}: {str(e)}")
        return False

def format_time(minutes: int) -> str:
    """Форматирование времени"""
    if minutes <= 0:
        return "0 минут"
    elif minutes == 1:
        return "1 минуту"
    elif 2 <= minutes % 10 <= 4 and (minutes < 10 or minutes > 20):
        return f"{minutes} минуты"
    else:
        return f"{minutes} минут"

def add_user(user: User) -> bool:
    """Добавление пользователя в БД"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user.id,))
        exists = cursor.fetchone()

        if exists:
            cursor.execute('''UPDATE users SET username = ?, first_name = ?, last_name = ?, last_active = ? 
                WHERE user_id = ?''', (user.username[:50] if user.username else None, 
                user.first_name[:50] if user.first_name else None, 
                user.last_name[:50] if user.last_name else None, now, user.id))
        else:
            cursor.execute('''INSERT INTO users (user_id, username, first_name, last_name, created_at, last_active) 
                VALUES (?, ?, ?, ?, ?, ?)''', (user.id, user.username[:50] if user.username else None, 
                user.first_name[:50] if user.first_name else None, 
                user.last_name[:50] if user.last_name else None, now, now))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка добавления пользователя {user.id}: {str(e)}")
        return False

def get_vip_status_message(user_id: int) -> Tuple[bool, str]:
    """Возвращает (активен?, текст статуса для пользователя)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT is_vip, vip_expires_at FROM users WHERE user_id = ?''', (user_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or not row['is_vip'] or not row['vip_expires_at']:
            return False, "VIP сейчас не активен."

        try:
            expires_at = datetime.fromisoformat(row['vip_expires_at'])
        except Exception:
            return False, "VIP сейчас не активен (дата некорректна)."

        now = datetime.now()
        if expires_at > now:
            days_left = (expires_at - now).days
            if days_left <= 0:
                return True, f"VIP активен до {expires_at.strftime('%d.%m.%Y')}."
            return True, f"VIP активен до {expires_at.strftime('%d.%m.%Y')} (осталось: {days_left} дн.)."

        return False, f"VIP истёк {expires_at.strftime('%d.%m.%Y')}."
    except Exception as e:
        logger.error(f"❌ Ошибка получения VIP: {str(e)}")
        return False, "VIP сейчас не активен."


def is_user_vip(user_id: int) -> bool:
    """Проверка VIP статуса"""
    active, _ = get_vip_status_message(user_id)
    return active

def get_game_settings(chat_id: int) -> dict:
    """Получение настроек игры для группы"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT default_discussion_time, default_voting_time, default_spies_count, 
            default_guess_attempts FROM groups WHERE chat_id = ?''', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            return {
                'discussion_time': result['default_discussion_time'],
                'voting_time': result['default_voting_time'],
                'spies_count': result['default_spies_count'],
                'guess_attempts': result['default_guess_attempts']
            }
        return DEFAULT_GAME_SETTINGS.copy()
    except Exception as e:
        logger.error(f"❌ Ошибка получения настроек: {str(e)}")
        return DEFAULT_GAME_SETTINGS.copy()

def update_game_settings(chat_id: int, settings: dict) -> Tuple[bool, str]:
    """Обновление настроек игры с валидацией"""
    try:
        discussion_time = settings.get('discussion_time', 5)
        voting_time = settings.get('voting_time', 2)
        spies_count = settings.get('spies_count', 1)
        guess_attempts = settings.get('guess_attempts', 3)

        errors = []

        if not isinstance(discussion_time, int) or not (1 <= discussion_time <= 80):
            errors.append("⏱️ Обсуждение: 1-80 минут")
        if not isinstance(voting_time, int) or not (1 <= voting_time <= 60):
            errors.append("🗳️ Голосование: 1-60 минут")
        if not isinstance(spies_count, int) or not (1 <= spies_count <= 5):
            errors.append("🕵️ Шпионы: 1-5")
        if not isinstance(guess_attempts, int) or not (1 <= guess_attempts <= 10):
            errors.append("🎯 Попытки: 1-10")

        if errors:
            return False, "❌ <b>Ошибки валидации:</b>\n\n" + "\n".join(errors)

        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute('SELECT chat_id FROM groups WHERE chat_id = ?', (chat_id,))
        exists = cursor.fetchone()

        if exists:
            cursor.execute('''UPDATE groups SET default_discussion_time = ?, default_voting_time = ?, 
                default_spies_count = ?, default_guess_attempts = ?, last_active = ? WHERE chat_id = ?''', 
                (discussion_time, voting_time, spies_count, guess_attempts, now, chat_id))
        else:
            cursor.execute('''INSERT INTO groups (chat_id, default_discussion_time, default_voting_time, 
                default_spies_count, default_guess_attempts, created_at, last_active) 
                VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                (chat_id, discussion_time, voting_time, spies_count, guess_attempts, now, now))

        conn.commit()
        conn.close()

        logger.info(f"✅ Настройки обновлены для чата {chat_id}")
        return True, "✅ Настройки успешно обновлены!"

    except Exception as e:
        logger.error(f"❌ Ошибка обновления настроек: {str(e)}")
        return False, "❌ Ошибка обновления настроек!"

def get_group_theme(chat_id: int) -> str:
    """Получение темы группы"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT theme FROM groups WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        return result['theme'] if result and result['theme'] in THEMES else 'default'
    except Exception as e:
        logger.error(f"❌ Ошибка получения темы: {str(e)}")
        return 'default'

def is_user_spy(game_id: int, user_id: int) -> bool:
    """Проверка, является ли пользователь шпионом"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT role FROM game_players WHERE game_id = ? AND user_id = ?''', 
            (game_id, user_id))
        result = cursor.fetchone()
        conn.close()

        return bool(result and result['role'] == ROLE_SPY)
    except Exception as e:
        logger.error(f"❌ Ошибка проверки роли: {str(e)}")
        return False

def is_player_alive(game_id: int, user_id: int) -> bool:
    """Проверка, жив ли игрок"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT alive FROM game_players WHERE game_id = ? AND user_id = ?''', 
            (game_id, user_id))
        result = cursor.fetchone()
        conn.close()

        return bool(result and result['alive'])
    except Exception as e:
        logger.error(f"❌ Ошибка проверки жизни: {str(e)}")
        return False

def update_game_message(chat_id: int, game_id: int, message_id: int):
    """Обновление сообщения с информацией об игре"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT COUNT(*) as count FROM game_players WHERE game_id = ?''', (game_id,))
        player_count = cursor.fetchone()['count']

        cursor.execute('''SELECT creator_id, discussion_time, voting_time, spies_count, guess_attempts 
            FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()

        if not game:
            conn.close()
            return

        creator_id = game['creator_id']
        discussion_time = game['discussion_time']
        voting_time = game['voting_time']
        spies_count = game['spies_count']
        guess_attempts = game['guess_attempts']

        min_players = SPY_RULES.get(spies_count, spies_count * 2 + 1)
        needed = max(0, min_players - player_count)

        cursor.execute('''SELECT user_id FROM game_players WHERE game_id = ?''', (game_id,))
        players = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        creator_text = f"👤 <b>Создатель:</b> {get_user_profile_link(creator_id)}\n\n" if creator_id else ""

        game_message = (
            f"🕵️‍♂️ <b>Набор в игру начат!</b>\n\n"
            f"{creator_text}"
            f"👥 <b>Участники ({player_count}/{min_players}):</b>\n"
            f"{', '.join([get_user_profile_link(p) for p in players]) or 'Пока никого'}\n\n"
            f"📊 <b>Статус:</b>\n"
            f"Игроков: {player_count}\n"
            f"Минимум: {min_players}\n"
            f"Осталось: {needed}\n\n"
            f"⚙️ <b>Настройки:</b>\n"
            f"⏱️ Обсуждение: {format_time(discussion_time)}\n"
            f"🗳️ Голосование: {format_time(voting_time)}\n"
            f"🕵️‍♂️ Шпионов: {spies_count}\n"
            f"🎯 Попыток: {guess_attempts}"
        )

        safe_edit_message(
            chat_id, 
            message_id, 
            game_message, 
            reply_markup=get_game_keyboard(chat_id, game_id)
        )

    except Exception as e:
        logger.error(f"❌ Ошибка обновления сообщения: {str(e)}")

# ==================== КЛАВИАТУРЫ ====================

def get_start_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура /start"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("📖 Правила игры", callback_data="rules"),
        InlineKeyboardButton("⭐ Купить VIP", callback_data="buy_vip"),
        InlineKeyboardButton("📍 Список локаций", callback_data="locations"),
        InlineKeyboardButton("📣 Наш канал", url="https://t.me/spygoo")
    )
    return keyboard

def get_vip_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура покупки VIP"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(f"1️⃣ месяц - {VIP_PRICES['1m']} ⭐", callback_data="vip_1m"),
        InlineKeyboardButton(f"3️⃣ месяца - {VIP_PRICES['3m']} ⭐", callback_data="vip_3m"),
        InlineKeyboardButton(f"6️⃣ месяцев - {VIP_PRICES['6m']} ⭐ 🔥", callback_data="vip_6m"),
        InlineKeyboardButton(f"1️⃣2️⃣ месяцев - {VIP_PRICES['1y']} ⭐", callback_data="vip_1y"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_vip")
    )
    return keyboard

def get_help_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура помощи"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("👥 Команды для всех", callback_data="help_general"),
        InlineKeyboardButton("⭐ VIP команды", callback_data="help_vip")
    )
    return keyboard

def get_game_keyboard(chat_id: int, game_id: int) -> InlineKeyboardMarkup:
    """Клавиатура игры"""
    theme = get_group_theme(chat_id)
    theme_data = THEMES[theme]

    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton(theme_data['join_phrase'], 
            url=f"https://t.me/{BOT_USERNAME}?start=join_{game_id}"),
        InlineKeyboardButton(theme_data['settings_phrase'], 
            callback_data=f"settings_{game_id}"),
        InlineKeyboardButton(theme_data['start_phrase'], 
            callback_data=f"start_game_{game_id}")
    )
    return keyboard

def get_theme_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора темы"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    for theme_name, theme_data in THEMES.items():
        keyboard.add(InlineKeyboardButton(
            f"{theme_data['emoji']} {theme_name.capitalize()}",
            callback_data=f"set_theme_{theme_name}"
        ))
    return keyboard

def get_voting_keyboard(game_id: int, exclude_user_id: int = None) -> InlineKeyboardMarkup:
    """Клавиатура голосования"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT user_id FROM game_players WHERE game_id = ? AND alive = 1''', (game_id,))
        players = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        if exclude_user_id:
            players = [p for p in players if p != exclude_user_id]

        keyboard = InlineKeyboardMarkup(row_width=2)
        for player_id in players:
            keyboard.add(InlineKeyboardButton(
                get_user_profile_link(player_id),
                callback_data=f"vote_{game_id}_{player_id}"
            ))

        return keyboard
    except Exception as e:
        logger.error(f"❌ Ошибка создания клавиатуры голосования: {str(e)}")
        return InlineKeyboardMarkup()

def get_locations_keyboard(game_id: int) -> InlineKeyboardMarkup:
    """Клавиатура выбора локации"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT location, chat_id FROM games WHERE game_id = ?', (game_id,))
        game = cursor.fetchone()

        if not game:
            conn.close()
            return InlineKeyboardMarkup()

        chat_id = game['chat_id']

        cursor.execute('''SELECT location_name FROM custom_locations 
            WHERE (chat_id = ? OR chat_id = 0) ORDER BY location_name''', (chat_id,))
        locations = [row['location_name'] for row in cursor.fetchall()]
        conn.close()

        keyboard = InlineKeyboardMarkup(row_width=2)
        for loc in locations:
            safe_loc = loc.replace('_', ' ')
            keyboard.add(InlineKeyboardButton(
                f"{safe_loc}",
                callback_data=f"guess_{game_id}_{loc}"
            ))

        return keyboard
    except Exception as e:
        logger.error(f"❌ Ошибка создания клавиатуры локаций: {str(e)}")
        return InlineKeyboardMarkup()

def get_spy_voting_keyboard(game_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для шпиона на голосовании"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🗳️ Голосовать", callback_data=f"spy_vote_{game_id}"),
        InlineKeyboardButton("🎯 Угадать локацию", callback_data=f"spy_guess_{game_id}")
    )
    return keyboard

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    """Команда /start"""
    try:
        add_user(message.from_user)

        if message.chat.type == 'private':
            welcome_text = (
                f"🕵️‍♂️ <b>Добро пожаловать в Шпионский Бот!</b>\n\n"
                f"Это захватывающая игра, где игроки пытаются вычислить шпиона, "
                f"а шпион должен угадать локацию и остаться незамеченным!\n\n"
                f"🎮 <b>Как играть:</b>\n"
                f"1. Добавьте бота в группу\n"
                f"2. Напишите /spygo для начала набора\n"
                f"3. Присоединитесь к игре и получите свою роль\n"
                f"4. Обсуждайте и голосуйте, чтобы найти шпиона!\n\n"
                f"❓ <b>Доступные команды:</b>\n"
                f"• /help - Показать список команд\n"
                f"• /rules - Правила игры\n"
                f"• /locations - Список локаций\n"
                f"• /buy_vip - Купить VIP-статус\n"
                f"• /stats - Ваша статистика"
            )

            args = message.text.split()
            if len(args) > 1 and args[1].startswith('join_'):
                try:
                    game_id = int(args[1].split('_')[1])
                    conn = get_db_connection()
                    cursor = conn.cursor()

                    cursor.execute('''SELECT status, chat_id, message_id FROM games 
                        WHERE game_id = ? AND status = 'pending' ''', (game_id,))
                    game = cursor.fetchone()

                    if game:
                        cursor.execute('''INSERT OR IGNORE INTO game_players (game_id, user_id) 
                            VALUES (?, ?)''', (game_id, message.from_user.id))

                        if cursor.rowcount > 0:
                            conn.commit()
                            confirmation_text = (
                                f"✅ <b>Вы успешно присоединились к игре!</b>\n\n"
                                f"🎮 <b>Группа:</b> {game['chat_id']}\n"
                                f"🆔 <b>ID игры:</b> {game_id}\n\n"
                                f"⏳ <b>Ожидайте начала игры.</b>"
                            )
                            safe_send_message(message.chat.id, confirmation_text)

                            if game['message_id']:
                                update_game_message(game['chat_id'], game_id, game['message_id'])

                            safe_send_message(
                                game['chat_id'],
                                f"✅ {get_user_profile_link(message.from_user.id)} присоединился к игре!"
                            )
                        else:
                            safe_send_message(message.chat.id, "❌ Вы уже в этой игре!")
                    else:
                        safe_send_message(message.chat.id, "❌ Игра не найдена или уже началась!")

                    conn.close()
                except Exception as e:
                    logger.error(f"❌ Ошибка присоединения: {str(e)}")
                    safe_send_message(message.chat.id, "❌ Ошибка присоединения!")
            else:
                safe_send_message(message.chat.id, welcome_text, reply_markup=get_start_keyboard())

        elif message.chat.type in ['group', 'supergroup']:
            has_perms = check_bot_permissions(message.chat.id)
            if has_perms:
                welcome_msg = (
                    "🎉 <b>Спасибо за добавление бота в группу!</b>\n\n"
                    "✅ <b>Все права получены!</b>\n"
                    "Теперь вы можете начать игру командой /spygo"
                )
                safe_send_message(message.chat.id, welcome_msg)
            else:
                perms_msg = (
                    "🛡️ <b>Требуются права для работы в группе!</b>\n\n"
                    "Пожалуйста, выдайте боту следующие права:\n"
                    "✅ Закрепление сообщений\n"
                    "✅ Удаление сообщений\n"
                    "✅ Пригласительные ссылки\n"
                    "✅ Блокировка пользователей\n\n"
                    "Без этих прав бот не сможет управлять игрой и поддерживать порядок."
                )
                safe_send_message(message.chat.id, perms_msg)

    except Exception as e:
        logger.error(f"❌ Ошибка /start: {str(e)}")
        logger.error(traceback.format_exc())

@bot.my_chat_member_handler()
def handle_my_chat_member(update: types.ChatMemberUpdated):
    """Обработка добавления/удаления бота из группы"""
    try:
        if update.new_chat_member.status == 'member':
            chat_id = update.chat.id
            logger.info(f"✅ Бот добавлен в группу {chat_id}")

            welcome_message = (
                "🎉 <b>Спасибо за добавление бота в группу!</b>\n\n"
                "Я бот для игры Кто шпион - увлекательной игры, где игроки пытаются вычислить шпиона, "
                "а шпион должен угадать локацию и остаться незамеченным!\n\n"
                "🎮 <b>Как начать играть:</b>\n"
                "1. Выдайте боту необходимые права\n"
                "2. Напишите команду /spygo для начала набора\n"
                "3. Присоединитесь к игре и получите свою роль\n"
                "4. Обсуждайте и голосуйте, чтобы найти шпиона!"
            )

            permissions_message = (
                "🛡️ <b>Требуются права для работы в группе!</b>\n\n"
                "Пожалуйста, выдайте боту следующие права:\n"
                "✅ Закрепление сообщений\n"
                "✅ Удаление сообщений\n"
                "✅ Пригласительные ссылки\n"
                "✅ Блокировка пользователей\n\n"
                "Без этих прав бот не сможет управлять игрой и поддерживать порядок."
            )

            safe_send_message(chat_id, welcome_message)
            time.sleep(0.5)
            safe_send_message(chat_id, permissions_message)

        elif update.new_chat_member.status == 'left':
            logger.info(f"⚠️ Бот удален из группы {update.chat.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки добавления бота: {str(e)}")
        logger.error(traceback.format_exc())

@bot.message_handler(commands=['help'])
def handle_help(message: Message):
    """Команда /help"""
    try:
        add_user(message.from_user)

        help_text = (
            f"❓ <b>Список команд</b>\n\n"
            f"👥 <b>Для всех:</b>\n"
            f"• /start - Начало\n"
            f"• /help - Помощь\n"
            f"• /rules - Правила\n"
            f"• /locations - Локации\n"
            f"• /stats - Статистика\n"
            f"• /spygo - Начать игру (группы)\n"
            f"• /leave - Выйти (группы)\n"
            f"• /stop - Остановить (группы)\n\n"
            f"⭐ <b>VIP:</b>\n"
            f"• /buy_vip - Купить VIP\n"
            f"• /addlocations - Добавить локацию\n"
            f"• /removelocations - Удалить локацию\n"
            f"• /viplocations - Мои локации\n"
            f"• /custom_game - Игра с локацией\n"
            f"• /viptheme - Выбрать тему"
        )

        safe_send_message(message.chat.id, help_text, reply_markup=get_help_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка /help: {str(e)}")

@bot.message_handler(commands=['rules', 'rule'])
def handle_rules(message: Message):
    """Команда /rules"""
    try:
        add_user(message.from_user)

        rules_text = (
            f"📖 <b>Кто шпион?</b>\n\n"
            f"🎯 <b>Цель</b>\n"
            f"• <b>Мирные</b> вычисляют шпиона и выбивают его голосованием\n"
            f"• <b>Шпион</b> угадывает <b>локацию</b> и должен остаться в игре\n\n"
            f"🎭 <b>Роли</b>\n"
            f"• <b>Мирный</b>: знает локацию и ищет шпиона\n"
            f"• <b>Шпион</b>: локацию не знает, но может угадать её\n\n"
            f"⏱️ <b>Раунд (повторяется)</b>\n"
            f"1) <b>Обсуждение</b>: каждый задаёт вопрос <b>следующему</b> в очередности (вопросы про локацию)\n"
            f"2) <b>Голосование</b>: голосуют в ЛС; больше всего голосов = выбывает\n"
            f"3) <b>Итоги</b>: выбывший показывает роль\n\n"
            f"🏆 <b>Победа</b>\n"
            f"• Мирные: шпионы выбыли\n"
            f"• Шпионы: живых мирных <= живых шпионов <i>или</i> шпионы угадали локацию нужное число раз\n\n"
            f"⚠️ <b>Баланс игры</b>\n"
            f"1→3, 2→5, 3→7, 4→9, 5→11 игроков (минимум под выбранное число шпионов)"
        )

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("📖 Подробные правила", callback_data="rules_detailed"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_rules")
        )

        safe_send_message(message.chat.id, rules_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"❌ Ошибка /rules: {str(e)}")

@bot.message_handler(commands=['locations'])
def handle_locations(message: Message):
    """Команда /locations"""
    try:
        add_user(message.from_user)

        locations_text = "📍 <b>Список локаций:</b>\n\n"
        for i, location in enumerate(DEFAULT_LOCATIONS, 1):
            locations_text += f"{i}. {location}\n"

        safe_send_message(message.chat.id, locations_text)

    except Exception as e:
        logger.error(f"❌ Ошибка /locations: {str(e)}")

@bot.message_handler(commands=['buy_vip'])
def handle_buy_vip(message: Message):
    """Команда /buy_vip"""
    try:
        add_user(message.from_user)

        if message.chat.type != 'private':
            safe_send_message(message.chat.id, "❌ Только в ЛС!")
            return

        is_active, vip_msg = get_vip_status_message(message.from_user.id)
        if is_active:
            safe_send_message(
                message.chat.id,
                "⭐ <b>VIP уже активен</b>\n\n"
                f"{vip_msg}\n\n"
                "Можно продлить — выбери срок ниже.",
                reply_markup=get_vip_keyboard(),
            )
            return

        vip_text = (
            f"⭐ <b>Покупка VIP</b>\n\n"
            f"VIP дает:\n"
            f"✅ Кастомные локации\n"
            f"✅ Выбор локации для игры\n"
            f"✅ Смена темы\n\n"
            f"💰 <b>Цены:</b>\n"
            f"• 1 месяц - {VIP_PRICES['1m']} ⭐\n"
            f"• 3 месяца - {VIP_PRICES['3m']} ⭐\n"
            f"• 6 месяцев - {VIP_PRICES['6m']} ⭐ (ВЫГОДНО!)\n"
            f"• 1 год - {VIP_PRICES['1y']} ⭐\n\n"
            f"💡 <i>Сроки не суммируются!</i>"
        )

        safe_send_message(message.chat.id, vip_text, reply_markup=get_vip_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка /buy_vip: {str(e)}")

@bot.message_handler(commands=['stats'])
def handle_stats(message: Message):
    """Команда /stats"""
    try:
        add_user(message.from_user)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT games_played, times_spy, times_civilian, is_vip, vip_expires_at 
            FROM users WHERE user_id = ?''', (message.from_user.id,))
        stats = cursor.fetchone()
        conn.close()

        if not stats:
            safe_send_message(message.chat.id, "❌ Статистика не найдена!")
            return

        vip_status = "❌ Не активен"
        if stats['is_vip'] and stats['vip_expires_at']:
            try:
                expires_date = datetime.fromisoformat(stats['vip_expires_at']).date()
                if expires_date > datetime.now().date():
                    vip_status = f"✅ До {expires_date.strftime('%d.%m.%Y')}"
            except:
                vip_status = "✅ Активен"

        win_rate = 0
        if stats['games_played'] > 0:
            win_rate = round((stats['times_spy'] + stats['times_civilian']) / stats['games_played'] * 100, 1)

        stats_text = (
            f"📊 <b>Ваша статистика</b>\n\n"
            f"🎮 Всего игр: {stats['games_played']}\n"
            f"🕵️‍♂️ Шпион: {stats['times_spy']} раз\n"
            f"👥 Мирный: {stats['times_civilian']} раз\n"
            f"📈 Процент побед: {win_rate}%\n\n"
            f"⭐ VIP: {vip_status}"
        )

        safe_send_message(message.chat.id, stats_text)

    except Exception as e:
        logger.error(f"❌ Ошибка /stats: {str(e)}")

@bot.message_handler(commands=['spygo'])
def handle_spygo(message: Message):
    """Команда /spygo"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        has_perms = check_bot_permissions(message.chat.id)
        if not has_perms:
            safe_send_message(
                message.chat.id,
                "🛡️ <b>Требуются права для работы в группе!</b>\n\n"
                "Пожалуйста, выдайте боту следующие права:\n"
                "✅ Закрепление сообщений\n"
                "✅ Удаление сообщений\n"
                "✅ Пригласительные ссылки\n"
                "✅ Блокировка пользователей"
            )
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT game_id FROM games WHERE chat_id = ? AND status IN ('pending', 'running')''', 
            (message.chat.id,))
        if cursor.fetchone():
            safe_send_message(message.chat.id, "❌ Игра уже идет!")
            conn.close()
            return

        settings = get_game_settings(message.chat.id)

        cursor.execute('''SELECT location_name FROM custom_locations 
            WHERE chat_id = ? OR chat_id = 0 ORDER BY RANDOM() LIMIT 1''', (message.chat.id,))
        result = cursor.fetchone()
        location = result['location_name'] if result else random.choice(DEFAULT_LOCATIONS)

        now = datetime.now().isoformat()
        cursor.execute('''INSERT INTO games (
            chat_id, creator_id, status, discussion_time, voting_time, spies_count, 
            guess_attempts, location, started_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            message.chat.id, message.from_user.id, 'pending',
            settings['discussion_time'], settings['voting_time'], settings['spies_count'],
            settings['guess_attempts'], location, now, now
        ))

        game_id = cursor.lastrowid
        cursor.execute('''INSERT INTO game_players (game_id, user_id) VALUES (?, ?)''', 
            (game_id, message.from_user.id))
        conn.commit()

        cursor.execute('SELECT user_id FROM game_players WHERE game_id = ?', (game_id,))
        players = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        min_players = SPY_RULES.get(settings['spies_count'], settings['spies_count'] * 2 + 1)
        needed = max(0, min_players - len(players))

        game_message = (
            f"🕵️‍♂️ <b>Набор в игру начат!</b>\n\n"
            f"👤 <b>Создатель:</b> {get_user_profile_link(message.from_user.id)}\n\n"
            f"👥 <b>Участники ({len(players)}/{min_players}):</b>\n"
            f"{', '.join([get_user_profile_link(p) for p in players]) or 'Пока никого'}\n\n"
            f"📊 <b>Статус:</b>\n"
            f"Игроков: {len(players)}\n"
            f"Минимум: {min_players}\n"
            f"Осталось: {needed}\n\n"
            f"⚙️ <b>Настройки:</b>\n"
            f"⏱️ Обсуждение: {format_time(settings['discussion_time'])}\n"
            f"🗳️ Голосование: {format_time(settings['voting_time'])}\n"
            f"🕵️‍♂️ Шпионов: {settings['spies_count']}\n"
            f"🎯 Попыток: {settings['guess_attempts']}"
        )

        msg = safe_send_message(message.chat.id, game_message, reply_markup=get_game_keyboard(message.chat.id, game_id))
        
        if msg:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE games SET message_id = ? WHERE game_id = ?', (msg.message_id, game_id))
            conn.commit()
            conn.close()

            try:
                bot.pin_chat_message(message.chat.id, msg.message_id)
            except:
                pass

        logger.info(f"✅ Игра {game_id} создана в чате {message.chat.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка /spygo: {str(e)}")
        logger.error(traceback.format_exc())
        safe_send_message(message.chat.id, "❌ Ошибка при создании игры!")

@bot.message_handler(commands=['leave'])
def handle_leave(message: Message):
    """Команда /leave"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT game_id, creator_id, message_id FROM games 
            WHERE chat_id = ? AND status = 'pending' ORDER BY game_id DESC LIMIT 1''', (message.chat.id,))
        game = cursor.fetchone()

        if not game:
            safe_send_message(message.chat.id, "❌ Нет активного набора!")
            conn.close()
            return

        if game['creator_id'] == message.from_user.id:
            safe_send_message(message.chat.id, "❌ Создатель не может выйти! Используйте /stop")
            conn.close()
            return

        cursor.execute('''DELETE FROM game_players WHERE game_id = ? AND user_id = ?''', 
            (game['game_id'], message.from_user.id))

        if cursor.rowcount > 0:
            conn.commit()
            safe_send_message(
                message.chat.id,
                f"✅ {get_user_profile_link(message.from_user.id)} вышел из игры!"
            )

            if game['message_id']:
                try:
                    update_game_message(message.chat.id, game['game_id'], game['message_id'])
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось обновить сообщение игры: {str(e)}")

        conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка /leave: {str(e)}")

@bot.message_handler(commands=['stop'])
def handle_stop(message: Message):
    """Команда /stop"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT game_id, creator_id, status, created_at FROM games 
            WHERE chat_id = ? AND status IN ('pending', 'running') ORDER BY game_id DESC LIMIT 1''', 
            (message.chat.id,))
        game = cursor.fetchone()

        if not game:
            safe_send_message(message.chat.id, "❌ Нет активной игры!")
            conn.close()
            return

        can_any_stop = False
        if game['status'] == 'pending' and game['created_at']:
            created_at = datetime.fromisoformat(game['created_at'])
            can_any_stop = (datetime.now() - created_at) >= timedelta(minutes=5)

        if game['creator_id'] != message.from_user.id and message.from_user.id != ADMIN_ID and not can_any_stop:
            safe_send_message(message.chat.id, "❌ Только создатель! (или после 5 минут ожидания)")
            conn.close()
            return

        game_id = game['game_id']

        cursor.execute('DELETE FROM games WHERE game_id = ?', (game_id,))
        cursor.execute('DELETE FROM game_players WHERE game_id = ?', (game_id,))
        cursor.execute('DELETE FROM votes WHERE game_id = ?', (game_id,))
        cursor.execute('DELETE FROM active_sessions WHERE game_id = ?', (game_id,))
        cursor.execute('DELETE FROM muted_players WHERE game_id = ?', (game_id,))

        conn.commit()
        conn.close()

        try:
            bot.unpin_chat_message(message.chat.id)
        except:
            pass

        safe_send_message(message.chat.id, "⏹️ Игра остановлена!")

    except Exception as e:
        logger.error(f"❌ Ошибка /stop: {str(e)}")

@bot.message_handler(commands=['addlocations'])
def handle_addlocations(message: Message):
    """Команда /addlocations"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        if not is_user_vip(message.from_user.id):
            _, vip_msg = get_vip_status_message(message.from_user.id)
            safe_send_message(
                message.chat.id,
                "❌ Доступно только для VIP.\n\n"
                f"{vip_msg}\n\n"
                "Оформить: /buy_vip",
            )
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            safe_send_message(message.chat.id, "❌ Укажите локацию!\nПример: /addlocations Космос")
            return

        location = args[1].strip()
        if len(location) < 3 or len(location) > 50:
            safe_send_message(message.chat.id, "❌ Длина: 3-50 символов!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            cursor.execute('''INSERT INTO custom_locations (chat_id, location_name, added_by, added_at) 
                VALUES (?, ?, ?, ?)''', (message.chat.id, location, message.from_user.id, now))
            conn.commit()
            safe_send_message(message.chat.id, f"✅ Локация '{location}' добавлена!")
        except sqlite3.IntegrityError:
            safe_send_message(message.chat.id, f"❌ Локация '{location}' уже существует!")
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка /addlocations: {str(e)}")

@bot.message_handler(commands=['removelocations'])
def handle_removelocations(message: Message):
    """Команда /removelocations"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        if not is_user_vip(message.from_user.id):
            _, vip_msg = get_vip_status_message(message.from_user.id)
            safe_send_message(
                message.chat.id,
                "❌ Доступно только для VIP.\n\n"
                f"{vip_msg}\n\n"
                "Оформить: /buy_vip",
            )
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            safe_send_message(message.chat.id, "❌ Укажите локацию!")
            return

        location = args[1].strip()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''DELETE FROM custom_locations 
            WHERE chat_id = ? AND location_name = ? AND chat_id != 0''', (message.chat.id, location))

        if cursor.rowcount > 0:
            conn.commit()
            safe_send_message(message.chat.id, f"✅ Локация '{location}' удалена!")
        else:
            safe_send_message(message.chat.id, f"❌ Локация не найдена!")

        conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка /removelocations: {str(e)}")

@bot.message_handler(commands=['viplocations'])
def handle_viplocations(message: Message):
    """Команда /viplocations"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        if not is_user_vip(message.from_user.id):
            _, vip_msg = get_vip_status_message(message.from_user.id)
            safe_send_message(
                message.chat.id,
                "❌ Доступно только для VIP.\n\n"
                f"{vip_msg}\n\n"
                "Оформить: /buy_vip",
            )
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT location_name FROM custom_locations 
            WHERE chat_id = ? AND chat_id != 0 ORDER BY location_name''', (message.chat.id,))
        locations = [row['location_name'] for row in cursor.fetchall()]
        conn.close()

        if not locations:
            safe_send_message(message.chat.id, "❌ Нет кастомных локаций!")
            return

        text = "📍 <b>Кастомные локации:</b>\n\n"
        for i, loc in enumerate(locations, 1):
            text += f"{i}. {loc}\n"

        safe_send_message(message.chat.id, text)

    except Exception as e:
        logger.error(f"❌ Ошибка /viplocations: {str(e)}")

@bot.message_handler(commands=['custom_game'])
def handle_custom_game(message: Message):
    """Команда /custom_game"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        if not is_user_vip(message.from_user.id):
            _, vip_msg = get_vip_status_message(message.from_user.id)
            safe_send_message(
                message.chat.id,
                "❌ Доступно только для VIP.\n\n"
                f"{vip_msg}\n\n"
                "Оформить: /buy_vip",
            )
            return

        if not check_bot_permissions(message.chat.id):
            safe_send_message(message.chat.id, "❌ Нет прав!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT game_id FROM games WHERE chat_id = ? AND status IN ('pending', 'running')''', 
            (message.chat.id,))
        if cursor.fetchone():
            safe_send_message(message.chat.id, "❌ Игра уже идет!")
            conn.close()
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            safe_send_message(message.chat.id, "❌ Укажите локацию!\nПример: /custom_game Аэропорт")
            conn.close()
            return

        location = args[1].strip()

        cursor.execute('''SELECT location_name FROM custom_locations 
            WHERE (chat_id = ? OR chat_id = 0) AND location_name = ?''', (message.chat.id, location))
        if not cursor.fetchone():
            safe_send_message(message.chat.id, f"❌ Локация '{location}' не найдена!")
            conn.close()
            return

        settings = get_game_settings(message.chat.id)
        now = datetime.now().isoformat()

        cursor.execute('''INSERT INTO games (
            chat_id, creator_id, status, discussion_time, voting_time, spies_count, 
            guess_attempts, location, started_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
            message.chat.id, message.from_user.id, 'pending',
            settings['discussion_time'], settings['voting_time'], settings['spies_count'],
            settings['guess_attempts'], location, now, now
        ))

        game_id = cursor.lastrowid
        cursor.execute('''INSERT INTO game_players (game_id, user_id) VALUES (?, ?)''', 
            (game_id, message.from_user.id))
        conn.commit()

        cursor.execute('SELECT user_id FROM game_players WHERE game_id = ?', (game_id,))
        players = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        min_players = SPY_RULES.get(settings['spies_count'], settings['spies_count'] * 2 + 1)
        needed = max(0, min_players - len(players))

        game_message = (
            f"🕵️‍♂️ <b>Набор в игру начат!</b>\n\n"
            f"👤 <b>Создатель:</b> {get_user_profile_link(message.from_user.id)}\n\n"
            f"🎯 <b>Локация:</b> {location}\n\n"
            f"👥 <b>Участники ({len(players)}/{min_players}):</b>\n"
            f"{', '.join([get_user_profile_link(p) for p in players]) or 'Пока никого'}\n\n"
            f"📊 <b>Статус:</b>\n"
            f"Игроков: {len(players)}\n"
            f"Минимум: {min_players}\n"
            f"Осталось: {needed}"
        )

        msg = safe_send_message(message.chat.id, game_message, reply_markup=get_game_keyboard(message.chat.id, game_id))
        
        if msg:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE games SET message_id = ? WHERE game_id = ?', (msg.message_id, game_id))
            conn.commit()
            conn.close()

            try:
                bot.pin_chat_message(message.chat.id, msg.message_id)
            except:
                pass

        logger.info(f"✅ Игра {game_id} с локацией '{location}' создана")

    except Exception as e:
        logger.error(f"❌ Ошибка /custom_game: {str(e)}")
        safe_send_message(message.chat.id, "❌ Ошибка!")

@bot.message_handler(commands=['viptheme'])
def handle_viptheme(message: Message):
    """Команда /viptheme"""
    try:
        if message.chat.type not in ['group', 'supergroup']:
            safe_send_message(message.chat.id, "❌ Только в группах!")
            return

        if not is_user_vip(message.from_user.id):
            _, vip_msg = get_vip_status_message(message.from_user.id)
            safe_send_message(
                message.chat.id,
                "❌ Доступно только для VIP.\n\n"
                f"{vip_msg}\n\n"
                "Оформить: /buy_vip",
            )
            return

        text = "🎨 <b>Выберите тему оформления:</b>"
        safe_send_message(message.chat.id, text, reply_markup=get_theme_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка /viptheme: {str(e)}")

# ==================== CALLBACK HANDLERS ====================

@bot.callback_query_handler(func=lambda call: call.data == "rules")
def callback_rules(call: CallbackQuery):
    """Callback правила"""
    try:
        safe_answer_callback(call.id)

        rules_text = (
            f"📖 <b>Правила игры</b>\n\n"
            f"🎯 <b>Цель:</b>\n"
            f"• Мирные вычисляют шпиона\n"
            f"• Шпион угадывает локацию\n\n"
            f"🎭 <b>Роли:</b>\n"
            f"• <b>Мирный</b>: Знает локацию\n"
            f"• <b>Шпион</b>: Не знает локацию\n\n"
            f"⏱️ <b>Ход:</b>\n"
            f"1. Обсуждение\n"
            f"2. Голосование\n"
            f"3. Результаты\n\n"
            f"🏆 <b>Победа:</b>\n"
            f"• Мирные: все шпионы выбыли\n"
            f"• Шпионы: угадали локацию"
        )

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("📖 Подробные правила", callback_data="rules_detailed"),
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, rules_text, reply_markup=keyboard):
            safe_send_message(call.message.chat.id, rules_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"❌ Ошибка callback_rules: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "rules_detailed")
def callback_rules_detailed(call: CallbackQuery):
    """Callback подробные правила"""
    try:
        safe_answer_callback(call.id)

        detailed_rules = (
            f"📖 <b>ПОДРОБНЫЕ ПРАВИЛА</b>\n\n"
            f"🎭 <b>Роли</b>\n"
            f"• <b>Мирный</b>: знает локацию и пытается найти шпиона\n"
            f"• <b>Шпион</b>: локацию не знает, но может угадать её и выиграть\n\n"
            f"⏱️ <b>Раунд</b>\n"
            f"1) <b>Обсуждение</b>\n"
            f"• Бот показывает очередность: кто кому задаёт вопрос\n"
            f"• Пишите свободно, обсуждайте локацию и поведение игроков\n\n"
            f"2) <b>Голосование</b>\n"
            f"• Все голосуют в ЛС\n"
            f"• Игрок с максимумом голосов выбывает (если ничья — выбирается случайно)\n"
            f"• Шпионы на голосовании выбирают действие:\n"
            f"  — <b>Голосовать</b> за подозреваемого\n"
            f"  — <b>Угадать локацию</b>\n\n"
            f"3) <b>Итоги</b>\n"
            f"• Выбывший показывает роль\n\n"
            f"🎯 <b>Угадывание локации</b>\n"
            f"• Угадывает только <b>живой шпион</b>\n"
            f"• Нужно угадать нужное число раз:\n"
            f"  1→1, 2→1, 3→2, 4→2, 5→3\n\n"
            f"🏆 <b>Победа</b>\n"
            f"• Мирные: шпионы выбыли\n"
            f"• Шпионы: живых мирных <= живых шпионов <i>или</i> нужное число угаданных локаций"
        )

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("⬅️ Назад", callback_data="rules_back"),
            InlineKeyboardButton("❌ Закрыть", callback_data="close_rules")
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, detailed_rules, reply_markup=keyboard):
            safe_send_message(call.message.chat.id, detailed_rules, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"❌ Ошибка callback_rules_detailed: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "rules_back")
def callback_rules_back(call: CallbackQuery):
    """Callback назад к основным правилам"""
    try:
        safe_answer_callback(call.id)

        rules_text = (
            f"📖 <b>Кто шпион?</b>\n\n"
            f"🎯 <b>Цель</b>\n"
            f"• <b>Мирные</b> вычисляют шпиона и выбивают его голосованием\n"
            f"• <b>Шпион</b> угадывает <b>локацию</b> и должен остаться в игре\n\n"
            f"🎭 <b>Роли</b>\n"
            f"• <b>Мирный</b>: знает локацию и ищет шпиона\n"
            f"• <b>Шпион</b>: локацию не знает, но может угадать её\n\n"
            f"⏱️ <b>Раунд (повторяется)</b>\n"
            f"1) <b>Обсуждение</b>: каждый задаёт вопрос <b>следующему</b> в очередности (вопросы про локацию)\n"
            f"2) <b>Голосование</b>: голосуют в ЛС; больше всего голосов = выбывает\n"
            f"3) <b>Итоги</b>: выбывший показывает роль\n\n"
            f"🏆 <b>Победа</b>\n"
            f"• Мирные: шпионы выбыли\n"
            f"• Шпионы: живых мирных <= живых шпионов <i>или</i> шпионы угадали локацию нужное число раз\n\n"
            f"⚠️ <b>Баланс игры</b>\n"
            f"1→3, 2→5, 3→7, 4→9, 5→11 игроков (минимум под выбранное число шпионов)"
        )

        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("📖 Подробные правила", callback_data="rules_detailed"),
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_start")
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, rules_text, reply_markup=keyboard):
            safe_send_message(call.message.chat.id, rules_text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"❌ Ошибка callback_rules_back: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_start")
def callback_back_to_start(call: CallbackQuery):
    """Callback назад к /start"""
    try:
        safe_answer_callback(call.id)

        welcome_text = (
            f"🕵️‍♂️ <b>Добро пожаловать в Шпионский Бот!</b>\n\n"
            f"Это захватывающая игра, где игроки пытаются вычислить шпиона, "
            f"а шпион должен угадать локацию и остаться незамеченным!\n\n"
            f"🎮 <b>Как играть:</b>\n"
            f"1. Добавьте бота в группу\n"
            f"2. Напишите /spygo для начала набора\n"
            f"3. Присоединитесь к игре и получите свою роль\n"
            f"4. Обсуждайте и голосуйте, чтобы найти шпиона!\n\n"
            f"❓ <b>Доступные команды:</b>\n"
            f"• /help - Показать список команд\n"
            f"• /rules - Правила игры\n"
            f"• /locations - Список локаций\n"
            f"• /buy_vip - Купить VIP-статус\n"
            f"• /stats - Ваша статистика"
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, welcome_text, reply_markup=get_start_keyboard()):
            safe_send_message(call.message.chat.id, welcome_text, reply_markup=get_start_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка callback_back_to_start: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "close_rules")
def callback_close_rules(call: CallbackQuery):
    """Callback закрыть правила"""
    try:
        safe_answer_callback(call.id)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
    except Exception as e:
        logger.error(f"❌ Ошибка callback_close_rules: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "buy_vip")
def callback_buy_vip(call: CallbackQuery):
    """Callback покупка VIP"""
    try:
        safe_answer_callback(call.id)

        vip_text = (
            f"⭐ <b>Покупка VIP</b>\n\n"
            f"VIP дает:\n"
            f"✅ Кастомные локации\n"
            f"✅ Выбор локации\n"
            f"✅ Смена темы\n\n"
            f"💰 <b>Цены:</b>\n"
            f"• 1 месяц - {VIP_PRICES['1m']} ⭐\n"
            f"• 3 месяца - {VIP_PRICES['3m']} ⭐\n"
            f"• 6 месяцев - {VIP_PRICES['6m']} ⭐ (ВЫГОДНО!)\n"
            f"• 1 год - {VIP_PRICES['1y']} ⭐"
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, vip_text, reply_markup=get_vip_keyboard()):
            safe_send_message(call.message.chat.id, vip_text, reply_markup=get_vip_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка callback_buy_vip: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "locations")
def callback_locations(call: CallbackQuery):
    """Callback локации"""
    try:
        safe_answer_callback(call.id)

        locations_text = "📍 <b>Список локаций:</b>\n\n"
        for i, location in enumerate(DEFAULT_LOCATIONS, 1):
            locations_text += f"{i}. {location}\n"

        if not safe_edit_message(call.message.chat.id, call.message.message_id, locations_text, reply_markup=get_start_keyboard()):
            safe_send_message(call.message.chat.id, locations_text, reply_markup=get_start_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка callback_locations: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_vip")
def callback_cancel_vip(call: CallbackQuery):
    """Callback отмена VIP"""
    try:
        safe_answer_callback(call.id)

        welcome_text = (
            f"🕵️‍♂️ <b>Добро пожаловать!</b>\n\n"
            f"Это захватывающая игра, где игроки пытаются вычислить шпиона!"
        )

        if not safe_edit_message(call.message.chat.id, call.message.message_id, welcome_text, reply_markup=get_start_keyboard()):
            safe_send_message(call.message.chat.id, welcome_text, reply_markup=get_start_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка callback_cancel_vip: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vip_"))
def callback_vip_purchase(call: CallbackQuery):
    """Callback покупка VIP"""
    try:
        safe_answer_callback(call.id)

        duration_code = call.data.split("_")[1]
        if duration_code not in VIP_PRICES:
            safe_send_message(call.message.chat.id, "❌ Ошибка!")
            return

        stars = VIP_PRICES[duration_code]
        duration_text = {'1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '1y': '1 год'}[duration_code]
        operation_id = f"vip_{duration_code}_{call.from_user.id}_{int(time.time())}"

        prices = [types.LabeledPrice(label=f"VIP на {duration_text}", amount=stars)]

        try:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title=f"VIP-статус на {duration_text}",
                description=f"VIP на {duration_text}",
                provider_token="",
                currency="XTR",
                prices=prices,
                invoice_payload=operation_id,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                is_flexible=False
            )
            logger.info(f"💰 Инвойс отправлен: {duration_text} ({stars} ⭐)")
        except TypeError:
            bot.send_invoice(
                chat_id=call.message.chat.id,
                title=f"VIP-статус на {duration_text}",
                description=f"VIP на {duration_text}",
                provider_token="",
                currency="XTR",
                prices=prices,
                payload=operation_id,
                need_name=False,
                need_phone_number=False,
                need_email=False,
                need_shipping_address=False,
                is_flexible=False
            )

    except Exception as e:
        logger.error(f"❌ Ошибка callback_vip_purchase: {str(e)}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Pre-checkout обработка"""
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logger.error(f"❌ Ошибка pre_checkout: {str(e)}")
        try:
            bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка!")
        except:
            pass

@bot.message_handler(content_types=['successful_payment'])
def successful_payment(message: Message):
    """Успешный платеж"""
    try:
        payment = message.successful_payment
        operation_id = payment.invoice_payload
        parts = operation_id.split('_')

        if len(parts) < 3 or parts[0] != 'vip':
            safe_send_message(message.chat.id, "❌ Ошибка обработки платежа!")
            return

        duration_code = parts[1]
        user_id = int(parts[2])

        if duration_code not in VIP_DURATIONS:
            safe_send_message(message.chat.id, "❌ Ошибка!")
            return

        duration_days = VIP_DURATIONS[duration_code]
        stars = payment.total_amount
        duration_text = {'1m': '1 месяц', '3m': '3 месяца', '6m': '6 месяцев', '1y': '1 год'}[duration_code]

        conn = get_db_connection()
        cursor = conn.cursor()

        now_dt = datetime.now()
        now = now_dt.isoformat()

        # Продление: если VIP еще активен, прибавляем ко времени окончания, а не “с нуля”.
        cursor.execute('SELECT is_vip, vip_expires_at FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()

        base = now_dt
        if row and row['is_vip'] and row['vip_expires_at']:
            try:
                existing_exp = datetime.fromisoformat(row['vip_expires_at'])
                if existing_exp > now_dt:
                    base = existing_exp
            except Exception:
                pass

        expires_at = base + timedelta(days=duration_days)

        if row:
            cursor.execute('''UPDATE users SET is_vip = 1, vip_expires_at = ?, stars_spent = stars_spent + ?, 
                last_active = ? WHERE user_id = ?''', (expires_at.isoformat(), stars, now, user_id))
        else:
            cursor.execute('''INSERT INTO users (user_id, is_vip, vip_expires_at, stars_spent, created_at, last_active) 
                VALUES (?, 1, ?, ?, ?, ?)''', (user_id, expires_at.isoformat(), stars, now, now))

        cursor.execute('''INSERT INTO vip_purchases (user_id, stars, duration, operation_id, purchased_at) 
            VALUES (?, ?, ?, ?, ?)''', (user_id, stars, duration_code, operation_id, now))

        conn.commit()
        conn.close()

        success_message = (
            f"🎉 <b>VIP активирован!</b>\n\n"
            f"🔥 <b>Срок:</b> {duration_text}\n"
            f"💰 <b>Оплачено:</b> {stars} ⭐\n\n"
            f"✨ <b>Доступные команды:</b>\n"
            f"• /addlocations - Добавить локацию\n"
            f"• /removelocations - Удалить локацию\n"
            f"• /viplocations - Мои локации\n"
            f"• /custom_game - Игра с локацией\n"
            f"• /viptheme - Выбрать тему"
        )

        safe_send_message(message.chat.id, success_message)

        try:
            admin_msg = (
                f"⭐ <b>Новая покупка VIP!</b>\n\n"
                f"Пользователь: {get_user_profile_link(user_id)}\n"
                f"ID: {user_id}\n"
                f"Срок: {duration_text}\n"
                f"Звезд: {stars}\n"
                f"ID операции: {operation_id}"
            )
            safe_send_message(ADMIN_ID, admin_msg)
        except:
            pass

        logger.info(f"✅ VIP куплен: {duration_text} ({stars} ⭐) пользователем {user_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка successful_payment: {str(e)}")
        safe_send_message(message.chat.id, "❌ Ошибка активации VIP!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_theme_"))
def callback_set_theme(call: CallbackQuery):
    """Callback установка темы"""
    try:
        safe_answer_callback(call.id)

        theme_name = call.data.split("_")[2]
        if theme_name not in THEMES:
            safe_send_message(call.message.chat.id, "❌ Ошибка!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT chat_id FROM groups WHERE chat_id = ?', (call.message.chat.id,))
        exists = cursor.fetchone()
        now = datetime.now().isoformat()

        if exists:
            cursor.execute('''UPDATE groups SET theme = ?, last_active = ? WHERE chat_id = ?''', 
                (theme_name, now, call.message.chat.id))
        else:
            cursor.execute('''INSERT INTO groups (chat_id, theme, created_at, last_active) 
                VALUES (?, ?, ?, ?)''', (call.message.chat.id, theme_name, now, now))

        conn.commit()
        conn.close()

        theme_emoji = THEMES[theme_name]['emoji']
        safe_send_message(call.message.chat.id, 
            f"✅ Тема изменена на {theme_emoji} {theme_name.capitalize()}!")

        logger.info(f"✅ Тема изменена на {theme_name} в группе {call.message.chat.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка callback_set_theme: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("settings_"))
def callback_settings(call: CallbackQuery):
    """Callback настройки"""
    try:
        if not safe_answer_callback(call.id):
            return

        game_id = int(call.data.split("_")[1])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT creator_id, chat_id FROM games WHERE game_id = ?', (game_id,))
        game = cursor.fetchone()

        if not game or game['creator_id'] != call.from_user.id:
            safe_send_message(call.from_user.id, "❌ Только создатель может менять настройки!")
            conn.close()
            return

        chat_id = game['chat_id']

        cursor.execute('''SELECT default_discussion_time, default_voting_time, default_spies_count, 
            default_guess_attempts FROM groups WHERE chat_id = ?''', (chat_id,))
        result = cursor.fetchone()
        conn.close()

        current = {
            'discussion_time': result['default_discussion_time'] if result else 5,
            'voting_time': result['default_voting_time'] if result else 2,
            'spies_count': result['default_spies_count'] if result else 1,
            'guess_attempts': result['default_guess_attempts'] if result else 3
        }

        settings_text = (
            f"⚙️ <b>Изменение настроек</b>\n\n"
            f"Текущие:\n"
            f"⏱️ Обсуждение: {current['discussion_time']} мин\n"
            f"🗳️ Голосование: {current['voting_time']} мин\n"
            f"🕵️‍♂️ Шпионов: {current['spies_count']}\n"
            f"🎯 Попыток: {current['guess_attempts']}\n\n"
            f"📝 <b>Введите в формате:</b>\n"
            f"<code>обсуждение голосование шпионы попытки</code>\n\n"
            f"Пример: <code>5 2 1 3</code>\n\n"
            f"❗ <b>Ограничения:</b>\n"
            f"• Обсуждение: 1-80 мин\n"
            f"• Голосование: 1-60 мин\n"
            f"• Шпионы: 1-5\n"
            f"• Попыты: 1-10\n\n"
            f"⚠️ <b>Правило баланса:</b>\n"
            f"Шпионов должно быть в 2 раза меньше мирных!\n"
            f"• 1 шпион = минимум 3 игрока\n"
            f"• 2 шпиона = минимум 5 игроков\n"
            f"• 3 шпиона = минимум 7 игроков\n"
            f"• 4 шпиона = минимум 9 игроков\n"
            f"• 5 шпионов = минимум 11 игроков"
        )

        safe_send_message(call.from_user.id, settings_text)

        user_states[call.from_user.id] = {
            'state': 'waiting_for_settings',
            'game_id': game_id,
            'chat_id': chat_id
        }

    except Exception as e:
        logger.error(f"❌ Ошибка callback_settings: {str(e)}")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id, {}).get('state') == 'waiting_for_settings')
def handle_settings_input(message: Message):
    """Обработка ввода настроек"""
    try:
        state = user_states.get(message.from_user.id)
        if not state:
            return

        game_id = state['game_id']
        chat_id = state['chat_id']
        del user_states[message.from_user.id]

        parts = message.text.split()
        if len(parts) != 4:
            safe_send_message(message.chat.id, "❌ Введите 4 числа!")
            return

        try:
            discussion_time = int(parts[0])
            voting_time = int(parts[1])
            spies_count = int(parts[2])
            guess_attempts = int(parts[3])
        except ValueError:
            safe_send_message(message.chat.id, "❌ Только числа!")
            return

        new_settings = {
            'discussion_time': discussion_time,
            'voting_time': voting_time,
            'spies_count': spies_count,
            'guess_attempts': guess_attempts
        }

        success, response_msg = update_game_settings(chat_id, new_settings)

        if success:
            safe_send_message(
                message.chat.id,
                f"✅ <b>Настройки обновлены!</b>\n\n"
                f"⏱️ Обсуждение: {discussion_time} мин\n"
                f"🗳️ Голосование: {voting_time} мин\n"
                f"🕵️‍♂️ Шпионы: {spies_count}\n"
                f"🎯 Попыты: {guess_attempts}"
            )

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT message_id FROM games WHERE game_id = ?', (game_id,))
            result = cursor.fetchone()
            conn.close()

            if result and result['message_id']:
                try:
                    update_game_message(chat_id, game_id, result['message_id'])
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось обновить сообщение игры: {str(e)}")
        else:
            safe_send_message(message.chat.id, response_msg)

    except Exception as e:
        logger.error(f"❌ Ошибка handle_settings_input: {str(e)}")
        safe_send_message(message.chat.id, "❌ Ошибка!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("start_game_"))
def callback_start_game(call: CallbackQuery):
    """Callback начало игры"""
    try:
        if not safe_answer_callback(call.id):
            return

        game_id = int(call.data.split("_")[2])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT creator_id, chat_id, discussion_time, voting_time, spies_count,
            guess_attempts, status, created_at FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()

        if not game:
            safe_send_message(call.from_user.id, "❌ Игра не найдена!")
            conn.close()
            return

        # Если игра pending больше 5 минут — старт может сделать любой.
        pending_grace_ok = False
        if game['status'] == 'pending' and game['created_at']:
            created_at = datetime.fromisoformat(game['created_at'])
            pending_grace_ok = (datetime.now() - created_at) >= timedelta(minutes=5)

        is_admin = call.from_user.id == ADMIN_ID
        is_creator = game['creator_id'] == call.from_user.id

        if game['status'] != 'pending':
            safe_send_message(call.from_user.id, "❌ Игра уже началась!")
            conn.close()
            return

        if not (is_creator or is_admin or pending_grace_ok):
            safe_send_message(call.from_user.id, "❌ Только создатель (или после 5 минут ожидания)!")
            conn.close()
            return

        chat_id = game['chat_id']
        spies_count = game['spies_count']
        guess_attempts = game['guess_attempts']

        cursor.execute('SELECT COUNT(*) as count FROM game_players WHERE game_id = ?', (game_id,))
        player_count = cursor.fetchone()['count']

        min_players = SPY_RULES.get(spies_count, spies_count * 2 + 1)

        if player_count < min_players:
            safe_send_message(
                chat_id,
                f"❌ <b>Ошибка запуска игры!</b>\n\n"
                f"Нужно {min_players} игроков, а присоединилось {player_count}.\n"
                f"Осталось: {min_players - player_count}\n\n"
                f"⚠️ <b>Правило баланса:</b>\n"
                f"• 1 шпион = минимум 3 игрока\n"
                f"• 2 шпиона = минимум 5 игроков\n"
                f"• 3 шпиона = минимум 7 игроков"
            )
            conn.close()
            return

        cursor.execute('SELECT user_id FROM game_players WHERE game_id = ?', (game_id,))
        all_players = [row['user_id'] for row in cursor.fetchall()]

        # Сброс состояния перед назначением ролей (защита от повторного старта кнопкой).
        cursor.execute('''UPDATE game_players
            SET alive = 1, voted = 0, guessed_location = 0, eliminated_round = 0, guess_attempts_left = ?
            WHERE game_id = ?''', (guess_attempts, game_id))

        cursor.execute('''DELETE FROM votes WHERE game_id = ?''', (game_id,))
        cursor.execute('''DELETE FROM active_sessions WHERE game_id = ?''', (game_id,))

        random.shuffle(all_players)
        spy_players = all_players[:spies_count]
        civilian_players = all_players[spies_count:]

        for user_id in spy_players:
            cursor.execute('''UPDATE game_players SET role = ? WHERE game_id = ? AND user_id = ?''', 
                (ROLE_SPY, game_id, user_id))

        for user_id in civilian_players:
            cursor.execute('''UPDATE game_players SET role = ? WHERE game_id = ? AND user_id = ?''', 
                (ROLE_CIVILIAN, game_id, user_id))

        cursor.execute('''UPDATE games SET status = ?, started_at = ? WHERE game_id = ?''', 
            ('running', datetime.now().isoformat(), game_id))

        conn.commit()

        cursor.execute('SELECT location FROM games WHERE game_id = ?', (game_id,))
        location = cursor.fetchone()['location']

        for user_id in civilian_players:
            msg = (
                f"🎭 <b>Ваша роль: Мирный житель</b>\n\n"
                f"🎯 <b>Локация:</b> {location}\n\n"
                f"Ваша задача - вычислить шпиона по вопросам!"
            )
            safe_send_message(user_id, msg)

        for user_id in spy_players:
            msg = (
                f"🎭 <b>Ваша роль: Шпион</b>\n\n"
                f"Ваша задача - угадать локацию и остаться незамеченным!"
            )
            safe_send_message(user_id, msg)

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        game_start_msg = (
            f"{theme_data['game_start']}\n\n"
            f"🔄 <b>Очередность вопросов:</b>\n"
        )

        order = all_players.copy()
        random.shuffle(order)

        for i in range(len(order)):
            current = order[i]
            next_p = order[(i + 1) % len(order)]
            game_start_msg += f"{get_user_profile_link(current)} ➡️ {get_user_profile_link(next_p)}\n"

        safe_send_message(chat_id, game_start_msg)

        try:
            bot.unpin_chat_message(chat_id)
        except:
            pass

        safe_send_message(call.from_user.id, "✅ Игра начата!")

        conn.close()

        time.sleep(1)
        start_game_phase(game_id, chat_id)

        logger.info(f"✅ Игра {game_id} запущена")

    except Exception as e:
        logger.error(f"❌ Ошибка callback_start_game: {str(e)}")
        safe_send_message(call.from_user.id, "❌ Ошибка!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("vote_"))
def callback_vote(call: CallbackQuery):
    """Callback голосование"""
    try:
        safe_answer_callback(call.id)

        parts = call.data.split("_")
        game_id = int(parts[1])
        voted_for_id = int(parts[2])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT current_round FROM active_sessions WHERE game_id = ?''', (game_id,))
        session = cursor.fetchone()
        current_round = session['current_round'] if session else 1

        # Dead/invalid users must not affect the vote.
        cursor.execute('''SELECT alive FROM game_players WHERE game_id = ? AND user_id = ?''',
            (game_id, call.from_user.id))
        voter_alive_row = cursor.fetchone()
        if not voter_alive_row or voter_alive_row['alive'] != 1:
            safe_send_message(call.from_user.id, "❌ Вы не можете голосовать (вы выбыли)!")
            conn.close()
            return

        cursor.execute('''SELECT alive FROM game_players WHERE game_id = ? AND user_id = ?''',
            (game_id, voted_for_id))
        target_alive_row = cursor.fetchone()
        if not target_alive_row or target_alive_row['alive'] != 1:
            safe_send_message(call.from_user.id, "❌ Нельзя голосовать за выбывшего игрока!")
            conn.close()
            return

        cursor.execute('''SELECT vote_id FROM votes WHERE game_id = ? AND round_number = ? AND voter_id = ?''', 
            (game_id, current_round, call.from_user.id))
        if cursor.fetchone():
            safe_send_message(call.from_user.id, "❌ Вы уже голосовали в этом раунде!")
            conn.close()
            return

        now = datetime.now().isoformat()
        cursor.execute('''INSERT INTO votes (game_id, round_number, voter_id, voted_for_id, timestamp) 
            VALUES (?, ?, ?, ?, ?)''', (game_id, current_round, call.from_user.id, voted_for_id, now))

        conn.commit()

        cursor.execute('''SELECT chat_id FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()
        chat_id = game['chat_id'] if game else None
        conn.close()

        if chat_id:
            safe_send_message(chat_id, 
                f"🗳️ {get_user_profile_link(call.from_user.id)} проголосовал за {get_user_profile_link(voted_for_id)}")

        safe_send_message(call.from_user.id, 
            f"✅ Вы проголосовали за {get_user_profile_link(voted_for_id)}")

        logger.info(f"✅ Голос учтен: {call.from_user.id} голосует за {voted_for_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка callback_vote: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("spy_vote_"))
def callback_spy_vote(call: CallbackQuery):
    """Callback голосование шпиона"""
    try:
        safe_answer_callback(call.id)

        game_id = int(call.data.split("_")[2])

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT alive, role FROM game_players WHERE game_id = ? AND user_id = ?''',
            (game_id, call.from_user.id))
        row = cursor.fetchone()
        conn.close()

        if not row or row['alive'] != 1 or row['role'] != ROLE_SPY:
            safe_send_message(call.from_user.id, "❌ Вы не можете голосовать в этой игре!")
            return

        msg = "🗳️ <b>Выберите, за кого голосовать:</b>"
        safe_send_message(call.from_user.id, msg, reply_markup=get_voting_keyboard(game_id, call.from_user.id))

    except Exception as e:
        logger.error(f"❌ Ошибка callback_spy_vote: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("spy_guess_"))
def callback_spy_guess(call: CallbackQuery):
    """Callback угадывание локации шпионом"""
    try:
        safe_answer_callback(call.id)

        game_id = int(call.data.split("_")[2])

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT role, alive, guessed_location, guess_attempts_left
            FROM game_players WHERE game_id = ? AND user_id = ?''',
            (game_id, call.from_user.id))
        player = cursor.fetchone()
        if not player or player['alive'] != 1 or player['role'] != ROLE_SPY:
            safe_send_message(call.from_user.id, "❌ Вы не можете угадывать локацию в этой игре!")
            conn.close()
            return

        if player['guessed_location'] == 1:
            safe_send_message(call.from_user.id, "✅ Вы уже угадали локацию!")
            conn.close()
            return

        attempts_left = player['guess_attempts_left'] if player else 0
        conn.close()

        if attempts_left <= 0:
            safe_send_message(call.from_user.id, "❌ У вас закончились попытки!")
            return

        msg = f"🎯 <b>Выберите локацию:</b>\n\n<i>Осталось попыток: {attempts_left}</i>"
        safe_send_message(call.from_user.id, msg, reply_markup=get_locations_keyboard(game_id))

    except Exception as e:
        logger.error(f"❌ Ошибка callback_spy_guess: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("guess_"))
def callback_guess_location(call: CallbackQuery):
    """Callback угадывание локации"""
    try:
        safe_answer_callback(call.id)

        parts = call.data.split("_", 2)
        game_id = int(parts[1])
        guessed_location = parts[2]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT location FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()
        correct_location = game['location'] if game else None

        cursor.execute('''SELECT role, alive, guessed_location, guess_attempts_left
            FROM game_players WHERE game_id = ? AND user_id = ?''',
            (game_id, call.from_user.id))
        player = cursor.fetchone()
        if not player or player['alive'] != 1 or player['role'] != ROLE_SPY:
            safe_send_message(call.from_user.id, "❌ Вы не можете угадывать локацию (вы выбыли)!")
            conn.close()
            return

        if player['guessed_location'] == 1:
            safe_send_message(call.from_user.id, "✅ Вы уже угадали локацию!")
            conn.close()
            return

        attempts_left = player['guess_attempts_left'] if player else 0
        if attempts_left <= 0:
            safe_send_message(call.from_user.id, "❌ У вас закончились попытки!")
            conn.close()
            return

        if guessed_location == correct_location:
            cursor.execute('''UPDATE game_players SET guessed_location = 1, guess_attempts_left = 0
                WHERE game_id = ? AND user_id = ? AND alive = 1 AND role = ? AND guessed_location = 0''',
                (game_id, call.from_user.id, ROLE_SPY))
            conn.commit()

            safe_send_message(call.from_user.id, 
                f"✅ <b>Правильно!</b>\n\nЛокация: {correct_location}")

            cursor.execute('''SELECT chat_id FROM games WHERE game_id = ?''', (game_id,))
            game = cursor.fetchone()
            chat_id = game['chat_id'] if game else None

            if chat_id:
                safe_send_message(chat_id, 
                    f"🎯 {get_user_profile_link(call.from_user.id)} угадал локацию!")

                check_win_conditions(game_id, chat_id)

        else:
            attempts_left = max(0, attempts_left - 1)
            cursor.execute('''UPDATE game_players SET guess_attempts_left = ?
                WHERE game_id = ? AND user_id = ? AND alive = 1 AND role = ?''',
                (attempts_left, game_id, call.from_user.id, ROLE_SPY))
            conn.commit()

            if attempts_left > 0:
                safe_send_message(call.from_user.id, 
                    f"❌ <b>Неправильно!</b>\n\n"
                    f"Осталось попыток: {attempts_left}\n\n"
                    f"Попробуйте еще раз!")

                msg = f"🎯 <b>Выберите локацию:</b>\n\n<i>Осталось попыток: {attempts_left}</i>"
                safe_send_message(call.from_user.id, msg, reply_markup=get_locations_keyboard(game_id))

            else:
                safe_send_message(call.from_user.id, 
                    f"❌ <b>Попытки закончились!</b>\n\n"
                    f"Правильная локация: {correct_location}")

        conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка callback_guess_location: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_"))
def callback_help(call: CallbackQuery):
    """Callback помощь"""
    try:
        safe_answer_callback(call.id)

        help_type = call.data.split("_")[1]

        if help_type == "general":
            text = (
                f"👥 <b>Команды для всех:</b>\n\n"
                f"• /start - Начало\n"
                f"• /help - Помощь\n"
                f"• /rules - Правила\n"
                f"• /locations - Локации\n"
                f"• /stats - Статистика\n"
                f"• /spygo - Начать игру\n"
                f"• /leave - Выйти\n"
                f"• /stop - Остановить"
            )

        elif help_type == "vip":
            text = (
                f"⭐ <b>VIP команды:</b>\n\n"
                f"• /buy_vip - Купить VIP\n"
                f"• /addlocations - Добавить локацию\n"
                f"• /removelocations - Удалить локацию\n"
                f"• /viplocations - Мои локации\n"
                f"• /custom_game - Игра с локацией\n"
                f"• /viptheme - Выбрать тему"
            )

        else:
            text = "❌ Ошибка!"

        if not safe_edit_message(call.message.chat.id, call.message.message_id, text, reply_markup=get_help_keyboard()):
            safe_send_message(call.message.chat.id, text, reply_markup=get_help_keyboard())

    except Exception as e:
        logger.error(f"❌ Ошибка callback_help: {str(e)}")

# ==================== ИГРОВАЯ ЛОГИКА ====================

def start_game_phase(game_id: int, chat_id: int):
    """Запуск фазы обсуждения с очередностью вопросов"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT discussion_time, voting_time, spies_count, location FROM games 
            WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()

        if not game:
            conn.close()
            return

        discussion_time = game['discussion_time']
        voting_time = game['voting_time']
        location = game['location']

        # В очередности должны быть ТОЛЬКО живые игроки
        cursor.execute('''SELECT user_id FROM game_players WHERE game_id = ? AND alive = 1 ORDER BY RANDOM()''', (game_id,))
        all_players = [row['user_id'] for row in cursor.fetchall()]
        if not all_players:
            conn.close()
            # Если по каким-то причинам никого не осталось живым, корректно завершим/перейдем дальше по правилам
            check_win_conditions(game_id, chat_id)
            return

        now = datetime.now()
        discussion_end = now + timedelta(minutes=discussion_time)
        voting_end = discussion_end + timedelta(minutes=voting_time)

        cursor.execute('''SELECT game_id FROM active_sessions WHERE game_id = ?''', (game_id,))
        existing_session = cursor.fetchone()

        if existing_session:
            cursor.execute('''UPDATE active_sessions 
                SET current_phase = 'discussion', 
                    discussion_end_time = ?, 
                    voting_end_time = ?
                WHERE game_id = ?''', 
                (discussion_end.isoformat(), voting_end.isoformat(), game_id))
        else:
            cursor.execute('''INSERT INTO active_sessions (game_id, chat_id, current_round, current_phase, 
                discussion_end_time, voting_end_time, created_at) 
                VALUES (?, ?, 1, 'discussion', ?, ?, ?)''', 
                (game_id, chat_id, discussion_end.isoformat(), voting_end.isoformat(), now.isoformat()))

        conn.commit()
        conn.close()

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        order = all_players.copy()
        random.shuffle(order)

        order_text = ""
        for i in range(len(order)):
            current = order[i]
            next_p = order[(i + 1) % len(order)]
            order_text += f"{get_user_profile_link(current)} ➡️ {get_user_profile_link(next_p)}\n"

        discussion_msg = (
            f"{theme_data['emoji']} <b>Начинается обсуждение!</b>\n\n"
            f"⏱️ <b>Время:</b> {format_time(discussion_time)}\n"
            f"🎯 <b>Локация:</b> {location}\n\n"
            f"🔄 <b>Очередность вопросов:</b>\n"
            f"{order_text}\n"
            f"💬 <b>Обсуждайте и вычисляйте шпиона!</b>\n\n"
            f"📝 <b>Как это работает:</b>\n"
            f"• Каждый игрок задает вопрос СЛЕДУЮЩЕМУ в очередности\n"
            f"• Вопросы должны быть про локацию\n"
            f"• Все видят очередность\n"
            f"• Пишите в группе свободно\n"
            f"• За 1 минуту до конца - предупреждение"
        )

        safe_send_message(chat_id, discussion_msg)

        threading.Thread(target=discussion_timer, args=(game_id, chat_id, discussion_time), daemon=True).start()

        logger.info(f"✅ Фаза обсуждения начата для игры {game_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка start_game_phase: {str(e)}")

def discussion_timer(game_id: int, chat_id: int, duration: int):
    """Таймер обсуждения"""
    try:
        start_time = time.time()
        warning_sent = False

        while time.time() - start_time < duration * 60:
            elapsed = time.time() - start_time
            remaining = duration * 60 - elapsed

            if remaining <= 60 and not warning_sent:
                warning_sent = True
                safe_send_message(chat_id, "⏰ <b>До конца обсуждения осталась 1 минута!</b>\n\n"
                    "🔍 Успейте вычислить всех шпионов!")

            time.sleep(1)

        start_voting_phase(game_id, chat_id)

    except Exception as e:
        logger.error(f"❌ Ошибка discussion_timer: {str(e)}")

def start_voting_phase(game_id: int, chat_id: int):
    """Запуск фазы голосования"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT voting_time FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()

        if not game:
            conn.close()
            return

        voting_time = game['voting_time']

        cursor.execute('''SELECT current_round FROM active_sessions WHERE game_id = ?''', (game_id,))
        session = cursor.fetchone()
        current_round = session['current_round'] if session else 1

        cursor.execute('''DELETE FROM votes WHERE game_id = ? AND round_number = ?''', (game_id, current_round))
        cursor.execute('''UPDATE game_players SET voted = 0 WHERE game_id = ?''', (game_id,))
        cursor.execute('''UPDATE active_sessions SET current_phase = 'voting' WHERE game_id = ?''', (game_id,))

        conn.commit()

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        voting_msg = (
            f"{theme_data['emoji']} <b>Начинается голосование!</b>\n\n"
            f"⏱️ <b>Время:</b> {format_time(voting_time)}\n\n"
            f"🗳️ <b>Голосуйте за подозреваемого!</b>"
        )

        safe_send_message(chat_id, voting_msg)

        cursor.execute('''SELECT user_id FROM game_players WHERE game_id = ? AND alive = 1''', (game_id,))
        players = [row['user_id'] for row in cursor.fetchall()]
        conn.close()

        for player_id in players:
            is_spy = is_user_spy(game_id, player_id)
            if is_spy:
                msg = "🗳️ <b>Выберите действие:</b>"
                safe_send_message(player_id, msg, reply_markup=get_spy_voting_keyboard(game_id))
            else:
                msg = "🗳️ <b>Выберите, за кого голосовать:</b>"
                safe_send_message(player_id, msg, reply_markup=get_voting_keyboard(game_id, player_id))

        threading.Thread(target=voting_timer, args=(game_id, chat_id, voting_time), daemon=True).start()

        logger.info(f"✅ Фаза голосования начата для игры {game_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка start_voting_phase: {str(e)}")

def voting_timer(game_id: int, chat_id: int, duration: int):
    """Таймер голосования"""
    try:
        start_time = time.time()
        warning_sent = False

        while time.time() - start_time < duration * 60:
            elapsed = time.time() - start_time
            remaining = duration * 60 - elapsed

            if remaining <= 60 and not warning_sent:
                warning_sent = True
                safe_send_message(chat_id, "⏰ <b>До конца голосования осталась 1 минута!</b>\n\n"
                    "🗳️ Поторопитесь голосовать!")

            time.sleep(1)

        process_voting_results(game_id, chat_id)

    except Exception as e:
        logger.error(f"❌ Ошибка voting_timer: {str(e)}")

def process_voting_results(game_id: int, chat_id: int):
    """Обработка результатов голосования"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT status FROM games WHERE game_id = ?''', (game_id,))
        game_status_row = cursor.fetchone()
        game_status = game_status_row['status'] if game_status_row else None
        # Если игру уже завершили (например, шпион угадал заранее), не делаем повторных результатов.
        if game_status != 'running':
            conn.close()
            return

        cursor.execute('''SELECT current_round FROM active_sessions WHERE game_id = ?''', (game_id,))
        session = cursor.fetchone()
        current_round = session['current_round'] if session else 1

        cursor.execute('''SELECT voted_for_id, COUNT(*) as vote_count FROM votes 
            WHERE game_id = ? AND round_number = ? GROUP BY voted_for_id ORDER BY vote_count DESC''', 
            (game_id, current_round))
        votes = cursor.fetchall()

        if not votes:
            safe_send_message(chat_id, "❌ <b>Никто не голосовал!</b>\n\n"
                "Игра продолжается...")
            conn.close()
            start_next_round(game_id, chat_id)
            return

        max_votes = votes[0]['vote_count']
        candidates = [row['voted_for_id'] for row in votes if row['vote_count'] == max_votes]

        if len(candidates) > 1:
            eliminated_id = random.choice(candidates)
        else:
            eliminated_id = candidates[0]

        cursor.execute('''SELECT role FROM game_players WHERE game_id = ? AND user_id = ?''', 
            (game_id, eliminated_id))
        player = cursor.fetchone()
        role = player['role'] if player else None

        cursor.execute('''UPDATE game_players SET alive = 0 WHERE game_id = ? AND user_id = ?''', 
            (game_id, eliminated_id))
        conn.commit()

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        role_text = "🕵️‍♂️ <b>Шпион!</b>" if role == ROLE_SPY else "👥 <b>Мирный житель!</b>"
        result_msg = (
            f"🗳️ <b>Результаты голосования:</b>\n\n"
            f"Наибольшее количество голосов получил:\n"
            f"{get_user_profile_link(eliminated_id)}\n\n"
            f"Роль: {role_text}"
        )

        safe_send_message(chat_id, result_msg)

        check_win_conditions(game_id, chat_id)

    except Exception as e:
        logger.error(f"❌ Ошибка process_voting_results: {str(e)}")

def check_win_conditions(game_id: int, chat_id: int):
    """Проверка условий победы"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT status, spies_count FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()
        if not game:
            conn.close()
            return
        if game['status'] == 'completed':
            conn.close()
            return
        spies_count = game['spies_count']

        cursor.execute('''SELECT COUNT(*) as count FROM game_players 
            WHERE game_id = ? AND role = ? AND alive = 1''', (game_id, ROLE_SPY))
        alive_spies = cursor.fetchone()['count']

        cursor.execute('''SELECT COUNT(*) as count FROM game_players 
            WHERE game_id = ? AND role = ? AND alive = 1''', (game_id, ROLE_CIVILIAN))
        alive_civilians = cursor.fetchone()['count']

        cursor.execute('''SELECT COUNT(*) as count FROM game_players 
            WHERE game_id = ? AND role = ? AND alive = 1 AND guessed_location = 1''', (game_id, ROLE_SPY))
        spies_guessed = cursor.fetchone()['count']

        spies_need_to_guess = SPY_WIN_RULES.get(spies_count, 1)
        winner = None

        if spies_guessed >= spies_need_to_guess:
            winner = 'spies'
        elif alive_spies == 0:
            winner = 'civilians'
        elif alive_civilians <= alive_spies:
            winner = 'spies'

        if winner:
            end_game(game_id, chat_id, winner)
        else:
            start_next_round(game_id, chat_id)

        conn.close()

    except Exception as e:
        logger.error(f"❌ Ошибка check_win_conditions: {str(e)}")

def start_next_round(game_id: int, chat_id: int):
    """Начало следующего раунда"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT current_round FROM active_sessions WHERE game_id = ?''', (game_id,))
        session = cursor.fetchone()
        current_round = session['current_round'] if session else 1
        new_round = current_round + 1

        cursor.execute('''UPDATE active_sessions SET current_round = ? WHERE game_id = ?''', 
            (new_round, game_id))

        cursor.execute('''SELECT guess_attempts FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()
        guess_attempts = game['guess_attempts'] if game else 3

        cursor.execute('''UPDATE game_players SET guess_attempts_left = ?, voted = 0 
            WHERE game_id = ? AND role = ? AND alive = 1 AND guessed_location = 0''',
            (guess_attempts, game_id, ROLE_SPY))

        conn.commit()
        conn.close()

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        round_msg = (
            f"{theme_data['round_text']} <b>{new_round}</b>\n\n"
            f"🔄 <b>Начинается новый раунд!</b>"
        )

        safe_send_message(chat_id, round_msg)
        time.sleep(2)

        start_game_phase(game_id, chat_id)

    except Exception as e:
        logger.error(f"❌ Ошибка start_next_round: {str(e)}")

def end_game(game_id: int, chat_id: int, winner: str):
    """Завершение игры"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''SELECT status FROM games WHERE game_id = ?''', (game_id,))
        status_row = cursor.fetchone()
        if status_row and status_row['status'] == 'completed':
            conn.close()
            return

        cursor.execute('''SELECT location, started_at FROM games WHERE game_id = ?''', (game_id,))
        game = cursor.fetchone()
        location = game['location'] if game else "Unknown"
        started_at = datetime.fromisoformat(game['started_at']) if game and game['started_at'] else datetime.now()

        cursor.execute('''SELECT user_id, role, alive, guessed_location FROM game_players WHERE game_id = ?''', (game_id,))
        players = cursor.fetchall()
        spies = [p['user_id'] for p in players if p['role'] == ROLE_SPY]
        civilians = [p['user_id'] for p in players if p['role'] == ROLE_CIVILIAN]
        spies_guessed_alive = [p['user_id'] for p in players if p['role'] == ROLE_SPY and p['alive'] == 1 and p['guessed_location'] == 1]

        now = datetime.now().isoformat()
        for player in players:
            user_id = player['user_id']
            role = player['role']

            cursor.execute('''UPDATE users SET games_played = games_played + 1, last_active = ? 
                WHERE user_id = ?''', (now, user_id))

            if winner == 'spies' and role == ROLE_SPY:
                cursor.execute('''UPDATE users SET times_spy = times_spy + 1 WHERE user_id = ?''', (user_id,))
            elif winner == 'civilians' and role == ROLE_CIVILIAN:
                cursor.execute('''UPDATE users SET times_civilian = times_civilian + 1 WHERE user_id = ?''', (user_id,))

        game_duration = int((datetime.now() - started_at).total_seconds() / 60)
        cursor.execute('''UPDATE games SET status = 'completed', winner = ?, ended_at = ? WHERE game_id = ?''', 
            (winner, now, game_id))

        conn.commit()
        conn.close()

        theme = get_group_theme(chat_id)
        theme_data = THEMES[theme]

        if winner == 'spies':
            winner_text = "🕵️‍♂️ <b>Победили шпионы!</b>"
        else:
            winner_text = "👥 <b>Победили мирные жители!</b>"

        end_msg = (
            f"{theme_data['emoji']} <b>Игра завершена!</b>\n\n"
            f"{winner_text}\n\n"
            f"🎯 <b>Локация:</b> {location}\n"
            f"⏱️ <b>Длительность:</b> {game_duration} минут\n\n"
            f"👥 <b>Мирные жители:</b>\n"
            f"{', '.join([get_user_profile_link(c) for c in civilians]) or 'Нет'}\n\n"
            f"🕵️‍♂️ <b>Шпионы:</b>\n"
            f"{', '.join([get_user_profile_link(s) for s in spies]) or 'Нет'}"
        )

        if winner == 'spies':
            end_msg += (
                "\n\n"
                f"🎯 <b>Угадали локацию (живы):</b>\n"
                f"{', '.join([get_user_profile_link(s) for s in spies_guessed_alive]) or 'Нет'}"
            )

        safe_send_message(chat_id, end_msg)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM active_sessions WHERE game_id = ?', (game_id,))
        cursor.execute('DELETE FROM muted_players WHERE game_id = ?', (game_id,))
        conn.commit()
        conn.close()

        logger.info(f"✅ Игра {game_id} завершена. Победители: {winner}")

    except Exception as e:
        logger.error(f"❌ Ошибка end_game: {str(e)}")

# ==================== АДМИН КОМАНДЫ ====================

@bot.message_handler(commands=['broadcast'])
def handle_broadcast(message: Message):
    """Команда /broadcast"""
    try:
        if message.from_user.id != ADMIN_ID:
            safe_send_message(message.chat.id, "❌ Нет прав!")
            return

        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            safe_send_message(message.chat.id, "❌ Укажите сообщение!")
            return

        broadcast_text = args[1]

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT user_id FROM users')
        users = [row['user_id'] for row in cursor.fetchall()]

        cursor.execute('SELECT chat_id FROM groups')
        groups = [row['chat_id'] for row in cursor.fetchall()]
        conn.close()

        success = 0
        removed = 0
        fail = 0
        text = f"📢 <b>Сообщение от администратора:</b>\n\n{broadcast_text}"

        for chat_id in users + groups:
            try:
                bot.send_message(chat_id, text, parse_mode='HTML')
                success += 1
            except telebot.apihelper.ApiException as e:
                if e.result.status_code in (403, 404):
                    removed += 1
                    cleanup_chat_in_db(chat_id)
                else:
                    fail += 1
                    logger.error(f"❌ /broadcast ошибка для {chat_id}: {str(e)}")
            except Exception as e:
                fail += 1
                logger.error(f"❌ /broadcast unexpected для {chat_id}: {str(e)}")

            time.sleep(0.1)

        safe_send_message(
            ADMIN_ID,
            f"✅ Рассылка завершена!\n\n"
            f"✅ Успешно: {success}\n"
            f"🧹 Удалено из БД (запрет/не найдено): {removed}\n"
            f"❌ Ошибок: {fail}",
        )

    except Exception as e:
        logger.error(f"❌ Ошибка /broadcast: {str(e)}")

@bot.message_handler(commands=['admstats'])
def handle_admstats(message: Message):
    """Команда /admstats"""
    try:
        if message.from_user.id != ADMIN_ID:
            safe_send_message(message.chat.id, "❌ Нет прав!")
            return

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) as count FROM users')
        users = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM groups')
        groups = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM games')
        games = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM games WHERE status = "completed"')
        completed_games = cursor.fetchone()['count']
        conn.close()

        stats_text = (
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Пользователи: {users}\n"
            f"🏠 Группы: {groups}\n"
            f"🎮 Всего игр: {games}\n"
            f"✅ Завершено: {completed_games}"
        )

        safe_send_message(ADMIN_ID, stats_text)

    except Exception as e:
        logger.error(f"❌ Ошибка /admstats: {str(e)}")

@bot.message_handler(commands=['give_vip'])
def handle_give_vip(message: Message):
    """Команда /give_vip"""
    try:
        if message.from_user.id != ADMIN_ID:
            safe_send_message(message.chat.id, "❌ Нет прав!")
            return

        # Формат:
        # /give_vip 1d 123456789
        # /give_vip 1d username
        # /give_vip 1d @username
        # /give_vip 1d (reply на пользователя)
        parts = message.text.split(maxsplit=2)
        if message.reply_to_message:
            if len(parts) < 2:
                safe_send_message(message.chat.id, "❌ Формат: /give_vip [время] (reply на пользователя)")
                return
            duration_str = parts[1]
            target_user_id = message.reply_to_message.from_user.id
        else:
            if len(parts) < 3:
                safe_send_message(message.chat.id, "❌ Формат: /give_vip [время] [ID/username]")
                return
            duration_str = parts[1]
            target_spec = parts[2].strip().split()[0]  # на случай лишних слов в конце

            # Попытка распознать user_id/username
            target_username = target_spec.lstrip('@')
            target_user_id = None

            if target_username.isdigit():
                target_user_id = int(target_username)
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''SELECT user_id FROM users WHERE username = ?''', (target_username,))
                row = cursor.fetchone()
                if row:
                    target_user_id = int(row['user_id'])
                conn.close()

                if target_user_id is None:
                    # Фоллбек: попробуем получить пользователя через Telegram API
                    try:
                        try_user = bot.get_chat('@' + target_username)
                        target_user_id = int(try_user.id)
                    except Exception:
                        try:
                            try_user = bot.get_chat(target_username)
                            target_user_id = int(try_user.id)
                        except Exception:
                            target_user_id = None

            if target_user_id is None:
                safe_send_message(message.chat.id, "❌ Пользователь не найден (не могу получить user_id).")
                return

        try:
            duration = parse_duration(duration_str)
        except Exception as e:
            safe_send_message(message.chat.id, f"❌ Ошибка времени: {str(e)}")
            return

        now_dt = datetime.now()
        now = now_dt.isoformat()

        # Если VIP уже активен — продлеваем с текущей даты окончания (чтобы не “укорачивать”).
        expires_at = now_dt + duration

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''SELECT vip_expires_at FROM users WHERE user_id = ? AND is_vip = 1 AND vip_expires_at IS NOT NULL''',
            (target_user_id,))
        row = cursor.fetchone()
        if row and row['vip_expires_at']:
            try:
                existing_exp = datetime.fromisoformat(row['vip_expires_at'])
                if existing_exp > now_dt:
                    expires_at = existing_exp + duration
            except Exception:
                pass

        cursor.execute('''UPDATE users SET is_vip = 1, vip_expires_at = ?, last_active = ?
            WHERE user_id = ?''', (expires_at.isoformat(), now, target_user_id))

        if cursor.rowcount == 0:
            cursor.execute('''INSERT INTO users (user_id, is_vip, vip_expires_at, created_at, last_active)
                VALUES (?, 1, ?, ?, ?)''', (target_user_id, expires_at.isoformat(), now, now))

        conn.commit()
        conn.close()

        user_msg = (
            f"🎉 <b>Вам выдан VIP-статус!</b>\n\n"
            f"📅 <b>Действует до:</b> {expires_at.strftime('%d.%m.%Y')}\n\n"
            f"✨ <b>Доступные команды:</b>\n"
            f"• /addlocations\n"
            f"• /removelocations\n"
            f"• /viplocations\n"
            f"• /custom_game\n"
            f"• /viptheme"
        )

        safe_send_message(target_user_id, user_msg)
        safe_send_message(
            message.chat.id,
            f"✅ VIP выдан пользователю {get_user_profile_link(target_user_id)}\n"
            f"⏳ До: {expires_at.strftime('%d.%m.%Y')}",
        )
    except Exception as e:
        logger.error(f"❌ Ошибка /give_vip: {str(e)}")

@bot.message_handler(commands=['refound'])
def handle_refound(message: Message):
    """Команда /refound"""
    try:
        if message.from_user.id != ADMIN_ID:
            safe_send_message(message.chat.id, "❌ Нет прав!")
            return

        args = message.text.split()
        if len(args) < 2:
            safe_send_message(message.chat.id, "❌ Формат: /refound [ID/юзернейм]")
            return

        target_id = args[1]
        try:
            target_user = bot.get_chat(int(target_id))
        except:
            safe_send_message(message.chat.id, "❌ Пользователь не найден!")
            return

        refund_msg = (
            f"🔄 <b>Возврат звезд</b>\n\n"
            f"Пользователь: {get_user_profile_link(target_user.id)}\n"
            f"ID: {target_user.id}\n\n"
            f"❗ Обработайте вручную через панель разработчика Telegram"
        )

        safe_send_message(ADMIN_ID, refund_msg)
        safe_send_message(message.chat.id, "✅ Запрос создан!")

    except Exception as e:
        logger.error(f"❌ Ошибка /refound: {str(e)}")

# ==================== БЭКАПЫ ====================

def backup_loop():
    """Цикл создания бэкапов"""
    logger.info("🔄 Запуск цикла бэкапов")

    while processing_active:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(BACKUP_DIR, f"backup_{timestamp}.db")
            shutil.copy2(DB_PATH, backup_path)
            logger.info(f"✅ Бэкап создан: {backup_path}")

            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.startswith('backup_')], reverse=True)
            for old in backups[10:]:
                try:
                    os.remove(os.path.join(BACKUP_DIR, old))
                except:
                    pass

            for _ in range(12 * 60):
                if not processing_active:
                    break
                time.sleep(60)

        except Exception as e:
            logger.error(f"❌ Ошибка бэкапа: {str(e)}")
            time.sleep(60)

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

if __name__ == '__main__':
    try:
        logger.info("🚀 Инициализация бота...")
        init_database()

        backup_thread = threading.Thread(target=backup_loop, daemon=True)
        backup_thread.start()

        logger.info("🚀 Бот запущен!")
        # Telegram может временно не отвечать. Перезапускаем polling при сетевых/таймаут ошибках.
        while True:
            try:
                bot.polling(none_stop=True, interval=0, timeout=20)
            except Exception as e:
                logger.error(f"⚠️ Ошибка polling: {str(e)}. Перезапуск через 10 сек...")
                time.sleep(10)

    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        logger.error(traceback.format_exc())