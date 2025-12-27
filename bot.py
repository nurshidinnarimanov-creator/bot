import os
import json
import time
import discord

from discord import app_commands
from discord.ext import commands
from pathlib import Path
from urllib.parse import urlparse

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

GUILD_ID = 1423020585881043016
NEWS_CHANNEL_ID = 1446886182913970377
LOG_CHANNEL_ID = 1450910208325980335
APPROVAL_CHANNEL_ID = NEWS_CHANNEL_ID
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
APPROVED_ROLE_ID = 1423344924262273157

APPROVAL_MAP_FILE = Path("approval_map.json")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

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

def load_approval_data():
    if not APPROVAL_MAP_FILE.exists():
        return {}
    with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_approval_data(data: dict):
    with APPROVAL_MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def find_approval_by_custom_id(data: dict, custom_id: str):
    for msg_id, info in data.items():
        if info["approve_cid"] == custom_id or info["deny_cid"] == custom_id:
            return msg_id, info
    return None, None

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

class NewsControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _):
        if not has_mod_rights(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        channel = bot.get_channel(NEWS_CHANNEL_ID)
        await channel.send(embeds=interaction.message.embeds)

        await log_action(
            interaction.guild,
            "Публикация размещена",
            f"Канал: <#{NEWS_CHANNEL_ID}>",
            user=interaction.user,
            color=discord.Color.green()
        )

        for c in self.children:
            c.disabled = True

        await interaction.message.edit(view=self)
        await interaction.response.send_message("Опубликовано", ephemeral=True)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _):
        if not has_mod_rights(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        await log_action(
            interaction.guild,
            "Публикация удалена",
            "Предпросмотр удалён",
            user=interaction.user,
            color=discord.Color.red()
        )

        await interaction.message.delete()

class NewsConstructorModal(discord.ui.Modal, title="Конструктор публикации"):
    news_title = discord.ui.TextInput(label="Заголовок")
    author_nick = discord.ui.TextInput(label="Кто выполнил работу", required=False)
    news_text = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph)
    image_links = discord.ui.TextInput(label="Ссылки на изображения (до 4)", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        embeds = []

        main = discord.Embed(
            title=self.news_title.value,
            description=self.news_text.value,
            color=discord.Color.dark_red()
        )

        if self.author_nick.value:
            main.add_field(name="Выполнил работу", value=self.author_nick.value, inline=False)

        main.set_footer(text="Ashra_team")
        embeds.append(main)

        if self.image_links.value:
            links = [l.strip() for l in self.image_links.value.splitlines() if is_valid_url(l.strip())][:4]
            for link in links:
                img = discord.Embed(color=discord.Color.dark_red())
                img.set_image(url=link)
                embeds.append(img)

        await log_action(
            interaction.guild,
            "Создан предпросмотр публикации",
            f"Заголовок: **{self.news_title.value}**",
            user=interaction.user
        )

        await interaction.response.send_message(embeds=embeds, view=NewsControlView())

class BuildersReportModal(discord.ui.Modal, title="Отчёт по работе"):
    report_title = discord.ui.TextInput(label="Заголовок отчёта")
    nick = discord.ui.TextInput(label="Ник исполнителя")
    reward = discord.ui.TextInput(label="Заработок")
    description = discord.ui.TextInput(label="Описание работы", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(title=self.report_title.value, color=discord.Color.dark_red())
        embed.add_field(name=self.nick.value, value=f"Заработок: {self.reward.value}\n{self.description.value}", inline=False)
        embed.set_footer(text="Ashra_team")

        await log_action(
            interaction.guild,
            "Создан отчёт",
            f"Исполнитель: {self.nick.value}",
            user=interaction.user
        )

        await interaction.response.send_message(embed=embed, view=NewsControlView())

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Бот запущен как {bot.user}")

    data = load_approval_data()
    for msg_id, info in data.items():
        bot.add_view(MemberApprovalView(info["approve_cid"], info["deny_cid"]), message_id=int(msg_id))

@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(APPROVAL_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(title="Новый участник", description=f"{member.mention}\nID: `{member.id}`", color=discord.Color.gold())
    embed.set_thumbnail(url=member.display_avatar.url)

    approve_cid = f"approve:{member.id}:{int(time.time())}"
    deny_cid = f"deny:{member.id}:{int(time.time())}"

    view = MemberApprovalView(approve_cid, deny_cid)
    message = await channel.send(embed=embed, view=view)

    data = load_approval_data()
    data[str(message.id)] = {"member_id": member.id, "approve_cid": approve_cid, "deny_cid": deny_cid}
    save_approval_data(data)

    await log_action(member.guild, "Новый участник", f"{member.mention}", user=member, color=discord.Color.gold())

@bot.tree.command(name="panel", description="Панель публикаций")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def panel(interaction: discord.Interaction):
    await log_action(interaction.guild, "Использована команда /panel", "Открыта панель публикаций", user=interaction.user)

    embed = discord.Embed(title="Конструктор публикации", description="Нажмите кнопку ниже", color=discord.Color.blurple())
    button = discord.ui.Button(label="Создать публикацию")

    async def cb(i: discord.Interaction):
        await i.response.send_modal(NewsConstructorModal())

    button.callback = cb
    view = discord.ui.View()
    view.add_item(button)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="news", description="Отчёт (только админ)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def news(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await log_action(interaction.guild, "Отказ в доступе", "Попытка использовать /news", user=interaction.user, color=discord.Color.red())
        return await interaction.response.send_message("Нет доступа", ephemeral=True)

    embed = discord.Embed(title="Отчёт по работе", description="Создать отчёт", color=discord.Color.blurple())
    button = discord.ui.Button(label="Создать отчёт")

    async def cb(i: discord.Interaction):
        await i.response.send_modal(BuildersReportModal())

    button.callback = cb
    view = discord.ui.View()
    view.add_item(button)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

bot.run(TOKEN)
