import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

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

BALANCE_FILE = Path("balance.json")
HISTORY_FILE = Path("history.json")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ================= BALANCE =================

def load_json(path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_balance(user_id: int, amount: int, link: str):
    balances = load_json(BALANCE_FILE)
    history = load_json(HISTORY_FILE)

    uid = str(user_id)
    balances[uid] = balances.get(uid, 0) + amount

    history.setdefault(uid, []).append({
        "amount": amount,
        "time": datetime.utcnow().strftime("%d.%m.%Y %H:%M"),
        "link": link
    })

    save_json(BALANCE_FILE, balances)
    save_json(HISTORY_FILE, history)

def get_balance(user_id: int) -> int:
    return load_json(BALANCE_FILE).get(str(user_id), 0)

# ================= UTILS =================

def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc

async def log_action(guild, title, desc, user=None, color=discord.Color.blurple()):
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if not ch:
        return
    embed = discord.Embed(title=title, description=desc, color=color, timestamp=discord.utils.utcnow())
    if user:
        embed.set_footer(text=f"{user} | {user.id}", icon_url=user.display_avatar.url)
    await ch.send(embed=embed)

# ================= NEWS VIEW =================

class NewsControlView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=None)
        self.author_id = author_id

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, _):
        channel = bot.get_channel(NEWS_CHANNEL_ID)
        msg = await channel.send(embeds=interaction.message.embeds)

        add_balance(self.author_id, 500, msg.jump_url)

        author = interaction.guild.get_member(self.author_id)
        await log_action(
            interaction.guild,
            "Публикация",
            f"{author.mention if author else self.author_id} получил +500",
            interaction.user,
            discord.Color.green()
        )

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        await interaction.response.send_message("✅ Опубликовано. Награда выдана автору.", ephemeral=True)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, _):
        await interaction.message.delete()
        await log_action(
            interaction.guild,
            "Предпросмотр удалён",
            f"Удалил {interaction.user.mention}",
            interaction.user,
            discord.Color.red()
        )

# ================= MODAL =================

class NewsConstructorModal(discord.ui.Modal, title="Конструктор публикации"):
    news_title = discord.ui.TextInput(label="Заголовок")
    author_nick = discord.ui.TextInput(label="Автор (ник)", required=False)
    news_text = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph)
    image_links = discord.ui.TextInput(label="Ссылки на изображения", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        embeds = []
        main = discord.Embed(
            title=self.news_title.value,
            description=self.news_text.value,
            color=discord.Color.dark_red()
        )

        if self.author_nick.value:
            main.add_field(name="Автор", value=self.author_nick.value, inline=False)

        embeds.append(main)

        if self.image_links.value:
            for link in self.image_links.value.splitlines():
                if is_valid_url(link):
                    e = discord.Embed(color=discord.Color.dark_red())
                    e.set_image(url=link)
                    embeds.append(e)

        author = interaction.user
        if self.author_nick.value:
            found = discord.utils.find(
                lambda m: m.display_name == self.author_nick.value or m.name == self.author_nick.value,
                interaction.guild.members
            )
            if found:
                author = found

        await interaction.response.send_message(
            embeds=embeds,
            view=NewsControlView(author.id)
        )

# ================= COMMANDS =================

@bot.tree.command(name="panel", description="Панель публикаций")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def panel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Панель публикаций",
        description="Нажмите кнопку ниже",
        color=discord.Color.blurple()
    )
    btn = discord.ui.Button(label="Создать публикацию")

    async def cb(i: discord.Interaction):
        await i.response.send_modal(NewsConstructorModal())

    btn.callback = cb
    view = discord.ui.View()
    view.add_item(btn)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="news", description="Алиас панели")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def news(interaction: discord.Interaction):
    await panel(interaction)

@bot.tree.command(name="balance", description="Ваш баланс")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def balance(interaction: discord.Interaction):
    bal = get_balance(interaction.user.id)
    embed = discord.Embed(
        title="💰 Ваш баланс",
        description=f"**{bal} скилкоинов**",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)

    btn = discord.ui.Button(label="История")

    async def cb(i: discord.Interaction):
        hist = load_json(HISTORY_FILE).get(str(i.user.id), [])
        text = "\n".join(f"{h['time']} | +{h['amount']} | [ссылка]({h['link']})" for h in hist[-10:]) or "Пусто"
        await i.response.send_message(text, ephemeral=True)

    btn.callback = cb
    view = discord.ui.View()
    view.add_item(btn)

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="balans", description="Баланс всех")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def balans(interaction: discord.Interaction):
    data = load_json(BALANCE_FILE)
    lines = []
    for uid, bal in sorted(data.items(), key=lambda x: x[1], reverse=True):
        member = interaction.guild.get_member(int(uid))
        lines.append(f"{member.mention if member else uid}: **{bal}**")

    embed = discord.Embed(
        title="📊 Баланс участников",
        description="\n".join(lines) if lines else "Пусто",
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(embed=embed)

# ================= READY =================

@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"Бот запущен как {bot.user}")

bot.run(TOKEN)
