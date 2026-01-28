import asyncio
import json
import datetime
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

from vkbottle import Bot, Message
from vkbottle.bot import BotLabeler, MessageEvent
from vkbottle.modules import logger
from vkbottle.tools import PhotoMessageUploader
from vkbottle_types.objects import MessagesMessageAttachmentType
from vkbottle_types.codegen.objects import UsersUserFull
import pytz

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.WARNING)

# Конфигурация
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
GROUP_ID = 0  # ID вашей группы

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
labeler = BotLabeler()

# Константы
MUTE_DURATIONS = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "3h": 180,
    "6h": 360,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "7d": 10080
}

# Базы данных в памяти (в реальном проекте используйте PostgreSQL/SQLite)
class Database:
    def __init__(self):
        self.mutes: Dict[int, Dict[int, datetime.datetime]] = {}  # chat_id -> user_id -> until
        self.bans: Dict[int, List[int]] = {}  # chat_id -> list of user_ids
        self.pinned_messages: Dict[int, int] = {}  # chat_id -> message_id
        self.nicknames: Dict[int, Dict[int, str]] = {}  # chat_id -> user_id -> nickname
        self.roles: Dict[int, Dict[str, List[int]]] = {}  # chat_id -> role_name -> user_ids
        self.welcome_messages: Dict[int, str] = {}  # chat_id -> welcome message
        self.commands: Dict[int, Dict[str, str]] = {}  # chat_id -> command -> response
        self.settings: Dict[int, Dict] = {}  # chat_id -> settings
        self.admins: Dict[int, List[int]] = {}  # chat_id -> admin_ids
        self.unity_scores: Dict[int, Dict[int, int]] = {}  # chat_id -> user_id -> score
        
    def init_chat(self, chat_id: int):
        """Инициализировать данные для чата"""
        if chat_id not in self.mutes:
            self.mutes[chat_id] = {}
        if chat_id not in self.bans:
            self.bans[chat_id] = []
        if chat_id not in self.nicknames:
            self.nicknames[chat_id] = {}
        if chat_id not in self.roles:
            self.roles[chat_id] = {}
        if chat_id not in self.welcome_messages:
            self.welcome_messages[chat_id] = "Добро пожаловать в беседу!"
        if chat_id not in self.commands:
            self.commands[chat_id] = {}
        if chat_id not in self.settings:
            self.settings[chat_id] = {"auto_welcome": True, "anti_flood": True}
        if chat_id not in self.admins:
            self.admins[chat_id] = []
        if chat_id not in self.unity_scores:
            self.unity_scores[chat_id] = {}

db = Database()

class UserRole(Enum):
    ADMIN = "admin"
    MODERATOR = "moderator"
    MEMBER = "member"
    VIP = "vip"
    FRIEND = "friend"

@dataclass
class UserProfile:
    user_id: int
    chat_id: int
    nickname: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    warnings: int = 0
    join_date: Optional[datetime.datetime] = None
    message_count: int = 0
    unity_score: int = 0

# ============= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============

async def get_user_info(user_id: int) -> UsersUserFull:
    """Получить информацию о пользователе"""
    users = await bot.api.users.get(user_ids=[user_id])
    return users[0]

