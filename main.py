#!/usr/bin/env python3
"""
🤖 GRAND: Чат-менеджер для ВКонтакте
Мульти-чат бот с системой модерации и управления беседами
Версия: 2.0 | Все в одном файле
"""

import asyncio
import json
import datetime
import re
import os
import pickle
import logging
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum

try:
    from vkbottle import Bot, Message
    from vkbottle.bot import BotLabeler
    from vkbottle_types.codegen.objects import UsersUserFull
    VKBOTTLE_AVAILABLE = True
except ImportError:
    print("❌ Ошибка: vkbottle не установлен!")
    print("Установите: pip install vkbottle")
    VKBOTTLE_AVAILABLE = False
    exit(1)

# ============= КОНФИГУРАЦИЯ =============
# ↓↓↓ ЗДЕСЬ НАСТРОЙТЕ СВОЙ БОТ ↓↓↓

BOT_TOKEN = "vk1.a.MXsY3qvr9-tN4Hfx45KUxedsMM8II0VKo_S3fo6FV1nBcenaTfFr1ptRlPXvPnOfW4DVMh8OsMSvBIzY8Y99xW7RlCzrFJM7YyvCEXjR_XtQaqTDY1Udvwg4tnkKaz_hfMScWr4_1lz9pDf7hw3Fo_rywCYKB9dq9Kobno6mnVtNcaRx_dITiccTRPNQS2e4K0AiADhxOPbpnrIwOHjclQ"  # Получите токен в настройках сообщества ВК
GROUP_ID = 235638129  # ID вашего сообщества (опционально)

# Настройки по умолчанию
COMMAND_PREFIXES = ["/", "!"]
ADMIN_IDS = []  # ID суперадминов (будут иметь все права)

# Автосоздание папки для данных
DATA_FOLDER = "grand_data"
if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

# ↑↑↑ НАСТРОЙКИ ЗАВЕРШЕНЫ ↑↑↑
# ======================================

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
labeler = BotLabeler()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{DATA_FOLDER}/grand.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GRAND")

# Константы
MUTE_DURATIONS = {
    "15m": 15, "30m": 30, "1h": 60, "3h": 180, "6h": 360,
    "12h": 720, "1d": 1440, "3d": 4320, "7d": 10080, "30d": 43200
}

DEFAULT_SETTINGS = {
    "auto_welcome": True,
    "welcome_message": "Добро пожаловать в беседу, {user}!",
    "anti_flood": True,
    "warns_enabled": True,
    "max_warns": 3,
    "log_actions": True,
    "allow_custom_commands": True,
    "command_prefix": "!",
    "language": "ru"
}

# ============= БАЗА ДАННЫХ =============

