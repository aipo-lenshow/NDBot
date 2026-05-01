"""
NDBot - Worker 服务
从 Redis 队列取任务 → yt-dlp / Pyrogram 下载 → rclone 同步 → 推结果回 Redis

修复：
- 文件大小用 postprocessor_hooks 的 after_move 事件获取合并后真实路径
- 删除文件通过 Redis 队列（type=delete）由 worker 执行，避免 web 容器需要写权限
"""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import redis.asyncio as aioredis
import yt_dlp
from pyrogram import Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WORKER] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── 环境变量 ──────────────────────────────────────────────────
BOT_TOKEN    = os.environ["BOT_TOKEN"]
TG_API_ID    = int(os.environ["TG_API_ID"])
TG_API_HASH  = os.environ["TG_API_HASH"]
PROXY_HOST   = os.environ.get("PROXY_HOST", "")
PROXY_PORT   = int(os.environ.get("PROXY_PORT", "7890"))
REDIS_URL    = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
MAX_WORKERS  = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS", "3"))
MAX_SIZE_MB  = int(os.environ.get("MAX_FILE_SIZE_MB", "2000"))
COOKIES_DIR  = Path("/cookies")

RCLONE_ENABLE       = os.environ.get("RCLONE_ENABLE", "false").lower() == "true"
RCLONE_REMOTE       = os.environ.get("RCLONE_REMOTE", "")
RCLONE_DEST         = os.environ.get("RCLONE_DEST", "NDBot")
RCLONE_DELETE_AFTER = os.environ.get("RCLONE_DELETE_AFTER", "false").lower() == "true"
RCLONE_MODE         = os.environ.get("RCLONE_MODE", "manual")
RCLONE_CONFIG       = "/config/rclone/rclone.conf"

PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}" if PROXY_HOST else ""
PROXY_CFG = (
    {"scheme": "http", "hostname": PROXY_HOST, "port": PROXY_PORT}
    if PROXY_HOST else None
)

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def fmt_size(b: int) -> str:
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {u}"
        b //= 1024
    return f"{b:.1f} TB"


def safe_rel(rel: str) -> Optional[Path]:
    """防路径穿越，返回安全的绝对路径，失败返回 None"""
    try:
        target = (DOWNLOAD_DIR / rel).resolve()
        if str(target).startswith(str(DOWNLOAD_DIR.resolve())):
            return target
    except Exception:
        pass
    return None


# ── Pyrogram 客户端 ───────────────────────────────────────────
_tg: Optional[Client] = None


async def get_tg() -> Client:
    global _tg
    if _tg is None:
        _tg = Client(
            name="ndbot_worker",
            api_id=TG_API_ID,
            api_hash=TG_API_HASH,
            bot_token=BOT_TOKEN,
            workdir="/sessions",
            proxy=PROXY_CFG,
            no_updates=True,
        )
        await _tg.start()
        log.info("Pyrogram worker 客户端已连接")
    return _tg


# ── rclone ───────────────────────────────────────────────────

def rclone_ok() -> bool:
    if not RCLONE_ENABLE or not RCLONE_REMOTE:
        return False
    if not shutil.which("rclone"):
        log.warning("rclone 命令不存在")
        return False
    if not Path(RCLONE_CONFIG).exists():
        log.warning(f"rclone 配置文件不存在：{RCLONE_CONFIG}")
        return False
    return True