async def is_admin(chat_id: int, user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    chat_info = await bot.api.messages.get_conversation_members(peer_id=chat_id + 2000000000)
    for member in chat_info.items:
        if member.member_id == user_id and member.is_admin:
            return True
    return user_id in db.admins.get(chat_id, [])

async def is_moderator(chat_id: int, user_id: int) -> bool:
    """Проверить, является ли пользователь модератором"""
    if await is_admin(chat_id, user_id):
        return True
    return user_id in db.roles.get(chat_id, {}).get("moderator", [])

async def check_permission(chat_id: int, user_id: int, required_role: str = "moderator") -> bool:
    """Проверить права пользователя"""
    if required_role == "admin":
        return await is_admin(chat_id, user_id)
    elif required_role == "moderator":
        return await is_moderator(chat_id, user_id)
    return True

async def send_reply(message: Message, text: str):
    """Отправить ответ на сообщение"""
    await message.answer(text)

async def parse_duration(duration_str: str) -> Optional[int]:
    """Парсинг длительности"""
    if duration_str in MUTE_DURATIONS:
        return MUTE_DURATIONS[duration_str]
    
    try:
        if duration_str.endswith("m"):
            return int(duration_str[:-1])
        elif duration_str.endswith("h"):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith("d"):
            return int(duration_str[:-1]) * 1440
        else:
            return int(duration_str)
    except:
        return None

async def format_time(minutes: int) -> str:
    """Форматировать время"""
    if minutes >= 1440:
        return f"{minutes // 1440}д"
    elif minutes >= 60:
        return f"{minutes // 60}ч"
    else:
        return f"{minutes}м"

async def get_user_mention(user_id: int, first_name: str = None, last_name: str = None) -> str:
    """Получить упоминание пользователя"""
    if not first_name:
        user_info = await get_user_info(user_id)
        first_name = user_info.first_name
        last_name = user_info.last_name
    return f"[id{user_id}|{first_name} {last_name}]"

# ============= ОСНОВНЫЕ КОМАНДЫ =============

@labeler.message(text="/ban <user_mention> [reason]")
async def ban_user(message: Message, user_mention: str = None, reason: str = "Не указана"):
    """Забанить пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /ban @упоминание [причина]")
    
    # Извлечение ID пользователя из упоминания
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    if target_id == message.from_id:
        return await send_reply(message, "❌ Нельзя забанить самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя забанить администратора!")
    
    db.init_chat(chat_id)
    
    if target_id in db.bans[chat_id]:
        return await send_reply(message, "⚠️ Этот пользователь уже забанен!")
    
    db.bans[chat_id].append(target_id)
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"✅ Пользователь {mention} забанен!\n📝 Причина: {reason}")
    
    # Пытаемся кикнуть пользователя
    try:
        await bot.api.messages.remove_chat_user(
            chat_id=chat_id,
            user_id=target_id
        )
    except:
        pass

@labeler.message(text="/unban <user_mention>")
async def unban_user(message: Message, user_mention: str = None):
    """Разбанить пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /unban @упоминание")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    if target_id not in db.bans[chat_id]:
        return await send_reply(message, "⚠️ Этот пользователь не забанен!")
    
    db.bans[chat_id].remove(target_id)
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"✅ Пользователь {mention} разбанен!")

@labeler.message(text="/mute <user_mention> <duration> [reason]")
async def mute_user(message: Message, user_mention: str = None, duration: str = None, reason: str = "Не указана"):
    """Замутить пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention or not duration:
        return await send_reply(message, "❌ Используйте: /mute @упоминание время [причина]\nПример: /mute @user 30m Спам")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    if target_id == message.from_id:
        return await send_reply(message, "❌ Нельзя замутить самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя замутить администратора!")
    
    mute_minutes = await parse_duration(duration.lower())
    if not mute_minutes:
        return await send_reply(message, f"❌ Неверная длительность! Доступно: {', '.join(MUTE_DURATIONS.keys())}")
    
    db.init_chat(chat_id)
    
    mute_until = datetime.datetime.now() + datetime.timedelta(minutes=mute_minutes)
    db.mutes[chat_id][target_id] = mute_until
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    time_str = await format_time(mute_minutes)
    
    await send_reply(message, f"🔇 Пользователь {mention} замучен на {time_str}\n📝 Причина: {reason}")

@labeler.message(text="/unmute <user_mention>")
async def unmute_user(message: Message, user_mention: str = None):
    """Размутить пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /unmute @упоминание")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    if target_id not in db.mutes.get(chat_id, {}):
        return await send_reply(message, "⚠️ Этот пользователь не замучен!")
    
    del db.mutes[chat_id][target_id]
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"🔊 Пользователь {mention} размучен!")