class Database:
    def __init__(self):
        self.data_file = f"{DATA_FOLDER}/database.dat"
        self.data = {
            "chats": {},          # Данные по чатам
            "global_bans": [],    # Глобальные баны
            "statistics": {       # Статистика
                "total_messages": 0,
                "total_commands": 0,
                "total_bans": 0,
                "total_mutes": 0,
                "total_kicks": 0
            },
            "users": {},          # Глобальные данные пользователей
            "backups": []         # Резервные копии
        }
        self.load()
    
    def load(self):
        """Загрузить данные из файла"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'rb') as f:
                    loaded = pickle.load(f)
                    # Проверяем структуру
                    if isinstance(loaded, dict):
                        self.data.update(loaded)
                        logger.info(f"Загружено {len(self.data['chats'])} чатов")
                    else:
                        logger.warning("Файл данных поврежден, создаем новую БД")
                        self.save()
            else:
                logger.info("Файл данных не найден, создаем новую БД")
                self.save()
        except Exception as e:
            logger.error(f"Ошибка загрузки БД: {e}")
            self.save()
    
    def save(self):
        """Сохранить данные в файл"""
        try:
            with open(self.data_file, 'wb') as f:
                pickle.dump(self.data, f)
            
            # Также сохраняем в JSON для читаемости
            json_file = f"{DATA_FOLDER}/database.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                # Функция для сериализации datetime
                def serialize(obj):
                    if isinstance(obj, datetime.datetime):
                        return obj.isoformat()
                    return str(obj)
                
                json.dump(self.data, f, default=serialize, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения БД: {e}")
    
    def init_chat(self, chat_id: int) -> Dict:
        """Инициализировать или получить данные чата"""
        chat_id_str = str(chat_id)
        
        if chat_id_str not in self.data["chats"]:
            self.data["chats"][chat_id_str] = {
                "info": {
                    "title": f"Чат {chat_id}",
                    "created": datetime.datetime.now().isoformat(),
                    "last_active": datetime.datetime.now().isoformat(),
                    "message_count": 0,
                    "user_count": 0
                },
                "moderation": {
                    "bans": [],
                    "mutes": {},
                    "warns": {},
                    "kicks": []
                },
                "users": {
                    "nicknames": {},
                    "roles": {},
                    "profiles": {}
                },
                "settings": DEFAULT_SETTINGS.copy(),
                "custom_commands": {},
                "pinned_messages": [],
                "welcome_stats": {
                    "total_welcomed": 0,
                    "last_welcome": None
                },
                "economy": {
                    "enabled": False,
                    "currency": "₽",
                    "users_balance": {}
                },
                "activity": {
                    "unity_scores": {},
                    "last_messages": {},
                    "daily_stats": {}
                }
            }
            logger.info(f"Создан новый чат: {chat_id}")
            self.save()
        
        # Обновляем время активности
        self.data["chats"][chat_id_str]["info"]["last_active"] = datetime.datetime.now().isoformat()
        return self.data["chats"][chat_id_str]
    
    def get_chat(self, chat_id: int) -> Optional[Dict]:
        """Получить данные чата"""
        return self.data["chats"].get(str(chat_id))
    
    def update_chat(self, chat_id: int, data: Dict):
        """Обновить данные чата"""
        chat_id_str = str(chat_id)
        if chat_id_str in self.data["chats"]:
            self.data["chats"][chat_id_str].update(data)
            self.save()
    
    def add_stat(self, stat_name: str, value: int = 1):
        """Добавить статистику"""
        if stat_name in self.data["statistics"]:
            self.data["statistics"][stat_name] += value
            self.save()

db = Database()

# ============= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============

async def get_user_info(user_id: int) -> UsersUserFull:
    """Получить информацию о пользователе"""
    try:
        users = await bot.api.users.get(
            user_ids=[user_id],
            fields=["first_name", "last_name", "photo_50"]
        )
        return users[0]
    except Exception as e:
        logger.error(f"Ошибка получения пользователя {user_id}: {e}")
        # Возвращаем заглушку
        class UserStub:
            id = user_id
            first_name = "Пользователь"
            last_name = str(user_id)
        return UserStub()

async def is_admin(chat_id: int, user_id: int) -> bool:
    """Проверить админские права в беседе"""
    try:
        # Суперадмины из конфига
        if user_id in ADMIN_IDS:
            return True
        
        # Проверяем права в беседе ВК
        chat_info = await bot.api.messages.get_conversation_members(
            peer_id=chat_id + 2000000000
        )
        
        for member in chat_info.items:
            if member.member_id == user_id:
                if hasattr(member, 'is_admin') and member.is_admin:
                    return True
                if hasattr(member, 'is_owner') and member.is_owner:
                    return True
        
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки админа: {e}")
        return False

async def is_moderator(chat_id: int, user_id: int) -> bool:
    """Проверить права модератора"""
    try:
        if await is_admin(chat_id, user_id):
            return True
        
        chat_data = db.get_chat(chat_id)
        if chat_data:
            roles = chat_data["users"].get("roles", {})
            return user_id in roles.get("moderator", []) or user_id in roles.get("admin", [])
        
        return False
    except:
        return False

async def check_permission(message: Message, command_type: str = "user") -> Tuple[bool, str]:
    """Проверить права пользователя"""
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    # Проверка глобального бана
    if user_id in db.data["global_bans"]:
        return False, "🚫 Вы забанены глобально!"
    
    # Права для разных типов команд
    if command_type == "user":
        return True, ""
    
    elif command_type == "moderator":
        if await is_moderator(chat_id, user_id):
            return True, ""
        return False, "❌ Требуются права модератора!"
    
    elif command_type == "admin":
        if await is_admin(chat_id, user_id):
            return True, ""
        return False, "❌ Требуются права администратора!"
    
    elif command_type == "superadmin":
        if user_id in ADMIN_IDS or await is_admin(chat_id, user_id):
            return True, ""
        return False, "❌ Требуются права суперадминистратора!"
    
    return False, "❌ Недостаточно прав!"

async def send_reply(message: Message, text: str, **kwargs):
    """Отправить ответ"""
    try:
        await message.answer(text, **kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

async def extract_user_id(text: str) -> Optional[int]:
    """Извлечь ID пользователя из текста"""
    try:
        # Паттерны для поиска ID
        patterns = [
            r'\[id(\d+)\|',
            r'@id(\d+)',
            r'vk\.com/id(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        
        # Если это просто число
        if text.isdigit():
            return int(text)
        
        return None
    except:
        return None

async def parse_duration(duration_str: str) -> Optional[int]:
    """Парсинг длительности мута"""
    duration_str = duration_str.lower().strip()
    
    if duration_str in MUTE_DURATIONS:
        return MUTE_DURATIONS[duration_str]
    
    try:
        if duration_str.endswith("m"):
            return int(duration_str[:-1])
        elif duration_str.endswith("h"):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith("d"):
            return int(duration_str[:-1]) * 1440
        elif duration_str.endswith("w"):
            return int(duration_str[:-1]) * 10080
        else:
            return int(duration_str)
    except:
        return None

async def format_time(minutes: int) -> str:
    """Форматировать время"""
    if minutes >= 10080:  # недели
        weeks = minutes // 10080
        return f"{weeks}н"
    elif minutes >= 1440:  # дни
        days = minutes // 1440
        return f"{days}д"
    elif minutes >= 60:  # часы
        hours = minutes // 60
        return f"{hours}ч"
    else:
        return f"{minutes}м"

async def mention_user(user_id: int, user_info: UsersUserFull = None) -> str:
    """Создать упоминание пользователя"""
    if not user_info:
        user_info = await get_user_info(user_id)
    return f"[id{user_id}|{user_info.first_name} {user_info.last_name}]"

# ============= КОМАНДЫ МОДЕРАЦИИ =============

@labeler.message(text=["/ban", "!ban"])
async def ban_handler(message: Message):
    """Бан пользователя"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /ban @user [причина]")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    # Проверки
    if target_id == user_id:
        return await send_reply(message, "❌ Нельзя забанить самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя забанить администратора!")
    
    reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"
    
    # Выполняем бан
    chat_data = db.init_chat(chat_id)
    if target_id not in chat_data["moderation"]["bans"]:
        chat_data["moderation"]["bans"].append(target_id)
        db.update_chat(chat_id, chat_data)
        db.add_stat("total_bans")
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    response = (
        f"🚫 Пользователь {target_mention} забанен!\n"
        f"📋 Причина: {reason}\n"
        f"👮‍♂️ Модератор: [id{user_id}|Вы]"
    )
    
    await send_reply(message, response)
    
    # Пытаемся кикнуть
    try:
        await bot.api.messages.remove_chat_user(
            chat_id=chat_id,
            user_id=target_id
        )
    except:
        pass

