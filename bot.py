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
from pathlib import Path
from urllib.parse import urlparse

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

GUILD_ID = 1423020585881043016
BACKUP_CHANNEL_ID = 1450910208325980335  # ID канала для хранения резервных копий
LOG_CHANNEL_ID = 1450910208325980335
APPROVAL_CHANNEL_ID = 1424167988571017326
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
SECOND_MOD_ROLE_ID = 1454381506934865986
BUILDER_ROLE_ID = 1423344924262273157
APPROVED_ROLE_ID = 1423344924262273157

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
            json_str = zlib.decompress(compressed).decode('utf-8')
            
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

# Классы представлений для Discord
class MemberApprovalView(discord.ui.View):
    """Представление для одобрения участников"""
    def __init__(self, approve_cid: str, deny_cid: str):
        super().__init__(timeout=None)
        self.approve_cid = approve_cid
        self.deny_cid = deny_cid

class HistoryView(discord.ui.View):
    """Представление для навигации по истории"""
    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.page = page

# Discord команды
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

# Автоматические задачи
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

@bot.event
async def on_ready():
    """Событие при запуске бота"""
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"✅ Бот запущен как {bot.user}")
        print(f"🆔 ID бота: {bot.user.id}")
        print(f"🏰 Сервер ID: {GUILD_ID}")
        print(f"📁 Папка данных: {DATA_FOLDER.absolute()}")
        
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
        
        print("🔄 Автоматические задачи запущены:")
        print("   • Резервное копирование: каждые 6 часов")
        print("   • Проверка целостности: каждые 30 минут")
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