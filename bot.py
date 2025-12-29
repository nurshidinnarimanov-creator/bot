import os
import json
import time
import datetime
import shutil
from typing import Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
from urllib.parse import urlparse

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

GUILD_ID = 1423020585881043016
NEWS_CHANNEL_ID = 1444051504444080139
LOG_CHANNEL_ID = 1450910208325980335
APPROVAL_CHANNEL_ID = 1424167988571017326
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
APPROVED_ROLE_ID = 1423344924262273157

DATA_FOLDER = Path("data")
BACKUP_FOLDER = Path("backups")

DATA_FOLDER.mkdir(exist_ok=True)
BACKUP_FOLDER.mkdir(exist_ok=True)

APPROVAL_MAP_FILE = DATA_FOLDER / "approval_map.json"
BALANCE_FILE = DATA_FOLDER / "balance.json"
HISTORY_FILE = DATA_FOLDER / "history.json"
CONFIG_FILE = DATA_FOLDER / "config.json"

if not BALANCE_FILE.exists():
    with BALANCE_FILE.open("w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

if not HISTORY_FILE.exists():
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

if not APPROVAL_MAP_FILE.exists():
    with APPROVAL_MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

if not CONFIG_FILE.exists():
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump({}, f, ensure_ascii=False, indent=2)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def create_backup():
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_FOLDER / f"backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)
        
        files_to_backup = [BALANCE_FILE, HISTORY_FILE, APPROVAL_MAP_FILE]
        for file in files_to_backup:
            if file.exists():
                shutil.copy2(file, backup_path / file.name)
        
        print(f"Резервная копия создана: {backup_path}")
        return True
    except Exception as e:
        print(f"Ошибка при создании резервной копии: {e}")
        return False

def load_balance() -> Dict[str, int]:
    try:
        with BALANCE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_balance(data: Dict[str, int]):
    try:
        create_backup()
        
        with BALANCE_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as e:
        print(f"Ошибка сохранения баланса: {e}")

def load_history() -> Dict[str, List[Dict]]:
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_history(data: Dict[str, List[Dict]]):
    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception as e:
        print(f"Ошибка сохранения истории: {e}")

def load_approval_data():
    try:
        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_approval_data(data: dict):
    try:
        with APPROVAL_MAP_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения данных принятия: {e}")

def restore_from_backup() -> bool:
    try:
        backups = sorted(BACKUP_FOLDER.glob("backup_*"), key=os.path.getmtime)
        if not backups:
            print("Резервные копии не найдены")
            return False
        
        latest_backup = backups[-1]
        print(f"Восстановление из резервной копии: {latest_backup}")
        
        for file_name in ["balance.json", "history.json", "approval_map.json"]:
            backup_file = latest_backup / file_name
            original_file = DATA_FOLDER / file_name
            
            if backup_file.exists():
                shutil.copy2(backup_file, original_file)
        
        return True
    except Exception as e:
        print(f"Ошибка восстановления из резервной копии: {e}")
        return False

def get_data_info() -> Dict[str, any]:
    info = {
        "balance_records": 0,
        "total_history": 0,
        "backup_count": 0,
        "last_backup": None,
        "data_size_mb": 0
    }
    
    balance_data = load_balance()
    info["balance_records"] = len(balance_data)
    
    history_data = load_history()
    total_transactions = sum(len(transactions) for transactions in history_data.values())
    info["total_history"] = total_transactions
    
    backups = list(BACKUP_FOLDER.glob("backup_*"))
    info["backup_count"] = len(backups)
    if backups:
        latest_backup = max(backups, key=os.path.getmtime)
        info["last_backup"] = datetime.datetime.fromtimestamp(
            os.path.getmtime(latest_backup)
        ).strftime("%Y-%m-%d %H:%M:%S")
    
    total_size = 0
    for file in [BALANCE_FILE, HISTORY_FILE, APPROVAL_MAP_FILE]:
        if file.exists():
            total_size += file.stat().st_size
    info["data_size_mb"] = round(total_size / (1024 * 1024), 2)
    
    return info

def add_transaction(user_id: int, amount: int, message_link: str = "", reason: str = ""):
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
    return load_balance().get(str(user_id), 0)

def get_history(user_id: int, limit: int = 10) -> List[Dict]:
    uid = str(user_id)
    history_data = load_history()
    if uid not in history_data:
        return []
    return history_data[uid][-limit:]

def export_balance_csv() -> str:
    balance_data = load_balance()
    if not balance_data:
        return "Нет данных для экспорта"
    
    csv_lines = ["ID пользователя,Баланс"]
    
    sorted_balance = sorted(balance_data.items(), key=lambda x: x[1], reverse=True)
    
    for user_id, balance in sorted_balance:
        csv_lines.append(f"{user_id},{balance}")
    
    filename = DATA_FOLDER / f"balance_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(csv_lines))
    
    return str(filename)

def find_approval_by_custom_id(data: dict, custom_id: str):
    for msg_id, info in data.items():
        if info["approve_cid"] == custom_id or info["deny_cid"] == custom_id:
            return msg_id, info
    return None, None

def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

def is_admin(member: discord.Member) -> bool:
    return member.id == ADMIN_USER_ID

def has_mod_rights(member: discord.Member) -> bool:
    return (
        member.id == ADMIN_USER_ID or
        any(role.id == MOD_ROLE_ID for role in member.roles)
    )

async def log_action(
    guild: discord.Guild,
    title: str,
    description: str,
    user: discord.Member | None = None,
    color: discord.Color = discord.Color.blurple()
):
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

class MemberApprovalView(discord.ui.View):
    def __init__(self, approve_cid: str, deny_cid: str):
        super().__init__(timeout=None)

        self.approve_btn = discord.ui.Button(
            label="Подтвердить",
            style=discord.ButtonStyle.success,
            custom_id=approve_cid
        )
        self.deny_btn = discord.ui.Button(
            label="Отклонить",
            style=discord.ButtonStyle.danger,
            custom_id=deny_cid
        )

        self.approve_btn.callback = self.approve
        self.deny_btn.callback = self.deny

        self.add_item(self.approve_btn)
        self.add_item(self.deny_btn)

    async def _disable(self, interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    async def approve(self, interaction: discord.Interaction):
        if not has_mod_rights(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        data = load_approval_data()
        msg_id, info = find_approval_by_custom_id(data, interaction.data["custom_id"])
        if not info:
            return await interaction.response.send_message("Уже обработано", ephemeral=True)

        member = interaction.guild.get_member(info["member_id"])
        role = interaction.guild.get_role(APPROVED_ROLE_ID)

        if member and role:
            await member.add_roles(role)

        await log_action(
            interaction.guild,
            "Участник принят",
            f"Участник: {member.mention}",
            user=interaction.user,
            color=discord.Color.green()
        )

        data.pop(msg_id, None)
        save_approval_data(data)

        await self._disable(interaction)
        await interaction.response.send_message("Принят", ephemeral=True)

    async def deny(self, interaction: discord.Interaction):
        if not has_mod_rights(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        data = load_approval_data()
        msg_id, info = find_approval_by_custom_id(data, interaction.data["custom_id"])

        member = interaction.guild.get_member(info["member_id"])
        if member:
            await member.kick(reason="Отклонён")

        await log_action(
            interaction.guild,
            "Участник отклонён",
            f"ID участника: `{info['member_id']}`",
            user=interaction.user,
            color=discord.Color.red()
        )

        data.pop(msg_id, None)
        save_approval_data(data)
        await self._disable(interaction)

class HistoryView(discord.ui.View):
    def __init__(self, user_id: int, user_name: str):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_name = user_name
        self.page = 0
        self.transactions_per_page = 5

    def get_page_embed(self) -> discord.Embed:
        history = get_history(self.user_id, limit=50)
        if not history:
            return discord.Embed(
                title=f"История начислений - {self.user_name}",
                description="Нет данных о транзакциях.",
                color=discord.Color.blue()
            )
        
        total_pages = (len(history) + self.transactions_per_page - 1) // self.transactions_per_page
        start_idx = self.page * self.transactions_per_page
        end_idx = min(start_idx + self.transactions_per_page, len(history))
        
        embed = discord.Embed(
            title=f"История начислений - {self.user_name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        total_amount = sum(t["amount"] for t in history)
        embed.set_footer(text=f"Страница {self.page + 1}/{total_pages} • Всего получено: {total_amount} скиллов")
        
        for i in range(start_idx, end_idx):
            t = history[-(i+1)]
            sign = "➕" if t["amount"] > 0 else "➖"
            amount_text = f"{sign} {abs(t['amount'])} скиллов"
            
            description = f"**{amount_text}**\n"
            description += f"📅 {t['datetime']}\n"
            if t["reason"]:
                description += f"📝 {t['reason']}\n"
            if t["message_link"]:
                description += f"[Ссылка на сообщение]({t['message_link']})"
            
            embed.add_field(
                name=f"Транзакция #{len(history)-i}",
                value=description,
                inline=False
            )
        
        return embed

    @discord.ui.button(label="◀️ Назад", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        history = get_history(self.user_id, limit=50)
        total_pages = (len(history) + self.transactions_per_page - 1) // self.transactions_per_page
        
        if self.page > 0:
            self.page -= 1
            await interaction.response.edit_message(embed=self.get_page_embed())
        else:
            await interaction.response.send_message("Это первая страница", ephemeral=True)

    @discord.ui.button(label="▶️ Вперед", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        history = get_history(self.user_id, limit=50)
        total_pages = (len(history) + self.transactions_per_page - 1) // self.transactions_per_page
        
        if self.page < total_pages - 1:
            self.page += 1
            await interaction.response.edit_message(embed=self.get_page_embed())
        else:
            await interaction.response.send_message("Это последняя страница", ephemeral=True)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            await self.message.edit(view=self)

class NewsControlView(discord.ui.View):
    def __init__(self, author_id: int, author_name: str = ""):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.author_name = author_name
        self.published = False

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _):
        if self.published:
            return await interaction.response.send_message("Уже опубликовано", ephemeral=True)
        
        channel = bot.get_channel(NEWS_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message("Канал не найден", ephemeral=True)
        
        await channel.send(embeds=interaction.message.embeds)
        
        author = interaction.guild.get_member(self.author_id)
        author_name_display = self.author_name or (author.mention if author else str(self.author_id))
        
        await log_action(
            interaction.guild,
            "Публикация через /panel",
            f"Автор публикации: {author_name_display} | Опубликовал: {interaction.user.mention}",
            user=interaction.user,
            color=discord.Color.green()
        )
        
        self.published = True
        for item in self.children:
            item.disabled = True
        
        await interaction.message.edit(view=self)
        await interaction.response.send_message(
            f"✅ Опубликовано! Автор: {author_name_display}",
            ephemeral=True
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _):
        await log_action(
            interaction.guild,
            "Предпросмотр публикации удалён",
            f"Удалил: {interaction.user.mention}",
            user=interaction.user,
            color=discord.Color.red()
        )
        await interaction.message.delete()

class NewsConstructorModal(discord.ui.Modal, title="Конструктор публикации"):
    news_title = discord.ui.TextInput(label="Заголовок")
    author_nick = discord.ui.TextInput(label="Кто выполнил работу", required=False)
    news_text = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph)
    image_links = discord.ui.TextInput(label="Ссылки на изображения", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        embeds = []

        main = discord.Embed(
            title=self.news_title.value,
            description=self.news_text.value,
            color=discord.Color.dark_red()
        )

        author_member = None
        author_name = ""
        
        if self.author_nick.value:
            for member in interaction.guild.members:
                if (self.author_nick.value.lower() in member.display_name.lower() or 
                    self.author_nick.value.lower() in member.name.lower()):
                    author_member = member
                    author_name = member.display_name
                    break
            
            if author_member:
                main.add_field(name="Выполнил работу", value=author_member.mention, inline=False)
            else:
                main.add_field(name="Выполнил работу", value=self.author_nick.value, inline=False)
                author_name = self.author_nick.value

        main.set_footer(text="Ashra_team")
        embeds.append(main)

        if self.image_links.value:
            for link in self.image_links.value.splitlines():
                if is_valid_url(link.strip()):
                    img = discord.Embed(color=discord.Color.dark_red())
                    img.set_image(url=link.strip())
                    embeds.append(img)

        await log_action(
            interaction.guild,
            "Создан предпросмотр публикации",
            f"Автор запроса: {interaction.user.mention}",
            user=interaction.user
        )

        author_id = author_member.id if author_member else interaction.user.id
        
        await interaction.response.send_message(
            embeds=embeds,
            view=NewsControlView(author_id, author_name)
        )

@bot.tree.command(name="panel", description="Панель публикаций")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def panel(interaction: discord.Interaction):
    await log_action(
        interaction.guild,
        "Использована команда /panel",
        f"Пользователь: {interaction.user.mention}",
        user=interaction.user
    )

    embed = discord.Embed(
        title="Конструктор публикации",
        description="Нажмите кнопку ниже",
        color=discord.Color.blurple()
    )

    button = discord.ui.Button(label="Создать публикацию")

    async def cb(i: discord.Interaction):
        await i.response.send_modal(NewsConstructorModal())

    button.callback = cb
    view = discord.ui.View()
    view.add_item(button)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="balance", description="Ваш баланс")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def balance(interaction: discord.Interaction):
    bal = get_balance(interaction.user.id)
    
    embed = discord.Embed(
        title="💰 Ваш баланс",
        description=f"**{bal} скиллов**",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(text=f"ID: {interaction.user.id}")
    
    view = discord.ui.View()
    history_button = discord.ui.Button(
        label="История начислений",
        style=discord.ButtonStyle.primary,
        emoji="📊"
    )
    
    async def history_cb(i: discord.Interaction):
        history_view = HistoryView(interaction.user.id, interaction.user.display_name)
        history_embed = history_view.get_page_embed()
        await i.response.send_message(embed=history_embed, view=history_view, ephemeral=True)
        history_view.message = await i.original_response()
    
    history_button.callback = history_cb
    view.add_item(history_button)
    
    await log_action(
        interaction.guild,
        "Проверка баланса",
        f"{interaction.user.mention}: {bal} скиллов",
        user=interaction.user
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="top", description="Топ участников по скилкоинам")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def top(interaction: discord.Interaction):
    balance_data = load_balance()
    
    sorted_users = sorted(balance_data.items(), key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(
        title="🏆 Топ участников по скилкоинам",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    
    for i, (user_id, balance) in enumerate(sorted_users[:10], 1):
        member = interaction.guild.get_member(int(user_id))
        if member:
            name = member.display_name
            avatar = member.display_avatar.url if i <= 3 else ""
        else:
            name = f"Участник {user_id}"
            avatar = ""
        
        medal = ""
        if i == 1: medal = "🥇 "
        elif i == 2: medal = "🥈 "
        elif i == 3: medal = "🥉 "
        
        embed.add_field(
            name=f"{medal}{i}. {name}",
            value=f"**{balance}** скиллов",
            inline=False
        )
        
        if i <= 3 and avatar:
            if i == 1:
                embed.set_thumbnail(url=avatar)
    
    await log_action(
        interaction.guild,
        "Просмотр топа",
        f"Пользователь: {interaction.user.mention}",
        user=interaction.user
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def execute_give(interaction: discord.Interaction, 
                      member: discord.Member, 
                      amount: int, 
                      reason: str,
                      current_balance: int):
    
    message_link = ""
    if interaction.channel:
        message_link = f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}/{interaction.id}"
    
    add_transaction(
        user_id=member.id,
        amount=amount,
        message_link=message_link,
        reason=reason or f"Выдано администратором {interaction.user.display_name}"
    )
    
    new_balance = get_balance(member.id)
    
    embed = discord.Embed(
        title="✅ Скилкоины успешно выданы",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(name="Администратор", value=interaction.user.mention, inline=True)
    embed.add_field(name="Получатель", value=member.mention, inline=True)
    embed.add_field(name="Сумма", value=f"**{'+' if amount > 0 else ''}{amount}** скиллов", inline=True)
    embed.add_field(name="Было", value=f"{current_balance} скиллов", inline=True)
    embed.add_field(name="Стало", value=f"{new_balance} скиллов", inline=True)
    embed.add_field(name="Изменение", value=f"{'+' if amount > 0 else ''}{amount}", inline=True)
    
    if reason:
        embed.add_field(name="📝 Причина", value=reason, inline=False)
    
    embed.set_footer(text=f"ID транзакции: {int(time.time())}")
    
    await log_action(
        interaction.guild,
        "Выдача скилкоинов",
        f"{interaction.user.mention} → {member.mention}: {amount} скиллов\nПричина: {reason or 'Не указана'}",
        user=interaction.user,
        color=discord.Color.green()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    try:
        if amount > 0:
            title = "💰 Вы получили скилкоины!"
            color = discord.Color.green()
        elif amount < 0:
            title = "⚠️ С вашего счёта списаны скилкоины"
            color = discord.Color.orange()
        else:
            title = "ℹ️ Информация о балансе"
            color = discord.Color.blue()
        
        notify_embed = discord.Embed(
            title=title,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        
        notify_embed.add_field(
            name="Сумма", 
            value=f"{'+' if amount > 0 else ''}{amount} скиллов", 
            inline=True
        )
        notify_embed.add_field(
            name="Текущий баланс", 
            value=f"{new_balance} скиллов", 
            inline=True
        )
        
        if reason:
            notify_embed.add_field(name="Причина", value=reason, inline=False)
        
        notify_embed.add_field(name="Администратор", value=interaction.user.mention, inline=False)
        notify_embed.set_footer(text=f"ID транзакции: {int(time.time())}")
        
        await member.send(embed=notify_embed)
        
    except discord.Forbidden:
        await log_action(
            interaction.guild,
            "Не удалось отправить уведомление",
            f"Не удалось отправить ЛС {member.mention} о выдаче скилкоинов",
            user=interaction.user,
            color=discord.Color.orange()
        )
    except Exception as e:
        await log_action(
            interaction.guild,
            "Ошибка при отправке уведомления",
            f"Ошибка: {str(e)[:100]}...",
            user=interaction.user,
            color=discord.Color.red()
        )

@bot.tree.command(name="give", description="Выдать скилкоины (админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    member="Участник, которому выдать скилкоины",
    amount="Количество скиллов (можно отрицательное)",
    reason="Причина выдачи"
)
async def give(interaction: discord.Interaction, 
              member: discord.Member,
              amount: int,
              reason: str = ""):
    
    if interaction.user.id != ADMIN_USER_ID:
        await log_action(
            interaction.guild,
            "Попытка несанкционированного доступа к /give",
            f"Пользователь {interaction.user.mention} (ID: {interaction.user.id}) попытался использовать команду /give",
            user=interaction.user,
            color=discord.Color.red()
        )
        
        embed = discord.Embed(
            title="❌ Отказано в доступе",
            description="Эта команда доступна только владельцу бота.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Требуемый ID пользователя",
            value=f"`{ADMIN_USER_ID}`",
            inline=False
        )
        embed.set_footer(text=f"Ваш ID: {interaction.user.id}")
        
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    if interaction.guild.owner_id != interaction.user.id:
        await log_action(
            interaction.guild,
            "Предупреждение: /give использован не владельцем сервера",
            f"Команду использовал {interaction.user.mention} (не владелец сервера)",
            user=interaction.user,
            color=discord.Color.orange()
        )
    
    if abs(amount) > 10000:
        embed = discord.Embed(
            title="❌ Превышен лимит",
            description="Слишком большая сумма за одну транзакцию.",
            color=discord.Color.red()
        )
        embed.add_field(name="Максимальный лимит", value="10000 скиллов", inline=True)
        embed.add_field(name="Запрошенная сумма", value=f"{amount} скиллов", inline=True)
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    if member.id == interaction.user.id:
        embed = discord.Embed(
            title="❌ Некорректный получатель",
            description="Нельзя выдавать скилкоины самому себе.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Используйте", 
            value="Для изменения своего баланса обратитесь к другому администратору.",
            inline=False
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    if member.bot:
        embed = discord.Embed(
            title="❌ Некорректный получатель",
            description="Нельзя выдавать скилкоины ботам.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    current_balance = get_balance(member.id)
    
    if abs(amount) >= 5000:
        embed = discord.Embed(
            title="⚠️ Подтвердите действие",
            description=f"Вы собираетесь **{'выдать' if amount > 0 else 'списать'} {abs(amount)} скиллов**.",
            color=discord.Color.gold()
        )
        embed.add_field(name="Получатель", value=member.mention, inline=True)
        embed.add_field(name="Текущий баланс", value=f"{current_balance} скиллов", inline=True)
        embed.add_field(name="Новый баланс", value=f"{current_balance + amount} скиллов", inline=False)
        if reason:
            embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text="Это действие будет записано в лог")
        
        confirm_view = discord.ui.View(timeout=30)
        
        confirm_button = discord.ui.Button(
            label="✅ Подтвердить",
            style=discord.ButtonStyle.success
        )
        
        cancel_button = discord.ui.Button(
            label="❌ Отменить",
            style=discord.ButtonStyle.danger
        )
        
        async def confirm_callback(i: discord.Interaction):
            if i.user.id != interaction.user.id:
                return await i.response.send_message("❌ Только инициатор может подтвердить действие.", ephemeral=True)
            
            await execute_give(i, member, amount, reason, current_balance)
        
        async def cancel_callback(i: discord.Interaction):
            if i.user.id != interaction.user.id:
                return await i.response.send_message("❌ Только инициатор может отменить действие.", ephemeral=True)
            
            embed = discord.Embed(
                title="❌ Действие отменено",
                description="Выдача скилкоинов отменена пользователем.",
                color=discord.Color.red()
            )
            
            for item in confirm_view.children:
                item.disabled = True
            
            await i.response.edit_message(embed=embed, view=confirm_view)
            await log_action(
                interaction.guild,
                "Выдача скилкоинов отменена",
                f"{interaction.user.mention} отменил выдачу {amount} скиллов {member.mention}",
                user=interaction.user,
                color=discord.Color.orange()
            )
        
        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        
        confirm_view.add_item(confirm_button)
        confirm_view.add_item(cancel_button)
        
        await interaction.response.send_message(embed=embed, view=confirm_view, ephemeral=True)
        return
    
    await execute_give(interaction, member, amount, reason, current_balance)

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
    
    info = get_data_info()
    
    embed = discord.Embed(
        title="📊 Информация о данных",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    embed.add_field(
        name="Балансы",
        value=f"Записей: {info['balance_records']}",
        inline=True
    )
    
    embed.add_field(
        name="История транзакций",
        value=f"Всего транзакций: {info['total_history']}",
        inline=True
    )
    
    embed.add_field(
        name="Резервные копии",
        value=f"Количество: {info['backup_count']}",
        inline=True
    )
    
    if info['last_backup']:
        embed.add_field(
            name="Последняя резервная копия",
            value=info['last_backup'],
            inline=False
        )
    
    embed.add_field(
        name="Размер данных",
        value=f"{info['data_size_mb']} MB",
        inline=True
    )
    
    embed.add_field(
        name="Путь к данным",
        value=f"`{DATA_FOLDER.absolute()}`",
        inline=False
    )
    
    view = discord.ui.View()
    
    backup_button = discord.ui.Button(
        label="🔄 Создать резервную копию",
        style=discord.ButtonStyle.primary
    )
    
    restore_button = discord.ui.Button(
        label="♻️ Восстановить из резервной копии",
        style=discord.ButtonStyle.secondary
    )
    
    export_button = discord.ui.Button(
        label="📤 Экспорт в CSV",
        style=discord.ButtonStyle.success
    )
    
    async def backup_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        
        success = create_backup()
        if success:
            await i.response.send_message("✅ Резервная копия создана!", ephemeral=True)
        else:
            await i.response.send_message("❌ Ошибка при создании резервной копии", ephemeral=True)
    
    async def restore_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        
        confirm_embed = discord.Embed(
            title="⚠️ Подтвердите восстановление",
            description="Это действие заменит текущие данные на данные из последней резервной копии.",
            color=discord.Color.orange()
        )
        
        confirm_view = discord.ui.View(timeout=30)
        
        yes_button = discord.ui.Button(label="✅ Да, восстановить", style=discord.ButtonStyle.danger)
        no_button = discord.ui.Button(label="❌ Нет, отменить", style=discord.ButtonStyle.secondary)
        
        async def yes_callback(ii: discord.Interaction):
            if not is_admin(ii.user):
                return await ii.response.send_message("❌ Только для администратора", ephemeral=True)
            
            success = restore_from_backup()
            if success:
                await ii.response.send_message("✅ Данные восстановлены из резервной копии!", ephemeral=True)
            else:
                await ii.response.send_message("❌ Ошибка при восстановлении", ephemeral=True)
        
        async def no_callback(ii: discord.Interaction):
            if not is_admin(ii.user):
                return await ii.response.send_message("❌ Только для администратора", ephemeral=True)
            
            await ii.response.send_message("❌ Восстановление отменено", ephemeral=True)
        
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        
        confirm_view.add_item(yes_button)
        confirm_view.add_item(no_button)
        
        await i.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)
    
    async def export_callback(i: discord.Interaction):
        if not is_admin(i.user):
            return await i.response.send_message("❌ Только для администратора", ephemeral=True)
        
        filename = export_balance_csv()
        if "Нет данных" in filename:
            await i.response.send_message("❌ Нет данных для экспорта", ephemeral=True)
        else:
            await i.response.send_message(f"✅ Данные экспортированы в: `{filename}`", ephemeral=True)
    
    backup_button.callback = backup_callback
    restore_button.callback = restore_callback
    export_button.callback = export_callback
    
    view.add_item(backup_button)
    view.add_item(restore_button)
    view.add_item(export_button)
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class BuildersReportModal(discord.ui.Modal, title="Отчёт по работе"):
    report_title = discord.ui.TextInput(label="Заголовок отчёта")
    nick = discord.ui.TextInput(label="Ник исполнителя")
    reward = discord.ui.TextInput(label="Заработок")
    description = discord.ui.TextInput(label="Описание работы", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.report_title.value, color=discord.Color.dark_red())
        
        author_member = None
        author_name = self.nick.value
        for member in interaction.guild.members:
            if (self.nick.value.lower() in member.display_name.lower() or 
                self.nick.value.lower() in member.name.lower()):
                author_member = member
                author_name = member.display_name
                break
        
        if author_member:
            embed.add_field(
                name=f"Исполнитель: {author_member.mention}",
                value=f"Заработок: {self.reward.value}\n{self.description.value}",
                inline=False
            )
            author_id = author_member.id
        else:
            embed.add_field(
                name=f"Исполнитель: {self.nick.value}",
                value=f"Заработок: {self.reward.value}\n{self.description.value}",
                inline=False
            )
            author_id = interaction.user.id
        
        embed.set_footer(text="Ashra_team")

        await log_action(
            interaction.guild,
            "Создан отчёт",
            f"Исполнитель: {self.nick.value}",
            user=interaction.user
        )

        await interaction.response.send_message(
            embed=embed, 
            view=NewsControlView(author_id, author_name)
        )

@bot.tree.command(name="news", description="Отчёт (только админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def news(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /news",
            user=interaction.user,
            color=discord.Color.red()
        )
        return await interaction.response.send_message("Нет доступа", ephemeral=True)

    embed = discord.Embed(
        title="Отчёт по работе",
        description="Создать отчёт",
        color=discord.Color.blurple()
    )

    button = discord.ui.Button(label="Создать отчёт")

    async def cb(i: discord.Interaction):
        await i.response.send_modal(BuildersReportModal())

    button.callback = cb
    view = discord.ui.View()
    view.add_item(button)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class BuildRatingModal(discord.ui.Modal, title="Оценка постройки"):
    builder_nick = discord.ui.TextInput(label="Ник строителя")
    build_description = discord.ui.TextInput(
        label="Описание постройки", 
        style=discord.TextStyle.paragraph
    )
    image_links = discord.ui.TextInput(
        label="Ссылки на скриншоты/видео", 
        style=discord.TextStyle.paragraph,
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        description_lower = self.build_description.value.lower()
        
        base_score = 500
        if len(self.build_description.value) > 200:
            base_score += 100
        if "крупн" in description_lower or "больш" in description_lower:
            base_score += 200
        if "детал" in description_lower or "прорабо" in description_lower:
            base_score += 150
        if "уникальн" in description_lower or "оригинальн" in description_lower:
            base_score += 200
        if self.image_links.value:
            base_score += 100
            
        final_score = min(base_score, 1500)
        
        builder_member = None
        for member in interaction.guild.members:
            if (self.builder_nick.value.lower() in member.display_name.lower() or 
                self.builder_nick.value.lower() in member.name.lower()):
                builder_member = member
                break
        
        embed = discord.Embed(
            title="🏗️ Оценка постройки",
            color=discord.Color.dark_green()
        )
        
        if builder_member:
            embed.add_field(name="Строитель", value=builder_member.mention, inline=True)
            builder_id = builder_member.id
            builder_name = builder_member.display_name
        else:
            embed.add_field(name="Строитель", value=self.builder_nick.value, inline=True)
            builder_id = interaction.user.id
            builder_name = self.builder_nick.value
        
        embed.add_field(name="Оценка", value=f"**{final_score}** скиллов", inline=True)
        embed.add_field(name="Описание", value=self.build_description.value, inline=False)
        
        if self.image_links.value:
            links = [link.strip() for link in self.image_links.value.splitlines() if is_valid_url(link.strip())]
            if links:
                embed.add_field(name="Материалы", value=f"{len(links)} прикреплено", inline=False)
        
        embed.set_footer(text="Автоматическая оценка")
        
        view = discord.ui.View()
        
        confirm_button = discord.ui.Button(
            label=f"Подтвердить ({final_score} скиллов)",
            style=discord.ButtonStyle.success
        )
        
        async def confirm_cb(i: discord.Interaction):
            if not has_mod_rights(i.user):
                return await i.response.send_message("❌ Только для модераторов", ephemeral=True)
            
            message_link = ""
            if i.channel:
                message_link = f"https://discord.com/channels/{i.guild.id}/{i.channel.id}/{i.message.id}"
            
            add_transaction(
                user_id=builder_id,
                amount=final_score,
                message_link=message_link,
                reason=f"Оценка постройки: {self.build_description.value[:100]}..."
            )
            
            new_balance = get_balance(builder_id)
            
            success_embed = discord.Embed(
                title="✅ Начисление подтверждено",
                color=discord.Color.green()
            )
            success_embed.add_field(name="Строитель", value=builder_name, inline=True)
            success_embed.add_field(name="Начислено", value=f"{final_score} скиллов", inline=True)
            success_embed.add_field(name="Новый баланс", value=f"{new_balance} скиллов", inline=True)
            success_embed.add_field(name="Проверил", value=i.user.mention, inline=False)
            
            await log_action(
                i.guild,
                "Оценка постройки",
                f"{i.user.mention} начислил {final_score} скиллов за постройку",
                user=i.user,
                color=discord.Color.green()
            )
            
            for item in view.children:
                item.disabled = True
            await i.message.edit(embed=success_embed, view=view)
            await i.response.send_message(f"✅ Начислено {final_score} скиллов {builder_name}", ephemeral=True)
        
        confirm_button.callback = confirm_cb
        view.add_item(confirm_button)
        
        adjust_button = discord.ui.Button(
            label="Изменить сумму",
            style=discord.ButtonStyle.primary
        )
        
        async def adjust_cb(i: discord.Interaction):
            if not has_mod_rights(i.user):
                return await i.response.send_message("❌ Только для модераторов", ephemeral=True)
            
            modal = discord.ui.Modal(title="Корректировка суммы")
            modal.add_item(discord.ui.TextInput(
                label="Новая сумма",
                default=str(final_score)
            ))
            
            async def modal_submit(m_interaction: discord.Interaction):
                try:
                    new_amount = int(m_interaction.data["components"][0]["components"][0]["value"])
                    if abs(new_amount) > 5000:
                        return await m_interaction.response.send_message(
                            "❌ Максимум 5000 скиллов",
                            ephemeral=True
                        )
                    
                    embed.set_field_at(
                        1,
                        name="Оценка",
                        value=f"**{new_amount}** скиллов (скорректировано)",
                        inline=True
                    )
                    
                    for item in view.children:
                        if isinstance(item, discord.ui.Button) and item.label.startswith("Подтвердить"):
                            item.label = f"Подтвердить ({new_amount} скиллов)"
                    
                    await m_interaction.response.edit_message(embed=embed, view=view)
                    
                except ValueError:
                    await m_interaction.response.send_message("❌ Введите число", ephemeral=True)
            
            modal.on_submit = modal_submit
            await i.response.send_modal(modal)
        
        adjust_button.callback = adjust_cb
        view.add_item(adjust_button)
        
        await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="rate_build", description="Оценить постройку")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def rate_build(interaction: discord.Interaction):
    if not has_mod_rights(interaction.user):
        await log_action(
            interaction.guild,
            "Отказ в доступе",
            "Попытка использовать /rate_build",
            user=interaction.user,
            color=discord.Color.red()
        )
        return await interaction.response.send_message("❌ Только для модераторов", ephemeral=True)
    
    await interaction.response.send_modal(BuildRatingModal())

@bot.event
async def on_ready():
    if not list(BACKUP_FOLDER.glob("backup_*")):
        print("Создаем начальную резервную копию...")
        create_backup()
    
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Бот запущен как {bot.user}")
    
    info = get_data_info()
    print(f"Загружено записей баланса: {info['balance_records']}")
    print(f"Всего транзакций: {info['total_history']}")
    print(f"Резервных копий: {info['backup_count']}")
    print(f"Путь к данным: {DATA_FOLDER.absolute()}")
    
    bot.add_view(MemberApprovalView("approve_temp", "deny_temp"))

bot.run(TOKEN)