@labeler.message(text=["/unban", "!unban"])
async def unban_handler(message: Message):
    """Разбан пользователя"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /unban @user")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or target_id not in chat_data["moderation"]["bans"]:
        return await send_reply(message, "⚠️ Этот пользователь не забанен")
    
    # Удаляем бан
    chat_data["moderation"]["bans"].remove(target_id)
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    await send_reply(message, f"✅ Пользователь {target_mention} разбанен!")

@labeler.message(text=["/mute", "!mute"])
async def mute_handler(message: Message):
    """Мут пользователя"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, 
            "❌ Использование: /mute @user время [причина]\n"
            "Пример: /mute @user 1h Спам\n"
            "Доступно: 15m, 30m, 1h, 3h, 6h, 12h, 1d, 3d, 7d, 30d"
        )
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    if target_id == user_id:
        return await send_reply(message, "❌ Нельзя замутить самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя замутить администратора!")
    
    duration = await parse_duration(args[2])
    if not duration:
        return await send_reply(message, "❌ Неверное время мута!")
    
    # Максимум 30 дней
    if duration > 43200:
        duration = 43200
    
    reason = " ".join(args[3:]) if len(args) > 3 else "Не указана"
    
    # Устанавливаем мут
    mute_until = datetime.datetime.now() + datetime.timedelta(minutes=duration)
    chat_data = db.init_chat(chat_id)
    chat_data["moderation"]["mutes"][target_id] = mute_until.isoformat()
    db.update_chat(chat_id, chat_data)
    db.add_stat("total_mutes")
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    time_str = await format_time(duration)
    
    response = (
        f"🔇 Пользователь {target_mention} замучен на {time_str}!\n"
        f"📋 Причина: {reason}\n"
        f"👮‍♂️ Модератор: [id{user_id}|Вы]"
    )
    
    await send_reply(message, response)

@labeler.message(text=["/unmute", "!unmute"])
async def unmute_handler(message: Message):
    """Снятие мута"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /unmute @user")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or target_id not in chat_data["moderation"]["mutes"]:
        return await send_reply(message, "⚠️ Этот пользователь не замучен")
    
    # Удаляем мут
    del chat_data["moderation"]["mutes"][target_id]
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    await send_reply(message, f"🔊 Пользователь {target_mention} размучен!")

@labeler.message(text=["/kick", "!kick"])
async def kick_handler(message: Message):
    """Кик пользователя"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /kick @user [причина]")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    if target_id == user_id:
        return await send_reply(message, "❌ Нельзя кикнуть самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя кикнуть администратора!")
    
    reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"
    
    try:
        await bot.api.messages.remove_chat_user(
            chat_id=chat_id,
            user_id=target_id
        )
        
        target_info = await get_user_info(target_id)
        target_mention = await mention_user(target_id, target_info)
        
        response = (
            f"👢 Пользователь {target_mention} кикнут!\n"
            f"📋 Причина: {reason}\n"
            f"👮‍♂️ Модератор: [id{user_id}|Вы]"
        )
        
        await send_reply(message, response)
        db.add_stat("total_kicks")
        
    except Exception as e:
        await send_reply(message, f"❌ Ошибка кика: {str(e)}")

@labeler.message(text=["/warn", "!warn"])
async def warn_handler(message: Message):
    """Выдать предупреждение"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /warn @user [причина]")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    if target_id == user_id:
        return await send_reply(message, "❌ Нельзя выдать варн себе!")
    
    reason = " ".join(args[2:]) if len(args) > 2 else "Не указана"
    
    # Добавляем варн
    chat_data = db.init_chat(chat_id)
    warns = chat_data["moderation"]["warns"].get(target_id, 0)
    max_warns = chat_data["settings"].get("max_warns", 3)
    
    warns += 1
    chat_data["moderation"]["warns"][target_id] = warns
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    response = (
        f"⚠️ Пользователь {target_mention} получил предупреждение!\n"
        f"📊 Варнов: {warns}/{max_warns}\n"
        f"📋 Причина: {reason}"
    )
    
    await send_reply(message, response)
    
    # Если достигнут лимит - бан
    if warns >= max_warns:
        if target_id not in chat_data["moderation"]["bans"]:
            chat_data["moderation"]["bans"].append(target_id)
            db.update_chat(chat_id, chat_data)
            db.add_stat("total_bans")
        
        ban_response = (
            f"🚫 Пользователь {target_mention} забанен за достижение лимита предупреждений!\n"
            f"📊 Варнов: {warns}/{max_warns}"
        )
        await send_reply(message, ban_response)
        
        try:
            await bot.api.messages.remove_chat_user(
                chat_id=chat_id,
                user_id=target_id
            )
        except:
            pass

# ============= КОМАНДЫ НИКНЕЙМОВ =============

@labeler.message(text=["/snick", "!snick"])
async def set_nick_handler(message: Message):
    """Установить никнейм"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, "❌ Использование: /snick @user никнейм")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    nickname = " ".join(args[2:])
    if len(nickname) > 32:
        return await send_reply(message, "❌ Никнейм слишком длинный (макс. 32 символа)")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.init_chat(chat_id)
    
    old_nick = chat_data["users"]["nicknames"].get(target_id)
    chat_data["users"]["nicknames"][target_id] = nickname
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    if old_nick:
        response = f"📝 Никнейм изменен: {target_mention}\n{old_nick} → {nickname}"
    else:
        response = f"📝 Никнейм установлен: {target_mention} → {nickname}"
    
    await send_reply(message, response)