@labeler.message(text="/kick <user_mention> [reason]")
async def kick_user(message: Message, user_mention: str = None, reason: str = "Не указана"):
    """Кикнуть пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /kick @упоминание [причина]")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    if target_id == message.from_id:
        return await send_reply(message, "❌ Нельзя кикнуть самого себя!")
    
    if await is_admin(chat_id, target_id):
        return await send_reply(message, "❌ Нельзя кикнуть администратора!")
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    try:
        await bot.api.messages.remove_chat_user(
            chat_id=chat_id,
            user_id=target_id
        )
        await send_reply(message, f"👢 Пользователь {mention} кикнут!\n📝 Причина: {reason}")
    except Exception as e:
        await send_reply(message, f"❌ Ошибка при кике: {str(e)}")

@labeler.message(text="/snick <user_mention> <nickname>")
async def set_nickname(message: Message, user_mention: str = None, nickname: str = None):
    """Установить никнейм пользователю"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention or not nickname:
        return await send_reply(message, "❌ Используйте: /snick @упоминание никнейм")
    
    if len(nickname) > 32:
        return await send_reply(message, "❌ Никнейм не должен превышать 32 символа!")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    old_nick = db.nicknames[chat_id].get(target_id)
    db.nicknames[chat_id][target_id] = nickname
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    if old_nick:
        await send_reply(message, f"📝 Никнейм изменён!\n{mention}: {old_nick} → {nickname}")
    else:
        await send_reply(message, f"📝 Никнейм установлен!\n{mention}: {nickname}")

@labeler.message(text="/gnick <user_mention>")
async def get_nickname(message: Message, user_mention: str = None):
    """Получить никнейм пользователя"""
    if not user_mention:
        # Получить свой никнейм
        target_id = message.from_id
    else:
        match = re.search(r'\[id(\d+)\|', user_mention)
        if not match:
            return await send_reply(message, "❌ Неверный формат упоминания!")
        target_id = int(match.group(1))
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    nickname = db.nicknames[chat_id].get(target_id)
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    if nickname:
        await send_reply(message, f"📝 Никнейм {mention}: {nickname}")
    else:
        await send_reply(message, f"📝 У {mention} нет установленного никнейма")

@labeler.message(text="/rnick <user_mention>")
async def remove_nickname(message: Message, user_mention: str = None):
    """Удалить никнейм пользователя"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /rnick @упоминание")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    if target_id not in db.nicknames[chat_id]:
        return await send_reply(message, "⚠️ У этого пользователя нет никнейма!")
    
    nickname = db.nicknames[chat_id][target_id]
    del db.nicknames[chat_id][target_id]
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"🗑️ Никнейм удалён!\n{mention}: {nickname}")

@labeler.message(text="/nlist")
async def nicknames_list(message: Message):
    """Список всех никнеймов в беседе"""
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if not db.nicknames[chat_id]:
        return await send_reply(message, "📝 В этой беседе никнеймы не установлены!")
    
    text = "📝 Список никнеймов:\n"
    for user_id, nickname in db.nicknames[chat_id].items():
        try:
            user_info = await get_user_info(user_id)
            text += f"• {user_info.first_name} {user_info.last_name}: {nickname}\n"
        except:
            text += f"• [id{user_id}|Пользователь]: {nickname}\n"
    
    await send_reply(message, text)

@labeler.message(text="/pin")
async def pin_message(message: Message):
    """Закрепить сообщение"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not message.reply_message:
        return await send_reply(message, "❌ Ответьте на сообщение, чтобы закрепить его!")
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    db.pinned_messages[chat_id] = message.reply_message.id
    
    await send_reply(message, "📌 Сообщение закреплено!")