async def rclone_upload(local_path: Path, delete_after: bool = False) -> dict:
    if not rclone_ok():
        return {"success": False, "msg": "rclone 未启用或配置缺失"}
    try:
        rel = local_path.relative_to(DOWNLOAD_DIR)
    except ValueError:
        rel = local_path.name
    remote_path = f"{RCLONE_REMOTE}:{RCLONE_DEST}/{rel}"
    cmd = [
        "rclone", "--config", RCLONE_CONFIG,
        "move" if delete_after else "copy",
        str(local_path), remote_path,
        "--transfers", "4", "--retries", "3", "--low-level-retries", "10",
    ]
    env = os.environ.copy()
    if PROXY_URL:
        env["HTTPS_PROXY"] = PROXY_URL
        env["HTTP_PROXY"]  = PROXY_URL
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
        output = stdout.decode(errors="replace").strip()
        ok = proc.returncode == 0
        if not ok:
            log.error(f"rclone 失败(rc={proc.returncode}): {output[:200]}")
        return {"success": ok, "msg": output[:200], "remote": remote_path}
    except asyncio.TimeoutError:
        return {"success": False, "msg": "上传超时", "remote": remote_path}
    except Exception as e:
        return {"success": False, "msg": str(e)[:200], "remote": remote_path}


async def rclone_sync(src: str, dst: str) -> dict:
    """通用同步：src（本地路径）→ dst（remote:path）"""
    if not shutil.which("rclone"):
        return {"success": False, "msg": "rclone 命令不存在"}
    if not Path(RCLONE_CONFIG).exists():
        return {"success": False, "msg": f"rclone 配置文件不存在：{RCLONE_CONFIG}"}
    cmd = [
        "rclone", "--config", RCLONE_CONFIG,
        "sync", src, dst,
        "--transfers", "4", "--retries", "3",
    ]
    env = os.environ.copy()
    if PROXY_URL:
        env["HTTPS_PROXY"] = PROXY_URL
        env["HTTP_PROXY"]  = PROXY_URL
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=7200)
        output = stdout.decode(errors="replace").strip()
        ok = proc.returncode == 0
        return {"success": ok, "msg": output[:300], "remote": dst}
    except asyncio.TimeoutError:
        return {"success": False, "msg": "同步超时", "remote": dst}
    except Exception as e:
        return {"success": False, "msg": str(e)[:200], "remote": dst}


# ── yt-dlp 下载 ──────────────────────────────────────────────

def _cookie_file(platform: str) -> Optional[str]:
    for name in [platform, "cookies"]:
        p = COOKIES_DIR / f"{name}.txt"
        if p.exists():
            return str(p)
    return None


def _build_opts(platform: str, action: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    opts: dict = {
        "outtmpl":             str(out_dir / "%(uploader)s_%(title).80s_%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist":          True,
        "quiet":               True,
        "no_warnings":         True,
        "max_filesize":        MAX_SIZE_MB * 1024 * 1024,
        # ── 超时与重试（解决长视频 read timeout）──
        "socket_timeout":      120,        # 单次 socket 读写超时（秒），默认20太短
        "retries":             10,         # 下载失败重试次数
        "fragment_retries":    10,         # 分片下载失败重试次数
        "retry_sleep_functions": {"http": lambda n: min(2 ** n, 30)},  # 指数退避重试
        "file_access_retries": 5,          # 文件写入重试
        "extractor_retries":   5,          # 提取器重试
        "noprogress":          True,       # 不打印进度条（容器内无意义）
    }
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    cookie = _cookie_file(platform)
    if cookie:
        opts["cookiefile"] = cookie

    # 对 YouTube 指定多客户端回退，兼容 SABR 实验组及普通账号
    # 并启用 Node.js 作为 JS 运行时解密 n challenge
    if platform == "youtube":
        opts["extractor_args"] = {
            "youtube": {
                "player_client": ["web", "tv_embedded", "ios"],
                "skip": ["translated_subs"],
            }
        }
        opts["js_runtimes"] = {"node": {}}

    if action == "best":
        opts["format"] = "bestvideo+bestaudio/bestvideo/best"
    elif action == "1080p":
        opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif action == "720p":
        opts["format"] = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif action == "480p":
        opts["format"] = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    elif action in ("video", "media"):
        opts["format"] = "bestvideo+bestaudio/bestvideo/best"
    elif action == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3", "preferredquality": "192"}]
        opts.pop("merge_output_format", None)
    elif action == "m4a":
        opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}]
        opts.pop("merge_output_format", None)
    elif action == "audio":
        opts["format"] = "bestaudio/best"
        opts.pop("merge_output_format", None)
    elif action == "subs":
        opts.update({"writesubtitles": True, "writeautomaticsub": True,
                     "subtitleslangs": ["zh-Hans", "zh-Hant", "en"],
                     "skip_download": True})
    elif action == "thumb":
        opts.update({"writethumbnail": True, "skip_download": True})
    elif action == "image":
        opts.update({"format": "best", "write_all_thumbnails": True})
    elif action == "text":
        opts.update({"skip_download": True, "writeinfojson": True,
                     "writedescription": True})
    elif action == "all":
        opts.update({"format": "best", "noplaylist": False,
                     "writethumbnail": True, "writedescription": True})
    else:
        opts["format"] = "best"

    return opts