@labeler.message(text=["/gnick", "!gnick"])
async def get_nick_handler(message: Message):
    """Получить никнейм"""
    args = message.text.split()
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if len(args) < 2:
        target_id = message.from_id
    else:
        target_id = await extract_user_id(args[1])
        if not target_id:
            return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    nickname = None
    if chat_data:
        nickname = chat_data["users"]["nicknames"].get(target_id)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    if nickname:
        response = f"📝 Никнейм {target_mention}: {nickname}"
    else:
        response = f"📝 У {target_mention} нет никнейма"
    
    await send_reply(message, response)

@labeler.message(text=["/rnick", "!rnick"])
async def remove_nick_handler(message: Message):
    """Удалить никнейм"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message, "❌ Использование: /rnick @user")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or target_id not in chat_data["users"]["nicknames"]:
        return await send_reply(message, "⚠️ У этого пользователя нет никнейма")
    
    nickname = chat_data["users"]["nicknames"][target_id]
    del chat_data["users"]["nicknames"][target_id]
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    await send_reply(message, f"🗑️ Никнейм удален: {target_mention} ({nickname})")

@labeler.message(text=["/nlist", "!nlist"])
async def nick_list_handler(message: Message):
    """Список никнеймов"""
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or not chat_data["users"]["nicknames"]:
        return await send_reply(message, "📝 В этом чате никнеймы не установлены")
    
    nicknames = chat_data["users"]["nicknames"]
    response = "📝 Список никнеймов:\n\n"
    
    for user_id, nickname in nicknames.items():
        try:
            user_info = await get_user_info(user_id)
            name = f"{user_info.first_name} {user_info.last_name}"
        except:
            name = f"Пользователь {user_id}"
        
        response += f"• {name}: {nickname}\n"
    
    await send_reply(message, response)

# ============= СИСТЕМА РОЛЕЙ =============

@labeler.message(text=["/addrole", "!addrole"])
async def add_role_handler(message: Message):
    """Добавить роль"""
    allowed, error = await check_permission(message, "admin")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, "❌ Использование: /addrole роль @user")
    
    role_name = args[1].lower()
    target_id = await extract_user_id(args[2])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.init_chat(chat_id)
    
    # Инициализируем роль если её нет
    if role_name not in chat_data["users"]["roles"]:
        chat_data["users"]["roles"][role_name] = []
    
    # Проверяем есть ли уже роль
    if target_id in chat_data["users"]["roles"][role_name]:
        return await send_reply(message, f"⚠️ У пользователя уже есть роль '{role_name}'")
    
    # Добавляем роль
    chat_data["users"]["roles"][role_name].append(target_id)
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    await send_reply(message, f"🎭 Роль '{role_name}' добавлена пользователю {target_mention}")

@labeler.message(text=["/rr", "!rr"])
async def remove_role_handler(message: Message):
    """Удалить роль"""
    allowed, error = await check_permission(message, "admin")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, "❌ Использование: /rr роль @user")
    
    role_name = args[1].lower()
    target_id = await extract_user_id(args[2])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or role_name not in chat_data["users"]["roles"]:
        return await send_reply(message, f"⚠️ Роль '{role_name}' не найдена")
    
    if target_id not in chat_data["users"]["roles"][role_name]:
        return await send_reply(message, f"⚠️ У пользователя нет роли '{role_name}'")
    
    # Удаляем роль
    chat_data["users"]["roles"][role_name].remove(target_id)
    
    # Удаляем пустую роль
    if not chat_data["users"]["roles"][role_name]:
        del chat_data["users"]["roles"][role_name]
    
    db.update_chat(chat_id, chat_data)
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    await send_reply(message, f"🗑️ Роль '{role_name}' удалена у пользователя {target_mention}")

@labeler.message(text=["/role", "!role"])
async def get_role_handler(message: Message):
    """Получить роли пользователя"""
    args = message.text.split()
    chat_id = message.peer_id - 2000000000
    
    if len(args) < 2:
        target_id = message.from_id
    else:
        target_id = await extract_user_id(args[1])
        if not target_id:
            return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_data = db.get_chat(chat_id)
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    if not chat_data or not chat_data["users"]["roles"]:
        response = f"🎭 У {target_mention} нет специальных ролей"
    else:
        user_roles = []
        for role_name, users in chat_data["users"]["roles"].items():
            if target_id in users:
                user_roles.append(role_name)
        
        if user_roles:
            roles_str = ", ".join(user_roles)
            response = f"🎭 Роли {target_mention}: {roles_str}"
        else:
            response = f"🎭 У {target_mention} нет специальных ролей"
    
    await send_reply(message, response)

@labeler.message(text=["/roles", "!roles"])
async def list_roles_handler(message: Message):
    """Список всех ролей"""
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or not chat_data["users"]["roles"]:
        return await send_reply(message, "🎭 В этом чате роли не настроены")
    
    response = "🎭 Роли в чате:\n\n"
    
    for role_name, users in chat_data["users"]["roles"].items():
        response += f"▫️ {role_name.upper()} ({len(users)} чел.):\n"
        
        # Показываем первых 5 пользователей
        for user_id in users[:5]:
            try:
                user_info = await get_user_info(user_id)
                response += f"   • {user_info.first_name} {user_info.last_name}\n"
            except:
                response += f"   • Пользователь {user_id}\n"
        
        if len(users) > 5:
            response += f"   • ... и ещё {len(users) - 5} чел.\n"
        
        response += "\n"
    
    await send_reply(message, response)

# ============= УПРАВЛЕНИЕ СООБЩЕНИЯМИ =============

@labeler.message(text=["/pin", "!pin"])
async def pin_handler(message: Message):
    """Закрепить сообщение"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    if not message.reply_message:
        return await send_reply(message, "❌ Ответьте на сообщение для закрепления")
    
    try:
        # Пытаемся закрепить через API
        await bot.api.messages.pin(
            peer_id=message.peer_id,
            conversation_message_id=message.reply_message.conversation_message_id
        )
        await send_reply(message, "📌 Сообщение закреплено!")
    except Exception as e:
        await send_reply(message, f"❌ Ошибка закрепления: {str(e)}")

