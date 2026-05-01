"""
NDBot v1.0501 - Bot 服务
Telegram callback_data 限制 64 字节
URL 通过 Redis 存储
Callback_data 只传 8 位短 ID。
"""

import asyncio
import html
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from pyrogram import Client, filters, idle
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BOT] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── 配置 ─────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]
TG_API_ID   = int(os.environ["TG_API_ID"])
TG_API_HASH = os.environ["TG_API_HASH"]
PROXY_HOST  = os.environ.get("PROXY_HOST", "")
PROXY_PORT  = int(os.environ.get("PROXY_PORT", "7890"))
REDIS_URL   = os.environ.get("REDIS_URL", "redis://redis:6379/0")

ALLOWED_USERS = {
    int(x.strip())
    for x in os.environ.get("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
}

RCLONE_ENABLE = os.environ.get("RCLONE_ENABLE", "false").lower() == "true"
RCLONE_REMOTE = os.environ.get("RCLONE_REMOTE", "")
RCLONE_DEST   = os.environ.get("RCLONE_DEST", "NDBot")
RCLONE_MODE   = os.environ.get("RCLONE_MODE", "manual")

# ── Pyrogram 客户端 ───────────────────────────────────────────
_proxy = (
    {"scheme": "http", "hostname": PROXY_HOST, "port": PROXY_PORT}
    if PROXY_HOST else None
)

app = Client(
    name="ndbot",
    api_id=TG_API_ID,
    api_hash=TG_API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/sessions",
    proxy=_proxy,
)

# ── Redis ─────────────────────────────────────────────────────
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def push_task(task: dict) -> str:
    task_id = uuid.uuid4().hex[:8]
    task["id"]     = task_id
    task["ts"]     = datetime.now(timezone.utc).isoformat()
    task["status"] = "queued"
    r = await get_redis()
    await r.lpush("dl:queue", json.dumps(task))
    await r.hset("dl:tasks", task_id, json.dumps(task))
    return task_id


async def store_url(platform: str, url: str) -> str:
    """把 URL 存入 Redis，返回 8 位短 ID（1小时过期）"""
    uid = uuid.uuid4().hex[:8]
    r = await get_redis()
    await r.setex(
        f"url:{uid}",
        3600,
        json.dumps({"platform": platform, "url": url}),
    )
    return uid


async def load_url(uid: str) -> tuple[str | None, str | None]:
    r = await get_redis()
    raw = await r.get(f"url:{uid}")
    if not raw:
        return None, None
    data = json.loads(raw)
    return data["platform"], data["url"]


# ── URL 平台检测 ──────────────────────────────────────────────
_URL_RULES = [
    (re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be)/\S+"),  "youtube"),
    (re.compile(r"https?://(www\.)?(x\.com|twitter\.com)/\S+"),     "xcom"),
    (re.compile(r"https?://(www\.)?bilibili\.com/\S+"),             "bilibili"),
    (re.compile(r"https?://(www\.)?instagram\.com/\S+"),            "instagram"),
    (re.compile(r"https?://(www\.)?tiktok\.com/\S+"),               "tiktok"),
    (re.compile(r"https?://(t\.me|telegram\.me)/\S+"),              "tglink"),
    (re.compile(r"https?://\S+"),                                   "generic"),
]

_PLATFORM_LABEL = {
    "youtube":   "🎬 YouTube",
    "xcom":      "🐦 X.com (Twitter)",
    "bilibili":  "📺 Bilibili",
    "instagram": "📸 Instagram",
    "tiktok":    "🎵 TikTok",
    "tglink":    "📨 Telegram 链接",
    "generic":   "🌐 通用链接",
}


def detect_url(text: str) -> tuple[str | None, str | None]:
    for pattern, platform in _URL_RULES:
        m = pattern.search(text)
        if m:
            return platform, m.group(0)
    return None, None


def allowed(uid: int) -> bool:
    return not ALLOWED_USERS or uid in ALLOWED_USERS


# ── 键盘（callback_data = dl:{action}:{uid8}，最长~16字节）──
def kb_youtube(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 最佳画质", callback_data=f"dl:best:{uid}"),
         InlineKeyboardButton("🎬 1080p",    callback_data=f"dl:1080p:{uid}")],
        [InlineKeyboardButton("🎬 720p",     callback_data=f"dl:720p:{uid}"),
         InlineKeyboardButton("🎬 480p",     callback_data=f"dl:480p:{uid}")],
        [InlineKeyboardButton("🎵 MP3",      callback_data=f"dl:mp3:{uid}"),
         InlineKeyboardButton("🎵 M4A",      callback_data=f"dl:m4a:{uid}")],
        [InlineKeyboardButton("📋 字幕",     callback_data=f"dl:subs:{uid}"),
         InlineKeyboardButton("🖼 封面图",   callback_data=f"dl:thumb:{uid}")],
    ])