async def download_url(task: dict) -> dict:
    platform = task.get("platform", "generic")
    action   = task.get("action", "best")
    url      = task["url"]
    out_dir  = DOWNLOAD_DIR / platform
    opts     = _build_opts(platform, action, out_dir)

    # ── 关键修复：用 postprocessor_hooks 捕获合并后的最终文件路径 ──
    # progress_hooks 的 "finished" 事件发生在 ffmpeg 合并前（临时文件），
    # postprocessor_hooks 的 "after_move" 事件才是合并并重命名后的真实文件。
    final_files: list[str] = []

    def pp_hook(d: dict):
        """postprocessor hook：捕获后处理完成后的最终文件路径"""
        # status 可能是 'started' / 'finished'
        if d.get("status") == "finished":
            filepath = d.get("info_dict", {}).get("filepath") or d.get("filepath", "")
            if filepath and filepath not in final_files:
                final_files.append(filepath)

    def progress_hook(d: dict):
        """progress hook：仅作为兜底，捕获不经过后处理器的文件（如直接下载的单流）"""
        if d["status"] == "finished":
            fname = d.get("filename", "")
            # 只在 postprocessor_hooks 没记录时才用这个
            if fname and fname not in final_files:
                final_files.append(fname)

    opts["progress_hooks"]       = [progress_hook]
    opts["postprocessor_hooks"]  = [pp_hook]

    loop = asyncio.get_event_loop()
    try:
        def _run():
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

        await loop.run_in_executor(None, _run)
    except yt_dlp.utils.DownloadError as e:
        return {"success": False, "error": str(e)[:500]}
    except Exception as e:
        log.exception("yt-dlp 未知异常")
        return {"success": False, "error": str(e)[:500]}

    # 过滤掉已被删除的临时文件（合并后 yt-dlp 会删临时流文件）
    existing = [f for f in final_files if Path(f).exists()]

    if existing:
        total = sum(Path(f).stat().st_size for f in existing)
        return {
            "success":  True,
            "files":    [Path(f).name for f in existing],
            "paths":    existing,
            "save_dir": str(out_dir),
            "size":     fmt_size(total),
        }
    else:
        # skip_download 场景（字幕/封面/文字），扫描目录新文件作兜底
        return {
            "success":  True,
            "files":    ["（文件已保存至目录）"],
            "paths":    [],
            "save_dir": str(out_dir),
            "size":     "—",
        }


# ── Telegram 媒体下载 ─────────────────────────────────────────

