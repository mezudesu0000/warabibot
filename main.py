\
import asyncio
import io
import json
import os
from datetime import timedelta, datetime

import discord
from discord import app_commands
from discord.ext import commands

import qrcode
import requests

import google.generativeai as genai

from flask import Flask
from threading import Thread

from config import TOKEN, GEMINI_API_KEY, VERIFY_ROLE_NAME, DB_PATH, PORT, MODEL_NAME

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Simple web server for Render Web Service health check
app = Flask(__name__)

@app.route("/")
def index():
    return "ok", 200

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

Thread(target=run_flask, daemon=True).start()

# Simple JSON storage for chat channel per guild
def load_db():
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(data):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

chat_channels = load_db()  # {guild_id: channel_id}

# Gemini
genai.configure(api_key=GEMINI_API_KEY or "")
gemini_model = None
if GEMINI_API_KEY:
    try:
        gemini_model = genai.GenerativeModel(MODEL_NAME)
    except Exception:
        gemini_model = None

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception:
        pass
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

# Slash commands
@bot.tree.command(name="clearmessages", description="指定数のメッセージを削除")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(count="削除するメッセージ数（最大100）")
async def clearmessages(interaction: discord.Interaction, count: int):
    await interaction.response.defer(ephemeral=True)
    count = max(1, min(100, count))
    deleted = await interaction.channel.purge(limit=count)
    await interaction.followup.send(f"{len(deleted)}件のメッセージを削除しました。", ephemeral=True)

