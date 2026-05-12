# 📥 NDBot v1.01.0512   by AiPo
## Self-hosted Docker bot for unified media downloads — YouTube / X.com / Bilibili / Instagram / TikTok / Telegram media + cloud sync

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Release](https://img.shields.io/github/v/release/aipo-lenshow/NDBot)](https://github.com/aipo-lenshow/NDBot/releases)
[![CI](https://github.com/aipo-lenshow/NDBot/actions/workflows/scan.yml/badge.svg)](https://github.com/aipo-lenshow/NDBot/actions/workflows/scan.yml)

> [中文 README](./README.md)

## Quick install

### Option 1: Shell interactive wizard (recommended, zero deps)

```bash
bash install.sh
```

### Option 2: Python TUI wizard (graphical, deps auto-installed)

```bash
python3 install_tui.py
```

Both wizards guide you through proxy / cloud sync / cookies configuration.

---

## Manual deployment

### Step 1 — configure `.env`

```bash
cp .env .env.bak   # backup if you already have one
nano .env
```

Required fields:

```
BOT_TOKEN=from @BotFather
TG_API_ID=from my.telegram.org/apps
TG_API_HASH=from my.telegram.org/apps
PROXY_HOST=your proxy IP (required for China servers)
PROXY_PORT=7890
ALLOWED_USERS=your Telegram user ID
DOWNLOAD_PATH=./downloads
```

### Step 2 — create directories and start

```bash
mkdir -p downloads sessions cookies rclone
docker compose up -d --build
docker compose logs -f
```

---

## Features

| Platform | Supported content |
|----------|-------------------|
| 🎬 YouTube | Video (best / 1080p / 720p / 480p) / MP3 / M4A / subs / thumbnails |
| 🐦 X.com (Twitter) | Video / images / all media |
| 📺 Bilibili | Video / audio |
| 📸 Instagram | Video / images |
| 🎵 TikTok | Video / audio |
| 🌐 Other | All 1000+ sites yt-dlp supports |
| 📨 Telegram media | Just forward the message to the bot to save it |

---

## Cookies configuration (for member content)

For YouTube Premium, X.com private content, Bilibili VIP videos, etc.

1. Install browser extension [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc)
2. Log in to the target site and export cookies as `.txt`
3. Upload to `./cookies/`, named per platform:

```
cookies/
├── youtube.txt     YouTube
├── xcom.txt        X.com / Twitter
├── bilibili.txt    Bilibili
└── cookies.txt     fallback for other platforms
```

No restart needed — picked up on next download.

---

## Cloud sync (rclone)

| Cloud | Mode | Note |
|-------|------|------|
| OneDrive | ✅ native | rclone storage type `onedrive` |
| Google Drive | ✅ native | rclone storage type `drive` |
| S3 / R2 / COS / OSS | ✅ native | rclone storage type `s3` |
| NAS (Samba) | ✅ native | rclone storage type `smb` |
| NAS (SFTP) | ✅ native | rclone storage type `sftp` |
| Baidu / Aliyun / Quark | 🔄 via AList | rclone has no native backend → use [AList](https://alist.nn.ci) as WebDAV bridge |

See the Chinese README for the detailed AList → WebDAV bridging recipe.

---

## Common ops

```bash
docker compose logs -f                  # follow all logs
docker compose logs -f bot              # bot only
docker compose logs -f worker           # download progress
docker compose restart                  # restart everything
# Update yt-dlp (fix platform-side breakage)
docker compose exec worker pip install -U yt-dlp && docker compose restart worker
```

---

## Uninstall

```bash
cd <install dir>
docker compose down --rmi all --volumes
cd .. && rm -rf <install dir>
```

> ⚠️ **Back up `downloads/` first!**

---

## License

NDBot is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
See [LICENSE](./LICENSE) for the full text.

In short: NDBot is free to use, modify, and redistribute, but any modified version (including network-deployed services) must release its source code under AGPL-3.0 as well.
