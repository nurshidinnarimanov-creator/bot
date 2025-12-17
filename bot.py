import os
import discord
from discord.ext import commands
import json
import time
from pathlib import Path
from urllib.parse import urlparse

# ================== CONFIG ==================
NEWS_CHANNEL_ID = 1446886182913970377
ADMIN_USER_ID = 673564170167255041
MOD_ROLE_ID = 1423344639531810927
APPROVED_ROLE_ID = 1423344924262273157
GUILD_ID = 1423020585881043016  # Укажите ID вашего сервера (гильдии) для быстрой синхронизации команд. Получить можно в Discord: правой кнопкой на сервере -> "Копировать ID"
APPROVAL_MAP_FILE = Path("approval_map.json")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Переменная среды DISCORD_TOKEN не установлена")

# ================== BOT SETUP ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# ================== UTILS ==================
def is_valid_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)

# ================== EVENTS ==================
@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")

    try:
        if GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            print(f"App commands synced for guild {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("App commands synced globally")
    except Exception as e:
        print(f"Failed to sync app commands: {e}")

    # Restore persistent approval views
    try:
        if APPROVAL_MAP_FILE.exists():
            with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
                approval_map = json.load(f)

            for message_id, info in approval_map.items():
                try:
                    view = MemberApprovalView(
                        approve_cid=info["approve_cid"],
                        deny_cid=info["deny_cid"],
                    )
                    bot.add_view(view, message_id=int(message_id))
                except Exception:
                    continue
            print("Loaded persisted approval views")
    except Exception as e:
        print(f"Failed loading approval views: {e}")

# ================== NEWS SYSTEM ==================
class NewsControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Опубликовать", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.message or not interaction.message.embeds:
            await interaction.response.send_message("❌ Нет новости.", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        channel = bot.get_channel(NEWS_CHANNEL_ID) or await bot.fetch_channel(NEWS_CHANNEL_ID)
        await channel.send(embed=embed)

        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_message("✅ Новость опубликована!", ephemeral=True)

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.delete()
            await interaction.response.send_message("✅ Сообщение удалено", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

class NewsConstructorModal(discord.ui.Modal, title="Конструктор новости"):
    news_title = discord.ui.TextInput(label="Заголовок", max_length=256)
    author_nick = discord.ui.TextInput(label="Автор", required=False)
    news_text = discord.ui.TextInput(label="Текст", style=discord.TextStyle.paragraph)
    image_link = discord.ui.TextInput(label="Ссылка на изображение", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=self.news_title.value,
            description=self.news_text.value,
            color=discord.Color.dark_red()
        )
        if self.author_nick.value:
            embed.add_field(name="👤 Автор", value=self.author_nick.value, inline=False)
        if self.image_link.value and is_valid_url(self.image_link.value):
            embed.set_image(url=self.image_link.value)
        embed.set_footer(text="McSkill.net | News")

        await interaction.response.send_message(embed=embed, view=NewsControlView())

@bot.command()
async def news(ctx):
    embed = discord.Embed(
        title="Конструктор новости",
        description="Нажмите кнопку ниже, чтобы создать новость",
        color=discord.Color.blurple()
    )
    button = discord.ui.Button(label="Создать новость", style=discord.ButtonStyle.primary)

    async def cb(interaction: discord.Interaction):
        await interaction.response.send_modal(NewsConstructorModal())

    button.callback = cb
    view = discord.ui.View()
    view.add_item(button)
    await ctx.send(embed=embed, view=view)

# ================== MEMBER APPROVAL ==================
class MemberApprovalView(discord.ui.View):
    def __init__(self, *, approve_cid: str, deny_cid: str):
        super().__init__(timeout=None)
        self.approve_cid = approve_cid
        self.deny_cid = deny_cid

        approve = discord.ui.Button(label="Подтвердить", style=discord.ButtonStyle.success, custom_id=approve_cid)
        deny = discord.ui.Button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id=deny_cid)

        approve.callback = self.approve
        deny.callback = self.deny

        self.add_item(approve)
        self.add_item(deny)

    def _authorized(self, member: discord.Member) -> bool:
        if member.id == ADMIN_USER_ID:
            return True
        return any(r.id == MOD_ROLE_ID for r in member.roles)

    async def approve(self, interaction: discord.Interaction):
        if not self._authorized(interaction.user):
            await interaction.response.send_message("Нет прав", ephemeral=True)
            return

        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        member_id = next(v["member_id"] for v in data.values() if v["approve_cid"] == interaction.data["custom_id"])

        member = interaction.guild.get_member(member_id)
        role = interaction.guild.get_role(APPROVED_ROLE_ID)
        await member.add_roles(role)

        # Отправить сообщение в канал принятых
        accepted_channel = bot.get_channel(1446886182913970377)
        if accepted_channel:
            embed = discord.Embed(
                title="🎉 Новый строитель!",
                description=f"{member.mention} принят на роль строителя!",
                color=discord.Color.green()
            )
            try:
                embed.set_thumbnail(url=member.display_avatar.url)
            except:
                pass
            await accepted_channel.send(embed=embed)

        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("✅ Участник подтверждён", ephemeral=True)

    async def deny(self, interaction: discord.Interaction):
        if not self._authorized(interaction.user):
            await interaction.response.send_message("Нет прав", ephemeral=True)
            return

        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        member_id = next(v["member_id"] for v in data.values() if v["deny_cid"] == interaction.data["custom_id"])

        member = interaction.guild.get_member(member_id)
        await member.kick()

        for c in self.children:
            c.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("❌ Участник отклонён", ephemeral=True)

@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(NEWS_CHANNEL_ID)
    embed = discord.Embed(title="Новый участник", description=f"{member.mention} ({member})", color=discord.Color.gold())
    try:
        embed.set_image(url=member.display_avatar.url)
    except Exception:
        pass

    ts = int(time.time())
    approve_cid = f"approve:{member.id}:{ts}"
    deny_cid = f"deny:{member.id}:{ts}"

    view = MemberApprovalView(approve_cid=approve_cid, deny_cid=deny_cid)
    msg = await channel.send(embed=embed, view=view)

    data = {}
    if APPROVAL_MAP_FILE.exists():
        with APPROVAL_MAP_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

    data[str(msg.id)] = {
        "member_id": member.id,
        "approve_cid": approve_cid,
        "deny_cid": deny_cid,
    }

    with APPROVAL_MAP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    bot.add_view(view, message_id=msg.id)

# ================== RUN ==================
bot.run(TOKEN)