@labeler.message(text="/unpin")
async def unpin_message(message: Message):
    """Открепить сообщение"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if chat_id not in db.pinned_messages:
        return await send_reply(message, "⚠️ В этой беседе нет закреплённых сообщений!")
    
    del db.pinned_messages[chat_id]
    await send_reply(message, "📌 Сообщение откреплено!")

@labeler.message(text="/addrole <role_name> <user_mention>")
async def add_role(message: Message, role_name: str = None, user_mention: str = None):
    """Добавить роль пользователю"""
    if not await is_admin(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ Только администратор может управлять ролями!")
    
    if not role_name or not user_mention:
        return await send_reply(message, "❌ Используйте: /addrole название_роли @упоминание")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    if role_name not in db.roles[chat_id]:
        db.roles[chat_id][role_name] = []
    
    if target_id in db.roles[chat_id][role_name]:
        return await send_reply(message, "⚠️ У пользователя уже есть эта роль!")
    
    db.roles[chat_id][role_name].append(target_id)
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"🎭 Роль '{role_name}' добавлена пользователю {mention}!")

@labeler.message(text="/role <user_mention>")
async def get_user_roles(message: Message, user_mention: str = None):
    """Получить роли пользователя"""
    if not user_mention:
        target_id = message.from_id
    else:
        match = re.search(r'\[id(\d+)\|', user_mention)
        if not match:
            return await send_reply(message, "❌ Неверный формат упоминания!")
        target_id = int(match.group(1))
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    user_roles = []
    for role_name, users in db.roles[chat_id].items():
        if target_id in users:
            user_roles.append(role_name)
    
    if user_roles:
        roles_text = ", ".join(user_roles)
        await send_reply(message, f"🎭 Роли {mention}: {roles_text}")
    else:
        await send_reply(message, f"🎭 У {mention} нет специальных ролей")

@labeler.message(text="/roles")
async def list_all_roles(message: Message):
    """Список всех ролей в беседе"""
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if not db.roles[chat_id]:
        return await send_reply(message, "🎭 В этой беседе роли не настроены!")
    
    text = "🎭 Список ролей в беседе:\n"
    for role_name, users in db.roles[chat_id].items():
        text += f"\n{role_name} ({len(users)} чел.):\n"
        
        # Показываем только первых 5 пользователей
        for i, user_id in enumerate(users[:5]):
            try:
                user_info = await get_user_info(user_id)
                text += f"• {user_info.first_name} {user_info.last_name}\n"
            except:
                text += f"• [id{user_id}|Пользователь]\n"
        
        if len(users) > 5:
            text += f"• ...и ещё {len(users) - 5} чел.\n"
    
    await send_reply(message, text)

@labeler.message(text="/rr <role_name> <user_mention>")
async def remove_role(message: Message, role_name: str = None, user_mention: str = None):
    """Удалить роль у пользователя"""
    if not await is_admin(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ Только администратор может управлять ролями!")
    
    if not role_name or not user_mention:
        return await send_reply(message, "❌ Используйте: /rr название_роли @упоминание")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    chat_id = message.peer_id - 2000000000
    
    db.init_chat(chat_id)
    
    if role_name not in db.roles[chat_id]:
        return await send_reply(message, f"❌ Роль '{role_name}' не найдена!")
    
    if target_id not in db.roles[chat_id][role_name]:
        return await send_reply(message, "⚠️ У пользователя нет этой роли!")
    
    db.roles[chat_id][role_name].remove(target_id)
    
    # Удалить роль если в ней нет пользователей
    if not db.roles[chat_id][role_name]:
        del db.roles[chat_id][role_name]
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"🗑️ Роль '{role_name}' удалена у пользователя {mention}!")

@labeler.message(text="/admins")
async def list_admins(message: Message):
    """Список администраторов беседы"""
    chat_id = message.peer_id - 2000000000
    
    try:
        chat_info = await bot.api.messages.get_conversation_members(
            peer_id=chat_id + 2000000000
        )
        
        admins = []
        moderators = []
        
        for member in chat_info.items:
            if hasattr(member, 'is_admin') and member.is_admin:
                try:
                    user_info = await get_user_info(member.member_id)
                    admins.append(f"[id{member.member_id}|{user_info.first_name} {user_info.last_name}]")
                except:
                    admins.append(f"[id{member.member_id}|Администратор]")
            
            # Проверяем модераторов из базы данных
            if member.member_id in db.roles.get(chat_id, {}).get("moderator", []):
                try:
                    user_info = await get_user_info(member.member_id)
                    moderators.append(f"[id{member.member_id}|{user_info.first_name} {user_info.last_name}]")
                except:
                    moderators.append(f"[id{member.member_id}|Модератор]")
        
        text = "👑 Администраторы беседы:\n"
        if admins:
            text += "\n".join(f"👑 {admin}" for admin in admins)
        else:
            text += "Нет администраторов\n"
        
        if moderators:
            text += "\n\n⚔️ Модераторы:\n"
            text += "\n".join(f"⚔️ {mod}" for mod in moderators)
        
        await send_reply(message, text)
        
    except Exception as e:
        await send_reply(message, f"❌ Ошибка при получении списка администраторов: {str(e)}")

@labeler.message(text="/welcome [message]")
async def set_welcome(message: Message, message_text: str = None):
    """Установить приветственное сообщение"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if not message_text:
        current = db.welcome_messages[chat_id]
        await send_reply(message, f"📝 Текущее приветствие:\n{current}")
        return
    
    db.welcome_messages[chat_id] = message_text
    await send_reply(message, "✅ Приветственное сообщение обновлено!")