class VerifyButton(discord.ui.View):
    def __init__(self, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(self.Verify())

    class Verify(discord.ui.Button):
        def __init__(self):
            super().__init__(label="認証する", style=discord.ButtonStyle.success, custom_id="verify_btn")

        async def callback(self, interaction: discord.Interaction):
            guild = interaction.guild
            if guild is None:
                return await interaction.response.send_message("サーバー内でのみ利用できます。", ephemeral=True)

            role = discord.utils.get(guild.roles, name=VERIFY_ROLE_NAME)
            if role is None:
                try:
                    role = await guild.create_role(name=VERIFY_ROLE_NAME, reason="Verify role auto-created")
                except discord.Forbidden:
                    return await interaction.response.send_message("ロール作成権限がありません。管理者に連絡してください。", ephemeral=True)

            member = interaction.user
            try:
                await member.add_roles(role, reason="Verified via button")
            except discord.Forbidden:
                return await interaction.response.send_message("ロール付与に失敗しました。権限を確認してください。", ephemeral=True)

            await interaction.response.send_message(f"{member.mention} さんを認証しました。", ephemeral=True)

@bot.tree.command(name="verify", description="認証ボタンを表示")
@app_commands.checks.has_permissions(manage_roles=True)
async def verify(interaction: discord.Interaction):
    await interaction.response.send_message("ボタンを押すと認証ロールが付与されます。", view=VerifyButton())

@bot.tree.command(name="qrcode", description="URLのQRコードを生成")
@app_commands.describe(url="QRコード化するURL")
async def qrcode_cmd(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    file = discord.File(buf, filename="qrcode.png")
    await interaction.followup.send(file=file, content="QRコードを生成しました。")

@bot.tree.command(name="ipinfo", description="IPアドレスの情報を表示")
@app_commands.describe(ip="例: 8.8.8.8")
async def ipinfo(interaction: discord.Interaction, ip: str):
    await interaction.response.defer()
    try:
        r = requests.get(f"https://ipapi.co/{ip}/json/", timeout=10)
        data = r.json()
        if data.get("error"):
            await interaction.followup.send(f"取得に失敗しました: {data.get('reason', 'unknown')}")
            return
        fields = [
            ("IP", data.get("ip")),
            ("国", data.get("country_name")),
            ("地域", data.get("region")),
            ("都市", data.get("city")),
            ("郵便番号", data.get("postal")),
            ("緯度", data.get("latitude")),
            ("経度", data.get("longitude")),
            ("組織", data.get("org")),
            ("タイムゾーン", data.get("timezone")),
        ]
        embed = discord.Embed(title="IP情報", color=0x00AAFF)
        for name, value in fields:
            if value is not None:
                embed.add_field(name=name, value=str(value), inline=True)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"取得エラー: {e}")

@bot.tree.command(name="timeout", description="ユーザーをタイムアウト")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(member="対象ユーザー", seconds="秒数（最大28日）", reason="理由")
async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, seconds: int, reason: str = "なし"):
    await interaction.response.defer(ephemeral=True)
    seconds = max(1, min(28*24*3600, seconds))
    try:
        await member.timeout(timedelta(seconds=seconds), reason=reason)
        await interaction.followup.send(f"{member.mention} を {seconds}秒 タイムアウトしました。理由: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("権限不足で失敗しました。", ephemeral=True)

@bot.tree.command(name="kick", description="ユーザーをキック")
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(member="対象ユーザー", reason="理由")
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "なし"):
    await interaction.response.defer(ephemeral=True)
    try:
        await member.kick(reason=reason)
        await interaction.followup.send(f"{member} をキックしました。理由: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("権限不足で失敗しました。", ephemeral=True)

@bot.tree.command(name="ban", description="ユーザーをBAN")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(member="対象ユーザー", reason="理由")
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "なし"):
    await interaction.response.defer(ephemeral=True)
    try:
        await member.ban(reason=reason, delete_message_days=0)
        await interaction.followup.send(f"{member} をBANしました。理由: {reason}", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("権限不足で失敗しました。", ephemeral=True)

@bot.tree.command(name="serverinfo", description="サーバー情報を表示")
async def serverinfo(interaction: discord.Interaction):
    g = interaction.guild
    if g is None:
        await interaction.response.send_message("サーバー内でのみ利用できます。", ephemeral=True)
        return
    embed = discord.Embed(title="サーバー情報", color=0x2ecc71)
    embed.add_field(name="名前", value=g.name, inline=True)
    embed.add_field(name="ID", value=g.id, inline=True)
    embed.add_field(name="メンバー数", value=g.member_count, inline=True)
    if g.owner:
        embed.add_field(name="オーナー", value=f"{g.owner} ({g.owner_id})", inline=False)
    embed.add_field(name="作成日", value=g.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)
    if g.features:
        embed.add_field(name="機能", value=", ".join(g.features), inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="ユーザー情報を表示")
@app_commands.describe(user="対象ユーザー")
async def userinfo(interaction: discord.Interaction, user: discord.User):
    member = interaction.guild.get_member(user.id) if interaction.guild else None
    embed = discord.Embed(title="ユーザー情報", color=0x3498db)
    embed.set_author(name=str(user), icon_url=user.display_avatar.url if user.display_avatar else None)
    embed.add_field(name="ID", value=user.id, inline=True)
    embed.add_field(name="Bot", value=str(user.bot), inline=True)
    embed.add_field(name="作成日", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)
    if member:
        embed.add_field(name="参加日", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC") if member.joined_at else "不明", inline=False)
        top_role = member.top_role.mention if member.top_role else "なし"
        roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
        embed.add_field(name="トップロール", value=top_role, inline=True)
        embed.add_field(name="ロール", value=", ".join(roles) if roles else "なし", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="chatset", description="AI応答チャンネルを設定")
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(channel="AIが返信するチャンネル")
async def chatset(interaction: discord.Interaction, channel: discord.TextChannel):
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内でのみ利用できます。", ephemeral=True)
        return
    chat_channels[str(interaction.guild.id)] = channel.id
    save_db(chat_channels)
    await interaction.response.send_message(f"AI応答チャンネルを <#{channel.id}> に設定しました。", ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # "わらび" への返信
    content = message.content or ""
    if "わらび" in content:
        try:
            await message.reply("なんやねん")
        except Exception:
            pass

    # Gemini連携（設定されたチャンネルのみ）
    guild = message.guild
    if guild and GEMINI_API_KEY and gemini_model:
        gid = str(guild.id)
        target_channel_id = chat_channels.get(gid)
        if target_channel_id and message.channel.id == target_channel_id:
            try:
                prompt = content.strip()
                if prompt:
                    resp = gemini_model.generate_content(prompt)
                    text = resp.text if hasattr(resp, "text") else "（応答を生成できませんでした）"
                    await message.channel.send(text[:1950])
            except Exception as e:
                await message.channel.send(f"AIエラー: {e}")

    await bot.process_commands(message)

if __name__ == "__main__":
    if not TOKEN:
        print("TOKEN is missing.")
    bot.run(TOKEN)