def kb_xcom(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 视频",     callback_data=f"dl:video:{uid}"),
         InlineKeyboardButton("🖼 图片",     callback_data=f"dl:image:{uid}")],
        [InlineKeyboardButton("🔁 所有媒体", callback_data=f"dl:all:{uid}"),
         InlineKeyboardButton("📝 仅文字",   callback_data=f"dl:text:{uid}")],
    ])


def kb_tglink(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 下载媒体", callback_data=f"dl:media:{uid}"),
         InlineKeyboardButton("📝 保存文字", callback_data=f"dl:text:{uid}")],
    ])


def kb_generic(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 视频（最佳）", callback_data=f"dl:best:{uid}"),
         InlineKeyboardButton("🎵 仅音频",       callback_data=f"dl:audio:{uid}")],
    ])


# ── 命令 ─────────────────────────────────────────────────────
@app.on_message(filters.command("start"))
async def cmd_start(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        await msg.reply("⛔ 无权限使用此机器人")
        return
    cloud_line = (
        f"\n☁️ 云盘同步已启用：`{RCLONE_REMOTE}:{RCLONE_DEST}`（{RCLONE_MODE} 模式）"
        if RCLONE_ENABLE else ""
    )
    await msg.reply(
        "**📥 NDBot 统一资源下载机器人**\n\n"
        "直接发送链接开始下载：\n\n"
        "🎬 YouTube — 视频/音频/字幕/封面\n"
        "🐦 X.com (Twitter) — 视频/图片\n"
        "📺 Bilibili\n"
        "📸 Instagram\n"
        "🎵 TikTok\n"
        "🌐 其他 yt-dlp 支持的网站\n"
        "📨 Telegram 媒体 — 直接转发消息给我\n"
        f"{cloud_line}\n\n"
        "**指令：**\n"
        "/start — 帮助\n"
        "/status — 任务统计\n"
        "/tasks — 最近任务列表\n"
        "/sync — 手动同步文件到云盘\n"
    )


@app.on_message(filters.command("status"))
async def cmd_status(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        return
    r = await get_redis()
    tasks = [json.loads(v) for v in (await r.hgetall("dl:tasks")).values()]
    queue = await r.llen("dl:queue")
    await msg.reply(
        "**📊 任务统计**\n\n"
        f"⏳ 队列中：{queue}\n"
        f"🔄 进行中：{sum(1 for t in tasks if t.get('status') == 'running')}\n"
        f"✅ 已完成：{sum(1 for t in tasks if t.get('status') == 'done')}\n"
        f"❌ 失败：{sum(1 for t in tasks if t.get('status') == 'failed')}"
    )


@app.on_message(filters.command("tasks"))
async def cmd_tasks(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        return
    r = await get_redis()
    raw = list((await r.hgetall("dl:tasks")).values())
    if not raw:
        await msg.reply("暂无任务记录")
        return
    tasks = sorted(
        [json.loads(t) for t in raw],
        key=lambda t: t.get("ts", ""),
        reverse=True,
    )[:10]
    icons = {"queued": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}
    lines = [
        f"{icons.get(t.get('status', ''), '❓')} `{t['id']}` "
        f"{t.get('platform', t.get('type', ''))} "
        f"{(t.get('url') or '')[:40]}"
        for t in tasks
    ]
    await msg.reply("**最近 10 条任务：**\n" + "\n".join(lines))


@app.on_message(filters.command("sync"))
async def cmd_sync(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        return
    if not RCLONE_ENABLE:
        await msg.reply(
            "☁️ 云盘同步未启用。\n"
            "请在 `.env` 设置 `RCLONE_ENABLE=true` 并配置 `./rclone/rclone.conf`。"
        )
        return
    notice = await msg.reply(
        f"☁️ 正在同步到 `{RCLONE_REMOTE}:{RCLONE_DEST}`...\n"
        "文件较多时需要数分钟，完成后通知。"
    )
    task_id = await push_task({
        "type":       "sync",
        "reply_chat": msg.chat.id,
        "reply_msg":  notice.id,
    })
    await notice.edit(f"☁️ 同步任务 `{task_id}` 已入队，等待执行...")


# ── URL 消息处理 ──────────────────────────────────────────────
@app.on_message(
    filters.text
    & ~filters.command(["start", "status", "tasks", "sync"])
)
async def handle_text(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        return
    platform, url = detect_url(msg.text or "")
    if not platform:
        return

    uid = await store_url(platform, url)
    label = _PLATFORM_LABEL[platform]

    if platform == "youtube":
        await msg.reply(
            f"**{label}**\n🔗 `{url[:60]}`\n\n请选择格式：",
            reply_markup=kb_youtube(uid),
        )
    elif platform == "xcom":
        await msg.reply(
            f"**{label}**\n🔗 `{url[:60]}`\n\n请选择内容：",
            reply_markup=kb_xcom(uid),
        )
    elif platform == "tglink":
        await msg.reply(
            f"**{label}**\n🔗 `{url[:60]}`\n\n请选择操作：",
            reply_markup=kb_tglink(uid),
        )
    else:
        await msg.reply(
            f"**{label}**\n🔗 `{url[:60]}`\n\n请选择格式：",
            reply_markup=kb_generic(uid),
        )


# ── 媒体 / 转发消息 ───────────────────────────────────────────
@app.on_message(
    filters.forwarded
    | filters.photo
    | filters.video
    | filters.document
    | filters.audio
    | filters.voice
    | filters.video_note
    | filters.sticker
    | filters.animation
)
async def handle_media(_: Client, msg: Message):
    if not allowed(msg.from_user.id):
        return
    notice = await msg.reply("⏳ 正在保存 Telegram 媒体...")
    task_id = await push_task({
        "type":       "tg_media",
        "chat_id":    msg.chat.id,
        "message_id": msg.id,
        "reply_chat": msg.chat.id,
        "reply_msg":  notice.id,
    })
    await notice.edit(f"⏳ 任务 `{task_id}` 已入队，处理中...")


# ── 按钮回调 ─────────────────────────────────────────────────
@app.on_callback_query()
async def handle_cb(_: Client, cb: CallbackQuery):
    if not allowed(cb.from_user.id):
        await cb.answer("⛔ 无权限", show_alert=True)
        return
    await cb.answer()

    parts = cb.data.split(":")
    if len(parts) != 3 or parts[0] != "dl":
        return
    _, action, uid = parts

    platform, url = await load_url(uid)
    if not url:
        await cb.message.edit("❌ 链接已过期（超过1小时），请重新发送 URL。")
        return

    notice = await cb.message.edit(
        f"⏳ 已接收，等待下载...\n"
        f"🔗 `{url[:60]}`\n"
        f"📦 格式：{action}"
    )
    task_id = await push_task({
        "type":       "url",
        "platform":   platform,
        "action":     action,
        "url":        url,
        "reply_chat": cb.message.chat.id,
        "reply_msg":  notice.id,
    })
    await notice.edit(
        f"⏳ 任务 `{task_id}` 已入队\n"
        f"🔗 `{url[:60]}`\n"
        f"📦 格式：{action}\n\n"
        "下载完成后此处更新。"
    )


# ── 结果监听 ─────────────────────────────────────────────────
async def result_listener():
    r = await get_redis()
    log.info("结果监听器已启动")
    while True:
        try:
            item = await r.brpop("dl:results", timeout=3)
            if not item:
                continue
            result  = json.loads(item[1])
            chat_id = result.get("reply_chat")
            msg_id  = result.get("reply_msg")
            if not chat_id:
                continue

            if result.get("type") == "sync":
                text = result.get("message", "☁️ 同步完成")
            elif result.get("success"):
                files = "\n".join(
                    f"  📄 `{f}`" for f in result.get("files", [])
                ) or "  （文件已保存到服务器）"
                rclone_info = result.get("rclone_msg", "")
                text = (
                    f"✅ **下载完成** `{result.get('id', '')}`\n\n"
                    f"{files}\n\n"
                    f"📦 大小：{result.get('size', '未知')}\n"
                    f"💾 目录：`{result.get('save_dir', '')}`"
                    f"{rclone_info}"
                )
            else:
                text = (
                    f"❌ **下载失败** `{result.get('id', '')}`\n\n"
                    f"{html.escape(result.get('error', '未知错误')[:300])}"
                )

            try:
                await app.edit_message_text(chat_id, msg_id, text)
            except Exception:
                try:
                    await app.send_message(chat_id, text)
                except Exception as e:
                    log.warning(f"回复用户失败: {e}")

        except Exception as e:
            log.exception(f"结果监听异常: {e}")
            await asyncio.sleep(2)


# ── 入口 ─────────────────────────────────────────────────────
async def main():
    await app.start()
    me = await app.get_me()
    log.info(f"✅ NDBot 已启动：@{me.username}")
    asyncio.create_task(result_listener())
    await idle()
    await app.stop()


if __name__ == "__main__":
    app.run(main())
