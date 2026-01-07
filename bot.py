import os
import json
import time
import datetime
import shutil
import base64
import asyncio
import zlib
import csv
from typing import Dict, List, Optional, Tuple, Any
import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Button, View
from pathlib import Path
from urllib.parse import urlparse
import aiohttp
import random

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

GUILD_ID = 1423020585881043016
BACKUP_CHANNEL_ID = 1457768411873415190
LOG_CHANNEL_ID = 1450910208325980335
APPROVAL_CHANNEL_ID = 1457805453127057428
WELCOME_CHANNEL_ID = 1457779107017261210
SUCCESS_CHANNEL_ID = 1424167988571017326
MONTHLY_REPORT_CHANNEL_ID = 1444051504444080139

ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
SECOND_MOD_ROLE_ID = 1454381506934865986
BUILDER_ROLE_ID = 1423344924262273157
APPROVED_ROLE_ID = 1423344924262273157

# Настройки ИИ оценки построек
AI_API_URL = "https://api-inference.huggingface.co/models/your-model"
AI_API_KEY = os.getenv("AI_API_KEY")
MIN_REWARD = 200
MAX_REWARD = 2000

# Настройки
APPROVAL_MESSAGE_EXPIRE_HOURS = 24

# Ежемесячное обнуление
MONTHLY_RESET_DAY = 26
ADMIN_NOTIFICATION_HOUR = 12
RESET_TIME_HOUR = 0

# Ограничения для Discord API
MAX_BACKUP_MESSAGES = 10
MAX_WELCOME_MESSAGES = 20

# Цвета для эмбедов
COLOR_SUCCESS = discord.Color.green()
COLOR_WARNING = discord.Color.orange()
COLOR_ERROR = discord.Color.red()
COLOR_INFO = discord.Color.blue()
COLOR_PURPLE = discord.Color.purple()
COLOR_GOLD = discord.Color.gold()

DATA_FOLDER = Path("data")
BACKUP_FOLDER = Path("backups")
MONTHLY_REPORTS_FOLDER = Path("monthly_reports")

DATA_FOLDER.mkdir(exist_ok=True)
BACKUP_FOLDER.mkdir(exist_ok=True)
MONTHLY_REPORTS_FOLDER.mkdir(exist_ok=True)

APPROVAL_MAP_FILE = DATA_FOLDER / "approval_map.json"
BALANCE_FILE = DATA_FOLDER / "balance.json"
HISTORY_FILE = DATA_FOLDER / "history.json"
CONFIG_FILE = DATA_FOLDER / "config.json"
BACKUP_CONFIG_FILE = DATA_FOLDER / "backup_config.json"
MONTHLY_RESET_TRACKER_FILE = DATA_FOLDER / "monthly_reset_tracker.json"
BUILD_SUBMISSIONS_FILE = DATA_FOLDER / "build_submissions.json"

BACKUP_SIGNATURE = "ashra_team_BACKUP_V2"

