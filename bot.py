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

NEWS_CHANNEL_ID = 1446886182913970377
LOG_CHANNEL_ID = 1450910208325980335
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
APPROVED_ROLE_ID = 1423344924262273157
GUILD_ID = 1423020585881043016

APPROVAL_MAP_FILE = Path("approval_map.json")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

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

async def log_action(guild, title, description, color=discord.Color.blurple()):
    channel = guild.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=discord.utils.utcnow()
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

    def _has_permission(self, member: discord.Member) -> bool:
        return (
            member.id == ADMIN_USER_ID or
            any(role.id == MOD_ROLE_ID for role in member.roles)
        )

    async def _disable(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    async def approve(self, interaction: discord.Interaction):
        if not self._has_permission(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        data = load_approval_data()
        msg_id, info = find_approval_by_custom_id(data, interaction.data["custom_id"])

        if not info:
            return await interaction.response.send_message(
                "Заявка уже обработана", ephemeral=True
            )

        member = interaction.guild.get_member(info["member_id"])

        if not member:
            data.pop(msg_id, None)
            save_approval_data(data)
            await self._disable(interaction)
            return await interaction.response.send_message(
                "Участник уже покинул сервер", ephemeral=True
            )

        role = interaction.guild.get_role(APPROVED_ROLE_ID)
        if role:
            await member.add_roles(role)

        await log_action(
            interaction.guild,
            "Участник принят",
            f"Модератор: {interaction.user.mention}\n"
            f"Участник: {member.mention}",
            discord.Color.green()
        )

        data.pop(msg_id, None)
        save_approval_data(data)

        await self._disable(interaction)
        await interaction.response.send_message("Принят", ephemeral=True)

    async def deny(self, interaction: discord.Interaction):
        if not self._has_permission(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        data = load_approval_data()
        msg_id, info = find_approval_by_custom_id(data, interaction.data["custom_id"])

        if not info:
            return await interaction.response.send_message(
                "Заявка уже обработана", ephemeral=True
            )

        member = interaction.guild.get_member(info["member_id"])

        await log_action(
            interaction.guild,
            "Участник отклонён",
            f"Модератор: {interaction.user.mention}\n"
            f"ID: {info['member_id']}",
            discord.Color.red()
        )

        if member:
            await member.kick(reason="Отклонён")

        data.pop(msg_id, None)
        save_approval_data(data)

        await self._disable(interaction)

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Бот запущен как {bot.user}")

    data = load_approval_data()
    for msg_id, info in data.items():
        bot.add_view(
            MemberApprovalView(
                approve_cid=info["approve_cid"],
                deny_cid=info["deny_cid"]
            ),
            message_id=int(msg_id)
        )

@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(NEWS_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="Новый участник",
        description=member.mention,
        color=discord.Color.gold()
    )

    approve_cid = f"approve:{member.id}:{int(time.time())}"
    deny_cid = f"deny:{member.id}:{int(time.time())}"

    view = MemberApprovalView(approve_cid, deny_cid)
    message = await channel.send(embed=embed, view=view)

    data = load_approval_data()
    data[str(message.id)] = {
        "member_id": member.id,
        "approve_cid": approve_cid,
        "deny_cid": deny_cid
    }
    save_approval_data(data)

    bot.add_view(view, message_id=message.id)

@bot.tree.command(name="news", description="Создать публикацию")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def news(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Функция news будет добавлена позже",
        ephemeral=True
    )

bot.run(TOKEN)