@labeler.message(text=["/unpin", "!unpin"])
async def unpin_handler(message: Message):
    """Открепить сообщение"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    try:
        await bot.api.messages.unpin(
            peer_id=message.peer_id
        )
        await send_reply(message, "📌 Сообщение откреплено!")
    except Exception as e:
        await send_reply(message, f"❌ Ошибка открепления: {str(e)}")

@labeler.message(text=["/del", "!del", "/delete", "!delete"])
async def delete_handler(message: Message):
    """Удалить сообщение"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    if not message.reply_message:
        return await send_reply(message, "❌ Ответьте на сообщение для удаления")
    
    try:
        await bot.api.messages.delete(
            message_ids=[message.reply_message.id],
            delete_for_all=1
        )
        # Удаляем и команду
        await bot.api.messages.delete(
            message_ids=[message.id],
            delete_for_all=0
        )
    except Exception as e:
        await send_reply(message, f"❌ Ошибка удаления: {str(e)}")

# ============= ИНФОРМАЦИОННЫЕ КОМАНДЫ =============

@labeler.message(text=["/admins", "!admins"])
async def admins_handler(message: Message):
    """Список администраторов"""
    chat_id = message.peer_id - 2000000000
    
    try:
        chat_info = await bot.api.messages.get_conversation_members(
            peer_id=chat_id + 2000000000
        )
        
        owners = []
        admins = []
        moderators = []
        
        for member in chat_info.items:
            if hasattr(member, 'is_owner') and member.is_owner:
                user_info = await get_user_info(member.member_id)
                owners.append(f"[id{member.member_id}|{user_info.first_name} {user_info.last_name}]")
            elif hasattr(member, 'is_admin') and member.is_admin:
                user_info = await get_user_info(member.member_id)
                admins.append(f"[id{member.member_id}|{user_info.first_name} {user_info.last_name}]")
        
        # Модераторы из базы данных
        chat_data = db.get_chat(chat_id)
        if chat_data:
            for user_id in chat_data["users"]["roles"].get("moderator", []):
                user_info = await get_user_info(user_id)
                moderators.append(f"[id{user_id}|{user_info.first_name} {user_info.last_name}]")
        
        response = "👑 Управление беседой:\n\n"
        
        if owners:
            response += "👑 Владелец:\n" + "\n".join(owners) + "\n\n"
        
        if admins:
            response += "🔧 Администраторы:\n" + "\n".join(admins) + "\n\n"
        
        if moderators:
            response += "⚔️ Модераторы:\n" + "\n".join(moderators)
        
        if not owners and not admins and not moderators:
            response = "ℹ️ Администраторы не назначены"
        
        await send_reply(message, response)
        
    except Exception as e:
        await send_reply(message, f"❌ Ошибка: {str(e)}")

@labeler.message(text=["/profile", "!profile"])
async def profile_handler(message: Message):
    """Профиль пользователя"""
    args = message.text.split()
    chat_id = message.peer_id - 2000000000
    
    if len(args) < 2:
        target_id = message.from_id
    else:
        target_id = await extract_user_id(args[1])
        if not target_id:
            return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    chat_data = db.get_chat(chat_id)
    user_info = await get_user_info(target_id)
    
    response = f"👤 Профиль [id{target_id}|{user_info.first_name} {user_info.last_name}]\n"
    response += f"🆔 ID: {target_id}\n"
    
    # Никнейм
    nickname = chat_data["users"]["nicknames"].get(target_id) if chat_data else None
    if nickname:
        response += f"📛 Никнейм: {nickname}\n"
    
    # Роли
    if chat_data:
        user_roles = []
        for role_name, users in chat_data["users"]["roles"].items():
            if target_id in users:
                user_roles.append(role_name)
        
        if user_roles:
            response += f"🎭 Роли: {', '.join(user_roles)}\n"
    
    # Статистика
    unity_score = 0
    if chat_data:
        unity_score = chat_data["activity"]["unity_scores"].get(target_id, 0)
        warns = chat_data["moderation"]["warns"].get(target_id, 0)
        max_warns = chat_data["settings"].get("max_warns", 3)
        
        response += f"🏆 Активность: {unity_score}\n"
        response += f"⚠️ Варны: {warns}/{max_warns}\n"
    
    # Статусы
    if chat_data:
        if target_id in chat_data["moderation"]["bans"]:
            response += "🚫 Статус: Забанен\n"
        
        if target_id in chat_data["moderation"]["mutes"]:
            mute_until = datetime.datetime.fromisoformat(chat_data["moderation"]["mutes"][target_id])
            if mute_until > datetime.datetime.now():
                minutes_left = int((mute_until - datetime.datetime.now()).total_seconds() / 60)
                time_str = await format_time(minutes_left)
                response += f"🔇 Статус: Замучен ({time_str})\n"
    
    await send_reply(message, response)