async def download_tg_media(task: dict) -> dict:
    chat_id    = task["chat_id"]
    message_id = task["message_id"]
    out_dir    = DOWNLOAD_DIR / "telegram"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        tg  = await get_tg()
        msg = await tg.get_messages(chat_id, message_id)
        saved: list[str] = []
        paths: list[str] = []

        media_types = ("photo", "video", "document", "audio",
                       "voice", "video_note", "sticker", "animation")
        if any(getattr(msg, mt, None) for mt in media_types):
            path = await tg.download_media(msg, file_name=str(out_dir) + "/")
            if path:
                saved.append(Path(path).name)
                paths.append(path)

        content = msg.text or msg.caption
        if content:
            fname = f"text_{chat_id}_{message_id}.txt"
            fpath = out_dir / fname
            fpath.write_text(content, encoding="utf-8")
            saved.append(fname)
            paths.append(str(fpath))

        if not saved:
            return {"success": False, "error": "消息中没有可保存的内容"}

        total = sum(Path(p).stat().st_size for p in paths if Path(p).exists())
        return {
            "success":  True,
            "files":    saved,
            "paths":    paths,
            "save_dir": str(out_dir),
            "size":     fmt_size(total),
        }
    except Exception as e:
        log.exception("Telegram 媒体下载失败")
        return {"success": False, "error": str(e)[:500]}


async def download_tg_link(task: dict) -> dict:
    ytdlp_task = {**task, "platform": "telegram", "action": "best"}
    result = await download_url(ytdlp_task)
    if result["success"] and result.get("paths"):
        return result
    return {
        "success": False,
        "error": (
            "无法直接下载此链接。\n"
            "请将消息**直接转发**给机器人，即可自动保存。"
        ),
    }


# ── rclone 自动上传（auto 模式）─────────────────────────────

async def auto_upload(result: dict) -> str:
    if not (RCLONE_ENABLE and RCLONE_MODE == "auto" and result.get("success")):
        return ""
    if not rclone_ok():
        return ""
    paths = result.get("paths", [])
    if paths:
        tasks = [rclone_upload(Path(p), RCLONE_DELETE_AFTER)
                 for p in paths if Path(p).exists()]
        results = await asyncio.gather(*tasks)
        ok = sum(1 for r in results if r.get("success"))
        return f"\n☁️ 已上传到 `{RCLONE_REMOTE}:{RCLONE_DEST}`（{ok}/{len(results)} 个文件）"
    else:
        save_dir = result.get("save_dir", "")
        if save_dir:
            r = await rclone_upload(Path(save_dir), RCLONE_DELETE_AFTER)
            if r.get("success"):
                return f"\n☁️ 目录已同步到 `{RCLONE_REMOTE}:{RCLONE_DEST}`"
    return ""


# ── 任务分发 ─────────────────────────────────────────────────

async def handle_sync(task: dict, r: aioredis.Redis):
    """处理 /sync 命令或 Web 端触发的云盘同步任务"""
    tid     = task["id"]
    src     = task.get("rclone_src", str(DOWNLOAD_DIR))
    dst     = task.get("rclone_dst", f"{RCLONE_REMOTE}:{RCLONE_DEST}")
    log.info(f"▶ [{tid}] 同步：{src} → {dst}")
    res = await rclone_sync(src, dst)
    msg = (
        f"☁️ **同步完成**\n📡 目标：`{res.get('remote', '')}`"
        if res["success"]
        else f"☁️ **同步失败**\n{res.get('msg', '')[:200]}"
    )
    # 更新任务状态
    stored = await r.hget("dl:tasks", tid)
    if stored:
        t = json.loads(stored)
        t["status"] = "done" if res["success"] else "failed"
        await r.hset("dl:tasks", tid, json.dumps(t))

    await r.lpush("dl:results", json.dumps({
        "id":         tid,
        "type":       "sync",
        "message":    msg,
        "reply_chat": task.get("reply_chat"),
        "reply_msg":  task.get("reply_msg"),
    }))


