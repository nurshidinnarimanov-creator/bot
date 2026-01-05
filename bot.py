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

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

GUILD_ID = 1423020585881043016
BACKUP_CHANNEL_ID = 1457768411873415190  # ID канала для хранения резервных копий
LOG_CHANNEL_ID = 1450910208325980335
APPROVAL_CHANNEL_ID = 1457779107017261210
WELCOME_CHANNEL_ID = 1457779107017261210  # Канал для подтверждения новых участников
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
SECOND_MOD_ROLE_ID = 1454381506934865986
BUILDER_ROLE_ID = 1423344924262273157
APPROVED_ROLE_ID = 1423344924262273157  # Роль для подтвержденных участников

# Настройки
APPROVAL_MESSAGE_EXPIRE_HOURS = 24  # Через сколько часов удалять сообщение об отказе

# Цвета для эмбедов
COLOR_SUCCESS = 0x00ff00  # Зеленый
COLOR_WARNING = 0xffaa00  # Оранжевый
COLOR_ERROR = 0xff0000    # Красный
COLOR_INFO = 0x0080ff     # Синий
COLOR_PURPLE = 0x8000ff   # Фиолетовый

DATA_FOLDER = Path("data")
BACKUP_FOLDER = Path("backups")

DATA_FOLDER.mkdir(exist_ok=True)
BACKUP_FOLDER.mkdir(exist_ok=True)

APPROVAL_MAP_FILE = DATA_FOLDER / "approval_map.json"
BALANCE_FILE = DATA_FOLDER / "balance.json"
HISTORY_FILE = DATA_FOLDER / "history.json"
CONFIG_FILE = DATA_FOLDER / "config.json"
BACKUP_CONFIG_FILE = DATA_FOLDER / "backup_config.json"