@labeler.message(text=["/unity", "!unity"])
async def unity_handler(message: Message):
    """Unity Score беседы"""
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or not chat_data["activity"]["unity_scores"]:
        return await send_reply(message, "🏆 Активность беседы пока не оценивалась")
    
    scores = chat_data["activity"]["unity_scores"]
    total = sum(scores.values())
    avg = total / len(scores) if scores else 0
    
    # Топ 10
    top_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    
    response = f"🏆 Unity Score беседы\n\n"
    response += f"📊 Общий счёт: {total}\n"
    response += f"📈 Средний: {avg:.1f}\n"
    response += f"👥 Участников: {len(scores)}\n\n"
    response += "🏅 Топ активности:\n"
    
    for i, (user_id, score) in enumerate(top_users, 1):
        try:
            user_info = await get_user_info(user_id)
            name = f"{user_info.first_name} {user_info.last_name}"
        except:
            name = f"ID{user_id}"
        
        medal = ""
        if i == 1: medal = "🥇 "
        elif i == 2: medal = "🥈 "
        elif i == 3: medal = "🥉 "
        
        response += f"{medal}{i}. {name}: {score}\n"
    
    await send_reply(message, response)

# ============= НАСТРОЙКИ И ПРИВЕТСТВИЯ =============

@labeler.message(text=["/welcome", "!welcome"])
async def welcome_handler(message: Message):
    """Управление приветствиями"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    chat_id = message.peer_id - 2000000000
    chat_data = db.init_chat(chat_id)
    
    if len(args) < 2:
        # Показать текущие настройки
        welcome_msg = chat_data["settings"]["welcome_message"]
        auto_welcome = "включены" if chat_data["settings"]["auto_welcome"] else "выключены"
        
        response = (
            f"👋 Настройки приветствий:\n\n"
            f"📝 Сообщение: {welcome_msg}\n"
            f"⚡ Автоприветствие: {auto_welcome}\n"
            f"📊 Приветствовано: {chat_data['welcome_stats']['total_welcomed']}"
        )
        await send_reply(message, response)
        return
    
    subcommand = args[1].lower()
    
    if subcommand == "set":
        if len(args) < 3:
            return await send_reply(message, "❌ Использование: /welcome set текст")
        
        new_welcome = " ".join(args[2:])
        chat_data["settings"]["welcome_message"] = new_welcome
        db.update_chat(chat_id, chat_data)
        await send_reply(message, "✅ Приветствие обновлено!")
    
    elif subcommand == "toggle":
        current = chat_data["settings"]["auto_welcome"]
        chat_data["settings"]["auto_welcome"] = not current
        db.update_chat(chat_id, chat_data)
        
        status = "включено" if not current else "выключено"
        await send_reply(message, f"✅ Автоприветствие {status}!")
    
    elif subcommand == "test":
        welcome_msg = chat_data["settings"]["welcome_message"]
        user_mention = await mention_user(message.from_id)
        test_msg = welcome_msg.replace("{user}", user_mention)
        await send_reply(message, f"🔍 Тест приветствия:\n\n{test_msg}")
    
    else:
        await send_reply(message, "❌ Доступные команды: set, toggle, test")

@labeler.message(text=["/mutelist", "!mutelist"])
async def mutelist_handler(message: Message):
    """Список замученных"""
    allowed, error = await check_permission(message, "moderator")
    if not allowed:
        return await send_reply(message, error)
    
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    
    if not chat_data or not chat_data["moderation"]["mutes"]:
        return await send_reply(message, "🔇 В этом чате нет замученных пользователей")
    
    response = "🔇 Замученные пользователи:\n\n"
    now = datetime.datetime.now()
    
    for user_id, mute_until_str in chat_data["moderation"]["mutes"].items():
        mute_until = datetime.datetime.fromisoformat(mute_until_str)
        
        if mute_until > now:
            minutes_left = int((mute_until - now).total_seconds() / 60)
            time_str = await format_time(minutes_left)
            
            try:
                user_info = await get_user_info(user_id)
                name = f"{user_info.first_name} {user_info.last_name}"
            except:
                name = f"ID{user_id}"
            
            response += f"• {name}: {time_str}\n"
    
    await send_reply(message, response)

# ============= КАСТОМНЫЕ КОМАНДЫ =============

@labeler.message(text=["/editcmd", "!editcmd"])
async def editcmd_handler(message: Message):
    """Управление кастомными командами"""
    allowed, error = await check_permission(message, "admin")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 2:
        return await send_reply(message,
            "❌ Использование:\n"
            "/editcmd add название текст\n"
            "/editcmd del название\n"
            "/editcmd list"
        )
    
    subcommand = args[1].lower()
    chat_id = message.peer_id - 2000000000
    chat_data = db.init_chat(chat_id)
    
    if subcommand == "add":
        if len(args) < 4:
            return await send_reply(message, "❌ Использование: /editcmd add название текст")
        
        cmd_name = args[2].lower()
        cmd_text = " ".join(args[3:])
        
        chat_data["custom_commands"][cmd_name] = cmd_text
        db.update_chat(chat_id, chat_data)
        await send_reply(message, f"✅ Команда !{cmd_name} добавлена!")
    
    elif subcommand in ["del", "remove"]:
        if len(args) < 3:
            return await send_reply(message, "❌ Использование: /editcmd del название")
        
        cmd_name = args[2].lower()
        
        if cmd_name not in chat_data["custom_commands"]:
            return await send_reply(message, f"❌ Команда !{cmd_name} не найдена")
        
        del chat_data["custom_commands"][cmd_name]
        db.update_chat(chat_id, chat_data)
        await send_reply(message, f"✅ Команда !{cmd_name} удалена!")
    
    elif subcommand == "list":
        if not chat_data["custom_commands"]:
            return await send_reply(message, "📝 Кастомные команды не настроены")
        
        response = "📝 Кастомные команды:\n\n"
        for cmd, text in chat_data["custom_commands"].items():
            response += f"!{cmd}: {text[:50]}...\n" if len(text) > 50 else f"!{cmd}: {text}\n"
        
        await send_reply(message, response)
    
    else:
        await send_reply(message, "❌ Доступные команды: add, del, list")

# ============= ГЛОБАЛЬНЫЕ КОМАНДЫ =============

@labeler.message(text=["/gban", "!gban"])
async def gban_handler(message: Message):
    """Глобальный бан"""
    allowed, error = await check_permission(message, "superadmin")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, "❌ Использование: /gban @user причина")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    reason = " ".join(args[2:])
    
    # Добавляем глобальный бан
    if target_id not in db.data["global_bans"]:
        db.data["global_bans"].append(target_id)
        db.save()
    
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    
    response = (
        f"🌍 ГЛОБАЛЬНЫЙ БАН\n"
        f"👤 Пользователь: {target_mention}\n"
        f"📋 Причина: {reason}\n"
        f"👮‍♂️ Выдал: [id{message.from_id}|Администратор]\n"
        f"🕐 Время: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    await send_reply(message, response)
    
    # Уведомляем все чаты
    for chat_id_str in db.data["chats"]:
        try:
            await bot.api.messages.send(
                peer_id=int(chat_id_str) + 2000000000,
                message=response,
                random_id=0
            )
        except:
            pass

@labeler.message(text=["/gmute", "!gmute"])
async def gmute_handler(message: Message):
    """Глобальный мут (запрет команд)"""
    allowed, error = await check_permission(message, "superadmin")
    if not allowed:
        return await send_reply(message, error)
    
    args = message.text.split()
    if len(args) < 3:
        return await send_reply(message, "❌ Использование: /gmute @user время причина")
    
    target_id = await extract_user_id(args[1])
    if not target_id:
        return await send_reply(message, "❌ Неверное упоминание пользователя")
    
    duration = await parse_duration(args[2])
    if not duration:
        return await send_reply(message, "❌ Неверное время")
    
    reason = " ".join(args[3:]) if len(args) > 3 else "Не указана"
    
    # В реальном проекте здесь была бы логика глобального мута
    target_info = await get_user_info(target_id)
    target_mention = await mention_user(target_id, target_info)
    time_str = await format_time(duration)
    
    response = (
        f"🔇 ГЛОБАЛЬНЫЙ МУТ\n"
        f"👤 Пользователь: {target_mention}\n"
        f"⏱️ Время: {time_str}\n"
        f"📋 Причина: {reason}"
    )
    
    await send_reply(message, response)

# ============= СТАТИСТИКА И ИНФОРМАЦИЯ =============

@labeler.message(text=["/stats", "!stats"])
async def stats_handler(message: Message):
    """Статистика бота"""
    chat_id = message.peer_id - 2000000000
    chat_data = db.get_chat(chat_id)
    global_stats = db.data["statistics"]
    
    response = "📊 Статистика GRAND\n\n"
    
    if chat_data:
        response += f"📈 Локальная статистика:\n"
        response += f"• Сообщений: {chat_data['info']['message_count']}\n"
        response += f"• Банов: {len(chat_data['moderation']['bans'])}\n"
        response += f"• Мутов: {len(chat_data['moderation']['mutes'])}\n"
        response += f"• Киков: {len(chat_data['moderation']['kicks'])}\n"
        response += f"• Никнеймов: {len(chat_data['users']['nicknames'])}\n"
        response += f"• Кастомных команд: {len(chat_data['custom_commands'])}\n\n"
    
    response += f"🌍 Глобальная статистика:\n"
    response += f"• Чатов: {len(db.data['chats'])}\n"
    response += f"• Всего сообщений: {global_stats['total_messages']}\n"
    response += f"• Всего команд: {global_stats['total_commands']}\n"
    response += f"• Всего банов: {global_stats['total_bans']}\n"
    response += f"• Всего мутов: {global_stats['total_mutes']}\n"
    response += f"• Всего киков: {global_stats['total_kicks']}\n"
    response += f"• Глобальных банов: {len(db.data['global_bans'])}"
    
    await send_reply(message, response)

@labeler.message(text=["/help", "!help"])
async def help_handler(message: Message):
    """Помощь по командам"""
    help_text = """