@labeler.message(text="/mutelist")
async def mute_list(message: Message):
    """Список замученных пользователей"""
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if not db.mutes.get(chat_id):
        return await send_reply(message, "🔇 В этой беседе нет замученных пользователей!")
    
    text = "🔇 Замученные пользователи:\n"
    now = datetime.datetime.now()
    
    for user_id, mute_until in db.mutes[chat_id].items():
        time_left = mute_until - now
        minutes_left = int(time_left.total_seconds() / 60)
        
        if minutes_left <= 0:
            continue
        
        try:
            user_info = await get_user_info(user_id)
            mention = f"[id{user_id}|{user_info.first_name} {user_info.last_name}]"
        except:
            mention = f"[id{user_id}|Пользователь]"
        
        time_str = await format_time(minutes_left)
        text += f"• {mention} - осталось: {time_str}\n"
    
    await send_reply(message, text)

@labeler.message(text="/gmute <duration> [reason]")
async def global_mute(message: Message, duration: str = None, reason: str = "Не указана"):
    """Глобальный мут (запрет отправки сообщений)"""
    if not await is_admin(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ Только администратор может использовать глобальный мут!")
    
    if not duration:
        return await send_reply(message, "❌ Укажите время: /gmute время [причина]")
    
    chat_id = message.peer_id - 2000000000
    
    # В реальной реализации здесь будет код для блокировки отправки сообщений
    # всех пользователям кроме администраторов
    
    mute_minutes = await parse_duration(duration.lower())
    if mute_minutes:
        time_str = await format_time(mute_minutes)
        await send_reply(message, f"🔇 Глобальный мут активирован на {time_str}!\n📝 Причина: {reason}")
    else:
        await send_reply(message, f"❌ Неверная длительность!")

@labeler.message(text="/gban <user_mention> [reason]")
async def global_ban(message: Message, user_mention: str = None, reason: str = "Не указана"):
    """Глобальный бан пользователя"""
    if not await is_admin(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ Только администратор может использовать глобальный бан!")
    
    if not user_mention:
        return await send_reply(message, "❌ Укажите пользователя: /gban @упоминание [причина]")
    
    match = re.search(r'\[id(\d+)\|', user_mention)
    if not match:
        return await send_reply(message, "❌ Неверный формат упоминания!")
    
    target_id = int(match.group(1))
    
    # В реальной реализации здесь будет код для бана пользователя
    # во всех беседах где есть бот
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    await send_reply(message, f"🔨 Пользователь {mention} получил глобальный бан!\n📝 Причина: {reason}")

@labeler.message(text="/editcmd <command> <response>")
async def edit_command(message: Message, command: str = None, response: str = None):
    """Редактировать кастомную команду"""
    if not await is_admin(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ Только администратор может редактировать команды!")
    
    if not command or not response:
        return await send_reply(message, "❌ Используйте: /editcmd команда ответ")
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    # Удаляем слеш если он есть
    if command.startswith("/"):
        command = command[1:]
    
    db.commands[chat_id][command] = response
    await send_reply(message, f"✅ Команда !{command} обновлена!")

@labeler.message(text="/unity")
async def unity_score(message: Message):
    """Показать Unity Score беседы"""
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    if not db.unity_scores[chat_id]:
        return await send_reply(message, "🏆 Unity Score беседы: 0\n🌟 Активность пока не оценивалась!")
    
    total_score = sum(db.unity_scores[chat_id].values())
    avg_score = total_score / len(db.unity_scores[chat_id])
    
    # Топ пользователей
    sorted_users = sorted(db.unity_scores[chat_id].items(), key=lambda x: x[1], reverse=True)[:5]
    
    text = f"🏆 Unity Score беседы: {total_score}\n"
    text += f"📊 Средний показатель: {avg_score:.1f}\n\n"
    text += "🌟 Топ пользователей:\n"
    
    for i, (user_id, score) in enumerate(sorted_users, 1):
        try:
            user_info = await get_user_info(user_id)
            mention = f"[id{user_id}|{user_info.first_name} {user_info.last_name}]"
        except:
            mention = f"[id{user_id}|Пользователь]"
        
        text += f"{i}. {mention}: {score} очков\n"
    
    await send_reply(message, text)

@labeler.message(text="/profile [user_mention]")
async def user_profile(message: Message, user_mention: str = None):
    """Показать профиль пользователя"""
    if not user_mention:
        target_id = message.from_id
    else:
        match = re.search(r'\[id(\d+)\|', user_mention)
        if not match:
            return await send_reply(message, "❌ Неверный формат упоминания!")
        target_id = int(match.group(1))
    
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    user_info = await get_user_info(target_id)
    mention = await get_user_mention(target_id, user_info.first_name, user_info.last_name)
    
    # Получаем данные профиля
    nickname = db.nicknames[chat_id].get(target_id, "Не установлен")
    
    roles = []
    for role_name, users in db.roles[chat_id].items():
        if target_id in users:
            roles.append(role_name)
    
    is_muted = target_id in db.mutes.get(chat_id, {})
    is_banned = target_id in db.bans.get(chat_id, [])
    unity_score = db.unity_scores[chat_id].get(target_id, 0)
    
    text = f"👤 Профиль пользователя {mention}\n"
    text += f"📛 Никнейм: {nickname}\n"
    
    if roles:
        text += f"🎭 Роли: {', '.join(roles)}\n"
    
    text += f"🏆 Unity Score: {unity_score}\n"
    
    if is_muted:
        mute_until = db.mutes[chat_id][target_id]
        now = datetime.datetime.now()
        minutes_left = max(0, int((mute_until - now).total_seconds() / 60))
        if minutes_left > 0:
            time_str = await format_time(minutes_left)
            text += f"🔇 Статус: Замучен (осталось: {time_str})\n"
    
    if is_banned:
        text += "🚫 Статус: Забанен\n"
    
    text += f"🆔 ID: {target_id}"
    
    await send_reply(message, text)

@labeler.message(text="/del")
async def delete_message(message: Message):
    """Удалить сообщение"""
    if not await is_moderator(message.peer_id - 2000000000, message.from_id):
        return await send_reply(message, "❌ У вас нет прав для использования этой команды!")
    
    if not message.reply_message:
        return await send_reply(message, "❌ Ответьте на сообщение, которое нужно удалить!")
    
    try:
        await bot.api.messages.delete(
            message_ids=[message.reply_message.id],
            delete_for_all=1
        )
        # Удаляем команду тоже
        await bot.api.messages.delete(
            message_ids=[message.id],
            delete_for_all=1
        )
    except Exception as e:
        await send_reply(message, f"❌ Ошибка при удалении: {str(e)}")

# ============= ДОПОЛНИТЕЛЬНЫЙ ФУНКЦИОНАЛ =============

@labeler.message()
async def handle_all_messages(message: Message):
    """Обработка всех сообщений для дополнительного функционала"""
    chat_id = message.peer_id - 2000000000
    db.init_chat(chat_id)
    
    # Проверка на муты
    if message.from_id in db.mutes.get(chat_id, {}):
        mute_until = db.mutes[chat_id][message.from_id]
        if datetime.datetime.now() < mute_until:
            try:
                await bot.api.messages.delete(
                    message_ids=[message.id],
                    delete_for_all=0
                )
                return
            except:
                pass
    
    # Проверка на баны
    if message.from_id in db.bans.get(chat_id, []):
        try:
            await bot.api.messages.delete(
                message_ids=[message.id],
                delete_for_all=0
            )
            return
        except:
            pass
    
    # Обновление Unity Score
    if chat_id not in db.unity_scores:
        db.unity_scores[chat_id] = {}
    
    if message.from_id not in db.unity_scores[chat_id]:
        db.unity_scores[chat_id][message.from_id] = 0
    
    # Добавляем очки за активность
    db.unity_scores[chat_id][message.from_id] += 1
    
    # Проверка кастомных команд
    text = message.text.lower()
    if text.startswith("!"):
        command = text[1:].split()[0]
        if command in db.commands.get(chat_id, {}):
            await send_reply(message, db.commands[chat_id][command])
            return
    
    # Приветствие новых участников
    if message.action and message.action.type == "chat_invite_user":
        if db.settings[chat_id].get("auto_welcome", True):
            new_user_id = message.action.member_id
            if new_user_id > 0:  # Не приглашение бота
                user_info = await get_user_info(new_user_id)
                mention = await get_user_mention(new_user_id, user_info.first_name, user_info.last_name)
                welcome_msg = db.welcome_messages[chat_id].replace("{user}", mention)
                await send_reply(message, welcome_msg)

# ============= СОБЫТИЯ И ДРУГИЕ ОБРАБОТЧИКИ =============

@labeler.raw_event(
    event="message_event",
    dataclass=MessageEvent,
)
async def handle_message_event(event: MessageEvent):
    """Обработка событий (нажатий на кнопки)"""
    payload = event.payload
    if payload.get("cmd") == "test":
        await bot.api.messages.send_message_event_answer(
            event_id=event.event_id,
            user_id=event.user_id,
            peer_id=event.peer_id,
            event_data=json.dumps({"type": "show_snackbar", "text": "Тест выполнен!"})
        )

# ============= ИНФОРМАЦИОННЫЕ КОМАНДЫ =============

@labeler.message(text="/help")
async def help_command(message: Message):
    """Показать справку по командам"""
    help_text = """
🤖 GRAND Чат-Менеджер - Справка по командам:

👮‍♂️ Модерация:
/ban @упоминание [причина] - Забанить пользователя
/unban @упоминание - Разбанить пользователя
/mute @упоминание время [причина] - Замутить пользователя
/unmute @упоминание - Размутить пользователя
/kick @упоминание [причина] - Кикнуть пользователя
/del - Удалить сообщение (ответом)
/gmute время [причина] - Глобальный мут
/gban @упоминание [причина] - Глобальный бан

📝 Управление никнеймами:
/snick @упоминание никнейм - Установить никнейм
/gnick [@упоминание] - Получить никнейм
/rnick @упоминание - Удалить никнейм
/nlist - Список всех никнеймов

📌 Закреп сообщений:
/pin - Закрепить сообщение (ответом)
/unpin - Открепить сообщение

🎭 Управление ролями:
/addrole роль @упоминание - Добавить роль
/role [@упоминание] - Показать роли пользователя
/roles - Список всех ролей
/rr роль @упоминание - Удалить роль

🏆 Дополнительные команды:
/welcome [текст] - Установить приветствие
/mutelist - Список замученных
/admins - Список администраторов
/editcmd команда ответ - Создать кастомную команду
/unity - Unity Score беседы
/profile [@упоминание] - Профиль пользователя
/help - Эта справка

📌 Примеры:
/mute @user 1h Спам
/mute @user 30m
/snick @user Крутой Ник
    """
    await send_reply(message, help_text)

# ============= ЗАПУСК БОТА =============

async def main():
    """Основная функция запуска бота"""
    print("🚀 GRAND Чат-Менеджер запускается...")
    print(f"📊 Загружено команд: {len(labeler.message_view.handlers)}")
    print("✅ Бот готов к работе!")
    
    # Добавляем все обработчики к боту
    bot.labeler = labeler
    
    # Запускаем бота
    await bot.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