async def handle_delete(task: dict, r: aioredis.Redis):
    """
    处理 Web 端发来的文件删除任务（方案二：通过队列由 worker 执行）
    Worker 容器有读写权限，Web 容器只读挂载。
    """
    tid = task["id"]
    rel = task.get("rel", "")
    log.info(f"▶ [{tid}] 删除文件：{rel}")

    result = {"id": tid, "type": "delete",
              "reply_chat": task.get("reply_chat"),
              "reply_msg":  task.get("reply_msg")}

    if not rel:
        result["success"] = False
        result["error"]   = "未指定文件路径"
    else:
        target = safe_rel(rel)
        if target is None:
            result["success"] = False
            result["error"]   = "非法路径"
        elif not target.exists():
            result["success"] = False
            result["error"]   = "文件不存在"
        else:
            try:
                target.unlink()
                log.info(f"[{tid}] 已删除：{target}")
                result["success"] = True
            except Exception as e:
                result["success"] = False
                result["error"]   = str(e)[:200]

    # 更新任务状态为 done/failed（否则 Web 端一直显示 queued）
    stored = await r.hget("dl:tasks", tid)
    if stored:
        t = json.loads(stored)
        t["status"] = "done" if result.get("success") else "failed"
        await r.hset("dl:tasks", tid, json.dumps(t))

    await r.lpush("dl:results", json.dumps(result))


async def process(task: dict, r: aioredis.Redis):
    tid = task["id"]
    typ = task.get("type", "url")

    if typ == "sync":
        await handle_sync(task, r)
        return

    if typ == "delete":
        await handle_delete(task, r)
        return

    log.info(
        f"▶ [{tid}] type={typ} platform={task.get('platform', '')} "
        f"url={str(task.get('url', ''))[:60]}"
    )

    raw = await r.hget("dl:tasks", tid)
    if raw:
        stored = json.loads(raw)
        stored["status"] = "running"
        await r.hset("dl:tasks", tid, json.dumps(stored))

    try:
        if typ == "tg_media":
            result = await download_tg_media(task)
        elif typ == "url" and task.get("platform") == "tglink":
            result = await download_tg_link(task)
        else:
            result = await download_url(task)
    except Exception as e:
        log.exception(f"[{tid}] 未捕获异常")
        result = {"success": False, "error": str(e)[:500]}

    rclone_msg = await auto_upload(result)

    if raw:
        stored["status"] = "done" if result["success"] else "failed"
        await r.hset("dl:tasks", tid, json.dumps(stored))

    result.update({
        "id":         tid,
        "rclone_msg": rclone_msg,
        "reply_chat": task.get("reply_chat"),
        "reply_msg":  task.get("reply_msg"),
    })
    await r.lpush("dl:results", json.dumps(result))
    log.info(f"{'✅' if result['success'] else '❌'} [{tid}] 完成")


async def worker_loop(wid: int, r: aioredis.Redis, sem: asyncio.Semaphore):
    log.info(f"Worker #{wid} 就绪")
    while True:
        try:
            item = await r.brpop("dl:queue", timeout=3)
            if not item:
                continue
            task = json.loads(item[1])
            async with sem:
                await process(task, r)
        except Exception as e:
            log.exception(f"Worker #{wid} 异常: {e}")
            await asyncio.sleep(2)


async def main():
    r   = await aioredis.from_url(REDIS_URL, decode_responses=True)
    sem = asyncio.Semaphore(MAX_WORKERS)

    try:
        await get_tg()
    except Exception as e:
        log.error(f"Pyrogram 连接失败（Telegram 媒体下载不可用）: {e}")

    if RCLONE_ENABLE:
        if rclone_ok():
            log.info(f"✅ rclone 已启用：{RCLONE_REMOTE}:{RCLONE_DEST}，模式：{RCLONE_MODE}")
        else:
            log.warning("⚠️ RCLONE_ENABLE=true 但 rclone 不可用，请检查 ./rclone/rclone.conf")

    log.info(f"✅ Worker 启动，并发={MAX_WORKERS}，最大文件={MAX_SIZE_MB}MB")
    await asyncio.gather(*[worker_loop(i, r, sem) for i in range(MAX_WORKERS)])


if __name__ == "__main__":
    asyncio.run(main())