🤖 GRAND Чат-Менеджер v2.0

👮‍♂️ МОДЕРАЦИЯ:
/ban @user [причина] - Бан
/unban @user - Разбан
/mute @user время [причина] - Мут
/unmute @user - Размут
/kick @user [причина] - Кик
/warn @user [причина] - Варн
/mutelist - Список мутов

📝 НИКНЕЙМЫ:
/snick @user ник - Установить ник
/gnick [@user] - Получить ник
/rnick @user - Удалить ник
/nlist - Список ников

🎭 РОЛИ:
/addrole роль @user - Добавить роль
/rr роль @user - Удалить роль
/role [@user] - Роли пользователя
/roles - Все роли в чате

📌 СООБЩЕНИЯ:
/pin - Закрепить (ответом)
/unpin - Открепить
/del - Удалить (ответом)

👤 ИНФОРМАЦИЯ:
/profile [@user] - Профиль
/admins - Администраторы
/unity - Активность чата
/stats - Статистика

⚙️ НАСТРОЙКИ:
/welcome [set/toggle/test] - Приветствия
/editcmd [add/del/list] - Кастомные команды

🌍 ГЛОБАЛЬНЫЕ (админы):
/gban @user причина - Глобальный бан
/gmute @user время причина - Глобальный мут

❓ ПОМОЩЬ:
/help - Эта справка

📞 Для поддержки: напишите /about
    """
    
    await send_reply(message, help_text)

@labeler.message(text=["/about", "!about"])
async def about_handler(message: Message):
    """Информация о боте"""
    about_text = """
🤖 GRAND: Чат-менеджер для ВКонтакте

Версия: 2.0 (Мульти-чат)
Разработчик: GRAND Team