# Константа для идентификации резервных копий
BACKUP_SIGNATURE = "SKILL_BOT_BACKUP_V2"

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
    except:
        try:
            content = filepath.read_bytes()
            if content.startswith(b'\xff\xfe'):
                content = content.decode('utf-16-le')
            elif content.startswith(b'\xfe\xff'):
                content = content.decode('utf-16-be')
            else:
                content = content.decode('utf-8', errors='ignore')
            
            if content.strip() == "":
                content = "{}"
            
            data = json.loads(content)
            with filepath.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except:
            with filepath.open("w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

# Исправляем кодировку всех файлов при запуске
fix_json_file_encoding(BALANCE_FILE)
fix_json_file_encoding(HISTORY_FILE)
fix_json_file_encoding(APPROVAL_MAP_FILE)
fix_json_file_encoding(CONFIG_FILE)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class BackupManager:
    """Менеджер резервного копирования"""
    
    @staticmethod
    def create_backup_payload() -> Dict[str, Any]:
        """Создает структурированный payload для резервной копии"""
        payload = {
            "signature": BACKUP_SIGNATURE,
            "version": "2.0",
            "timestamp": datetime.datetime.now().isoformat(),
            "created_by": "skill_bot",
            "data": {}
        }
        
        # Читаем все файлы данных
        files_to_backup = [
            ("balance", BALANCE_FILE),
            ("history", HISTORY_FILE),
            ("approval_map", APPROVAL_MAP_FILE)
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
        json_str = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        
        # Сжимаем данные
        compressed = zlib.compress(json_str.encode('utf-8'))
        
        # Кодируем в base64 для безопасной передачи
        encoded = base64.b64encode(compressed).decode('utf-8')
        
        return encoded
    
    @staticmethod
    def decompress_backup(encoded_data: str) -> Optional[Dict]:
        """Восстанавливает резервную копию из закодированной строки"""
        try:
            # Декодируем из base64
            compressed = base64.b64decode(encoded_data)
            
            # Распаковываем
            json_str = zlib.depress(compressed).decode('utf-8')
            
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
        current_chunk = ""
        
        # Разделяем по строкам, чтобы не разрывать JSON
        lines = data.split('\n')
        
        for line in lines:
            if len(current_chunk) + len(line) + 1 < max_chunk:
                current_chunk += line + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    @staticmethod
    def create_human_readable_backup() -> str:
        """Создает читабельную резервную копию для ручного восстановления"""
        balance_data = load_balance()
        history_data = load_history()
        
        output = [
            "=" * 60,
            "РЕЗЕРВНАЯ КОПИЯ SKILL БОТА",
            f"Дата создания: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            f"Сигнатура: {BACKUP_SIGNATURE}",
            "=" * 60,
            "",
            "1. БАЛАНСЫ ПОЛЬЗОВАТЕЛЕЙ:",
            "=" * 60
        ]
        
        for user_id, balance in sorted(balance_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            output.append(f"ID: {user_id} -> Баланс: {balance} скиллов")
        
        output.extend([
            "",
            "2. ИСТОРИЯ ТРАНЗАКЦИЙ (последние 3 на каждого пользователя):",
            "=" * 60
        ])
        
        for user_id, transactions in history_data.items():
            if transactions:
                output.append(f"\nПользователь ID: {user_id}")
                for i, tx in enumerate(reversed(transactions[-3:]), 1):
                    output.append(f"  {i}. {tx.get('datetime', 'N/A')}: {tx.get('amount', 0):+d} скиллов")
                    if tx.get('reason'):
                        output.append(f"     Причина: {tx['reason'][:50]}")
        
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
    
    @staticmethod
    def create_simple_backup() -> str:
        """Создает упрощенную резервную копию в формате CSV"""
        balance_data = load_balance()
        history_data = load_history()
        
        lines = [
            "# SKILL BOT BACKUP DATA",
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
            for tx in transactions[-5:]:  # Последние 5 транзакций
                lines.append(f"{user_id},{tx.get('datetime', '')},{tx.get('amount', 0)},{tx.get('reason', '')}")
        
        return '\n'.join(lines)

async def create_enhanced_backup(interaction: discord.Interaction = None):
    """Создает улучшенную резервную копию"""
    try:
        channel = bot.get_channel(BACKUP_CHANNEL_ID)
        if not channel:
            raise Exception(f"Канал для резервных копий не найден (ID: {BACKUP_CHANNEL_ID})")
        
        # Удаляем старые резервные копии (оставляем только 10 последних)
        messages_to_delete = []
        async for message in channel.history(limit=50):
            if message.author == bot.user and ("Резервная копия" in message.content or BACKUP_SIGNATURE in message.content):
                messages_to_delete.append(message)
        
        if len(messages_to_delete) > 10:
            for msg in messages_to_delete[10:]:
                try:
                    await msg.delete()
                except:
                    pass
        
        # Создаем два типа резервных копий
        timestamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        backup_id = f"{int(time.time())}"
        
        # 1. Сжатая версия для автоматического восстановления
        payload = BackupManager.create_backup_payload()
        compressed_backup = BackupManager.compress_backup(payload)
        
        # 2. Читаемая версия для ручного восстановления
        human_readable = BackupManager.create_human_readable_backup()
        
        # 3. Простая CSV версия
        simple_backup = BackupManager.create_simple_backup()
        
        # Отправляем основное сообщение с читаемой версией
        backup_msg = await channel.send(
            f"**📦 РЕЗЕРВНАЯ КОПИЯ SKILL БОТА**\n"
            f"```\n"
            f"ID: {backup_id}\n"
            f"Дата: {timestamp}\n"
            f"Сигнатура: {BACKUP_SIGNATURE}\n"
            f"```\n"
            f"Для восстановления используйте команды:\n"
            f"• `/restore_backup` - автоматическое восстановление\n"
            f"• `/restore_from_text` - ручное восстановление\n"
            f"• `/restore_from_text backup_id={backup_id}` - по ID\n\n"
            f"**Читаемая версия:**\n"
            f"```\n{human_readable[:800]}...\n```"
        )
        
        # Отправляем сжатую версию как ответ
        chunks = BackupManager.split_for_discord(compressed_backup)
        for i, chunk in enumerate(chunks, 1):
            await backup_msg.reply(f"**СЖАТАЯ КОПИЯ {i}/{len(chunks)}**\n```\n{chunk}\n```")
        
        # Отправляем простую CSV версию
        simple_chunks = BackupManager.split_for_discord(simple_backup)
        for i, chunk in enumerate(simple_chunks, 1):
            await backup_msg.reply(f"**CSV КОПИЯ {i}/{len(simple_chunks)}**\n```\n{chunk}\n```")
        
        # Сохраняем ID последней резервной копии в конфиг
        backup_config = load_json_file_safe(BACKUP_CONFIG_FILE, {})
        backup_config["last_backup_id"] = backup_msg.id
        backup_config["last_backup_time"] = time.time()
        backup_config["backup_id"] = backup_id
        save_json_file_safe(BACKUP_CONFIG_FILE, backup_config)
        
        # Уведомление
        if interaction:
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
        
        print(f"Резервная копия создана: {backup_msg.id} (ID: {backup_id})")
        return backup_msg.id
        
    except Exception as e:
        print(f"Ошибка при создании резервной копии: {e}")
        if interaction:
            await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)
        return None

async def restore_backup_auto(interaction: discord.Interaction = None, backup_id: str = None):
    """Автоматически восстанавливает из резервной копии"""
    try:
        channel = bot.get_channel(BACKUP_CHANNEL_ID)
        if not channel:
            raise Exception("Канал для резервных копий не найден")
        
        # Ищем резервную копию
        backup_msg = None
        
        if backup_id:
            # Ищем по backup_id в сообщениях
            async for message in channel.history(limit=100):
                if message.author == bot.user and f"ID: {backup_id}" in message.content:
                    backup_msg = message
                    break
            
            if not backup_msg:
                raise Exception(f"Резервная копия с ID {backup_id} не найдена")
        else:
            # Ищем последнюю резервную копию
            async for message in channel.history(limit=50):
                if message.author == bot.user and ("Резервная копия" in message.content or BACKUP_SIGNATURE in message.content):
                    backup_msg = message
                    break
        
        if not backup_msg:
            raise Exception("Резервные копии не найдены")
        
        # Собираем все части сжатой резервной копии
        compressed_data = ""
        async for reply in channel.history(limit=30):
            if reply.reference and reply.reference.message_id == backup_msg.id:
                content = reply.content
                if "СЖАТАЯ КОПИЯ" in content and "```" in content:
                    # Извлекаем данные из кодового блока
                    try:
                        code_block = content.split('```')[1].strip()
                        compressed_data += code_block
                    except:
                        continue
        
        if not compressed_data:
            # Пробуем найти CSV версию
            csv_data = ""
            async for reply in channel.history(limit=30):
                if reply.reference and reply.reference.message_id == backup_msg.id:
                    content = reply.content
                    if "CSV КОПИЯ" in content and "```" in content:
                        try:
                            code_block = content.split('```')[1].strip()
                            csv_data += code_block + '\n'
                        except:
                            continue
            
            if csv_data:
                # Восстанавливаем из CSV
                return await restore_from_csv_text(interaction, csv_data, backup_msg.id)
            else:
                raise Exception("Не удалось найти сжатые данные резервной копии")
        
        # Восстанавливаем из сжатых данных
        payload = BackupManager.decompress_backup(compressed_data)
        if not payload:
            raise Exception("Не удалось декомпрессировать резервную копию")
        
        # Сохраняем данные
        restored_files = 0
        for name, content in payload.get("data", {}).items():
            if content:
                filepath = None
                if name == "balance":
                    filepath = BALANCE_FILE
                elif name == "history":
                    filepath = HISTORY_FILE
                elif name == "approval_map":
                    filepath = APPROVAL_MAP_FILE
                
                if filepath:
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(content)
                    restored_files += 1
        
        # Исправляем кодировку
        fix_json_file_encoding(BALANCE_FILE)
        fix_json_file_encoding(HISTORY_FILE)
        fix_json_file_encoding(APPROVAL_MAP_FILE)
        
        # Обновляем конфиг
        backup_config = load_json_file_safe(BACKUP_CONFIG_FILE, {})
        backup_config["last_restore_time"] = time.time()
        backup_config["last_restore_from"] = backup_msg.id
        save_json_file_safe(BACKUP_CONFIG_FILE, backup_config)
        
        # Отправляем уведомление
        if interaction:
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
        
        print(f"Автовосстановление выполнено из {backup_msg.id}")
        return True
        
    except Exception as e:
        print(f"Ошибка автовосстановления: {e}")
        if interaction:
            await interaction.followup.send(f"❌ Ошибка автовосстановления: {str(e)}", ephemeral=True)
        return False

async def restore_from_text(interaction: discord.Interaction, text_data: str):
    """Восстанавливает из текстового представления"""
    try:
        # Проверяем, это CSV формат или читаемый формат
        if "[BALANCE]" in text_data and "[HISTORY]" in text_data:
            # CSV формат
            return await restore_from_csv_text(interaction, text_data, "text_input")
        else:
            # Читаемый формат
            return await restore_from_human_text(interaction, text_data)
        
    except Exception as e:
        print(f"Ошибка восстановления из текста: {e}")
        await interaction.followup.send(f"❌ Ошибка восстановления: {str(e)}", ephemeral=True)
        return False

async def restore_from_human_text(interaction: discord.Interaction, text_data: str):
    """Восстанавливает из читаемого текстового формата"""
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
        elif "КОНЕЦ РЕЗЕРВНОЙ КОПИИ" in line:
            break
        
        if current_section == "balance" and "->" in line:
            # Формат: ID: 123456789 -> Баланс: 100 скиллов
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
                # Формат: "  1. 2024-01-05 14:30:00: +50 скиллов"
                try:
                    tx_parts = line.strip().split(". ", 1)
                    if len(tx_parts) == 2:
                        tx_info = tx_parts[1]
                        if ":" in tx_info:
                            date_part, rest = tx_info.split(":", 1)
                            if "+" in rest or "-" in rest:
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
        raise

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
        return json.loads(content)
    except:
        try:
            content = filepath.read_bytes()
            for encoding in ['utf-8-sig', 'utf-8', 'utf-16-le', 'utf-16-be', 'cp1251']:
                try:
                    decoded = content.decode(encoding)
                    if decoded.strip() == "":
                        return default
                    return json.loads(decoded)
                except:
                    continue
            
            return default
        except:
            return default

def save_json_file_safe(filepath: Path, data):
    """Безопасно сохраняет JSON файл"""
    try:
        with filepath.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        return True
    except Exception as e:
        print(f"Ошибка сохранения файла {filepath.name}: {e}")
        return False

def load_balance() -> Dict[str, int]:
    """Загружает данные о балансах"""
    return load_json_file_safe(BALANCE_FILE, {})

def save_balance(data: Dict[str, int]):
    """Сохраняет данные о балансах"""
    try:
        save_json_file_safe(BALANCE_FILE, data)
    except Exception as e:
        print(f"Ошибка сохранения баланса: {e}")

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
    return (
        is_admin(member) or
        any(role.id == MOD_ROLE_ID for role in member.roles) or
        any(role.id == SECOND_MOD_ROLE_ID for role in member.roles)
    )

def has_builder_rights(member: discord.Member) -> bool:
    """Проверяет, есть ли у пользователя права строителя"""
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
            icon_url=user.display_avatar.url
        )

    await channel.send(embed=embed)

def add_transaction(user_id: int, amount: int, message_link: str = "", reason: str = ""):
    """Добавляет транзакцию в историю"""
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
    if len(history_data[uid]) > 50:
        history_data[uid] = history_data[uid][-50:]
    
    save_history(history_data)
    
    print(f"Транзакция: {amount:+d} скиллов для {uid} | Причина: {reason[:50]}")

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
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

# ==============================================
# СОБЫТИЕ ПРИ ПОЯВЛЕНИИ НОВОГО УЧАСТНИКА
# ==============================================

@bot.event
async def on_member_join(member: discord.Member):
    """Событие при присоединении нового участника"""
    try:
        # Проверяем, чтобы это был не бот
        if member.bot:
            return
        
        # Проверяем, существует ли канал для подтверждения
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if not welcome_channel:
            print(f"Канал для подтверждения не найден (ID: {WELCOME_CHANNEL_ID})")
            return
        
        # Проверяем, есть ли у пользователя уже одобренная роль
        approved_role = member.guild.get_role(APPROVED_ROLE_ID)
        if approved_role and approved_role in member.roles:
            return  # Уже подтвержден
        
        # Создаем embed для подтверждения
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
        
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Для подтверждения используйте кнопки ниже")
        
        # Создаем кнопки
        view = discord.ui.View(timeout=None)
        
        # Генерируем уникальные custom_id для кнопок
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
        
        async def approve_callback(interaction: discord.Interaction):
            """Коллбэк для кнопки подтверждения"""
            if not has_mod_rights(interaction.user):
                await interaction.response.send_message(
                    "❌ Только модераторы могут подтверждать участников",
                    ephemeral=True
                )
                return
            
            # Даем роль подтвержденного участника
            approved_role = member.guild.get_role(APPROVED_ROLE_ID)
            if approved_role:
                try:
                    await member.add_roles(approved_role, reason="Подтверждение модератором")
                    
                    # Обновляем embed
                    embed.color = discord.Color.green()
                    embed.title = "✅ Участник подтвержден"
                    embed.add_field(
                        name="Модератор",
                        value=interaction.user.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Время",
                        value=f"<t:{int(time.time())}:R>",
                        inline=True
                    )
                    
                    # Отправляем приветственное сообщение участнику
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
                        welcome_dm.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
                        await member.send(embed=welcome_dm)
                    except:
                        pass  # Не отправляем DM если пользователь запретил
                    
                    # Отключаем все кнопки
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await interaction.response.edit_message(embed=embed, view=view)
                    
                    # Логируем действие
                    await log_action(
                        member.guild,
                        "Участник подтвержден",
                        f"**Модератор:** {interaction.user.mention}\n"
                        f"**Участник:** {member.mention} (`{member.id}`)\n"
                        f"**Роль выдана:** {approved_role.mention}",
                        user=interaction.user,
                        color=discord.Color.green()
                    )
                    
                    print(f"Участник {member.id} подтвержден модератором {interaction.user.id}")
                    
                except Exception as e:
                    await interaction.response.send_message(
                        f"❌ Ошибка при выдаче роли: {e}",
                        ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "❌ Роль для подтверждения не найдена",
                    ephemeral=True
                )
        
        async def deny_callback(interaction: discord.Interaction):
            """Коллбэк для кнопки отклонения"""
            if not has_mod_rights(interaction.user):
                await interaction.response.send_message(
                    "❌ Только модераторы могут отклонять участников",
                    ephemeral=True
                )
                return
            
            # Спрашиваем причину
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
                    # Кикаем участника
                    await member.kick(reason=f"Отклонен модератором: {reason}")
                    
                    # Обновляем embed
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
                    
                    # Отключаем все кнопки
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await modal_interaction.response.edit_message(embed=embed, view=view)
                    
                    # Логируем действие
                    await log_action(
                        member.guild,
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
            await interaction.response.send_modal(modal)
        
        async def timeout_callback(interaction: discord.Interaction):
            """Коллбэк для кнопки таймаута"""
            if not has_mod_rights(interaction.user):
                await interaction.response.send_message(
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
                    
                    if duration <= 0 or duration > 168:  # Максимум 7 дней
                        await modal_interaction.response.send_message(
                            "❌ Некорректная длительность. Используйте от 1 до 168 часов.",
                            ephemeral=True
                        )
                        return
                    
                    # Вычисляем время окончания таймаута
                    timeout_duration = datetime.timedelta(hours=duration)
                    timeout_until = discord.utils.utcnow() + timeout_duration
                    
                    # Устанавливаем таймаут
                    await member.timeout(timeout_until, reason=f"Таймаут от модератора: {reason}")
                    
                    # Обновляем embed
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
                    
                    # Отключаем все кнопки
                    for child in view.children:
                        if isinstance(child, discord.ui.Button):
                            child.disabled = True
                    
                    await modal_interaction.response.edit_message(embed=embed, view=view)
                    
                    # Логируем действие
                    await log_action(
                        member.guild,
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
            await interaction.response.send_modal(modal)
        
        # Привязываем коллбэки к кнопкам
        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        timeout_button.callback = timeout_callback
        
        view.add_item(approve_button)
        view.add_item(deny_button)
        view.add_item(timeout_button)
        
        # Отправляем сообщение в канал
        await welcome_channel.send(embed=embed, view=view)
        
        print(f"Создана заявка для нового участника: {member.id} ({member.name})")
        
        # Сохраняем информацию о заявке
        approval_data = load_approval_data()
        approval_data[str(member.id)] = {
            "message_id": None,  # Будет обновлено после отправки
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
async def balance(interaction: discord.Interaction):
    """Команда для просмотра баланса"""
    try:
        user_id = interaction.user.id
        balance_amount = get_balance(user_id)
        
        embed = discord.Embed(
            title=f"💰 Баланс скиллов",
            description=f"**{interaction.user.mention}**, ваш баланс:",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Текущий баланс",
            value=f"**{balance_amount}** скиллов",
            inline=False
        )
        
        # Получаем последние транзакции
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
async def give(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    """Команда для передачи скиллов"""
    try:
        # Проверка на передачу самому себе
        if member.id == interaction.user.id:
            await interaction.response.send_message(
                "❌ Нельзя передавать скиллы самому себе!",
                ephemeral=True
            )
            return
        
        # Проверка баланса отправителя
        sender_balance = get_balance(interaction.user.id)
        if sender_balance < amount:
            await interaction.response.send_message(
                f"❌ Недостаточно скиллов! Ваш баланс: {sender_balance}",
                ephemeral=True
            )
            return
        
        # Проверка прав для больших сумм
        if amount > 500 and not has_mod_rights(interaction.user):
            await interaction.response.send_message(
                "❌ Только модераторы могут передавать более 500 скиллов за раз",
                ephemeral=True
            )
            return
        
        # Выполняем транзакцию
        add_transaction(interaction.user.id, -amount, reason=f"Перевод для {member.name}: {reason}")
        add_transaction(member.id, amount, reason=f"Перевод от {interaction.user.name}: {reason}")
        
        # Создаем embed для подтверждения
        embed = discord.Embed(
            title="✅ Перевод выполнен",
            color=discord.Color.green(),
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
        
        # Логируем действие
        await log_action(
            interaction.guild,
            "Перевод скиллов",
            f"**Отправитель:** {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"**Получатель:** {member.mention} (`{member.id}`)\n"
            f"**Сумма:** {amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=discord.Color.gold()
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
async def top(interaction: discord.Interaction, limit: app_commands.Range[int, 1, 20] = 10):
    """Команда для отображения топа участников"""
    try:
        await interaction.response.defer()
        
        balance_data = load_balance()
        if not balance_data:
            await interaction.followup.send("📭 Балансы участников пусты")
            return
        
        # Сортируем по балансу
        sorted_balance = sorted(balance_data.items(), key=lambda x: x[1], reverse=True)
        
        # Берем только нужное количество
        top_list = sorted_balance[:limit]
        
        # Создаем embed
        embed = discord.Embed(
            title=f"🏆 Топ {len(top_list)} участников по скиллам",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        
        # Получаем информацию об участниках
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
        
        # Добавляем статистику
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
    """Команда для просмотра истории транзакций"""
    try:
        user_id = interaction.user.id
        history = get_history(user_id, limit=limit)
        
        if not history:
            embed = discord.Embed(
                title="📝 История транзакций",
                description="У вас еще нет транзакций",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Создаем embed
        embed = discord.Embed(
            title=f"📝 История транзакций",
            description=f"Последние {len(history)} операций",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        # Добавляем транзакции
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
            
            # Считаем статистику
            if tx["amount"] > 0:
                total_income += tx["amount"]
            else:
                total_outcome += abs(tx["amount"])
        
        # Разделяем историю если слишком длинная
        if len(history_text) > 1024:
            chunks = [history_text[i:i+1024] for i in range(0, len(history_text), 1024)]
            embed.add_field(name="История операций", value=chunks[0], inline=False)
            for i, chunk in enumerate(chunks[1:], 1):
                embed.add_field(name=f"Продолжение {i}", value=chunk, inline=False)
        else:
            embed.add_field(name="Операции", value=history_text or "Нет операций", inline=False)
        
        # Добавляем статистику
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
async def add_skils(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    """Команда для добавления скиллов (только для модераторов)"""
    try:
        if not has_mod_rights(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /add_skils",
                user=interaction.user,
                color=discord.Color.red()
            )
            return await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
        
        # Проверка на добавление себе
        if member.id == interaction.user.id and not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ Нельзя добавлять скиллы себе!",
                ephemeral=True
            )
            return
        
        # Добавляем скиллы
        add_transaction(
            member.id, 
            amount, 
            reason=f"Добавлено модератором {interaction.user.name}: {reason}"
        )
        
        # Создаем embed
        embed = discord.Embed(
            title="✅ Скиллы добавлены",
            color=discord.Color.green(),
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
        
        # Логируем действие
        await log_action(
            interaction.guild,
            "Добавление скиллов",
            f"**Модератор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сумма:** +{amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=discord.Color.green()
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
async def remove_skils(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 1, 100000],
    reason: str = ""
):
    """Команда для удаления скиллов (только для модераторов)"""
    try:
        if not has_mod_rights(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /remove_skils",
                user=interaction.user,
                color=discord.Color.red()
            )
            return await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
        
        # Проверка баланса участника
        current_balance = get_balance(member.id)
        if current_balance < amount:
            await interaction.response.send_message(
                f"❌ У участника недостаточно скиллов! Баланс: {current_balance}",
                ephemeral=True
            )
            return
        
        # Убираем скиллы
        add_transaction(
            member.id, 
            -amount, 
            reason=f"Убрано модератором {interaction.user.name}: {reason}"
        )
        
        # Создаем embed
        embed = discord.Embed(
            title="✅ Скиллы убраны",
            color=discord.Color.orange(),
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
        
        # Логируем действие
        await log_action(
            interaction.guild,
            "Удаление скиллов",
            f"**Модератор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сумма:** -{amount} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=discord.Color.orange()
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
async def set_balance(
    interaction: discord.Interaction,
    member: discord.Member,
    amount: app_commands.Range[int, 0, 1000000],
    reason: str = ""
):
    """Команда для установки баланса (только для админа)"""
    try:
        if not is_admin(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /set_balance",
                user=interaction.user,
                color=discord.Color.red()
            )
            return await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
        
        # Получаем текущий баланс
        current_balance = get_balance(member.id)
        difference = amount - current_balance
        
        # Устанавливаем новый баланс
        balance_data = load_balance()
        balance_data[str(member.id)] = amount
        save_balance(balance_data)
        
        # Записываем в историю
        add_transaction(
            member.id,
            difference,
            reason=f"Баланс установлен администратором {interaction.user.name}: {reason}"
        )
        
        # Создаем embed
        embed = discord.Embed(
            title="✅ Баланс установлен",
            color=discord.Color.purple(),
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
        
        # Логируем действие
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
            color=discord.Color.purple()
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
async def reset_balance(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = ""
):
    """Команда для сброса баланса (только для админа)"""
    try:
        if not is_admin(interaction.user):
            await log_action(
                interaction.guild,
                "Отказ в доступе",
                "Попытка использовать /reset_balance",
                user=interaction.user,
                color=discord.Color.red()
            )
            return await interaction.response.send_message(
                "❌ Только администратор может использовать эту команду",
                ephemeral=True
            )
        
        # Получаем текущий баланс
        current_balance = get_balance(member.id)
        
        if current_balance == 0:
            await interaction.response.send_message(
                f"✅ У участника {member.mention} и так нулевой баланс",
                ephemeral=True
            )
            return
        
        # Сбрасываем баланс
        balance_data = load_balance()
        balance_data[str(member.id)] = 0
        save_balance(balance_data)
        
        # Записываем в историю
        add_transaction(
            member.id,
            -current_balance,
            reason=f"Баланс сброшен администратором {interaction.user.name}: {reason}"
        )
        
        # Создаем embed
        embed = discord.Embed(
            title="⚠️ Баланс сброшен",
            color=discord.Color.red(),
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
        
        # Логируем действие
        await log_action(
            interaction.guild,
            "Сброс баланса",
            f"**Администратор:** {interaction.user.mention}\n"
            f"**Участник:** {member.mention}\n"
            f"**Сброшено:** {current_balance} скиллов\n"
            f"**Причина:** {reason}",
            user=interaction.user,
            color=discord.Color.red()
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
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
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
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if message_id:
        # Восстановление по ID сообщения
        try:
            channel = bot.get_channel(BACKUP_CHANNEL_ID)
            if not channel:
                raise Exception("Канал не найден")
            
            backup_msg = await channel.fetch_message(int(message_id))
            
            # Собираем сжатые данные
            compressed_data = ""
            async for reply in channel.history(limit=30):
                if reply.reference and reply.reference.message_id == backup_msg.id:
                    content = reply.content
                    if "СЖАТАЯ КОПИЯ" in content and "```" in content:
                        try:
                            code_block = content.split('```')[1].strip()
                            compressed_data += code_block
                        except:
                            continue
            
            if not compressed_data:
                await interaction.followup.send("❌ Не найдены сжатые данные в этом сообщении", ephemeral=True)
                return
            
            # Восстанавливаем
            payload = BackupManager.decompress_backup(compressed_data)
            if not payload:
                await interaction.followup.send("❌ Не удалось декомпрессировать данные", ephemeral=True)
                return
            
            # Сохраняем данные
            restored_files = 0
            for name, content in payload.get("data", {}).items():
                if content:
                    filepath = None
                    if name == "balance":
                        filepath = BALANCE_FILE
                    elif name == "history":
                        filepath = HISTORY_FILE
                    
                    if filepath:
                        with open(filepath, "w", encoding="utf-8") as f:
                            f.write(content)
                        restored_files += 1
            
            embed = discord.Embed(
                title="✅ Восстановлено",
                description=f"Данные восстановлены из сообщения {message_id}",
                color=discord.Color.green()
            )
            embed.add_field(name="Восстановлено файлов", value=str(restored_files), inline=True)
            embed.add_field(name="Дата копии", value=payload.get("timestamp", "Неизвестно"), inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
            
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)
            return
    
    # Автоматическое восстановление
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
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    
    if backup_id and not text_data:
        # Извлекаем текст из резервной копии по ID
        try:
            channel = bot.get_channel(BACKUP_CHANNEL_ID)
            if not channel:
                raise Exception("Канал не найден")
            
            # Ищем сообщение с указанным backup_id
            backup_msg = None
            async for message in channel.history(limit=100):
                if message.author == bot.user and f"ID: {backup_id}" in message.content:
                    backup_msg = message
                    break
            
            if not backup_msg:
                raise Exception(f"Резервная копия с ID {backup_id} не найдена")
            
            # Извлекаем читаемую версию
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
        # Восстанавливаем из предоставленного текста
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
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Канал не найден", ephemeral=True)
    
    # Собираем информацию о резервных копиях
    backups = []
    async for message in channel.history(limit=100):
        if message.author == bot.user and ("Резервная копия" in message.content or BACKUP_SIGNATURE in message.content):
            # Извлекаем backup_id из сообщения
            backup_id = "Неизвестно"
            if "ID:" in message.content:
                for line in message.content.split('\n'):
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
    
    # Проверяем наличие сжатых данных для каждой копии
    for backup in backups:
        async for reply in channel.history(limit=20):
            if reply.reference and reply.reference.message_id == backup["id"]:
                if "СЖАТАЯ КОПИЯ" in reply.content:
                    backup["has_compressed"] = True
                if "CSV КОПИЯ" in reply.content:
                    backup["has_csv"] = True
    
    embed = discord.Embed(
        title="📊 Информация о резервных копиях",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    if backups:
        embed.description = f"Найдено резервных копий: {len(backups)}"
        
        # Показываем последние 5 копий
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
    
    # Добавляем кнопки
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
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="data_info", description="Информация о данных (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def data_info(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /data_info",
            user=interaction.user,
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для администратора", ephemeral=True)
    
    balance_data = load_balance()
    history_data = load_history()
    
    total_transactions = sum(len(transactions) for transactions in history_data.values())
    
    # Получаем информацию о последней резервной копии
    backup_config = load_json_file_safe(BACKUP_CONFIG_FILE, {})
    last_backup_time = backup_config.get("last_backup_time")
    last_backup_id = backup_config.get("last_backup_id")
    
    if last_backup_time:
        last_backup_str = f"<t:{int(last_backup_time)}:R>"
        if last_backup_id:
            last_backup_str += f"\nID: `{last_backup_id}`"
    else:
        last_backup_str = "Никогда"
    
    embed = discord.Embed(
        title="📊 Информация о данных",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(
        name="Балансы",
        value=f"Записей: {len(balance_data)}",
        inline=True
    )
    
    embed.add_field(
        name="История транзакций",
        value=f"Всего транзакций: {total_transactions}",
        inline=True
    )
    
    embed.add_field(
        name="Последняя резервная копия",
        value=last_backup_str,
        inline=True
    )
    
    # Размер данных
    total_size = 0
    for file in [BALANCE_FILE, HISTORY_FILE, APPROVAL_MAP_FILE]:
        if file.exists():
            total_size += file.stat().st_size
    
    embed.add_field(
        name="Размер данных",
        value=f"{round(total_size / 1024, 2)} KB",
        inline=True
    )
    
    embed.add_field(
        name="Канал резервных копий",
        value=f"<#{BACKUP_CHANNEL_ID}>",
        inline=True
    )
    
    embed.add_field(
        name="Путь к данным",
        value=f"`{DATA_FOLDER.absolute()}`",
        inline=False
    )
    
    view = discord.ui.View(timeout=180)
    
    backup_button = discord.ui.Button(
        label="🔄 Создать резервную копию",
        style=discord.ButtonStyle.primary,
        custom_id="create_backup_info"
    )
    
    restore_button = discord.ui.Button(
        label="♻️ Восстановить данные",
        style=discord.ButtonStyle.success,
        custom_id="restore_backup_info"
    )
    
    backup_info_button = discord.ui.Button(
        label="📋 Список копий",
        style=discord.ButtonStyle.secondary,
        custom_id="backup_list_info"
    )
    
    async def backup_callback(i: discord.Interaction):
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
        await backup_info_command(i)
    
    backup_button.callback = backup_callback
    restore_button.callback = restore_callback
    backup_info_button.callback = list_callback
    
    view.add_item(backup_button)
    view.add_item(restore_button)
    view.add_item(backup_info_button)
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ==============================================
# КОМАНДЫ ДЛЯ РАБОТЫ С ПОСТРОЙКАМИ
# ==============================================

@bot.tree.command(name="submit_build", description="Отправить постройку на проверку")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    screenshot_url="Ссылка на скриншот постройки",
    description="Описание постройки",
    coordinates="Координаты постройки (если есть)"
)
async def submit_build(
    interaction: discord.Interaction,
    screenshot_url: str,
    description: str = "",
    coordinates: str = ""
):
    """Команда для отправки постройки на проверку"""
    try:
        # Проверяем валидность URL
        if not is_valid_url(screenshot_url):
            await interaction.response.send_message(
                "❌ Пожалуйста, укажите корректную ссылку на изображение",
                ephemeral=True
            )
            return
        
        # Создаем embed для проверки
        embed = discord.Embed(
            title="🏗️ Новая постройка на проверку",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="Автор",
            value=f"{interaction.user.mention} (`{interaction.user.id}`)",
            inline=False
        )
        
        if description:
            embed.add_field(
                name="Описание",
                value=description[:500],
                inline=False
            )
        
        if coordinates:
            embed.add_field(
                name="Координаты",
                value=coordinates,
                inline=True
            )
        
        embed.set_image(url=screenshot_url)
        embed.set_footer(text=f"ID заявки: {int(time.time())}")
        
        # Создаем кнопки для модерации
        view = discord.ui.View(timeout=None)
        
        approve_button = discord.ui.Button(
            label="✅ Одобрить",
            style=discord.ButtonStyle.success,
            custom_id=f"approve_build_{int(time.time())}"
        )
        
        deny_button = discord.ui.Button(
            label="❌ Отклонить",
            style=discord.ButtonStyle.danger,
            custom_id=f"deny_build_{int(time.time())}"
        )
        
        async def approve_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут одобрять постройки",
                    ephemeral=True
                )
                return
            
            # Начисляем награду
            reward = 50  # Базовая награда за постройку
            add_transaction(
                interaction.user.id,
                reward,
                reason=f"Награда за постройку: {description[:100]}"
            )
            
            # Обновляем сообщение
            embed.color = discord.Color.green()
            embed.title = "✅ Постройка одобрена"
            embed.add_field(
                name="Модератор",
                value=i.user.mention,
                inline=True
            )
            embed.add_field(
                name="Награда",
                value=f"+{reward} скиллов",
                inline=True
            )
            
            # Отправляем уведомление автору
            try:
                await interaction.user.send(
                    f"🎉 Ваша постройка была одобрена модератором {i.user.mention}!\n"
                    f"Вы получили **+{reward}** скиллов!"
                )
            except:
                pass  # Не отправляем DM если пользователь запретил
            
            await i.response.edit_message(embed=embed, view=None)
            
            # Логируем действие
            await log_action(
                i.guild,
                "Постройка одобрена",
                f"**Модератор:** {i.user.mention}\n"
                f"**Автор:** {interaction.user.mention}\n"
                f"**Награда:** +{reward} скиллов\n"
                f"**Описание:** {description[:200]}",
                user=i.user,
                color=discord.Color.green()
            )
        
        async def deny_callback(i: discord.Interaction):
            if not has_mod_rights(i.user):
                await i.response.send_message(
                    "❌ Только модераторы могут отклонять постройки",
                    ephemeral=True
                )
                return
            
            # Спрашиваем причину отказа
            modal = discord.ui.Modal(title="Причина отказа")
            modal.add_item(
                discord.ui.TextInput(
                    label="Причина отказа",
                    style=discord.TextStyle.paragraph,
                    placeholder="Укажите причину, по которой постройка отклонена...",
                    required=True
                )
            )
            
            async def modal_callback(modal_interaction: discord.Interaction):
                reason = modal.children[0].value
                
                # Обновляем сообщение
                embed.color = discord.Color.red()
                embed.title = "❌ Постройка отклонена"
                embed.add_field(
                    name="Модератор",
                    value=modal_interaction.user.mention,
                    inline=True
                )
                embed.add_field(
                    name="Причина",
                    value=reason[:500],
                    inline=False
                )
                
                # Отправляем уведомление автору
                try:
                    await interaction.user.send(
                        f"😔 Ваша постройка была отклонена модератором {modal_interaction.user.mention}.\n"
                        f"**Причина:** {reason}"
                    )
                except:
                    pass
                
                await modal_interaction.response.edit_message(embed=embed, view=None)
                
                # Логируем действие
                await log_action(
                    modal_interaction.guild,
                    "Постройка отклонена",
                    f"**Модератор:** {modal_interaction.user.mention}\n"
                    f"**Автор:** {interaction.user.mention}\n"
                    f"**Причина:** {reason[:200]}",
                    user=modal_interaction.user,
                    color=discord.Color.red()
                )
            
            modal.on_submit = modal_callback
            await i.response.send_modal(modal)
        
        approve_button.callback = approve_callback
        deny_button.callback = deny_callback
        
        view.add_item(approve_button)
        view.add_item(deny_button)
        
        # Отправляем заявку в канал проверки
        channel = bot.get_channel(APPROVAL_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed, view=view)
            await interaction.response.send_message(
                "✅ Ваша постройка отправлена на проверку!",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Канал для проверки не найден",
                ephemeral=True
            )
        
    except Exception as e:
        print(f"Ошибка в команде submit_build: {e}")
        await interaction.response.send_message(
            "❌ Произошла ошибка при отправке постройки",
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
async def send_welcome(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = ""
):
    """Команда для повторной отправки приглашения участнику"""
    try:
        if not has_mod_rights(interaction.user):
            await interaction.response.send_message(
                "❌ Только модераторы могут использовать эту команду",
                ephemeral=True
            )
            return
        
        # Проверяем, есть ли у пользователя уже одобренная роль
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
            color=discord.Color.green()
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
            color=discord.Color.green()
        )
        
    except Exception as e:
        print(f"Ошибка в команде send_welcome: {e}")
        await interaction.response.send_message(
            f"❌ Ошибка: {str(e)}",
            ephemeral=True
        )

# ==============================================
# ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ
# ==============================================

@bot.tree.command(name="help", description="Показать список всех команд")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def help_command(interaction: discord.Interaction):
    """Команда помощи"""
    try:
        embed = discord.Embed(
            title="📚 Помощь по командам Skill бота",
            description="Все доступные команды:",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        # Команды для всех пользователей
        embed.add_field(
            name="👤 Основные команды",
            value="• `/balance` - Показать ваш баланс\n"
                  "• `/give [участник] [количество] [причина]` - Передать скиллы\n"
                  "• `/top [количество]` - Топ участников по скиллам\n"
                  "• `/history [количество]` - История ваших транзакций\n"
                  "• `/submit_build [скриншот] [описание]` - Отправить постройку на проверку",
            inline=False
        )
        
        # Команды для модераторов
        if has_mod_rights(interaction.user):
            embed.add_field(
                name="🛡️ Команды модераторов",
                value="• `/add_skils [участник] [количество] [причина]` - Добавить скиллы\n"
                      "• `/remove_skils [участник] [количество] [причина]` - Убрать скиллы\n"
                      "• `/send_welcome [участник] [причина]` - Отправить приглашение",
                inline=False
            )
        
        # Команды для администратора
        if is_admin(interaction.user):
            embed.add_field(
                name="⚙️ Команды администратора",
                value="• `/set_balance [участник] [количество] [причина]` - Установить баланс\n"
                      "• `/reset_balance [участник] [причина]` - Сбросить баланс\n"
                      "• `/backup` - Создать резервную копию\n"
                      "• `/restore_backup [id]` - Восстановить из резервной копии\n"
                      "• `/backup_info` - Информация о резервных копиях\n"
                      "• `/data_info` - Информация о данных",
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
# АВТОМАТИЧЕСКИЕ ЗАДАЧИ И СОБЫТИЯ
# ==============================================

@tasks.loop(hours=6)
async def auto_backup_task():
    """Автоматическое создание резервной копии каждые 6 часов"""
    try:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Запуск автоматического резервного копирования...")
        await create_enhanced_backup()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Автоматическое резервное копирование завершено")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Ошибка автоматического резервного копирования: {e}")

@tasks.loop(minutes=30)
async def check_data_integrity():
    """Проверка целостности данных"""
    try:
        balance_data = load_balance()
        
        if not balance_data:
            print("Данные не найдены. Попытка автовосстановления...")
            try:
                await restore_backup_auto()
                print("Данные восстановлены автоматически")
            except Exception as e:
                print(f"Не удалось восстановить данные: {e}")
    except Exception as e:
        print(f"Ошибка проверки целостности данных: {e}")

@tasks.loop(hours=1)
async def cleanup_old_approvals():
    """Очистка старых сообщений с заявками"""
    try:
        welcome_channel = bot.get_channel(WELCOME_CHANNEL_ID)
        if not welcome_channel:
            return
        
        approval_data = load_approval_data()
        current_time = time.time()
        messages_to_delete = []
        
        # Находим старые сообщения
        async for message in welcome_channel.history(limit=200):
            if message.author == bot.user:
                if message.embeds:
                    embed_title = message.embeds[0].title if message.embeds else ""
                    if "Новый участник" in embed_title or "Участник" in embed_title:
                        message_age_hours = (current_time - message.created_at.timestamp()) / 3600
                        
                        if message_age_hours > APPROVAL_MESSAGE_EXPIRE_HOURS:
                            messages_to_delete.append(message)
        
        # Удаляем старые сообщения
        for message in messages_to_delete:
            try:
                await message.delete()
                print(f"Удалено старое сообщение с заявкой: {message.id}")
            except Exception as e:
                print(f"Ошибка при удалении сообщения {message.id}: {e}")
        
        # Очищаем старые записи из approval_data
        if approval_data:
            updated_data = {}
            for user_id, data in approval_data.items():
                if "created_at" in data:
                    data_age_hours = (current_time - data["created_at"]) / 3600
                    if data_age_hours <= APPROVAL_MESSAGE_EXPIRE_HOURS * 2:  # Храним дольше чем сообщения
                        updated_data[user_id] = data
            
            if len(updated_data) != len(approval_data):
                save_approval_data(updated_data)
                print(f"Очищено {len(approval_data) - len(updated_data)} старых записей о заявках")
                
    except Exception as e:
        print(f"Ошибка при очистке старых заявок: {e}")

@bot.event
async def on_ready():
    """Событие при запуске бота"""
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Бот запущен как {bot.user}")
        print(f"🆔 ID бота: {bot.user.id}")
        print(f"🏰 Сервер ID: {GUILD_ID}")
        print(f"📁 Папка данных: {DATA_FOLDER.absolute()}")
        print(f"👋 Канал для подтверждения: {WELCOME_CHANNEL_ID}")
        
        # Проверяем и восстанавливаем данные при запуске
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
        
        # Запускаем автоматические задачи
        auto_backup_task.start()
        check_data_integrity.start()
        cleanup_old_approvals.start()
        
        print("🔄 Автоматические задачи запущены:")
        print("   • Резервное копирование: каждые 6 часов")
        print("   • Проверка целостности: каждые 30 минут")
        print("   • Очистка старых заявок: каждый час")
        print("🤖 Бот готов к работе!")
        
    except Exception as e:
        print(f"❌ Критическая ошибка в on_ready: {e}")
        import traceback
        traceback.print_exc()

@bot.event
async def setup_hook():
    """Настройка при запуске"""
    print("🔧 Настройка бота...")
    # Здесь можно добавить дополнительную настройку

# Запуск бота
if __name__ == "__main__":
    print("🚀 Запуск бота...")
    bot.run(TOKEN)