def fix_json_file_encoding(filepath: Path):
    """Исправляет кодировку JSON файлов"""
    if not filepath.exists():
        with filepath.open("w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)
        return
    
    try:
        content = filepath.read_text(encoding="utf-8-sig")
        if content.strip() == "":
            content = "{}"
        data = json.loads(content)
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка при исправлении кодировки {filepath}: {e}")
        try:
            with filepath.open("w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)
        except:
            pass

for filepath in [BALANCE_FILE, HISTORY_FILE, APPROVAL_MAP_FILE, CONFIG_FILE, 
                 BACKUP_CONFIG_FILE, MONTHLY_RESET_TRACKER_FILE, BUILD_SUBMISSIONS_FILE]:
    fix_json_file_encoding(filepath)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================

async def safe_send_message(channel, content=None, embed=None, view=None, **kwargs):
    """Безопасно отправляет сообщение с обработкой ошибок"""
    try:
        return await channel.send(content=content, embed=embed, view=view, **kwargs)
    except discord.errors.HTTPException as e:
        print(f"Ошибка при отправке сообщения: {e}")
        return None
    except Exception as e:
        print(f"Неизвестная ошибка при отправке сообщения: {e}")
        return None

async def safe_fetch_channel(channel_id):
    """Безопасно получает канал с обработкой ошибок"""
    try:
        channel = bot.get_channel(channel_id)
        if channel:
            return channel
        
        try:
            channel = await bot.fetch_channel(channel_id)
            return channel
        except discord.errors.NotFound:
            print(f"Канал с ID {channel_id} не найден")
            return None
        except discord.errors.Forbidden:
            print(f"Нет доступа к каналу с ID {channel_id}")
            return None
    except Exception as e:
        print(f"Ошибка при получении канала {channel_id}: {e}")
        return None

async def safe_history_fetch(channel, limit=50, delay_between_requests=0.5):
    """Безопасно получает историю сообщений с задержкой"""
    messages = []
    try:
        async for message in channel.history(limit=limit):
            messages.append(message)
            await asyncio.sleep(delay_between_requests)
    except discord.errors.HTTPException as e:
        print(f"Ошибка при получении истории сообщений: {e}")
    except Exception as e:
        print(f"Неизвестная ошибка при получении истории: {e}")
    
    return messages

def load_json_file_safe(filepath: Path, default=None):
    """Безопасно загружает JSON файл"""
    if default is None:
        default = {}
    
    if not filepath.exists():
        return default
    
    try:
        content = filepath.read_text(encoding="utf-8-sig")
        if content.strip() == "":
            return default
        
        # Попробуем исправить возможные проблемы с кодировкой
        if not content.startswith('{') and not content.startswith('['):
            # Попробуем удалить BOM и другие невидимые символы
            content = content.lstrip('\ufeff').strip()
        
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON в файле {filepath}: {e}")
        try:
            # Попробуем исправить распространенные проблемы
            content = filepath.read_text(encoding="utf-8", errors='ignore')
            content = content.replace('\r', '').replace('\t', ' ')
            
            # Попробуем найти начало JSON
            start_idx = content.find('{')
            if start_idx == -1:
                start_idx = content.find('[')
            
            if start_idx != -1:
                content = content[start_idx:]
                return json.loads(content)
        except:
            pass
        
        return default
    except Exception as e:
        print(f"Ошибка чтения файла {filepath}: {e}")
        return default

def save_json_file_safe(filepath: Path, data):
    """Безопасно сохраняет JSON файл"""
    try:
        # Создаем временный файл
        temp_file = filepath.with_suffix('.tmp')
        
        with temp_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        
        # Заменяем оригинальный файл
        if filepath.exists():
            backup_file = filepath.with_suffix('.bak')
            shutil.copy2(filepath, backup_file)
        
        shutil.move(temp_file, filepath)
        
        # Удаляем старый backup если существует
        backup_file = filepath.with_suffix('.bak')
        if backup_file.exists():
            backup_file.unlink()
        
        return True
    except Exception as e:
        print(f"Ошибка сохранения файла {filepath.name}: {e}")
        return False

def load_balance() -> Dict[str, int]:
    """Загружает данные о балансах"""
    return load_json_file_safe(BALANCE_FILE, {})

def save_balance(data: Dict[str, int]):
    """Сохраняет данные о балансах"""
    save_json_file_safe(BALANCE_FILE, data)

def load_history() -> Dict[str, List[Dict]]:
    """Загружает историю транзакций"""
    return load_json_file_safe(HISTORY_FILE, {})

def save_history(data: Dict[str, List[Dict]]):
    """Сохраняет историю транзакций"""
    save_json_file_safe(HISTORY_FILE, data)

def load_approval_data():
    """Загружает данные об одобрениях"""
    return load_json_file_safe(APPROVAL_MAP_FILE, {})

def save_approval_data(data: dict):
    """Сохраняет данные об одобрениях"""
    save_json_file_safe(APPROVAL_MAP_FILE, data)

def is_admin(user: discord.User | discord.Member) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user.id == ADMIN_USER_ID

def has_mod_rights(member: discord.Member) -> bool:
    """Проверяет, есть ли у пользователя права модератора"""
    if not isinstance(member, discord.Member):
        return False
    
    return (
        is_admin(member) or
        any(role.id == MOD_ROLE_ID for role in member.roles) or
        any(role.id == SECOND_MOD_ROLE_ID for role in member.roles)
    )

def has_builder_rights(member: discord.Member) -> bool:
    """Проверяет, есть ли у пользователя права строителя"""
    if not isinstance(member, discord.Member):
        return False
    
    return any(role.id == BUILDER_ROLE_ID for role in member.roles)

async def log_action(
    guild: discord.Guild,
    title: str,
    description: str,
    user: discord.Member | None = None,
    color: discord.Color = discord.Color.blurple()
):
    """Логирует действия в канал"""
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
    )

    if user:
        embed.set_footer(
            text=f"{user} | ID: {user.id}",
            icon_url=user.display_avatar.url if user.avatar else None
        )

    await channel.send(embed=embed)

def add_transaction(user_id: int, amount: int, message_link: str = "", reason: str = ""):
    """Добавляет транзакцию в историю"""
    try:
        balance_data = load_balance()
        uid = str(user_id)
        balance_data[uid] = balance_data.get(uid, 0) + amount
        save_balance(balance_data)
        
        history_data = load_history()
        if uid not in history_data:
            history_data[uid] = []
        
        transaction = {
            "amount": amount,
            "timestamp": time.time(),
            "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message_link": message_link,
            "reason": reason,
            "balance_after": balance_data[uid]
        }
        
        history_data[uid].append(transaction)
        if len(history_data[uid]) > 100:
            history_data[uid] = history_data[uid][-100:]
        
        save_history(history_data)
        
        print(f"Транзакция: {amount:+d} скиллов для {uid} | Причина: {reason[:50]}")
    except Exception as e:
        print(f"Ошибка при добавлении транзакции: {e}")

def get_balance(user_id: int) -> int:
    """Получает баланс пользователя"""
    return load_balance().get(str(user_id), 0)

def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    """Получает историю транзакций пользователя"""
    uid = str(user_id)
    history_data = load_history()
    if uid not in history_data:
        return []
    return history_data[uid][-limit:]

def find_approval_by_custom_id(data: dict, custom_id: str):
    """Находит заявку по custom ID"""
    for msg_id, info in data.items():
        if info["approve_cid"] == custom_id or info["deny_cid"] == custom_id:
            return msg_id, info
    return None, None

def is_valid_url(url: str) -> bool:
    """Проверяет валидность URL"""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except:
        return False

# ==============================================
# ФУНКЦИИ ДЛЯ ЕЖЕМЕСЯЧНОГО ОБНУЛЕНИЯ
# ==============================================

def load_monthly_reset_tracker() -> dict:
    """Загружает трекер ежемесячных сбросов"""
    return load_json_file_safe(MONTHLY_RESET_TRACKER_FILE, {"last_reset_month": None, "reset_history": []})

def save_monthly_reset_tracker(data: dict):
    """Сохраняет трекер ежемесячных сбросов"""
    save_json_file_safe(MONTHLY_RESET_TRACKER_FILE, data)

def load_build_submissions() -> dict:
    """Загружает данные об отправленных постройках"""
    return load_json_file_safe(BUILD_SUBMISSIONS_FILE, {"submissions": [], "user_builds": {}})

def save_build_submissions(data: dict):
    """Сохраняет данные об отправленных постройках"""
    save_json_file_safe(BUILD_SUBMISSIONS_FILE, data)

def add_build_submission(user_id: int, build_data: dict):
    """Добавляет информацию о постройке"""
    try:
        submissions_data = load_build_submissions()
        
        build_entry = {
            "user_id": str(user_id),
            "timestamp": time.time(),
            "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "build_data": build_data
        }
        submissions_data["submissions"].append(build_entry)
        
        if len(submissions_data["submissions"]) > 1000:
            submissions_data["submissions"] = submissions_data["submissions"][-1000:]
        
        uid = str(user_id)
        if uid not in submissions_data["user_builds"]:
            submissions_data["user_builds"][uid] = []
        
        submissions_data["user_builds"][uid].append(build_entry)
        
        if len(submissions_data["user_builds"][uid]) > 50:
            submissions_data["user_builds"][uid] = submissions_data["user_builds"][uid][-50:]
        
        save_build_submissions(submissions_data)
    except Exception as e:
        print(f"Ошибка при добавлении постройки: {e}")

def get_user_builds(user_id: int, limit: int = 20) -> List[dict]:
    """Получает список построек пользователя"""
    submissions_data = load_build_submissions()
    uid = str(user_id)
    
    if uid not in submissions_data["user_builds"]:
        return []
    
    return submissions_data["user_builds"][uid][-limit:]

async def perform_monthly_reset():
    """Выполняет ежемесячное обнуление балансов"""
    try:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Запуск ежемесячного обнуления балансов...")
        
        now = datetime.datetime.now()
        current_month = now.month
        current_year = now.year
        
        tracker = load_monthly_reset_tracker()
        
        if tracker.get("last_reset_month") == f"{current_year}-{current_month:02d}":
            print(f"Сброс за месяц {current_month}/{current_year} уже выполнен")
            return
        
        balance_data = load_balance()
        history_data = load_history()
        
        if not balance_data:
            print("Нет данных балансов для обнуления")
            return
        
        # Создаем резервную копию
        try:
            await create_enhanced_backup()
        except Exception as e:
            print(f"Ошибка при создании резервной копии: {e}")
        
        report_channel = await safe_fetch_channel(MONTHLY_REPORT_CHANNEL_ID)
        if not report_channel:
            print(f"Канал для отчетов не найден: {MONTHLY_REPORT_CHANNEL_ID}")
            return
        
        # Создаем основной отчет
        report_embed = discord.Embed(
            title="📊 ЕЖЕМЕСЯЧНЫЙ ОТЧЕТ",
            description=f"**Месяц: {now.strftime('%B %Y')}**\n"
                       f"**Дата обнуления: {now.strftime('%d.%m.%Y %H:%M')}**\n\n"
                       f"Дорогие строители! Вот и подошел к концу очередной месяц вашего творчества и усердного труда. "
                       f"Каждая ваша постройка - это шаг к совершенству и проявление вашего мастерства. "
                       f"Спасибо за вашу активность и вклад в развитие нашего сообщества!\n\n"
                       f"**Ваша награда за труды:** Полученные навыки и опыт, которые останутся с вами! 🎉",
            color=COLOR_GOLD,
            timestamp=discord.utils.utcnow()
        )
        
        total_skils_reset = 0
        user_reports = []
        users_reset = 0
        
        # Собираем информацию о пользователях
        for user_id_str, balance in balance_data.items():
            try:
                user_id = int(user_id_str)
                
                # Пропускаем админа
                if user_id == ADMIN_USER_ID:
                    continue
                
                # Пропускаем нулевые балансы
                if balance <= 0:
                    continue
                
                # Получаем информацию о пользователе
                user_name = f"Участник ({user_id})"
                user_mention = f"`{user_id}`"
                
                try:
                    guild = bot.get_guild(GUILD_ID)
                    if guild:
                        member = guild.get_member(user_id)
                        if member:
                            user_name = member.display_name
                            user_mention = member.mention
                except:
                    pass
                
                # Получаем постройки пользователя за месяц
                user_builds = get_user_builds(user_id)
                builds_links = []
                
                for build in user_builds[-5:]:
                    build_data = build.get("build_data", {})
                    approval_msg_id = build_data.get("approval_message_id")
                    if approval_msg_id:
                        builds_links.append(
                            f"[Постройка от {build['datetime'][:10]}](https://discord.com/channels/{GUILD_ID}/{APPROVAL_CHANNEL_ID}/{approval_msg_id})"
                        )
                
                # Добавляем в отчет
                user_report = {
                    "user_id": user_id,
                    "user_mention": user_mention,
                    "user_name": user_name,
                    "balance_reset": balance,
                    "builds_count": len(user_builds),
                    "builds_links": builds_links[:3]
                }
                user_reports.append(user_report)
                
                total_skils_reset += balance
                users_reset += 1
                
            except Exception as e:
                print(f"Ошибка при обработке пользователя {user_id_str}: {e}")
                continue
        
        # Сортируем по балансу (по убыванию)
        user_reports.sort(key=lambda x: x["balance_reset"], reverse=True)
        
        # Добавляем статистику в embed
        report_embed.add_field(
            name="📈 Общая статистика",
            value=f"**Всего обнулено:** {total_skils_reset} скиллов\n"
                  f"**Участников:** {users_reset}\n"
                  f"**Дата следующего обнуления:** {(now + datetime.timedelta(days=30)).strftime('%d.%m.%Y')}",
            inline=False
        )
        
        # Добавляем топ 10 участников
        if user_reports:
            top_users_text = ""
            for i, user_report in enumerate(user_reports[:10], 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                top_users_text += f"{medal} {user_report['user_mention']} - **{user_report['balance_reset']}** скиллов\n"
            
            report_embed.add_field(
                name="🏆 Топ участников месяца",
                value=top_users_text,
                inline=False
            )
        
        # Отправляем основной отчет
        report_message = await safe_send_message(report_channel, embed=report_embed)
        
        # Отправляем детализированные отчеты для каждого участника
        if user_reports:
            details_embed = discord.Embed(
                title="📋 Детали по участникам",
                description="Подробная информация о балансах и постройках каждого участника:",
                color=COLOR_INFO
            )
            
            # Разбиваем на части, если слишком много участников
            for i, user_report in enumerate(user_reports, 1):
                field_value = f"**Баланс обнулен:** {user_report['balance_reset']} скиллов\n"
                field_value += f"**Всего построек за месяц:** {user_report['builds_count']}\n"
                
                if user_report['builds_links']:
                    field_value += "**Последние постройки:**\n"
                    for link in user_report['builds_links']:
                        field_value += f"• {link}\n"
                
                # Добавляем поле (максимум 1024 символа на поле)
                if len(field_value) > 1000:
                    field_value = field_value[:997] + "..."
                
                details_embed.add_field(
                    name=f"{i}. {user_report['user_name']}",
                    value=field_value,
                    inline=False
                )
                
                # Если embed слишком большой, отправляем и создаем новый
                if len(details_embed) > 5500 or i % 8 == 0:
                    await safe_send_message(report_channel, embed=details_embed)
                    details_embed = discord.Embed(
                        title="📋 Детали по участникам (продолжение)",
                        color=COLOR_INFO
                    )
            
            # Отправляем оставшиеся детали
            if len(details_embed.fields) > 0:
                await safe_send_message(report_channel, embed=details_embed)
        
        # Выполняем обнуление балансов
        for user_report in user_reports:
            user_id = user_report["user_id"]
            balance = user_report["balance_reset"]
            
            try:
                # Обнуляем баланс
                balance_data[str(user_id)] = 0
                
                # Добавляем запись в историю
                if str(user_id) not in history_data:
                    history_data[str(user_id)] = []
                
                transaction = {
                    "amount": -balance,
                    "timestamp": time.time(),
                    "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "reason": f"Ежемесячное обнуление баланса ({now.strftime('%B %Y')})",
                    "balance_after": 0
                }
                history_data[str(user_id)].append(transaction)
                
                # Ограничиваем историю
                if len(history_data[str(user_id)]) > 100:
                    history_data[str(user_id)] = history_data[str(user_id)][-100:]
                    
            except Exception as e:
                print(f"Ошибка при обнулении баланса пользователя {user_id}: {e}")
                continue
        
        # Сохраняем изменения
        save_balance(balance_data)
        save_history(history_data)
        
        # Обновляем трекер сбросов
        tracker["last_reset_month"] = f"{current_year}-{current_month:02d}"
        tracker["reset_history"].append({
            "timestamp": time.time(),
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "users_reset": users_reset,
            "total_skils_reset": total_skils_reset,
            "report_message_id": report_message.id if report_message else None
        })
        
        # Ограничиваем историю сбросов
        if len(tracker["reset_history"]) > 24:
            tracker["reset_history"] = tracker["reset_history"][-24:]
        
        save_monthly_reset_tracker(tracker)
        
        # Уведомляем админа
        try:
            admin = await bot.fetch_user(ADMIN_USER_ID)
            if admin:
                admin_embed = discord.Embed(
                    title="⚠️ ЕЖЕМЕСЯЧНОЕ ОБНУЛЕНИЕ ВЫПОЛНЕНО",
                    description=f"Балансы участников были обнулены.",
                    color=COLOR_WARNING,
                    timestamp=discord.utils.utcnow()
                )
                
                admin_embed.add_field(
                    name="📊 Статистика",
                    value=f"**Дата:** {now.strftime('%d.%m.%Y %H:%M')}\n"
                          f"**Участников обнулено:** {users_reset}\n"
                          f"**Всего скиллов обнулено:** {total_skils_reset}\n"
                          f"**Канал отчета:** <#{MONTHLY_REPORT_CHANNEL_ID}>",
                    inline=False
                )
                
                if report_message:
                    admin_embed.add_field(
                        name="🔗 Ссылка на отчет",
                        value=f"[Перейти к отчету](https://discord.com/channels/{GUILD_ID}/{MONTHLY_REPORT_CHANNEL_ID}/{report_message.id})",
                        inline=False
                    )
                
                await admin.send(embed=admin_embed)
        except Exception as e:
            print(f"Ошибка при уведомлении админа: {e}")
        
        print(f"Ежемесячное обнуление выполнено: {users_reset} участников, {total_skils_reset} скиллов обнулено")
        
        # Логируем действие
        try:
            await log_action(
                bot.get_guild(GUILD_ID),
                "Ежемесячное обнуление балансов",
                f"**Месяц:** {now.strftime('%B %Y')}\n"
                f"**Участников обнулено:** {users_reset}\n"
                f"**Скиллов обнулено:** {total_skils_reset}",
                color=COLOR_GOLD
            )
        except Exception as e:
            print(f"Ошибка при логировании: {e}")
        
    except Exception as e:
        print(f"Ошибка при выполнении ежемесячного обнуления: {e}")
        import traceback
        traceback.print_exc()

def should_perform_reset() -> bool:
    """Проверяет, нужно ли выполнять обнуление"""
    now = datetime.datetime.now()
    
    # Проверяем день месяца (26-27)
    if now.day not in [MONTHLY_RESET_DAY, MONTHLY_RESET_DAY + 1]:
        return False
    
    # Проверяем время (после указанного часа)
    if now.hour < RESET_TIME_HOUR:
        return False
    
    # Проверяем, не выполнялся ли уже сброс в этом месяце
    tracker = load_monthly_reset_tracker()
    current_month_str = f"{now.year}-{now.month:02d}"
    
    return tracker.get("last_reset_month") != current_month_str

# ==============================================
# ФУНКЦИИ ДЛЯ ИИ ОЦЕНКИ ПОСТРОЙКИ
# ==============================================

async def evaluate_build_with_ai(screenshot_url: str, description: str) -> Dict[str, Any]:
    """Оценивает постройку с помощью ИИ"""
    try:
        if not AI_API_KEY or AI_API_URL == "https://api-inference.huggingface.co/models/your-model":
            print("API ключ ИИ не настроен, используется случайная оценка")
            return await evaluate_build_random(screenshot_url, description)
        
        async with aiohttp.ClientSession() as session:
            data = {
                "inputs": {
                    "image_url": screenshot_url,
                    "description": description
                }
            }
            
            headers = {
                "Authorization": f"Bearer {AI_API_KEY}",
                "Content-Type": "application/json"
            }
            
            async with session.post(AI_API_URL, json=data, headers=headers, timeout=30) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    ai_score = result.get("score", 5)
                    reward = int(MIN_REWARD + (ai_score - 1) * (MAX_REWARD - MIN_REWARD) / 9)
                    
                    return {
                        "reward": min(max(reward, MIN_REWARD), MAX_REWARD),
                        "ai_score": min(max(ai_score, 1), 10),
                        "comment": result.get("comment", "ИИ оценил вашу постройку.")[:500],
                        "criteria": result.get("criteria", ["Качество", "Креативность", "Сложность"])[:3],
                        "is_ai": True
                    }
                else:
                    print(f"Ошибка ИИ API: {response.status}")
                    return await evaluate_build_random(screenshot_url, description)
                    
    except asyncio.TimeoutError:
        print("Таймаут запроса к ИИ API")
        return await evaluate_build_random(screenshot_url, description)
    except Exception as e:
        print(f"Ошибка при оценке ИИ: {e}")
        return await evaluate_build_random(screenshot_url, description)

async def evaluate_build_random(screenshot_url: str, description: str) -> Dict[str, Any]:
    """Случайная оценка постройки"""
    try:
        criteria = ["Качество", "Креативность", "Сложность", "Детализация", "Оригинальность"]
        
        description_score = min(len(description) / 50, 1.0)
        random_score = random.uniform(0.3, 0.9)
        total_score = (description_score * 0.4 + random_score * 0.6) * 10
        
        reward = int(MIN_REWARD + (total_score - 1) * (MAX_REWARD - MIN_REWARD) / 9)
        reward = max(MIN_REWARD, min(MAX_REWARD, reward))
        
        if total_score >= 8:
            comment = "Отличная работа! Постройка впечатляет качеством исполнения."
        elif total_score >= 6:
            comment = "Хорошая постройка, есть потенциал для улучшения."
        elif total_score >= 4:
            comment = "Неплохая работа, но можно добавить больше деталей."
        else:
            comment = "Простая постройка, попробуйте добавить больше креативности."
        
        return {
            "reward": reward,
            "ai_score": round(total_score, 1),
            "comment": comment,
            "criteria": random.sample(criteria, 3),
            "is_ai": False
        }
    except Exception as e:
        print(f"Ошибка в случайной оценке: {e}")
        return {
            "reward": MIN_REWARD,
            "ai_score": 5,
            "comment": "Базовая оценка постройки.",
            "criteria": ["Качество", "Креативность", "Сложность"],
            "is_ai": False
        }

# ==============================================
# РЕЗЕРВНОЕ КОПИРОВАНИЕ
# ==============================================

class BackupManager:
    """Менеджер резервного копирования"""
    
    @staticmethod
    def create_backup_payload() -> Dict[str, Any]:
        """Создает структурированный payload для резервной копии"""
        payload = {
            "signature": BACKUP_SIGNATURE,
            "version": "2.0",
            "timestamp": datetime.datetime.now().isoformat(),
            "created_by": "ashra_team_bot",
            "data": {}
        }
        
        files_to_backup = [
            ("balance", BALANCE_FILE),
            ("history", HISTORY_FILE),
            ("approval_map", APPROVAL_MAP_FILE),
            ("build_submissions", BUILD_SUBMISSIONS_FILE),
            ("monthly_reset_tracker", MONTHLY_RESET_TRACKER_FILE)
        ]
        
        for name, filepath in files_to_backup:
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8")
                    payload["data"][name] = content
                    payload[f"{name}_size"] = len(content)
                except Exception as e:
                    print(f"Ошибка чтения файла {filepath}: {e}")
                    payload["data"][name] = ""
        
        payload["total_size"] = sum(len(str(v)) for v in payload["data"].values())
        return payload
    
    @staticmethod
    def compress_backup(payload: Dict) -> str:
        """Сжимает и кодирует резервную копию для Discord"""
        try:
            json_str = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            compressed = zlib.compress(json_str.encode('utf-8'))
            encoded = base64.b64encode(compressed).decode('utf-8')
            
            return encoded
        except Exception as e:
            print(f"Ошибка сжатия резервной копии: {e}")
            # Возвращаем несжатую версию
            return base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')
    
    @staticmethod
    def decompress_backup(encoded_data: str) -> Optional[Dict]:
        """Восстанавливает резервную копию из закодированной строки"""
        try:
            # Декодируем из base64
            compressed = base64.b64decode(encoded_data)
            
            # Пытаемся распаковать
            try:
                json_str = zlib.decompress(compressed).decode('utf-8')
            except:
                # Если не сжато, используем как есть
                json_str = compressed.decode('utf-8')
            
            # Парсим JSON
            payload = json.loads(json_str)
            
            # Проверяем сигнатуру
            if payload.get("signature") != BACKUP_SIGNATURE:
                print("Неверная сигнатура резервной копии")
                return None
            
            return payload
        except Exception as e:
            print(f"Ошибка декомпрессии резервной копии: {e}")
            return None
    
    @staticmethod
    def split_for_discord(data: str, max_chunk: int = 1900) -> List[str]:
        """Разделяет данные на части для отправки в Discord"""
        chunks = []
        
        # Если данные меньше максимального размера, возвращаем как есть
        if len(data) <= max_chunk:
            return [data]
        
        # Разделяем на равные части
        for i in range(0, len(data), max_chunk):
            chunks.append(data[i:i + max_chunk])
        
        return chunks
    
    @staticmethod
    def create_human_readable_backup() -> str:
        """Создает читабельную резервную копию для ручного восстановления"""
        try:
            balance_data = load_balance()
            history_data = load_history()
            submissions_data = load_build_submissions()
            
            output = [
                "=" * 60,
                "РЕЗЕРВНАЯ КОПИЯ ashra_team БОТА",
                f"Дата создания: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
                f"Сигнатура: {BACKUP_SIGNATURE}",
                "=" * 60,
                "",
                "1. БАЛАНСЫ ПОЛЬЗОВАТЕЛЕЙ:",
                "=" * 60
            ]
            
            if balance_data:
                for user_id, balance in sorted(balance_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    output.append(f"ID: {user_id} -> Баланс: {balance} скиллов")
            else:
                output.append("Нет данных о балансах")
            
            output.extend([
                "",
                "2. ИСТОРИЯ ТРАНЗАКЦИЙ (последние 3 на каждого пользователя):",
                "=" * 60
            ])
            
            if history_data:
                for user_id, transactions in history_data.items():
                    if transactions:
                        output.append(f"\nПользователь ID: {user_id}")
                        for i, tx in enumerate(reversed(transactions[-3:]), 1):
                            output.append(f"  {i}. {tx.get('datetime', 'N/A')}: {tx.get('amount', 0):+d} скиллов")
                            if tx.get('reason'):
                                output.append(f"     Причина: {tx['reason'][:50]}")
            else:
                output.append("Нет данных о транзакциях")
            
            output.extend([
                "",
                "3. ПОСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ:",
                "=" * 60
            ])
            
            if submissions_data.get("user_builds"):
                user_count = 0
                for user_id, builds in submissions_data["user_builds"].items():
                    if builds:
                        user_count += 1
                        output.append(f"\nПользователь ID: {user_id}")
                        output.append(f"  Всего построек: {len(builds)}")
                        for i, build in enumerate(reversed(builds[-2:]), 1):
                            build_data = build.get("build_data", {})
                            output.append(f"  Постройка {i}: {build['datetime']}")
                            if build_data.get("description"):
                                output.append(f"    Описание: {build_data['description'][:30]}...")
            else:
                output.append("Нет данных о постройках")
            
            output.extend([
                "",
                "=" * 60,
                "КОМАНДЫ ДЛЯ ВОССТАНОВЛЕНИЯ:",
                "=" * 60,
                "1. Восстановить через Discord: /restore_backup",
                "2. Восстановить из этого сообщения: скопируйте всё содержимое",
                "   ниже и используйте команду /restore_from_text",
                "",
                "КОНЕЦ РЕЗЕРВНОЙ КОПИИ",
                "=" * 60
            ])
            
            return '\n'.join(output)
        except Exception as e:
            print(f"Ошибка создания читаемой резервной копии: {e}")
            return f"Ошибка создания резервной копии: {e}"
    
    @staticmethod
    def create_simple_backup() -> str:
        """Создает упрощенную резервную копию в формате CSV"""
        try:
            balance_data = load_balance()
            history_data = load_history()
            
            lines = [
                "# ashra_team BOT BACKUP DATA",
                f"# Generated: {datetime.datetime.now().isoformat()}",
                f"# Signature: {BACKUP_SIGNATURE}",
                "",
                "[BALANCE]"
            ]
            
            # Балансы
            for user_id, balance in balance_data.items():
                lines.append(f"{user_id},{balance}")
            
            lines.extend([
                "",
                "[HISTORY]"
            ])
            
            # История
            for user_id, transactions in history_data.items():
                for tx in transactions[-10:]:  # Последние 10 транзакций
                    reason = tx.get('reason', '').replace(',', ';').replace('\n', ' ')
                    lines.append(f"{user_id},{tx.get('datetime', '')},{tx.get('amount', 0)},{reason}")
            
            return '\n'.join(lines)
        except Exception as e:
            print(f"Ошибка создания CSV резервной копии: {e}")
            return f"# ERROR: {e}"

async def create_enhanced_backup(interaction: discord.Interaction = None):
    """Создает улучшенную резервную копию"""
    try:
        if interaction:
            await interaction.response.defer(ephemeral=True, thinking=True)
        
        channel = await safe_fetch_channel(BACKUP_CHANNEL_ID)
        if not channel:
            raise Exception(f"Канал для резервных копий не найден (ID: {BACKUP_CHANNEL_ID})")
        
        # Удаляем старые резервные копии (оставляем только 10 последних)
        try:
            messages_to_delete = []
            messages = await safe_history_fetch(channel, limit=50)
            
            for message in messages:
                if message.author == bot.user and ("Резервная копия" in message.content or BACKUP_SIGNATURE in message.content):
                    messages_to_delete.append(message)
            
            if len(messages_to_delete) > 10:
                for msg in messages_to_delete[10:]:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.5)
                    except:
                        pass
        except Exception as e:
            print(f"Ошибка при удалении старых резервных копий: {e}")
        
        timestamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        backup_id = f"{int(time.time())}"
        
        # Создаем разные версии резервных копий
        payload = BackupManager.create_backup_payload()
        compressed_backup = BackupManager.compress_backup(payload)
        
        human_readable = BackupManager.create_human_readable_backup()
        simple_backup = BackupManager.create_simple_backup()
        
        # Отправляем основное сообщение
        backup_msg = await safe_send_message(
            channel,
            f"**📦 РЕЗЕРВНАЯ КОПИЯ ashra_team БОТА**\n"
            f"```\n"
            f"ID: {backup_id}\n"
            f"Дата: {timestamp}\n"
            f"Сигнатура: {BACKUP_SIGNATURE}\n"
            f"Размер данных: {payload.get('total_size', 0)} байт\n"
            f"```\n"
            f"Для восстановления используйте команды:\n"
            f"• `/restore_backup` - автоматическое восстановление\n"
            f"• `/restore_from_text` - ручное восстановление\n"
            f"• `/restore_from_text backup_id={backup_id}` - по ID\n\n"
            f"**Читаемая версия (начало):**\n"
            f"```\n{human_readable[:500]}...\n```"
        )
        
        if not backup_msg:
            raise Exception("Не удалось отправить основное сообщение резервной копии")
        
        # Отправляем сжатую версию частями
        if compressed_backup:
            chunks = BackupManager.split_for_discord(compressed_backup)
            for i, chunk in enumerate(chunks, 1):
                try:
                    await backup_msg.reply(f"**СЖАТАЯ КОПИЯ {i}/{len(chunks)}**\n```\n{chunk}\n```")
                    await asyncio.sleep(0.5)
                except:
                    # Если слишком большой чанк, разбиваем еще
                    sub_chunks = [chunk[j:j+1800] for j in range(0, len(chunk), 1800)]
                    for sub_i, sub_chunk in enumerate(sub_chunks, 1):
                        await backup_msg.reply(f"**СЖАТАЯ КОПИЯ {i}.{sub_i}**\n```\n{sub_chunk}\n```")
                        await asyncio.sleep(0.5)
        
        # Отправляем CSV версию
        if simple_backup:
            simple_chunks = BackupManager.split_for_discord(simple_backup)
            for i, chunk in enumerate(simple_chunks, 1):
                try:
                    await backup_msg.reply(f"**CSV КОПИЯ {i}/{len(simple_chunks)}**\n```\n{chunk}\n```")
                    await asyncio.sleep(0.5)
                except:
                    pass
        
        # Сохраняем информацию о резервной копии
        backup_config = load_json_file_safe(BACKUP_CONFIG_FILE, {})
        backup_config["last_backup_id"] = backup_msg.id
        backup_config["last_backup_time"] = time.time()
        backup_config["backup_id"] = backup_id
        save_json_file_safe(BACKUP_CONFIG_FILE, backup_config)
        
        # Отправляем подтверждение
        if interaction:
            try:
                embed = discord.Embed(
                    title="✅ Резервная копия создана",
                    description=f"Резервная копия успешно сохранена в канале <#{BACKUP_CHANNEL_ID}>",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                
                embed.add_field(name="ID сообщения", value=f"`{backup_msg.id}`", inline=True)
                embed.add_field(name="Backup ID", value=f"`{backup_id}`", inline=True)
                embed.add_field(name="Типы копий", value="Сжатая + Читаемая + CSV", inline=True)
                embed.set_footer(text="Восстановить: /restore_backup или /restore_from_text")
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.errors.InteractionResponded:
                pass
        
        print(f"Резервная копия создана: {backup_msg.id} (ID: {backup_id})")
        return backup_msg.id
        
    except Exception as e:
        print(f"Ошибка при создании резервной копии: {e}")
        if interaction:
            try:
                await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)
            except:
                pass
        return None

async def restore_backup_auto(interaction: discord.Interaction = None, backup_id: str = None):
    """Автоматически восстанавливает из резервной копии"""
    try:
        if interaction:
            await interaction.response.defer(ephemeral=True, thinking=True)
        
        channel = await safe_fetch_channel(BACKUP_CHANNEL_ID)
        if not channel:
            raise Exception("Канал для резервных копий не найден")
        
        backup_msg = None
        
        if backup_id:
            try:
                messages = await safe_history_fetch(channel, limit=MAX_BACKUP_MESSAGES)
                for message in messages:
                    if message.author == bot.user and f"ID: {backup_id}" in message.content:
                        backup_msg = message
                        break
                
                if not backup_msg:
                    raise Exception(f"Резервная копия с ID {backup_id} не найдена")
            except Exception as e:
                raise Exception(f"Ошибка при поиске резервной копии: {e}")
        else:
            try:
                messages = await safe_history_fetch(channel, limit=MAX_BACKUP_MESSAGES)
                for message in messages:
                    if message.author == bot.user and ("Резервная копия" in message.content or BACKUP_SIGNATURE in message.content):
                        backup_msg = message
                        break
            except Exception as e:
                raise Exception(f"Ошибка при поиске последней резервной копии: {e}")
        
        if not backup_msg:
            raise Exception("Резервные копии не найдены")
        
        # Собираем сжатые данные
        compressed_data = ""
        try:
            replies = await safe_history_fetch(channel, limit=50)
            for reply in replies:
                if reply.reference and reply.reference.message_id == backup_msg.id:
                    content = reply.content
                    if "СЖАТАЯ КОПИЯ" in content and "```" in content:
                        try:
                            code_block = content.split('```')[1].strip()
                            compressed_data += code_block
                        except:
                            continue
        except Exception as e:
            print(f"Ошибка при сборе сжатых данных: {e}")
        
        if not compressed_data:
            # Пробуем найти CSV версию
            csv_data = ""
            try:
                replies = await safe_history_fetch(channel, limit=50)
                for reply in replies:
                    if reply.reference and reply.reference.message_id == backup_msg.id:
                        content = reply.content
                        if "CSV КОПИЯ" in content and "```" in content:
                            try:
                                code_block = content.split('```')[1].strip()
                                csv_data += code_block + '\n'
                            except:
                                continue
            except Exception as e:
                print(f"Ошибка при поиске CSV данных: {e}")
            
            if csv_data:
                # Восстанавливаем из CSV
                await restore_from_csv_text(interaction, csv_data, backup_msg.id)
                return True
            else:
                raise Exception("Не удалось найти данные резервной копии")
        
        # Восстанавливаем из сжатых данных
        payload = BackupManager.decompress_backup(compressed_data)
        if not payload:
            raise Exception("Не удалось декомпрессировать резервную копию")
        
        # Сохраняем данные
        restored_files = 0
        for name, content in payload.get("data", {}).items():
            if content and content.strip():
                filepath = None
                if name == "balance":
                    filepath = BALANCE_FILE
                elif name == "history":
                    filepath = HISTORY_FILE
                elif name == "approval_map":
                    filepath = APPROVAL_MAP_FILE
                elif name == "build_submissions":
                    filepath = BUILD_SUBMISSIONS_FILE
                elif name == "monthly_reset_tracker":
                    filepath = MONTHLY_RESET_TRACKER_FILE
                
                if filepath:
                    try:
                        filepath.write_text(content, encoding="utf-8")
                        restored_files += 1
                    except Exception as e:
                        print(f"Ошибка сохранения файла {name}: {e}")
        
        # Исправляем кодировку
        for filepath in [BALANCE_FILE, HISTORY_FILE, APPROVAL_MAP_FILE, BUILD_SUBMISSIONS_FILE, MONTHLY_RESET_TRACKER_FILE]:
            fix_json_file_encoding(filepath)
        
        # Обновляем конфиг
        backup_config = load_json_file_safe(BACKUP_CONFIG_FILE, {})
        backup_config["last_restore_time"] = time.time()
        backup_config["last_restore_from"] = backup_msg.id
        save_json_file_safe(BACKUP_CONFIG_FILE, backup_config)
        
        # Отправляем уведомление
        if interaction:
            try:
                embed = discord.Embed(
                    title="✅ Данные восстановлены",
                    description=f"Данные успешно восстановлены из резервной копии",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                
                embed.add_field(name="ID сообщения", value=f"`{backup_msg.id}`", inline=True)
                embed.add_field(name="Дата создания", value=payload.get("timestamp", "Неизвестно"), inline=True)
                embed.add_field(name="Восстановлено файлов", value=str(restored_files), inline=True)
                
                await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.errors.InteractionResponded:
                pass
        
        print(f"Автовосстановление выполнено из {backup_msg.id}")
        return True
        
    except Exception as e:
        print(f"Ошибка автовосстановления: {e}")
        if interaction:
            try:
                await interaction.followup.send(f"❌ Ошибка автовосстановления: {str(e)}", ephemeral=True)
            except:
                pass
        return False

async def restore_from_text(interaction: discord.Interaction, text_data: str):
    """Восстанавливает из текстового представления"""
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # Проверяем формат
        if "[BALANCE]" in text_data and "[HISTORY]" in text_data:
            # CSV формат
            return await restore_from_csv_text(interaction, text_data, "text_input")
        elif "РЕЗЕРВНАЯ КОПИЯ ashra_team БОТА" in text_data:
            # Читаемый формат
            return await restore_from_human_text(interaction, text_data)
        else:
            await interaction.followup.send("❌ Неизвестный формат резервной копии", ephemeral=True)
            return False
        
    except Exception as e:
        print(f"Ошибка восстановления из текста: {e}")
        await interaction.followup.send(f"❌ Ошибка восстановления: {str(e)}", ephemeral=True)
        return False

async def restore_from_human_text(interaction: discord.Interaction, text_data: str):
    """Восстанавливает из читаемого текстового формата"""
    try:
        lines = text_data.split('\n')
        balance_data = {}
        history_data = {}
        current_section = None
        current_user = None
        
        for line in lines:
            line = line.strip()
            
            if "БАЛАНСЫ ПОЛЬЗОВАТЕЛЕЙ" in line:
                current_section = "balance"
                continue
            elif "ИСТОРИЯ ТРАНЗАКЦИЙ" in line:
                current_section = "history"
                continue
            elif "ПОСТРОЙКИ ПОЛЬЗОВАТЕЛЕЙ" in line:
                break
            elif "КОНЕЦ РЕЗЕРВНОЙ КОПИИ" in line:
                break
            
            if current_section == "balance" and "->" in line:
                if "ID:" in line and "Баланс:" in line:
                    parts = line.split("->")
                    if len(parts) == 2:
                        user_id = parts[0].split("ID:")[1].strip()
                        balance_str = parts[1].split("Баланс:")[1].split("скиллов")[0].strip()
                        try:
                            balance_data[user_id] = int(balance_str)
                        except:
                            pass
            
            elif current_section == "history":
                if "Пользователь ID:" in line:
                    user_id = line.split("Пользователь ID:")[1].strip()
                    current_user = user_id
                    history_data[user_id] = []
                elif current_user and line.startswith("  ") and ". " in line:
                    try:
                        tx_parts = line.strip().split(". ", 1)
                        if len(tx_parts) == 2:
                            tx_info = tx_parts[1]
                            if ":" in tx_info:
                                date_part, rest = tx_info.split(":", 1)
                                amount_str = ""
                                for char in rest:
                                    if char.isdigit() or char in '+-':
                                        amount_str += char
                                    elif amount_str and not char.isdigit():
                                        break
                                
                                try:
                                    amount = int(amount_str)
                                    transaction = {
                                        "amount": amount,
                                        "timestamp": time.time(),
                                        "datetime": date_part.strip(),
                                        "balance_after": balance_data.get(current_user, 0) + amount
                                    }
                                    history_data[current_user].append(transaction)
                                except:
                                    pass
                    except:
                        pass
        
        # Сохраняем данные
        save_balance(balance_data)
        save_history(history_data)
        
        # Отправляем отчет
        embed = discord.Embed(
            title="✅ Восстановление из текста",
            description="Данные успешно восстановлены из текстовой резервной копии",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="Балансов восстановлено", value=str(len(balance_data)), inline=True)
        embed.add_field(name="Историй пользователей", value=str(len(history_data)), inline=True)
        
        total_transactions = sum(len(txs) for txs in history_data.values())
        embed.add_field(name="Всего транзакций", value=str(total_transactions), inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return True
    except Exception as e:
        print(f"Ошибка восстановления из текста: {e}")
        await interaction.followup.send(f"❌ Ошибка восстановления: {str(e)}", ephemeral=True)
        return False

async def restore_from_csv_text(interaction: discord.Interaction, csv_data: str, source: str):
    """Восстанавливает из CSV формата"""
    try:
        balance_data = {}
        history_data = {}
        
        lines = csv_data.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            
            if not line or line.startswith('#'):
                continue
            
            if line == "[BALANCE]":
                current_section = "balance"
                continue
            elif line == "[HISTORY]":
                current_section = "history"
                continue
            
            if current_section == "balance":
                parts = line.split(',', 1)
                if len(parts) == 2:
                    user_id, balance_str = parts
                    try:
                        balance_data[user_id] = int(balance_str)
                    except:
                        pass
            
            elif current_section == "history":
                parts = line.split(',', 3)
                if len(parts) >= 3:
                    user_id, date_str, amount_str = parts[0], parts[1], parts[2]
                    reason = parts[3] if len(parts) > 3 else ""
                    
                    try:
                        amount = int(amount_str)
                        
                        if user_id not in history_data:
                            history_data[user_id] = []
                        
                        transaction = {
                            "amount": amount,
                            "timestamp": time.time(),
                            "datetime": date_str,
                            "reason": reason,
                            "balance_after": balance_data.get(user_id, 0) + amount
                        }
                        
                        history_data[user_id].append(transaction)
                    except:
                        pass
        
        # Сохраняем данные
        save_balance(balance_data)
        save_history(history_data)
        
        # Отправляем отчет
        embed = discord.Embed(
            title="✅ Восстановление из CSV",
            description="Данные успешно восстановлены из CSV резервной копии",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(name="Источник", value=source, inline=True)
        embed.add_field(name="Балансов восстановлено", value=str(len(balance_data)), inline=True)
        embed.add_field(name="Историй пользователей", value=str(len(history_data)), inline=True)
        
        total_transactions = sum(len(txs) for txs in history_data.values())
        embed.add_field(name="Всего транзакций", value=str(total_transactions), inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        return True
        
    except Exception as e:
        print(f"Ошибка восстановления из CSV: {e}")
        await interaction.followup.send(f"❌ Ошибка восстановления: {str(e)}", ephemeral=True)
        return False

# ==============================================
# СОБЫТИЕ ПРИ ПОЯВЛЕНИИ НОВОГО УЧАСТНИКА
# ==============================================

@bot.event
async def on_member_join(member: discord.Member):
    """Событие при присоединении нового участника"""
    try:
        if member.bot:
            return
        
        welcome_channel = await safe_fetch_channel(WELCOME_CHANNEL_ID)
        if not welcome_channel:
            print(f"Канал для подтверждения не найден (ID: {WELCOME_CHANNEL_ID})")
            return
        
        approved_role = member.guild.get_role(APPROVED_ROLE_ID)
        if approved_role and approved_role in member.roles:
            return
        
        embed = discord.Embed(
            title="👋 Новый участник",
            description=f"{member.mention} присоединился к серверу.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Информация об участнике",
            value=f"**Имя:** {member.display_name}\n"
                  f"**ID:** `{member.id}`\n"
                  f"**Аккаунт создан:** <t:{int(member.created_at.timestamp())}:R>",
            inline=False
        )
        
        embed.add_field(
            name="Статистика сервера",
            value=f"Участников: {member.guild.member_count}",
            inline=True
        )
        
        embed.set_thumbnail(url=member.display_avatar.url if member.avatar else None)
        embed.set_footer(text="Для подтверждения используйте кнопки ниже")
        
        view = discord.ui.View(timeout=None)
        
        timestamp = int(time.time())
        approve_cid = f"approve_member_{member.id}_{timestamp}"
        deny_cid = f"deny_member_{member.id}_{timestamp}"
        timeout_cid = f"timeout_member_{member.id}_{timestamp}"
        
        approve_button = discord.ui.Button(
            label="✅ Подтвердить",
            style=discord.ButtonStyle.success,
            custom_id=approve_cid,
            emoji="✅"
        )
        
        deny_button = discord.ui.Button(
            label="❌ Отклонить",
            style=discord.ButtonStyle.danger,
            custom_id=deny_cid,
            emoji="❌"
        )
        
        timeout_button = discord.ui.Button(
            label="⏰ Таймаут",
            style=discord.ButtonStyle.secondary,
            custom_id=timeout_cid,
            emoji="⏰"
        )
        
        async def approve_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут подтверждать участников",
                    ephemeral=True
                )
                return
            
            approved_role = member.guild.get_role(APPROVED_ROLE_ID)
            if approved_role:
                try:
                    await member.add_roles(approved_role, reason="Подтверждение модератором")
                    
                    embed.color = discord.Color.green()
                    embed.title = "✅ Участник подтвержден"
                    embed.add_field(
                        name="Модератор",
                        value=i.user.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Время",
                        value=f"<t:{int(time.time())}:R>",
                        inline=True
                    )
                    
                    try:
                        welcome_dm = discord.Embed(
                            title=f"Добро пожаловать на {member.guild.name}!",
                            description="Ваша заявка была одобрена модератором.\n\n"
                                      "**Доступные команды:**\n"
                                      "• `/balance` - Узнать свой баланс скиллов\n"
                                      "• `/help` - Получить список всех команд\n"
                                      "• `/submit_build` - Отправить постройку на проверку",
                            color=discord.Color.green()
                        )
                        if member.guild.icon:
                            welcome_dm.set_thumbnail(url=member.guild.icon.url)
                        await member.send(embed=welcome_dm)
                    except:
                        pass
                    
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await i.response.edit_message(embed=embed, view=view)
                    
                    await log_action(
                        member.guild,
                        "Участник подтвержден",
                        f"**Модератор:** {i.user.mention}\n"
                        f"**Участник:** {member.mention} (`{member.id}`)\n"
                        f"**Роль выдана:** {approved_role.mention}",
                        user=i.user,
                        color=discord.Color.green()
                    )
                    
                    print(f"Участник {member.id} подтвержден модератором {i.user.id}")
                    
                except Exception as e:
                    await i.response.send_message(
                        f"❌ Ошибка при выдаче роли: {e}",
                        ephemeral=True
                    )
            else:
                await i.response.send_message(
                    "❌ Роль для подтверждения не найдена",
                    ephemeral=True
                )
        
        async def deny_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут отклонять участников",
                    ephemeral=True
                )
                return
            
            modal = discord.ui.Modal(title="Причина отклонения")
            reason_input = discord.ui.TextInput(
                label="Причина отказа",
                style=discord.TextStyle.paragraph,
                placeholder="Укажите причину, по которой участник отклонен...",
                required=True,
                max_length=500
            )
            modal.add_item(reason_input)
            
            async def modal_callback(modal_interaction: discord.Interaction):
                reason = reason_input.value
                
                try:
                    await member.kick(reason=f"Отклонен модератором: {reason}")
                    
                    embed.color = discord.Color.red()
                    embed.title = "❌ Участник отклонен"
                    embed.add_field(
                        name="Модератор",
                        value=modal_interaction.user.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Причина",
                        value=reason[:200],
                        inline=False
                    )
                    embed.add_field(
                        name="Время",
                        value=f"<t:{int(time.time())}:R>",
                        inline=True
                    )
                    
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await modal_interaction.response.edit_message(embed=embed, view=view)
                    
                    await log_action(
                        modal_interaction.guild,
                        "Участник отклонен",
                        f"**Модератор:** {modal_interaction.user.mention}\n"
                        f"**Участник:** {member.mention} (`{member.id}`)\n"
                        f"**Причина:** {reason}",
                        user=modal_interaction.user,
                        color=discord.Color.red()
                    )
                    
                    print(f"Участник {member.id} отклонен модератором {modal_interaction.user.id}")
                    
                except discord.Forbidden:
                    await modal_interaction.response.send_message(
                        "❌ Недостаточно прав для кика участника",
                        ephemeral=True
                    )
                except Exception as e:
                    await modal_interaction.response.send_message(
                        f"❌ Ошибка при кике участника: {e}",
                        ephemeral=True
                    )
            
            modal.on_submit = modal_callback
            await i.response.send_modal(modal)
        
        async def timeout_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут ставить таймаут",
                    ephemeral=True
                )
                return
            
            modal = discord.ui.Modal(title="Настройки таймаута")
            
            duration_input = discord.ui.TextInput(
                label="Длительность (в часах)",
                placeholder="1, 2, 3, 6, 12, 24...",
                required=True,
                max_length=3
            )
            
            reason_input = discord.ui.TextInput(
                label="Причина таймаута",
                style=discord.TextStyle.paragraph,
                placeholder="Укажите причину таймаута...",
                required=True,
                max_length=500
            )
            
            modal.add_item(duration_input)
            modal.add_item(reason_input)
            
            async def modal_callback(modal_interaction: discord.Interaction):
                try:
                    duration = int(duration_input.value)
                    reason = reason_input.value
                    
                    if duration <= 0 or duration > 168:
                        await modal_interaction.response.send_message(
                            "❌ Некорректная длительность. Используйте от 1 до 168 часов.",
                            ephemeral=True
                        )
                        return
                    
                    timeout_duration = datetime.timedelta(hours=duration)
                    timeout_until = discord.utils.utcnow() + timeout_duration
                    
                    await member.timeout(timeout_until, reason=f"Таймаут от модератора: {reason}")
                    
                    embed.color = discord.Color.orange()
                    embed.title = "⏰ Участнику дан таймаут"
                    embed.add_field(
                        name="Модератор",
                        value=modal_interaction.user.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Длительность",
                        value=f"{duration} часов",
                        inline=True
                    )
                    embed.add_field(
                        name="Причина",
                        value=reason[:200],
                        inline=False
                    )
                    embed.add_field(
                        name="Закончится",
                        value=f"<t:{int(timeout_until.timestamp())}:R>",
                        inline=True
                    )
                    
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await modal_interaction.response.edit_message(embed=embed, view=view)
                    
                    await log_action(
                        modal_interaction.guild,
                        "Участнику дан таймаут",
                        f"**Модератор:** {modal_interaction.user.mention}\n"
                        f"**Участник:** {member.mention} (`{member.id}`)\n"
                        f"**Длительность:** {duration} часов\n"
                        f"**Причина:** {reason}",
                        user=modal_interaction.user,
                        color=discord.Color.orange()
                    )
                    
                    print(f"Участнику {member.id} дан таймаут на {duration} часов")
                    
                except ValueError:
                    await modal_interaction.response.send_message(
                        "❌ Некорректная длительность. Введите число.",
                        ephemeral=True
                    )
                except Exception as e:
                    await modal_interaction.response.send_message(
                        f"❌ Ошибка при установке таймаута: {e}",
                        ephemeral=True
                    )
            
            modal.on_submit = modal_callback
            await i.response.send_modal(modal)
        
        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        timeout_button.callback = timeout_callback
        
        view.add_item(approve_button)
        view.add_item(deny_button)
        view.add_item(timeout_button)
        
        message = await safe_send_message(welcome_channel, embed=embed, view=view)
        
        if message:
            print(f"Создана заявка для нового участника: {member.id} ({member.name})")
            
            approval_data = load_approval_data()
            approval_data[str(member.id)] = {
                "message_id": message.id,
                "created_at": time.time(),
                "status": "pending",
                "approve_cid": approve_cid,
                "deny_cid": deny_cid
            }
            save_approval_data(approval_data)
        
    except Exception as e:
        print(f"Ошибка при создании заявки на подтверждение: {e}")
        import traceback
        traceback.print_exc()

# ==============================================
# ОСНОВНЫЕ КОМАНДЫ БОТА
# ==============================================

@bot.tree.command(name="balance", description="Показать ваш баланс скиллов")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def balance_command(interaction: discord.Interaction):
    try:
        user_id = interaction.user.id
        balance_amount = get_balance(user_id)
        
        embed = discord.Embed(
            title=f"💰 Баланс скиллов",
            description=f"**{interaction.user.mention}**, ваш баланс:",
            color=COLOR_GOLD,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Текущий баланс",
            value=f"**{balance_amount}** скиллов",
            inline=False
        )
        
        history = get_history(user_id, limit=3)
        if history:
            history_text = ""
            for tx in reversed(history):
                sign = "+" if tx["amount"] > 0 else ""
                history_text += f"• {tx['datetime']}: {sign}{tx['amount']} скиллов"
                if tx.get('reason'):
                    history_text += f" ({tx['reason'][:30]})"
                history_text += "\n"
            
            embed.add_field(
                name="Последние операции",
                value=history_text or "Нет операций",
                inline=False
            )
        
        embed.set_footer(text=f"ID: {user_id}")
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде balance: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при получении баланса",
            ephemeral=True
        )

@bot.tree.command(name="give", description="Передать скиллы другому участнику")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник, которому передаются скиллы",
    amount="Количество скиллов",
    reason="Причина передачи"
)
async def give_command(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    try:
        if member.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Нельзя передавать скиллы самому себе!",
                ephemeral=True
            )
            return
        
        sender_balance = get_balance(interaction.user.id)
        if sender_balance < amount:
            await interaction.response.send_message(
                f"❌ Недостаточно скиллов! Ваш баланс: {sender_balance}",
                ephemeral=True
            )
            return
        
        if amount > 500 and not has_mod_rights(interaction.user):
            await interaction.response.send_message(
                "❌ Только модераторы могут передавать более 500 скиллов за раз",
                ephemeral=True
            )
            return
        
        add_transaction(interaction.user.id, -amount, reason=f"Перевод для {member.name}: {reason}")
        add_transaction(member.id, amount, reason=f"Перевод от {interaction.user.name}: {reason}")
        
        embed = discord.Embed(
            title="✅ Перевод выполнен",
            color=COLOR_SUCCESS,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Отправитель",
            value=f"{interaction.user.mention}\nБаланс: {get_balance(interaction.user.id)} (-{amount})",
            inline=True
        )
        
        embed.add_field(
            name="Получатель",
            value=f"{member.mention}\nБаланс: {get_balance(member.id)} (+{amount})",
            inline=True
        )
        
        if reason:
            embed.add_field(
                name="Причина",
                value=reason[:200],
                inline=False
            )
        
        embed.set_footer(text=f"ID операции: {int(time.time())}")
        
        await interaction.response.send_message(embed=embed)
        
        await log_action(
            interaction.guild,
            "Перевод скиллов",
            f"**Отправитель:** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"**Получатель:** {member.mention} (`{member.id}`)\n"
            f"**Сумма:** {amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_GOLD
        )
        
    except Exception as e:
        print(f"Ошибка в команде give: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при выполнении перевода",
            ephemeral=True
        )

@bot.tree.command(name="top", description="Топ участников по количеству скиллов")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    limit="Количество участников в топе (от 1 до 20)"
)
async def top_command(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
    try:
        await interaction.response.defer()
        
        balance_data = load_balance()
        if not balance_data:
            await interaction.followup.send("📭 Балансы участников пусты")
            return
        
        sorted_balance = sorted(balance_data.items(), key=lambda x: x[1], reverse=True)
        top_list = sorted_balance[:limit]
        
        embed = discord.Embed(
            title=f"🏆 Топ {len(top_list)} участников по скиллам",
            color=COLOR_GOLD,
            timestamp=discord.utils.utcnow()
        )
        
        description_lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        
        for i, (user_id, balance) in enumerate(top_list):
            try:
                member = await interaction.guild.fetch_member(int(user_id))
                mention = member.mention
                name = member.display_name
            except:
                mention = f"`{user_id}`"
                name = f"Участник ({user_id})"
            
            medal = medals[i] if i < len(medals) else f"{i+1}."
            description_lines.append(
                f"{medal} {mention} - **{balance}** скиллов"
            )
        
        embed.description = "\n".join(description_lines)
        
        total_skils = sum(balance for _, balance in top_list)
        embed.add_field(
            name="📊 Статистика",
            value=f"Всего скиллов в топе: **{total_skils}**\n"
                  f"Участников в рейтинге: **{len(balance_data)}**",
            inline=False
        )
        
        embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Ошибка в команде top: {e}")
        await interaction.followup.send(
            "❌ Произошла ошибка при получении топа",
            ephemeral=True
        )

@bot.tree.command(name="history", description="Показать историю ваших транзакций")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    limit="Количество записей (от 1 до 20)"
)
async def history_command(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
    try:
        user_id = interaction.user.id
        history = get_history(user_id, limit=limit)
        
        if not history:
            embed = discord.Embed(
                title="📝 История транзакций",
                description="У вас еще нет транзакций",
                color=COLOR_INFO
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"📝 История транзакций",
            description=f"Последние {len(history)} операций",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        history_text = ""
        total_income = 0
        total_outcome = 0
        
        for tx in reversed(history):
            sign = "+" if tx["amount"] > 0 else ""
            history_text += f"**{tx['datetime']}**\n"
            history_text += f"Сумма: `{sign}{tx['amount']}` скиллов\n"
            history_text += f"Баланс после: `{tx['balance_after']}` скиллов\n"
            
            if tx.get('reason'):
                history_text += f"Причина: {tx['reason'][:50]}\n"
            
            if tx.get('message_link') and is_valid_url(tx['message_link']):
                history_text += f"[Ссылка на сообщение]({tx['message_link']})\n"
            
            history_text += "\n"
            
            if tx["amount"] > 0:
                total_income += tx["amount"]
            else:
                total_outcome += abs(tx["amount"])
        
        if len(history_text) > 1024:
            chunks = [history_text[i:i+1024] for i in range(0, len(history_text), 1024)]
            embed.add_field(name="История операций", value=chunks[0], inline=False)
            for i, chunk in enumerate(chunks[1:], 1):
                embed.add_field(name=f"Продолжение {i}", value=chunk, inline=False)
        else:
            embed.add_field(name="Операции", value=history_text or "Нет операций", inline=False)
        
        embed.add_field(
            name="📊 Статистика",
            value=f"Всего получено: **+{total_income}** скиллов\n"
                  f"Всего потрачено: **-{total_outcome}** скиллов\n"
                  f"Текущий баланс: **{get_balance(user_id)}** скиллов",
            inline=False
        )
        
        embed.set_footer(text=f"ID: {user_id}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде history: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при получении истории",
            ephemeral=True
        )

@bot.tree.command(name="add_skils", description="Добавить скиллы участнику (модераторы)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник, которому добавляются скиллы",
    amount="Количество скиллов",
    reason="Причина добавления"
)
async def add_skils_command(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    try:
        if not has_mod_rights(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /add_skils",
                user=interaction.user,
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
        
        if member.id == interaction.user.id and not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Нельзя добавлять скиллы себе!",
                ephemeral=True
            )
            return
        
        add_transaction(
            member.id, 
            amount, 
            reason=f"Добавлено модератором {interaction.user.name}: {reason}"
        )
        
        embed = discord.Embed(
            title="✅ Скиллы добавлены",
            color=COLOR_SUCCESS,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Участник",
            value=f"{member.mention}\nНовый баланс: **{get_balance(member.id)}** скиллов",
            inline=False
        )
        
        embed.add_field(
            name="Добавлено",
            value=f"**+{amount}** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Модератор",
            value=interaction.user.mention,
            inline=True
        )
        
        if reason:
            embed.add_field(
                name="Причина",
                value=reason[:200],
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        await log_action(
            interaction.guild,
            "Добавление скиллов",
            f"**Модератор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сумма:** +{amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_SUCCESS
        )
        
    except Exception as e:
        print(f"Ошибка в команде add_skils: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при добавлении скиллов",
            ephemeral=True
        )

@bot.tree.command(name="remove_skils", description="Убрать скиллы у участника (модераторы)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник, у которого убираются скиллы",
    amount="Количество скиллов",
    reason="Причина"
)
async def remove_skils_command(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    try:
        if not has_mod_rights(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /remove_skils",
                user=interaction.user,
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
        
        current_balance = get_balance(member.id)
        if current_balance < amount:
            await interaction.response.send_message(
                f"❌ У участника недостаточно скиллов! Баланс: {current_balance}",
                ephemeral=True
            )
            return
        
        add_transaction(
            member.id, 
            -amount, 
            reason=f"Убрано модератором {interaction.user.name}: {reason}"
        )
        
        embed = discord.Embed(
            title="✅ Скиллы убраны",
            color=COLOR_WARNING,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Участник",
            value=f"{member.mention}\nНовый баланс: **{get_balance(member.id)}** скиллов",
            inline=False
        )
        
        embed.add_field(
            name="Убрано",
            value=f"**-{amount}** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Модератор",
            value=interaction.user.mention,
            inline=True
        )
        
        if reason:
            embed.add_field(
                name="Причина",
                value=reason[:200],
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        await log_action(
            interaction.guild,
            "Удаление скиллов",
            f"**Модератор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сумма:** -{amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_WARNING
        )
        
    except Exception as e:
        print(f"Ошибка в команде remove_skils: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при удалении скиллов",
            ephemeral=True
        )

@bot.tree.command(name="set_balance", description="Установить баланс участника (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник",
    amount="Новый баланс",
    reason="Причина"
)
async def set_balance_command(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 0, 1000000],
    reason: str = ""
):
    try:
        if not is_admin(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /set_balance",
                user=interaction.user,
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
        
        current_balance = get_balance(member.id)
        difference = amount - current_balance
        
        balance_data = load_balance()
        balance_data[str(member.id)] = amount
        save_balance(balance_data)
        
        add_transaction(
            member.id,
            difference,
            reason=f"Баланс установлен администратором {interaction.user.name}: {reason}"
        )
        
        embed = discord.Embed(
            title="✅ Баланс установлен",
            color=COLOR_PURPLE,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Участник",
            value=member.mention,
            inline=True
        )
        
        embed.add_field(
            name="Старый баланс",
            value=f"**{current_balance}** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Новый баланс",
            value=f"**{amount}** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Изменение",
            value=f"**{difference:+d}** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Администратор",
            value=interaction.user.mention,
            inline=True
        )
        
        if reason:
            embed.add_field(
                name="Причина",
                value=reason[:200],
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        await log_action(
            interaction.guild,
            "Установка баланса",
            f"**Администратор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Старый баланс:** {current_balance}\n"
            f"**Новый баланс:** {amount}\n"
            f"**Изменение:** {difference:+d}\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_PURPLE
        )
        
    except Exception as e:
        print(f"Ошибка в команде set_balance: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при установке баланса",
            ephemeral=True
        )

@bot.tree.command(name="reset_balance", description="Сбросить баланс участника (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник",
    reason="Причина сброса"
)
async def reset_balance_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = ""
):
    try:
        if not is_admin(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /reset_balance",
                user=interaction.user,
                color=COLOR_ERROR
            )
            return await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
        
        current_balance = get_balance(member.id)
        
        if current_balance == 0:
            await interaction.response.send_message(
                f"✅ У участника {member.mention} и так нулевой баланс",
                ephemeral=True
            )
            return
        
        balance_data = load_balance()
        balance_data[str(member.id)] = 0
        save_balance(balance_data)
        
        add_transaction(
            member.id,
            -current_balance,
            reason=f"Баланс сброшен администратором {interaction.user.name}: {reason}"
        )
        
        embed = discord.Embed(
            title="⚠️ Баланс сброшен",
            color=COLOR_ERROR,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Участник",
            value=member.mention,
            inline=True
        )
        
        embed.add_field(
            name="Сброшено скиллов",
            value=f"**{current_balance}**",
            inline=True
        )
        
        embed.add_field(
            name="Новый баланс",
            value="**0** скиллов",
            inline=True
        )
        
        embed.add_field(
            name="Администратор",
            value=interaction.user.mention,
            inline=True
        )
        
        if reason:
            embed.add_field(
                name="Причина",
                value=reason[:200],
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
        
        await log_action(
            interaction.guild,
            "Сброс баланса",
            f"**Администратор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сброшено:** {current_balance} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_ERROR
        )
        
    except Exception as e:
        print(f"Ошибка в команде reset_balance: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при сбросе баланса",
            ephemeral=True
        )

# ==============================================
# КОМАНДЫ РЕЗЕРВНОГО КОПИРОВАНИЯ
# ==============================================

@bot.tree.command(name="backup", description="Создать резервную копию (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def backup_command(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /backup",
            user=interaction.user,
            color=COLOR_ERROR
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await create_enhanced_backup(interaction)

@bot.tree.command(name="restore_backup", description="Восстановить из резервной копии (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    backup_id="ID резервной копии (оставьте пустым для последней)",
    message_id="ID сообщения с резервной копией"
)
async def restore_backup_command(
    interaction: discord.Interaction,
    backup_id: str = None,
    message_id: str = None
):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /restore_backup",
            user=interaction.user,
            color=COLOR_ERROR
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if message_id:
        try:
            channel = await safe_fetch_channel(BACKUP_CHANNEL_ID)
            if not channel:
                raise Exception("Канал не найден")
            
            backup_msg = await channel.fetch_message(int(message_id))
            
            compressed_data = ""
            try:
                replies = await safe_history_fetch(channel, limit=30)
                for reply in replies:
                    if reply.reference and reply.reference.message_id == backup_msg.id:
                        content = reply.content
                        if "СЖАТАЯ КОПИЯ" in content and "```" in content:
                            try:
                                code_block = content.split('```')[1].strip()
                                compressed_data += code_block
                            except:
                                continue
            except Exception as e:
                print(f"Ошибка при сборе сжатых данных: {e}")
            
            if not compressed_data:
                await interaction.followup.send("❌ Не найдены сжатые данные в этом сообщении", ephemeral=True)
                return
            
            payload = BackupManager.decompress_backup(compressed_data)
            if not payload:
                await interaction.followup.send("❌ Не удалось декомпрессировать данные", ephemeral=True)
                return
            
            restored_files = 0
            for name, content in payload.get("data", {}).items():
                if content and content.strip():
                    filepath = None
                    if name == "balance":
                        filepath = BALANCE_FILE
                    elif name == "history":
                        filepath = HISTORY_FILE
                    
                    if filepath:
                        try:
                            filepath.write_text(content, encoding="utf-8")
                            restored_files += 1
                        except:
                            pass
            
            embed = discord.Embed(
                title="✅ Восстановлено",
                description=f"Данные восстановлены из сообщения {message_id}",
                color=COLOR_SUCCESS
            )
            embed.add_field(name="Восстановлено файлов", value=str(restored_files), inline=True)
            embed.add_field(name="Дата копии", value=payload.get("timestamp", "Неизвестно"), inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)
            return
    
    await restore_backup_auto(interaction, backup_id)

@bot.tree.command(name="restore_from_text", description="Восстановить из текстовой копии (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    text_data="Текст резервной копии (скопируйте из сообщения)",
    backup_id="ID резервной копии для автоматического извлечения"
)
async def restore_from_text_command(
    interaction: discord.Interaction,
    text_data: str = None,
    backup_id: str = None
):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /restore_from_text",
            user=interaction.user,
            color=COLOR_ERROR
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if backup_id and not text_data:
        try:
            channel = await safe_fetch_channel(BACKUP_CHANNEL_ID)
            if not channel:
                raise Exception("Канал не найден")
            
            backup_msg = None
            try:
                messages = await safe_history_fetch(channel, limit=100)
                for message in messages:
                    if message.author == bot.user and f"ID: {backup_id}" in message.content:
                        backup_msg = message
                        break
            except Exception as e:
                raise Exception(f"Ошибка при поиске резервной копии: {e}")
            
            if not backup_msg:
                raise Exception(f"Резервная копия с ID {backup_id} не найдена")
            
            text_data = ""
            for part in backup_msg.content.split('```'):
                if "РЕЗЕРВНАЯ КОПИЯ" in part or "БАЛАНСЫ" in part or "ИСТОРИЯ" in part:
                    text_data += part + '\n'
            
            if not text_data:
                raise Exception("Не удалось извлечь текстовые данные")
            
            await restore_from_text(interaction, text_data)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка извлечения данных: {str(e)}", ephemeral=True)
            return
    elif text_data:
        await restore_from_text(interaction, text_data)
    else:
        await interaction.followup.send("❌ Необходимо указать либо текст, либо ID резервной копии", ephemeral=True)

@bot.tree.command(name="backup_info", description="Информация о резервных копиях (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def backup_info_command(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /backup_info",
            user=interaction.user,
            color=COLOR_ERROR
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    channel = await safe_fetch_channel(BACKUP_CHANNEL_ID)
    if not channel:
        await interaction.followup.send("❌ Канал не найден", ephemeral=True)
        return
    
    backups = []
    try:
        messages = await safe_history_fetch(channel, limit=MAX_BACKUP_MESSAGES)
        
        for message in messages:
            if message.author == bot.user:
                content = message.content
                if "Резервная копия" in content or BACKUP_SIGNATURE in content:
                    backup_id = "Неизвестно"
                    if "ID:" in content:
                        for line in content.split('\n'):
                            if "ID:" in line:
                                parts = line.split("ID:")
                                if len(parts) > 1:
                                    backup_id = parts[1].strip().split()[0]
                    
                    backups.append({
                        "id": message.id,
                        "backup_id": backup_id,
                        "created_at": message.created_at,
                        "has_compressed": False,
                        "has_csv": False
                    })
    except Exception as e:
        print(f"Ошибка при сборе информации о резервных копиях: {e}")
        await interaction.followup.send("❌ Ошибка при получении информации о резервных копиях", ephemeral=True)
        return
    
    for backup in backups:
        try:
            replies = await safe_history_fetch(channel, limit=20)
            for reply in replies:
                if reply.reference and reply.reference.message_id == backup["id"]:
                    if "СЖАТАЯ КОПИЯ" in reply.content:
                        backup["has_compressed"] = True
                    if "CSV КОПИЯ" in reply.content:
                        backup["has_csv"] = True
        except Exception as e:
            print(f"Ошибка при проверке данных резервной копии {backup['id']}: {e}")
    
    embed = discord.Embed(
        title="📊 Информация о резервных копиях",
        color=COLOR_INFO,
        timestamp=discord.utils.utcnow()
    )
    
    if backups:
        embed.description = f"Найдено резервных копий: {len(backups)}"
        
        for backup in backups[:5]:
            status = []
            if backup["has_compressed"]:
                status.append("📦")
            if backup["has_csv"]:
                status.append("📄")
            
            embed.add_field(
                name=f"Backup ID: `{backup['backup_id']}`",
                value=f"Сообщение ID: `{backup['id']}`\n"
                      f"Дата: {backup['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                      f"Форматы: {''.join(status) if status else '❌'}\n"
                      f"[Ссылка](https://discord.com/channels/{GUILD_ID}/{BACKUP_CHANNEL_ID}/{backup['id']})",
                inline=False
            )
        
        if len(backups) > 5:
            embed.set_footer(text=f"И еще {len(backups) - 5} резервных копий...")
    else:
        embed.description = "Резервные копии не найдены"
    
    view = discord.ui.View(timeout=180)
    
    create_button = discord.ui.Button(
        label="🔄 Создать новую копию",
        style=discord.ButtonStyle.primary,
        custom_id="create_backup"
    )
    
    restore_button = discord.ui.Button(
        label="♻️ Восстановить последнюю",
        style=discord.ButtonStyle.success,
        custom_id="restore_last"
    )
    
    list_button = discord.ui.Button(
        label="📋 Обновить список",
        style=discord.ButtonStyle.secondary,
        custom_id="refresh_list"
    )
    
    async def create_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        await create_enhanced_backup(i)
    
    async def restore_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        await restore_backup_auto(i)
    
    async def list_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        await i.response.defer(ephemeral=True)
        await backup_info_command(i)
    
    create_button.callback = create_callback
    restore_button.callback = restore_callback
    list_button.callback = list_callback
    
    view.add_item(create_button)
    view.add_item(restore_button)
    view.add_item(list_button)
    
    try:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        print(f"Ошибка при отправке информации о резервных копиях: {e}")
        await interaction.followup.send("❌ Ошибка при отправке информации", ephemeral=True)

# ==============================================
# КОМАНДА ДЛЯ ОТПРАВКИ ПОСТРОЙКИ С ИИ ОЦЕНКОЙ
# ==============================================

@bot.tree.command(name="submit_build", description="Отправить постройку на проверку ИИ")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    screenshot_url="Ссылка на скриншот постройки",
    description="Описание постройки (чем детальнее, тем лучше оценка)",
    coordinates="Координаты постройки (если есть)"
)
async def submit_build_command(
    interaction: discord.Interaction,
    screenshot_url: str,
    description: str = "",
    coordinates: str = ""
):
    try:
        if not is_valid_url(screenshot_url):
            await interaction.response.send_message(
                "❌ Пожалуйста, укажите корректную ссылку на изображение",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        evaluation_result = await evaluate_build_with_ai(screenshot_url, description)
        
        approval_channel = await safe_fetch_channel(APPROVAL_CHANNEL_ID)
        success_channel = await safe_fetch_channel(SUCCESS_CHANNEL_ID)
        
        if not approval_channel or not success_channel:
            await interaction.followup.send(
                "❌ Не удалось найти необходимые каналы для отправки",
                ephemeral=True
            )
            return
        
        approval_embed = discord.Embed(
            title="🏗️ Новая постройка на проверку",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        approval_embed.add_field(
            name="Автор",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False
        )
        
        if description:
            approval_embed.add_field(
                name="Описание",
                value=description[:500],
                inline=False
            )
        
        if coordinates:
            approval_embed.add_field(
                name="Координаты",
                value=coordinates,
                inline=True
            )
        
        approval_embed.add_field(
            name="Оценка ИИ",
            value=f"**{evaluation_result['ai_score']}/10** ({evaluation_result['reward']} скиллов)",
            inline=True
        )
        
        approval_embed.add_field(
            name="Критерии оценки",
            value=", ".join(evaluation_result['criteria']),
            inline=True
        )
        
        approval_embed.set_image(url=screenshot_url)
        approval_embed.set_footer(text=f"ID заявки: {int(time.time())}")
        
        success_embed = discord.Embed(
            title="✅ Постройка отправлена на проверку",
            description=f"**{interaction.user.mention}**, ваша постройка успешно отправлена на оценку!",
            color=COLOR_SUCCESS,
            timestamp=discord.utils.utcnow()
        )
        
        success_embed.add_field(
            name="Предварительная оценка ИИ",
            value=f"**{evaluation_result['ai_score']}/10**",
            inline=True
        )
        
        success_embed.add_field(
            name="Потенциальная награда",
            value=f"**{evaluation_result['reward']}** скиллов",
            inline=True
        )
        
        if description:
            success_embed.add_field(
                name="Ваше описание",
                value=description[:300],
                inline=False
            )
        
        success_embed.add_field(
            name="Комментарий ИИ",
            value=evaluation_result['comment'],
            inline=False
        )
        
        success_embed.add_field(
            name="Статус",
            value="⏳ Ожидает модерации",
            inline=True
        )
        
        success_embed.set_footer(text="Окончательная оценка будет после проверки модератором")
        
        view = discord.ui.View(timeout=None)
        
        timestamp = int(time.time())
        user_id = interaction.user.id
        
        approve_button = discord.ui.Button(
            label="✅ Подтвердить оценку",
            style=discord.ButtonStyle.success,
            custom_id=f"approve_build_{timestamp}_{user_id}",
            emoji="✅"
        )
        
        adjust_button = discord.ui.Button(
            label="📝 Настроить награду",
            style=discord.ButtonStyle.primary,
            custom_id=f"adjust_build_{timestamp}_{user_id}",
            emoji="📝"
        )
        
        deny_button = discord.ui.Button(
            label="❌ Отклонить",
            style=discord.ButtonStyle.danger,
            custom_id=f"deny_build_{timestamp}_{user_id}",
            emoji="❌"
        )
        
        async def approve_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут подтверждать оценки",
                    ephemeral=True
                )
                return
            
            reward = evaluation_result['reward']
            add_transaction(
                user_id,
                reward,
                reason=f"Награда за постройку (оценка ИИ: {evaluation_result['ai_score']}/10): {description[:100]}"
            )
            
            approval_embed.color = COLOR_SUCCESS
            approval_embed.title = "✅ Постройка подтверждена"
            approval_embed.add_field(
                name="Модератор",
                value=i.user.mention,
                inline=True
            )
            approval_embed.add_field(
                name="Награда выдана",
                value=f"**+{reward}** скиллов",
                inline=True
            )
            
            success_embed.color = COLOR_SUCCESS
            success_embed.title = "🎉 Постройка одобрена!"
            
            # Обновляем поле "Статус"
            for field in success_embed.fields:
                if field.name == "Статус":
                    field.value = "✅ Одобрено модератором"
                    break
            
            success_embed.add_field(
                name="Подтвердил",
                value=i.user.mention,
                inline=True
            )
            
            success_embed.set_footer(text=f"Награда выдана: {reward} скиллов")
            
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            
            await i.response.edit_message(embed=approval_embed, view=view)
            
            # Обновляем сообщение в канале успеха
            try:
                async for message in success_channel.history(limit=50):
                    if message.author == bot.user and str(user_id) in message.content:
                        await message.edit(embed=success_embed)
                        break
            except:
                pass
            
            # Отправляем уведомление автору
            try:
                await interaction.user.send(
                    f"🎉 Ваша постройка была одобрена модератором {i.user.mention}!\n"
                    f"Вы получили **+{reward}** скиллов!\n"
                    f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
                    f"**Комментарий:** {evaluation_result['comment']}"
                )
            except:
                pass
            
            await log_action(
                i.guild,
                "Постройка одобрена",
                f"**Модератор:** {i.user.mention}\n"
                f"**Автор:** {interaction.user.mention}\n"
                f"**Награда:** +{reward} скиллов\n"
                f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
                f"**Описание:** {description[:200]}",
                user=i.user,
                color=COLOR_SUCCESS
            )
            
            print(f"Постройка {user_id} одобрена модератором {i.user.id}")
            
            # Добавляем информацию о постройке
            build_id = f"build_{timestamp}_{user_id}"
            build_data = {
                "build_id": build_id,
                "user_id": str(user_id),
                "screenshot_url": screenshot_url,
                "description": description,
                "coordinates": coordinates,
                "evaluation": evaluation_result,
                "approval_message_id": i.message.id if i.message else None,
                "success_message_id": None,
                "created_at": time.time(),
                "status": "approved"
            }
            add_build_submission(user_id, build_data)
        
        async def adjust_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут настраивать награды",
                    ephemeral=True
                )
                return
            
            modal = discord.ui.Modal(title="Настройка награды")
            
            reward_input = discord.ui.TextInput(
                label="Новая награда (200-2000 скиллов)",
                placeholder=f"Текущая: {evaluation_result['reward']}",
                default=str(evaluation_result['reward']),
                required=True,
                max_length=4
            )
            
            comment_input = discord.ui.TextInput(
                label="Комментарий модератора",
                style=discord.TextStyle.paragraph,
                placeholder="Укажите причину изменения награды...",
                required=False,
                max_length=500
            )
            
            modal.add_item(reward_input)
            modal.add_item(comment_input)
            
            async def modal_callback(modal_interaction: discord.Interaction):
                try:
                    new_reward = int(reward_input.value)
                    moderator_comment = comment_input.value
                    
                    if new_reward < MIN_REWARD or new_reward > MAX_REWARD:
                        await modal_interaction.response.send_message(
                            f"❌ Награда должна быть от {MIN_REWARD} до {MAX_REWARD} скиллов",
                            ephemeral=True
                        )
                        return
                    
                    add_transaction(
                        user_id,
                        new_reward,
                        reason=f"Награда за постройку (скорректировано модератором): {description[:100]}"
                    )
                    
                    approval_embed.color = COLOR_GOLD
                    approval_embed.title = "📝 Награда скорректирована"
                    approval_embed.add_field(
                        name="Модератор",
                        value=modal_interaction.user.mention,
                        inline=True
                    )
                    approval_embed.add_field(
                        name="Награда выдана",
                        value=f"**+{new_reward}** скиллов (было: {evaluation_result['reward']})",
                        inline=True
                    )
                    
                    if moderator_comment:
                        approval_embed.add_field(
                            name="Комментарий модератора",
                            value=moderator_comment,
                            inline=False
                        )
                    
                    success_embed.color = COLOR_GOLD
                    success_embed.title = "📝 Награда скорректирована"
                    
                    # Обновляем поле "Потенциальная награда"
                    for field in success_embed.fields:
                        if field.name == "Потенциальная награда":
                            field.value = f"**{new_reward}** скиллов (скорректировано)"
                            break
                    
                    # Обновляем поле "Статус"
                    for field in success_embed.fields:
                        if field.name == "Статус":
                            field.value = "📝 Скорректировано модератором"
                            break
                    
                    if moderator_comment:
                        success_embed.add_field(
                            name="Комментарий модератора",
                            value=moderator_comment,
                            inline=False
                        )
                    
                    success_embed.add_field(
                        name="Скорректировал",
                        value=modal_interaction.user.mention,
                        inline=True
                    )
                    
                    success_embed.set_footer(text=f"Награда выдана: {new_reward} скиллов")
                    
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await modal_interaction.response.edit_message(embed=approval_embed, view=view)
                    
                    # Обновляем сообщение в канале успеха
                    try:
                        async for message in success_channel.history(limit=50):
                            if message.author == bot.user and str(user_id) in message.content:
                                await message.edit(embed=success_embed)
                                break
                    except:
                        pass
                    
                    # Отправляем уведомление автору
                    try:
                        message_text = f"📝 Ваша постройка была проверена модератором {modal_interaction.user.mention}!\n"
                        message_text += f"Награда скорректирована до **{new_reward}** скиллов.\n"
                        message_text += f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
                        if moderator_comment:
                            message_text += f"**Комментарий модератора:** {moderator_comment}"
                        
                        await interaction.user.send(message_text)
                    except:
                        pass
                    
                    log_text = f"**Модератор:** {modal_interaction.user.mention}\n"
                    log_text += f"**Автор:** {interaction.user.mention}\n"
                    log_text += f"**Награда:** +{new_reward} скиллов (было: {evaluation_result['reward']})\n"
                    log_text += f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
                    if moderator_comment:
                        log_text += f"**Комментарий:** {moderator_comment}\n"
                    log_text += f"**Описание:** {description[:200]}"
                    
                    await log_action(
                        modal_interaction.guild,
                        "Награда скорректирована",
                        log_text,
                        user=modal_interaction.user,
                        color=COLOR_GOLD
                    )
                    
                    print(f"Награда для постройки {user_id} скорректирована модератором {modal_interaction.user.id}")
                    
                    # Добавляем информацию о постройке
                    build_id = f"build_{timestamp}_{user_id}"
                    build_data = {
                        "build_id": build_id,
                        "user_id": str(user_id),
                        "screenshot_url": screenshot_url,
                        "description": description,
                        "coordinates": coordinates,
                        "evaluation": evaluation_result,
                        "approval_message_id": modal_interaction.message.id if modal_interaction.message else None,
                        "success_message_id": None,
                        "created_at": time.time(),
                        "status": "adjusted",
                        "adjusted_reward": new_reward,
                        "moderator_comment": moderator_comment
                    }
                    add_build_submission(user_id, build_data)
                    
                except ValueError:
                    await modal_interaction.response.send_message(
                        "❌ Пожалуйста, введите корректное число",
                        ephemeral=True
                    )
                except Exception as e:
                    await modal_interaction.response.send_message(
                        f"❌ Ошибка: {str(e)}",
                        ephemeral=True
                    )
            
            modal.on_submit = modal_callback
            await i.response.send_modal(modal)
        
        async def deny_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут отклонять постройки",
                    ephemeral=True
                )
                return
            
            modal = discord.ui.Modal(title="Причина отклонения")
            modal.add_item(
                discord.ui.TextInput(
                    label="Причина отказа",
                    style=discord.TextStyle.paragraph,
                    placeholder="Укажите причину, по которой постройка отклонена...",
                    required=True,
                    max_length=500
                )
            )
            
            async def modal_callback(modal_interaction: discord.Interaction):
                reason = modal.children[0].value
                
                approval_embed.color = COLOR_ERROR
                approval_embed.title = "❌ Постройка отклонена"
                approval_embed.add_field(
                    name="Модератор",
                    value=modal_interaction.user.mention,
                    inline=True
                )
                approval_embed.add_field(
                    name="Причина",
                    value=reason[:200],
                    inline=False
                )
                
                success_embed.color = COLOR_ERROR
                success_embed.title = "❌ Постройка отклонена"
                
                # Обновляем поле "Статус"
                for field in success_embed.fields:
                    if field.name == "Статус":
                        field.value = "❌ Отклонено"
                        break
                
                success_embed.add_field(
                    name="Причина",
                    value=reason[:200],
                    inline=False
                )
                
                success_embed.add_field(
                    name="Отклонил",
                    value=modal_interaction.user.mention,
                    inline=True
                )
                
                success_embed.set_footer(text="Постройка не соответствует требованиям")
                
                for child in view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                
                await modal_interaction.response.edit_message(embed=approval_embed, view=view)
                
                # Обновляем сообщение в канале успеха
                try:
                    async for message in success_channel.history(limit=50):
                        if message.author == bot.user and str(user_id) in message.content:
                            await message.edit(embed=success_embed)
                            break
                except:
                    pass
                
                # Отправляем уведомление автору
                try:
                    await interaction.user.send(
                        f"😔 Ваша постройка была отклонена модератором {modal_interaction.user.mention}.\n"
                        f"**Причина:** {reason}\n"
                        f"**Оценка ИИ:** {evaluation_result['ai_score']}/10"
                    )
                except:
                    pass
                
                await log_action(
                    modal_interaction.guild,
                    "Постройка отклонена",
                    f"**Модератор:** {modal_interaction.user.mention}\n"
                    f"**Автор:** {interaction.user.mention}\n"
                    f"**Причина:** {reason}\n"
                    f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
                    f"**Описание:** {description[:200]}",
                    user=modal_interaction.user,
                    color=COLOR_ERROR
                )
                
                print(f"Постройка {user_id} отклонена модератором {modal_interaction.user.id}")
                
                # Добавляем информацию о постройке
                build_id = f"build_{timestamp}_{user_id}"
                build_data = {
                    "build_id": build_id,
                    "user_id": str(user_id),
                    "screenshot_url": screenshot_url,
                    "description": description,
                    "coordinates": coordinates,
                    "evaluation": evaluation_result,
                    "approval_message_id": modal_interaction.message.id if modal_interaction.message else None,
                    "success_message_id": None,
                    "created_at": time.time(),
                    "status": "denied",
                    "deny_reason": reason
                }
                add_build_submission(user_id, build_data)
            
            modal.on_submit = modal_callback
            await i.response.send_modal(modal)
        
        approve_button.callback = approve_callback
        adjust_button.callback = adjust_callback
        deny_button.callback = deny_callback
        
        view.add_item(approve_button)
        view.add_item(adjust_button)
        view.add_item(deny_button)
        
        approval_message = await safe_send_message(approval_channel, embed=approval_embed, view=view)
        success_message = await safe_send_message(success_channel, embed=success_embed)
        
        # Сохраняем информацию о постройке
        build_id = f"build_{timestamp}_{user_id}"
        build_data = {
            "build_id": build_id,
            "user_id": str(user_id),
            "screenshot_url": screenshot_url,
            "description": description,
            "coordinates": coordinates,
            "evaluation": evaluation_result,
            "approval_message_id": approval_message.id if approval_message else None,
            "success_message_id": success_message.id if success_message else None,
            "created_at": time.time(),
            "status": "pending"
        }
        add_build_submission(user_id, build_data)
        
        confirmation_embed = discord.Embed(
            title="✅ Постройка отправлена!",
            description=f"Ваша постройка отправлена на оценку ИИ и ожидает проверки модератором.",
            color=COLOR_SUCCESS,
            timestamp=discord.utils.utcnow()
        )
        
        confirmation_embed.add_field(
            name="Канал проверки",
            value=f"<#{APPROVAL_CHANNEL_ID}>",
            inline=True
        )
        
        confirmation_embed.add_field(
            name="Канал подтверждений",
            value=f"<#{SUCCESS_CHANNEL_ID}>",
            inline=True
        )
        
        confirmation_embed.add_field(
            name="Предварительная оценка",
            value=f"**{evaluation_result['ai_score']}/10**",
            inline=False
        )
        
        confirmation_embed.add_field(
            name="Потенциальная награда",
            value=f"**{evaluation_result['reward']}** скиллов",
            inline=False
        )
        
        confirmation_embed.set_footer(text="Окончательное решение принимает модератор")
        
        await interaction.followup.send(embed=confirmation_embed, ephemeral=True)
        
        await log_action(
            interaction.guild,
            "Новая постройка отправлена",
            f"**Автор:** {interaction.user.mention}\n"
            f"**Оценка ИИ:** {evaluation_result['ai_score']}/10\n"
            f"**Предполагаемая награда:** {evaluation_result['reward']} скиллов\n"
            f"**Описание:** {description[:200]}",
            user=interaction.user,
            color=COLOR_INFO
        )
        
        print(f"Новая постройка от {user_id} отправлена на оценку")
        
    except Exception as e:
        print(f"Ошибка в команде submit_build: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Произошла ошибка при отправке постройки",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"❌ Ошибка: {str(e)}",
                ephemeral=True
            )

# ==============================================
# КОМАНДА ДЛЯ ПОВТОРНОЙ ОТПРАВКИ ПРИГЛАШЕНИЯ
# ==============================================

@bot.tree.command(name="send_welcome", description="Отправить приглашение участнику (модераторы)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник для приглашения",
    reason="Причина повторной отправки"
)
async def send_welcome_command(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = ""
):
    try:
        if not has_mod_rights(interaction.user):
            await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
            return
        
        approved_role = member.guild.get_role(APPROVED_ROLE_ID)
        if approved_role and approved_role in member.roles:
            await interaction.response.send_message(
                f"❌ Участник {member.mention} уже имеет подтвержденную роль",
                ephemeral=True
            )
            return
        
        # Имитируем событие присоединения
        await on_member_join(member)
        
        embed = discord.Embed(
            title="✅ Приглашение отправлено",
            description=f"Новая заявка создана для {member.mention}",
            color=COLOR_SUCCESS
        )
        
        if reason:
            embed.add_field(name="Причина", value=reason, inline=False)
        
        embed.set_footer(text=f"Отправил: {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
        await log_action(
            interaction.guild,
            "Повторная отправка приглашения",
            f"**Модератор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=COLOR_SUCCESS
        )
        
    except Exception as e:
        print(f"Ошибка в команде send_welcome: {e}")
        await interaction.response.send_message(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )

# ==============================================
# НОВЫЕ КОМАНДЫ ДЛЯ ЕЖЕМЕСЯЧНОГО ОБНУЛЕНИЯ
# ==============================================

@bot.tree.command(name="force_monthly_reset", description="Принудительное выполнение ежемесячного обнуления (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    confirm="Введите 'ПОДТВЕРЖДАЮ' для выполнения обнуления"
)
async def force_monthly_reset_command(
    interaction: discord.Interaction,
    confirm: str = ""
):
    try:
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
            return
        
        if confirm != "ПОДТВЕРЖДАЮ":
            confirm_embed = discord.Embed(
                title="⚠️ ПОДТВЕРЖДЕНИЕ ОБНУЛЕНИЯ",
                description="Это действие обнулит балансы ВСЕХ участников (кроме администратора).",
                color=COLOR_WARNING
            )
            
            confirm_embed.add_field(
                name="Последствия:",
                value="• Все балансы будут сброшены в 0\n"
                      "• Будет создан подробный отчет\n"
                      "• Изменения нельзя будет отменить\n"
                      "• Будет создана резервная копия",
                inline=False
            )
            
            confirm_embed.add_field(
                name="Для подтверждения:",
                value="Введите команду: `/force_monthly_reset confirm:ПОДТВЕРЖДАЮ`",
                inline=False
            )
            
            await interaction.response.send_message(embed=confirm_embed, ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        await perform_monthly_reset()
        
        success_embed = discord.Embed(
            title="✅ Обнуление выполнено",
            description="Ежемесячное обнуление балансов успешно выполнено.",
            color=COLOR_SUCCESS
        )
        
        await interaction.followup.send(embed=success_embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде force_monthly_reset: {e}")
        await interaction.followup.send(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="reset_status", description="Показать статус ежемесячного обнуления (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def reset_status_command(interaction: discord.Interaction):
    try:
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
            return
        
        tracker = load_monthly_reset_tracker()
        now = datetime.datetime.now()
        
        embed = discord.Embed(
            title="📅 Статус ежемесячного обнуления",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        if tracker.get("last_reset_month"):
            last_reset = None
            for reset in tracker.get("reset_history", []):
                if f"{reset['datetime'][:7]}" == tracker["last_reset_month"]:
                    last_reset = reset
                    break
            
            if last_reset:
                embed.add_field(
                    name="Последний сброс",
                    value=f"**Дата:** {last_reset['datetime']}\n"
                          f"**Участников:** {last_reset.get('users_reset', 0)}\n"
                          f"**Скиллов обнулено:** {last_reset.get('total_skils_reset', 0)}",
                    inline=False
                )
        
        # Вычисляем дату следующего сброса
        next_reset_date = datetime.datetime(now.year, now.month, MONTHLY_RESET_DAY, RESET_TIME_HOUR)
        if now.day > MONTHLY_RESET_DAY or (now.day == MONTHLY_RESET_DAY and now.hour >= RESET_TIME_HOUR):
            # Если текущий день уже прошел день сброса, переходим к следующему месяцу
            if now.month == 12:
                next_reset_date = datetime.datetime(now.year + 1, 1, MONTHLY_RESET_DAY, RESET_TIME_HOUR)
            else:
                next_reset_date = datetime.datetime(now.year, now.month + 1, MONTHLY_RESET_DAY, RESET_TIME_HOUR)
        
        days_until_reset = (next_reset_date - now).days
        hours_until_reset = (next_reset_date - now).seconds // 3600
        
        embed.add_field(
            name="Следующий сброс",
            value=f"**Дата:** {next_reset_date.strftime('%d.%m.%Y %H:%M')}\n"
                  f"**Через:** {days_until_reset} дн. {hours_until_reset} час.",
            inline=False
        )
        
        reset_count = len(tracker.get("reset_history", []))
        if reset_count > 0:
            total_skils = sum(r.get("total_skils_reset", 0) for r in tracker["reset_history"])
            total_users = sum(r.get("users_reset", 0) for r in tracker["reset_history"])
            
            embed.add_field(
                name="📊 Общая статистика",
                value=f"**Всего сбросов:** {reset_count}\n"
                      f"**Всего участников:** {total_users}\n"
                      f"**Всего скиллов обнулено:** {total_skils}",
                inline=False
            )
        
        current_month_str = f"{now.year}-{now.month:02d}"
        is_reset_done = tracker.get("last_reset_month") == current_month_str
        
        embed.add_field(
            name="Текущий месяц",
            value=f"**Месяц:** {now.strftime('%B %Y')}\n"
                  f"**Статус:** {'✅ Обнулен' if is_reset_done else '⏳ Ожидает обнуления'}",
            inline=False
        )
        
        embed.set_footer(text=f"Автоматическое обнуление: {MONTHLY_RESET_DAY}-{MONTHLY_RESET_DAY+1} число каждого месяца")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде reset_status: {e}")
        await interaction.response.send_message(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )

@bot.tree.command(name="my_builds", description="Показать ваши последние постройки")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    limit="Количество построек для показа (1-20)"
)
async def my_builds_command(
    interaction: discord.Interaction,
    limit: app_commands.Range[int, 1, 20] = 10
):
    try:
        user_builds = get_user_builds(interaction.user.id, limit)
        
        if not user_builds:
            embed = discord.Embed(
                title="🏗️ Ваши постройки",
                description="У вас еще нет отправленных построек.",
                color=COLOR_INFO
            )
            embed.add_field(
                name="Как отправить постройку?",
                value="Используйте команду `/submit_build` чтобы отправить свою постройку на оценку!",
                inline=False
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"🏗️ Ваши последние {len(user_builds)} построек",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        for i, build in enumerate(reversed(user_builds), 1):
            build_data = build.get("build_data", {})
            evaluation = build_data.get("evaluation", {})
            
            field_value = f"**Дата:** {build['datetime']}\n"
            
            if build_data.get("description"):
                field_value += f"**Описание:** {build_data['description'][:50]}...\n"
            
            if evaluation:
                field_value += f"**Оценка ИИ:** {evaluation.get('ai_score', 'N/A')}/10\n"
                field_value += f"**Награда:** {evaluation.get('reward', 0)} скиллов\n"
            
            status = build_data.get('status', 'pending')
            status_emoji = "⏳" if status == "pending" else "✅" if status == "approved" else "📝" if status == "adjusted" else "❌"
            field_value += f"**Статус:** {status_emoji} {status}\n"
            
            if build_data.get("approval_message_id"):
                field_value += f"[Ссылка на проверку](https://discord.com/channels/{GUILD_ID}/{APPROVAL_CHANNEL_ID}/{build_data['approval_message_id']})"
            
            embed.add_field(
                name=f"{i}. Постройка от {build['datetime'][:10]}",
                value=field_value,
                inline=False
            )
        
        total_builds = len(get_user_builds(interaction.user.id, 1000))
        embed.set_footer(text=f"Всего построек за все время: {total_builds}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде my_builds: {e}")
        await interaction.response.send_message(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )

# ==============================================
# КОМАНДА ПОМОЩИ
# ==============================================

@bot.tree.command(name="help", description="Показать список всех команд")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help_command(interaction: discord.Interaction):
    try:
        embed = discord.Embed(
            title="📚 Помощь по командам ashra_team бота",
            description="Все доступные команды:",
            color=COLOR_INFO,
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="👤 Основные команды",
            value="• `/balance` - Показать ваш баланс\n"
                  "• `/give [участник] [количество] [причина]` - Передать скиллы\n"
                  "• `/top [количество]` - Топ участников по скиллам\n"
                  "• `/history [количество]` - История ваших транзакций\n"
                  f"• `/submit_build [скриншот] [описание]` - Отправить постройку на оценку ИИ\n"
                  f"  (Награда: **{MIN_REWARD}-{MAX_REWARD}** скиллов)\n"
                  "• `/my_builds [количество]` - Показать ваши последние постройки",
            inline=False
        )
        
        if has_mod_rights(interaction.user):
            embed.add_field(
                name="🛡️ Команды модераторов",
                value="• `/add_skils [участник] [количество] [причина]` - Добавить скиллы\n"
                      "• `/remove_skils [участник] [количество] [причина]` - Убрать скиллы\n"
                      "• `/send_welcome [участник] [причина]` - Отправить приглашение",
                inline=False
            )
        
        if is_admin(interaction.user):
            embed.add_field(
                name="⚙️ Команды администратора",
                value="• `/set_balance [участник] [количество] [причина]` - Установить баланс\n"
                      "• `/reset_balance [участник] [причина]` - Сбросить баланс\n"
                      "• `/backup` - Создать резервную копию\n"
                      "• `/restore_backup [id]` - Восстановить из резервной копии\n"
                      "• `/backup_info` - Информация о резервных копиях\n"
                      "• `/restore_from_text` - Восстановить из текстовой копии\n"
                      "• `/force_monthly_reset` - Принудительное обнуление балансов\n"
                      "• `/reset_status` - Статус ежемесячного обнуления",
                inline=False
            )
        
        embed.add_field(
            name="🏗️ Система оценок построек",
            value=f"• **ИИ оценка:** Каждая постройка оценивается ИИ от 1 до 10 баллов\n"
                  f"• **Награда:** Преобразуется в **{MIN_REWARD}-{MAX_REWARD}** скиллов\n"
                  f"• **Канал проверки:** <#{APPROVAL_CHANNEL_ID}>\n"
                  f"• **Канал подтверждений:** <#{SUCCESS_CHANNEL_ID}>\n"
                  f"• **Канал ежемесячных отчетов:** <#{MONTHLY_REPORT_CHANNEL_ID}>",
            inline=False
        )
        
        embed.add_field(
            name="🔄 Ежемесячное обнуление",
            value=f"• **Когда:** {MONTHLY_RESET_DAY}-{MONTHLY_RESET_DAY+1} число каждого месяца\n"
                  f"• **Что происходит:** Балансы всех участников (кроме админа) обнуляются\n"
                  f"• **Отчет:** Создается подробный отчет с ссылками на постройки\n"
                  f"• **Уведомление:** Администратор получает уведомление",
            inline=False
        )
        
        embed.set_footer(text=f"Запросил: {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        print(f"Ошибка в команде help: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при получении справки",
            ephemeral=True
        )

# ==============================================
# АВТОМАТИЧЕСКИЕ ЗАДАЧИ
# ==============================================

@tasks.loop(hours=6)
async def auto_backup_task():
    try:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Запуск автоматического резервного копирования...")
        await create_enhanced_backup()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Автоматическое резервное копирование завершено")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Ошибка автоматического резервного копирования: {e}")

@tasks.loop(minutes=30)
async def check_data_integrity():
    try:
        balance_data = load_balance()
        
        if not balance_data:
            print("Данные не найдены. Попытка автовосстановления...")
            try:
                success = await restore_backup_auto()
                if success:
                    print("Данные восстановлены автоматически")
                else:
                    print("Автовосстановление не удалось")
            except Exception as e:
                print(f"Не удалось восстановить данные: {e}")
    except Exception as e:
        print(f"Ошибка проверки целостности данных: {e}")

@tasks.loop(hours=1)
async def cleanup_old_approvals():
    try:
        welcome_channel = await safe_fetch_channel(WELCOME_CHANNEL_ID)
        if not welcome_channel:
            return
        
        approval_data = load_approval_data()
        current_time = time.time()
        messages_to_delete = []
        
        try:
            messages = await safe_history_fetch(welcome_channel, limit=MAX_WELCOME_MESSAGES)
            
            for message in messages:
                if message.author == bot.user:
                    if message.embeds:
                        embed_title = message.embeds[0].title if message.embeds else ""
                        if "Новый участник" in embed_title or "Участник" in embed_title:
                            message_age_hours = (current_time - message.created_at.timestamp()) / 3600
                            
                            if message_age_hours > APPROVAL_MESSAGE_EXPIRE_HOURS:
                                messages_to_delete.append(message)
        except Exception as e:
            print(f"Ошибка при поиске старых сообщений: {e}")
            return
        
        for message in messages_to_delete:
            try:
                await message.delete()
                print(f"Удалено старое сообщение с заявкой: {message.id}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"Ошибка при удалении сообщения {message.id}: {e}")
        
        if approval_data:
            updated_data = {}
            for user_id, data in approval_data.items():
                if "created_at" in data:
                    data_age_hours = (current_time - data["created_at"]) / 3600
                    if data_age_hours <= APPROVAL_MESSAGE_EXPIRE_HOURS * 2:
                        updated_data[user_id] = data
            
            if len(updated_data) != len(approval_data):
                save_approval_data(updated_data)
                print(f"Очищено {len(approval_data) - len(updated_data)} старых записей о заявках")
                
    except Exception as e:
        print(f"Ошибка при очистке старых заявок: {e}")

@tasks.loop(hours=1)
async def check_monthly_reset():
    try:
        if should_perform_reset():
            await perform_monthly_reset()
    except Exception as e:
        print(f"Ошибка при проверке ежемесячного обнуления: {e}")

@tasks.loop(hours=6)
async def notify_admin_before_reset():
    try:
        now = datetime.datetime.now()
        
        if now.day == MONTHLY_RESET_DAY and now.hour == ADMIN_NOTIFICATION_HOUR:
            tracker = load_monthly_reset_tracker()
            current_month_str = f"{now.year}-{now.month:02d}"
            
            if tracker.get("last_reset_month") != current_month_str:
                try:
                    admin = await bot.fetch_user(ADMIN_USER_ID)
                    if admin:
                        notification_embed = discord.Embed(
                            title="⚠️ НАПОМИНАНИЕ: Ежемесячное обнуление",
                            description=f"Сегодня в {RESET_TIME_HOUR:02d}:00 произойдет автоматическое обнуление балансов всех участников (кроме администратора).",
                            color=COLOR_WARNING,
                            timestamp=discord.utils.utcnow()
                        )
                        
                        notification_embed.add_field(
                            name="📅 Дата",
                            value=f"**{now.strftime('%d.%m.%Y')}** в **{RESET_TIME_HOUR:02d}:00**",
                            inline=False
                        )
                        
                        notification_embed.add_field(
                            name="ℹ️ Информация",
                            value="• Балансы всех участников будут обнулены\n"
                                  "• Будет создан подробный отчет\n"
                                  "• Администратор получит уведомление\n"
                                  "• Будет создана резервная копия перед обнулением",
                            inline=False
                        )
                        
                        notification_embed.set_footer(text="Это автоматическое напоминание")
                        
                        await admin.send(embed=notification_embed)
                        print(f"Админ уведомлен о предстоящем обнулении: {now.strftime('%d.%m.%Y %H:%M')}")
                except Exception as e:
                    print(f"Ошибка при уведомлении админа: {e}")
    except Exception as e:
        print(f"Ошибка в задаче уведомления админа: {e}")

# ==============================================
# СОБЫТИЯ БОТА
# ==============================================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Бот запущен как {bot.user}")
        print(f"🆔 ID бота: {bot.user.id}")
        print(f"🏰 Сервер ID: {GUILD_ID}")
        print(f"📁 Папка данных: {DATA_FOLDER.absolute()}")
        print(f"👋 Канал для подтверждения: {WELCOME_CHANNEL_ID}")
        print(f"🏗️ Канал проверки построек: {APPROVAL_CHANNEL_ID}")
        print(f"✅ Канал подтверждений построек: {SUCCESS_CHANNEL_ID}")
        print(f"📊 Канал ежемесячных отчетов: {MONTHLY_REPORT_CHANNEL_ID}")
        print(f"💰 Награда за постройки: {MIN_REWARD}-{MAX_REWARD} скиллов")
        print(f"🔄 Ежемесячное обнуление: {MONTHLY_RESET_DAY}-{MONTHLY_RESET_DAY+1} число каждого месяца")
        
        print("🔍 Проверка данных...")
        balance_data = load_balance()
        
        if not balance_data:
            print("⚠️  Данные не найдены. Попытка автовосстановления...")
            try:
                success = await restore_backup_auto()
                if success:
                    print("✅ Автовосстановление выполнено успешно")
                else:
                    print("❌ Автовосстановление не удалось")
            except Exception as e:
                print(f"❌ Ошибка автовосстановления: {e}")
        else:
            print(f"✅ Данные загружены: {len(balance_data)} записей баланса")
            
            history_data = load_history()
            total_transactions = sum(len(transactions) for transactions in history_data.values())
            print(f"📊 Всего транзакций: {total_transactions}")
            
            tracker = load_monthly_reset_tracker()
            now = datetime.datetime.now()
            current_month_str = f"{now.year}-{now.month:02d}"
            
            if tracker.get("last_reset_month") == current_month_str:
                print(f"✅ Обнуление за {now.strftime('%B %Y')} уже выполнено")
            else:
                print(f"⚠️  Обнуление за {now.strftime('%B %Y')} еще не выполнено")
        
        auto_backup_task.start()
        check_data_integrity.start()
        cleanup_old_approvals.start()
        check_monthly_reset.start()
        notify_admin_before_reset.start()
        
        print("🔄 Автоматические задачи запущены:")
        print("   • Резервное копирование: каждые 6 часов")
        print("   • Проверка целостности: каждые 30 минут")
        print("   • Очистка старых заявок: каждый час")
        print("   • Проверка ежемесячного обнуления: каждый час")
        print("   • Уведомление админа: каждые 6 часов")
        print("🤖 Бот готов к работе!")
        
    except Exception as e:
        print(f"❌ Критическая ошибка в on_ready: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def setup_hook():
    print("🔧 Настройка бота...")

# ==============================================
# ЗАПУСК БОТА
# ==============================================

if __name__ == "__main__":
    print("🚀 Запуск бота...")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Ошибка запуска бота: {e}")