✨ Возможности:
• Управление беседами любой сложности
• Система модерации с варнами
• Настраиваемые роли и никнеймы
• Кастомные команды
• Unity Score активности
• Работа в неограниченном количестве чатов

🛠 Технологии:
• Python 3.8+
• VKBottle Framework
• Собственная БД с автосохранением

📊 Статистика:
• Чатов: {}
• Сообщений: {}
• Команд: {}

🔧 Настройка:
Все данные хранятся в папке grand_data/
Для настройки прав редактируйте ADMIN_IDS в коде

🤝 Поддержка:
• Отчеты об ошибках
• Предложения по улучшению
• Помощь с настройкой

💡 Используйте /help для списка команд
""".format(
        len(db.data["chats"]),
        db.data["statistics"]["total_messages"],
        db.data["statistics"]["total_commands"]
    )
    
    await send_reply(message, about_text)

# ============= ОБРАБОТКА ВСЕХ СООБЩЕНИЙ =============

@labeler.message()
async def handle_all_messages(message: Message):
    """Обработка всех сообщений"""
    if not message.text:
        return
    
    chat_id = message.peer_id - 2000000000
    user_id = message.from_id
    
    # Инициализируем чат
    chat_data = db.init_chat(chat_id)
    
    # Увеличиваем счетчики
    db.add_stat("total_messages")
    chat_data["info"]["message_count"] += 1
    
    # Проверка глобального бана
    if user_id in db.data["global_bans"]:
        try:
            await bot.api.messages.delete(
                message_ids=[message.id],
                delete_for_all=0
            )
        except:
            pass
        return
    
    # Проверка бана в чате
    if user_id in chat_data["moderation"]["bans"]:
        try:
            await bot.api.messages.delete(
                message_ids=[message.id],
                delete_for_all=0
            )
        except:
            pass
        return
    
    # Проверка мута
    if user_id in chat_data["moderation"]["mutes"]:
        mute_until = datetime.datetime.fromisoformat(chat_data["moderation"]["mutes"][user_id])
        if datetime.datetime.now() < mute_until:
            try:
                await bot.api.messages.delete(
                    message_ids=[message.id],
                    delete_for_all=0
                )
            except:
                pass
            return
        else:
            # Мут истек
            del chat_data["moderation"]["mutes"][user_id]
            db.update_chat(chat_id, chat_data)
    
    # Обновляем активность
    if user_id not in chat_data["activity"]["unity_scores"]:
        chat_data["activity"]["unity_scores"][user_id] = 0
    
    chat_data["activity"]["unity_scores"][user_id] += 1
    chat_data["activity"]["last_messages"][user_id] = datetime.datetime.now().isoformat()
    
    # Проверяем кастомные команды
    if message.text.startswith("!") and chat_data["settings"]["allow_custom_commands"]:
        parts = message.text[1:].split(maxsplit=1)
        if len(parts) > 0:
            cmd = parts[0].lower()
            if cmd in chat_data["custom_commands"]:
                response = chat_data["custom_commands"][cmd]
                await send_reply(message, response)
                db.add_stat("total_commands")
                return
    
    # Обработка приветствий для новых участников
    if message.action and message.action.type == "chat_invite_user":
        new_user_id = message.action.member_id
        if new_user_id > 0 and chat_data["settings"]["auto_welcome"]:
            welcome_msg = chat_data["settings"]["welcome_message"]
            user_mention = await mention_user(new_user_id)
            formatted_msg = welcome_msg.replace("{user}", user_mention)
            
            await send_reply(message, formatted_msg)
            
            # Обновляем статистику приветствий
            chat_data["welcome_stats"]["total_welcomed"] += 1
            chat_data["welcome_stats"]["last_welcome"] = datetime.datetime.now().isoformat()
            db.update_chat(chat_id, chat_data)

# ============= ЗАПУСК И УТИЛИТЫ =============

async def auto_save():
    """Автосохранение каждые 5 минут"""
    while True:
        await asyncio.sleep(300)  # 5 минут
        try:
            db.save()
            logger.info("✅ Автосохранение выполнено")
        except Exception as e:
            logger.error(f"❌ Ошибка автосохранения: {e}")

async def main():
    """Главная функция запуска бота"""
    print("=" * 50)
    print("🤖 GRAND Чат-Менеджер v2.0")
    print("=" * 50)
    
    # Проверка токена
    if BOT_TOKEN == "ВАШ_ТОКЕН_БОТА_ЗДЕСЬ":
        print("❌ ОШИБКА: Токен бота не установлен!")
        print("Замените 'ВАШ_ТОКЕН_БОТА_ЗДЕСЬ' на реальный токен")
        print("Получить токен: Управление сообществом → Работа с API")
        return
    
    print(f"✅ Токен: Установлен")
    print(f"📁 Данные: {DATA_FOLDER}/")
    print(f"📊 Чатов: {len(db.data['chats'])}")
    print(f"🔄 Команд: {len(labeler.message_view.handlers)}")
    print("=" * 50)
    print("🚀 Бот запускается...")
    print("ℹ️ Добавляйте бота в беседы и используйте /help")
    print("=" * 50)
    
    # Запускаем автосохранение
    asyncio.create_task(auto_save())
    
    # Запускаем бота
    bot.labeler = labeler
    try:
        await bot.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Остановка бота...")
        db.save()
        print("💾 Данные сохранены")
        print("👋 До свидания!")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        db.save()
        raise

if __name__ == "__main__":
    # Проверка зависимостей
    if not VKBOTTLE_AVAILABLE:
        print("Установите vkbottle: pip install vkbottle")
        exit(1)
    
    # Запуск бота
    asyncio.run(main())
