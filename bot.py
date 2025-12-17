import os
import discord
from discord.ext import commands
import json
import time
from pathlib import Path
from urllib.parse import urlparse

NEWS_CHANNEL_ID = 1446886182913970377
LOG_CHANNEL_ID = 1450910208325980335
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
APPROVED_ROLE_ID = 1423344924262273157
GUILD_ID = 1423020585881043016
APPROVAL_MAP_FILE = Path("approval_map.json")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не установлен")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

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

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))

    if APPROVAL_MAP_FILE.exists():
        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for msg_id, info in data.items():
            bot.add_view(
                MemberApprovalView(
                    approve_cid=info["approve_cid"],
                    deny_cid=info["deny_cid"]
                ),
                message_id=int(msg_id)
            )

class NewsControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _):
        channel = bot.get_channel(NEWS_CHANNEL_ID)
        await channel.send(embeds=interaction.message.embeds)

        await log_action(
            interaction.guild,
            "✅ Новость опубликована",
            f"Пользователь: {interaction.user.mention}",
            discord.Color.green()
        )

        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("Опубликовано", ephemeral=True)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _):
        await log_action(
            interaction.guild,
            "🗑 Новость удалена",
            f"Пользователь: {interaction.user.mention}",
            discord.Color.red()
        )
        await interaction.message.delete()

class NewsConstructorModal(discord.ui.Modal, title="Конструктор новости"):
    news_title = discord.ui.TextInput(
        label="Заголовок",
        max_length=256
    )

    author_nick = discord.ui.TextInput(
        label="Кто выполнил работу",
        placeholder="Ник игрока",
        required=False,
        max_length=256
    )

    news_text = discord.ui.TextInput(
        label="Текст новости",
        style=discord.TextStyle.paragraph,
        max_length=4000
    )

    image_links = discord.ui.TextInput(
        label="Ссылки на изображения (до 4)",
        placeholder="https://img1.png\nhttps://img2.png",
        required=False,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        embeds = []

        main_embed = discord.Embed(
            title=self.news_title.value,
            description=self.news_text.value,
            color=discord.Color.dark_red()
        )

        if self.author_nick.value:
            main_embed.add_field(
                name="👤 Выполнил работу",
                value=self.author_nick.value,
                inline=False
            )

        main_embed.set_footer(text="McSkill.net | News")
        embeds.append(main_embed)

        if self.image_links.value:
            links = [
                l.strip() for l in self.image_links.value.replace(",", "\n").split("\n")
                if is_valid_url(l.strip())
            ][:4]

            for link in links:
                img_embed = discord.Embed(color=discord.Color.dark_red())
                img_embed.set_image(url=link)
                embeds.append(img_embed)

        await log_action(
            interaction.guild,
            "📝 Создание новости",
            f"Автор: {interaction.user.mention}\nЗаголовок: **{self.news_title.value}**"
        )

        await interaction.response.send_message(
            embeds=embeds,
            view=NewsControlView()
        )

@bot.command()
async def news(ctx):
    embed = discord.Embed(
        title="Конструктор новости",
        description="Нажмите кнопку ниже",
        color=discord.Color.blurple()
    )

    button = discord.ui.Button(
        label="Создать новость",
        style=discord.ButtonStyle.primary
    )

    async def callback(interaction: discord.Interaction):
        await interaction.response.send_modal(NewsConstructorModal())

    button.callback = callback
    view = discord.ui.View(timeout=None)
    view.add_item(button)

    await ctx.send(embed=embed, view=view)

class MemberApprovalView(discord.ui.View):
    def __init__(self, *, approve_cid, deny_cid):
        super().__init__(timeout=None)

        approve = discord.ui.Button(
            label="Подтвердить",
            style=discord.ButtonStyle.success,
            custom_id=approve_cid
        )
        deny = discord.ui.Button(
            label="Отклонить",
            style=discord.ButtonStyle.danger,
            custom_id=deny_cid
        )

        approve.callback = self.approve
        deny.callback = self.deny

        self.add_item(approve)
        self.add_item(deny)

    def _auth(self, member):
        return member.id == ADMIN_USER_ID or any(r.id == MOD_ROLE_ID for r in member.roles)

    async def approve(self, interaction: discord.Interaction):
        if not self._auth(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        member_id = next(v["member_id"] for v in data.values() if v["approve_cid"] == interaction.data["custom_id"])
        member = interaction.guild.get_member(member_id)
        role = interaction.guild.get_role(APPROVED_ROLE_ID)
        await member.add_roles(role)

        await log_action(
            interaction.guild,
            "🟢 Участник принят",
            f"Модератор: {interaction.user.mention}\nУчастник: {member.mention}",
            discord.Color.green()
        )

        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("Принят", ephemeral=True)

    async def deny(self, interaction: discord.Interaction):
        if not self._auth(interaction.user):
            return await interaction.response.send_message("Нет прав", ephemeral=True)

        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        member_id = next(v["member_id"] for v in data.values() if v["deny_cid"] == interaction.data["custom_id"])
        member = interaction.guild.get_member(member_id)

        await log_action(
            interaction.guild,
            "🔴 Участник отклонён",
            f"Модератор: {interaction.user.mention}\nУчастник: {member.mention}",
            discord.Color.red()
        )

        await member.kick(reason="Отклонён")

        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(NEWS_CHANNEL_ID)

    embed = discord.Embed(
        title="Новый участник",
        description=member.mention,
        color=discord.Color.gold()
    )

    approve_cid = f"approve:{member.id}:{int(time.time())}"
    deny_cid = f"deny:{member.id}:{int(time.time())}"

    view = MemberApprovalView(
        approve_cid=approve_cid,
        deny_cid=deny_cid
    )

    msg = await channel.send(embed=embed, view=view)

    data = {}
    if APPROVAL_MAP_FILE.exists():
        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

    data[str(msg.id)] = {
        "member_id": member.id,
        "approve_cid": approve_cid,
        "deny_cid": deny_cid
    }

    with APPROVAL_MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    bot.add_view(view, message_id=msg.id)

bot.run(TOKEN)
