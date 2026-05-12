#!/usr/bin/env bash
# =============================================================
#  NDBot v1.01.0512 一键安装脚本
#  支持：Ubuntu / Debian / CentOS / RHEL / Rocky
#  --- By AiPo ---
# =============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅ $*${NC}"; }
err()  { echo -e "  ${RED}❌ $*${NC}"; exit 1; }
warn() { echo -e "  ${YELLOW}⚠️  $*${NC}"; }
info() { echo -e "  ${CYAN}ℹ  $*${NC}"; }
step() { echo ""; echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}";
         echo -e "${BOLD}${BLUE}  ▶ $*${NC}";
         echo -e "${BOLD}${BLUE}══════════════════════════════════════════${NC}"; echo ""; }
ask()  { echo -ne "  ${YELLOW}→ $*${NC} "; }
hr()   { echo -e "  ${BLUE}──────────────────────────────────────────${NC}"; }

read_env() { [ -f ".env" ] && grep "^$1=" .env 2>/dev/null | cut -d= -f2- || echo ""; }

clear
echo -e "${BOLD}${CYAN}"
cat << 'BANNER'

    ███╗   ██╗██████╗ ██████╗  ██████╗ ████████╗
    ████╗  ██║██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝
    ██╔██╗ ██║██║  ██║██████╔╝██║   ██║   ██║
    ██║╚██╗██║██║  ██║██╔══██╗██║   ██║   ██║
    ██║ ╚████║██████╔╝██████╔╝╚██████╔╝   ██║
    ╚═╝  ╚═══╝╚═════╝ ╚═════╝  ╚═════╝    ╚═╝

    ─────────────────────────────────────────────

        🐳  Docker Container Initialized

        Project : NDBot Service
        Author  : AiPo
    ─────────────────────────────────────────────

BANNER
echo -e "${NC}${BOLD}  NDBot v1.01.0512 · 安装向导
  by AiPo${NC}"
echo -e "  支持 YouTube / X.com / Bilibili / Instagram / TikTok / Telegram 媒体"
echo ""; sleep 1

# ── 检查 Docker ───────────────────────────────────────────
step "第一步：检查系统环境"
if ! command -v docker &>/dev/null; then
    warn "未检测到 Docker，正在自动安装..."
    curl -fsSL https://get.docker.com | sh || err "请手动安装 Docker：https://docs.docker.com/engine/install/"
fi
ok "Docker：$(docker --version | grep -oP '[\d.]+' | head -1)"
docker compose version &>/dev/null || err "请安装 Docker Compose Plugin：https://docs.docker.com/compose/install/linux/"
ok "Docker Compose：已就绪"

# ── 安装目录 ──────────────────────────────────────────────
step "第二步：安装位置"
DEFAULT_DIR="$HOME/NDBot"
ask "安装目录 [${DEFAULT_DIR}]："
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"; INSTALL_DIR="${INSTALL_DIR%/}"
[ -f "$INSTALL_DIR/docker-compose.yml" ] && UPDATE_MODE=true || UPDATE_MODE=false
mkdir -p "$INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$INSTALL_DIR/docker-compose.yml" ]; then
    if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        cp -r "$SCRIPT_DIR"/. "$INSTALL_DIR/" 2>/dev/null || true
        ok "项目文件已复制"
    else
        err "找不到项目文件！请将 NDBot 解压后，从解压目录运行此脚本。"
    fi
fi
cd "$INSTALL_DIR"
ok "安装目录：$INSTALL_DIR"
[ "$UPDATE_MODE" = true ] && warn "检测到已有配置，进入更新模式"

# ── 代理（最先收集，构建时需要）──────────────────────────
step "第三步：代理配置（重要）"
echo -e "  ${CYAN}如果服务器在中国大陆，必须配置代理才能：${NC}"
echo -e "  • 拉取 Docker 镜像（python、redis 等）"
echo -e "  • 连接 Telegram 服务器"
echo -e "  • 下载 YouTube / X.com 等平台内容"
echo ""
EXISTING_PROXY=""
PH=$(read_env PROXY_HOST); PP=$(read_env PROXY_PORT)
[ -n "$PH" ] && EXISTING_PROXY="${PH}:${PP}"

ask "代理地址（格式 IP:端口，如 <你的代理IP>:7890，留空不使用）[${EXISTING_PROXY:-无}]："
read -r PROXY_INPUT
PROXY_INPUT="${PROXY_INPUT:-$EXISTING_PROXY}"
PROXY_HOST_NEW=""; PROXY_PORT_NEW="7890"; PROXY_URL=""
if [ -n "$PROXY_INPUT" ]; then
    PROXY_HOST_NEW="${PROXY_INPUT%:*}"
    PROXY_PORT_NEW="${PROXY_INPUT##*:}"
    PROXY_URL="http://${PROXY_HOST_NEW}:${PROXY_PORT_NEW}"
    # 立即 export，后续所有 docker 命令都走代理
    export HTTPS_PROXY="$PROXY_URL" HTTP_PROXY="$PROXY_URL"
    export https_proxy="$PROXY_URL" http_proxy="$PROXY_URL"
    ok "代理已设置：$PROXY_URL（已应用到本次会话所有操作）"
else
    warn "未设置代理，请确保服务器可直接访问外网"
fi

# ── Telegram 配置 ─────────────────────────────────────────
step "第四步：Telegram Bot 配置"
echo -e "  ${CYAN}需要准备：${NC}"
echo -e "  Bot Token  → 与 @BotFather 对话，/newbot"
echo -e "  API ID     → https://my.telegram.org/apps（创建应用）"
echo -e "  API Hash   → 同上（32位十六进制字符串）"
echo -e "  User ID    → 向 @userinfobot 发任意消息获取"
echo ""

while true; do
    ask "Bot Token [$([ -n "$(read_env BOT_TOKEN)" ] && echo '已有，回车保留' || echo '必填')]："
    read -r INPUT; INPUT="${INPUT:-$(read_env BOT_TOKEN)}"
    [[ "$INPUT" =~ ^[0-9]+:[A-Za-z0-9_-]{30,}$ ]] && { BOT_TOKEN_NEW="$INPUT"; ok "格式正确"; break; } \
        || warn "格式错误，应为：数字:至少30位字母数字（如 1234567890:ABCdef...）"
done
while true; do
    ask "TG_API_ID [$([ -n "$(read_env TG_API_ID)" ] && echo '已有，回车保留' || echo '必填')]："
    read -r INPUT; INPUT="${INPUT:-$(read_env TG_API_ID)}"
    [[ "$INPUT" =~ ^[0-9]{5,}$ ]] && { TG_API_ID_NEW="$INPUT"; ok "格式正确"; break; } \
        || warn "应为5位以上纯数字"
done
while true; do
    ask "TG_API_HASH [$([ -n "$(read_env TG_API_HASH)" ] && echo '已有，回车保留' || echo '必填')]："
    read -r INPUT; INPUT="${INPUT:-$(read_env TG_API_HASH)}"
    [ "${#INPUT}" -eq 32 ] && { TG_API_HASH_NEW="$INPUT"; ok "格式正确（32位）"; break; } \
        || warn "应为32位字符（当前 ${#INPUT} 位）"
done
EXISTING_USERS=$(read_env ALLOWED_USERS)
ask "允许使用的 Telegram User ID（逗号分隔，留空=所有人）[${EXISTING_USERS:-无限制}]："
read -r INPUT; ALLOWED_USERS_NEW="${INPUT:-$EXISTING_USERS}"

# ── 下载路径 ──────────────────────────────────────────────
step "第五步：下载保存位置"
EXISTING_DL=$(read_env DOWNLOAD_PATH)
DEFAULT_DL="${EXISTING_DL:-$INSTALL_DIR/downloads}"
ask "文件保存路径 [${DEFAULT_DL}]："
read -r INPUT; DOWNLOAD_PATH_NEW="${INPUT:-$DEFAULT_DL}"
ok "下载目录：$DOWNLOAD_PATH_NEW"

# ── 下载参数 ──────────────────────────────────────────────
step "第六步：下载参数"
EXISTING_CONC=$(read_env MAX_CONCURRENT_DOWNLOADS); EXISTING_CONC="${EXISTING_CONC:-3}"
EXISTING_SIZE=$(read_env MAX_FILE_SIZE_MB); EXISTING_SIZE="${EXISTING_SIZE:-2000}"

ask "最大并发下载数（同时下载几个文件）[${EXISTING_CONC}]："
read -r INPUT; MAX_CONC_NEW="${INPUT:-$EXISTING_CONC}"
[[ "$MAX_CONC_NEW" =~ ^[0-9]+$ ]] || MAX_CONC_NEW=3
ok "并发数：$MAX_CONC_NEW"

ask "单文件最大体积 MB（超过则跳过）[${EXISTING_SIZE}]："
read -r INPUT; MAX_SIZE_NEW="${INPUT:-$EXISTING_SIZE}"
[[ "$MAX_SIZE_NEW" =~ ^[0-9]+$ ]] || MAX_SIZE_NEW=2000
ok "最大文件：${MAX_SIZE_NEW} MB"

# ── Web UI ────────────────────────────────────────────────
step "第七步：Web UI 配置"
EXISTING_PORT=$(read_env WEB_PORT); EXISTING_PORT="${EXISTING_PORT:-5000}"
ask "Web UI 端口 [${EXISTING_PORT}]："
read -r INPUT; WEB_PORT_NEW="${INPUT:-$EXISTING_PORT}"
ask "Web UI 访问密码（留空无需密码）："
read -r WEB_SECRET_NEW
ok "端口：$WEB_PORT_NEW  密码：${WEB_SECRET_NEW:+（已设置）}${WEB_SECRET_NEW:-（无）}"

# ── Cookies 引导 ──────────────────────────────────────────
step "第八步：Cookies 配置说明（可选）"
echo -e "  ${CYAN}以下情况需要配置 Cookies：${NC}"
echo -e "  • YouTube 会员专属视频"
echo -e "  • X.com 登录后才能看的内容"
echo -e "  • B 站大会员视频"
echo ""
echo -e "  ${CYAN}获取方法：${NC}"
echo -e "  1. 浏览器安装扩展 ${YELLOW}Get cookies.txt LOCALLY${NC}"
echo -e "     https://chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc"
echo -e "  2. 登录对应网站后点击扩展图标，导出 Cookie 为 .txt 文件"
echo -e "  3. 上传到服务器目录 ${CYAN}${INSTALL_DIR}/cookies/${NC}，按平台命名："
echo -e "       ${YELLOW}youtube.txt${NC}   YouTube"
echo -e "       ${YELLOW}xcom.txt${NC}      X.com / Twitter"
echo -e "       ${YELLOW}bilibili.txt${NC}  B站"
echo -e "       ${YELLOW}cookies.txt${NC}   通用兜底（其他平台）"
echo ""
info "安装完成后随时可以添加，无需重启即可生效"
echo ""
ask "按回车继续..."
read -r _

# ── rclone 云盘同步 ───────────────────────────────────────
step "第九步：云盘同步（可选）"
echo -e "  ${CYAN}直接支持：OneDrive / Google Drive / S3 / NAS 等${NC}"
    echo -e "  ${YELLOW}国内云盘（百度/阿里/夸克）需通过 AList 中转，详见后续说明${NC}"
echo ""
ask "是否启用云盘同步？[1=是 2=否，默认2]："
read -r INPUT
if [ "$INPUT" = "1" ]; then
    RCLONE_ENABLE_NEW="true"

    # ── 检查 / 安装 rclone ──────────────────────────────────
    if ! command -v rclone &>/dev/null; then
        echo ""
        warn "未检测到 rclone，开始安装..."
        [ -n "$PROXY_URL" ] && echo -e "  ${CYAN}（通过代理：$PROXY_URL）${NC}"
        echo ""
        # 先下载安装脚本到临时文件，再执行，实时显示进度
        RCLONE_TMP=$(mktemp /tmp/rclone-install-XXXX.sh)
        # 代理已通过 export 设置，curl 自动继承
        if curl -fsSL --progress-bar https://rclone.org/install.sh -o "$RCLONE_TMP"; then
            echo ""
            echo -e "  正在安装 rclone..."
            bash "$RCLONE_TMP" 2>&1 | while IFS= read -r line; do
                echo -e "  ${CYAN}│${NC} $line"
            done
            rm -f "$RCLONE_TMP"
        else
            rm -f "$RCLONE_TMP"
            warn "rclone 脚本下载失败"
            if [ -n "$PROXY_URL" ]; then
                warn "请检查代理是否可用：$PROXY_URL"
            fi
            warn "可手动安装：curl https://rclone.org/install.sh | sudo bash"
        fi
        echo ""
    fi

    if command -v rclone &>/dev/null; then
        ok "rclone：$(rclone --version | head -1)"
        echo ""
        echo -e "  ${CYAN}各云盘类型说明：${NC}"
        echo -e "  ${YELLOW}⚠ 百度网盘、阿里云盘、夸克网盘在 rclone 中没有原生后端！${NC}"
        echo -e "  ${YELLOW}  需先部署 AList（https://alist.nn.ci）转为 WebDAV 再连接。${NC}"
        echo ""
        echo -e "  ✅ 直接支持：OneDrive → ${CYAN}onedrive${NC}  Google Drive → ${CYAN}drive${NC}  S3 → ${CYAN}s3${NC}"
        echo -e "  🔄 中转支持：百度/阿里/夸克 → AList → ${CYAN}webdav${NC}"
        echo ""
        ask "是否现在运行 rclone config 配置云盘？[1=是 2=稍后配置，默认2]："
        read -r RC_INPUT
        if [ "$RC_INPUT" = "1" ]; then
            echo ""
            echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${BOLD}${CYAN}  ║           rclone 云盘配置向导 · 中文操作说明               ║${NC}"
            echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            echo -e "  rclone 使用英文交互界面，请对照以下说明操作："
            echo ""
            echo -e "  ${BOLD}【第1步 - 主菜单】${NC} 看到 n/s/q 选项时："
            echo -e "    输入 ${GREEN}n${NC} → 新建云盘连接"
            echo ""
            echo -e "  ${BOLD}【第2步 - 输入名称】${NC} 看到 ${YELLOW}name>${NC} 时："
            echo -e "    输入一个英文名称，例如："
            echo -e "    OneDrive → ${YELLOW}onedrive${NC}   Google → ${YELLOW}gdrive${NC}   AList中转 → ${YELLOW}alist${NC}"
            echo -e "    OneDrive → ${YELLOW}onedrive${NC}  家用NAS  → ${YELLOW}mynas${NC}"
            echo -e "    ${RED}⚠ 记住这个名字！后面 .env 的 RCLONE_REMOTE 要填它${NC}"
            echo ""
            echo -e "  ${BOLD}【第3步 - 选择类型】${NC} 看到 ${YELLOW}Storage>${NC} 时，输入关键词："
            echo ""
            echo -e "  ${BOLD}★ 支持直接配置的云盘：${NC}"
            echo -e "    ${CYAN}onedrive${NC}       微软 OneDrive"
            echo -e "    ${CYAN}drive${NC}          Google Drive"
            echo -e "    ${CYAN}s3${NC}             S3兼容（Cloudflare R2 / 腾讯COS / 阿里OSS）"
            echo ""
            echo -e "  ${BOLD}★ 国内云盘（百度/阿里/夸克）需通过 AList 中转：${NC}"
            echo -e "    ${YELLOW}说明：百度网盘、阿里云盘、夸克网盘在 rclone 中没有原生后端，${NC}"
            echo -e "    ${YELLOW}需要先部署 AList（https://alist.nn.ci），开启 WebDAV，再用 rclone 连接${NC}"
            echo -e "    ${CYAN}webdav${NC}         WebDAV（连接 AList 或 CloudDrive2 中转）"
            echo -e "    地址示例：${YELLOW}http://服务器IP:5244/dav${NC}（AList 默认地址）"
            echo ""
            echo -e "  ${BOLD}★ 家用 NAS：${NC}"
            echo -e "    ${GREEN}smb${NC}            Samba 共享（最通用，群晖/威联通/Windows 均支持）"
            echo -e "    ${GREEN}sftp${NC}           SFTP（群晖 DSM / 威联通 QTS 均支持）"
            echo -e "    ${GREEN}webdav${NC}         WebDAV（群晖 DSM 支持）"
            echo -e "    ${GREEN}ftp${NC}            FTP"
            echo -e "    ${GREEN}s3${NC}             S3 兼容（MinIO / Cloudflare R2 / 腾讯COS）"
            echo ""
            echo -e "  ${BOLD}【第4步 - 应用密钥】${NC} 看到 ${YELLOW}client_id>${NC} / ${YELLOW}client_secret>${NC} 时："
            echo -e "    直接按 ${GREEN}回车${NC} 使用默认值即可"
            echo ""
            echo -e "  ${BOLD}【第5步 - 高级设置】${NC} 看到 ${YELLOW}Edit advanced config${NC} 时："
            echo -e "    输入 ${RED}n${NC} 跳过"
            echo ""
            echo -e "  ${BOLD}【第6步 - OAuth 授权】${NC} 看到 ${YELLOW}Use web browser${NC} 时："
            echo -e "    服务器有图形界面 → 输入 ${GREEN}y${NC}，浏览器自动打开"
            echo -e "    纯命令行服务器  → 输入 ${YELLOW}n${NC}，复制链接到本地浏览器授权"
            echo -e "                       将授权码粘贴回终端"
            echo ""
            echo -e "  ${BOLD}【第7步 - 确认】${NC} 看到 ${YELLOW}Yes this is OK${NC} 时："
            echo -e "    输入 ${GREEN}y${NC} 保存"
            echo ""
            echo -e "  ${BOLD}【完成】${NC} 看到云盘列表时："
            echo -e "    输入 ${GREEN}q${NC} 退出，记住 Name 列的名称"
            echo ""
            echo -e "  ${CYAN}────────────────────────────────────────────────────────────${NC}"
            echo -e "  ${BOLD}现在启动 rclone config ...${NC}"
            echo -e "  ${CYAN}────────────────────────────────────────────────────────────${NC}"
            echo ""
            # 代理已通过 export 设置，rclone 自动继承
            rclone config
            if [ -f "$HOME/.config/rclone/rclone.conf" ]; then
                mkdir -p "$INSTALL_DIR/rclone"
                cp "$HOME/.config/rclone/rclone.conf" "$INSTALL_DIR/rclone/rclone.conf"
                ok "rclone.conf 已复制到 $INSTALL_DIR/rclone/"
            else
                warn "未找到配置文件，请稍后手动复制"
            fi
        else
            echo ""
            info "稍后手动配置步骤："
            echo -e "  1. 运行：${YELLOW}rclone config${NC}"
            echo -e "  2. 复制：${YELLOW}cp ~/.config/rclone/rclone.conf $INSTALL_DIR/rclone/rclone.conf${NC}"
            echo -e "  3. 修改 .env：RCLONE_REMOTE=你的远端名称"
            echo -e "  4. 重启：${YELLOW}cd $INSTALL_DIR && docker compose up -d${NC}"
        fi
    else
        warn "rclone 安装未成功，跳过云盘配置。稍后可手动安装。"
    fi

    ask "rclone 远端名称（与 rclone.conf 里 [xxx] 一致）："
    read -r RCLONE_REMOTE_NEW
    RCLONE_REMOTE_NEW="${RCLONE_REMOTE_NEW:-$(read_env RCLONE_REMOTE)}"
    ask "云盘目标目录 [NDBot]："
    read -r INPUT; RCLONE_DEST_NEW="${INPUT:-NDBot}"
    ask "上传后删除本地文件？[1=是 2=否，默认2]："
    read -r INPUT; [ "$INPUT" = "1" ] && RCLONE_DELETE_NEW="true" || RCLONE_DELETE_NEW="false"
    ask "触发方式 [1=下载后自动上传 2=/sync命令触发，默认1]："
    read -r INPUT; [ "$INPUT" = "2" ] && RCLONE_MODE_NEW="manual" || RCLONE_MODE_NEW="auto"
else
    RCLONE_ENABLE_NEW="false"
    RCLONE_REMOTE_NEW="$(read_env RCLONE_REMOTE)"
    RCLONE_DEST_NEW="NDBot"
    RCLONE_DELETE_NEW="false"
    RCLONE_MODE_NEW="auto"
fi

# ── 写入 .env ─────────────────────────────────────────────
step "写入配置文件"
cat > .env << ENVEOF
# NDBot 配置文件 - 由安装脚本生成于 $(date)
# 修改后执行：docker compose up -d 即可生效

BOT_TOKEN=${BOT_TOKEN_NEW}
TG_API_ID=${TG_API_ID_NEW}
TG_API_HASH=${TG_API_HASH_NEW}
ALLOWED_USERS=${ALLOWED_USERS_NEW}
PROXY_HOST=${PROXY_HOST_NEW}
PROXY_PORT=${PROXY_PORT_NEW}
DOWNLOAD_PATH=${DOWNLOAD_PATH_NEW}
MAX_CONCURRENT_DOWNLOADS=${MAX_CONC_NEW}
MAX_FILE_SIZE_MB=${MAX_SIZE_NEW}
WEB_PORT=${WEB_PORT_NEW}
WEB_SECRET=${WEB_SECRET_NEW}
RCLONE_ENABLE=${RCLONE_ENABLE_NEW}
RCLONE_REMOTE=${RCLONE_REMOTE_NEW}
RCLONE_DEST=${RCLONE_DEST_NEW}
RCLONE_DELETE_AFTER=${RCLONE_DELETE_NEW}
RCLONE_MODE=${RCLONE_MODE_NEW}
ENVEOF
ok ".env 已生成"

mkdir -p "$DOWNLOAD_PATH_NEW" sessions cookies rclone
chmod 777 sessions cookies rclone "$DOWNLOAD_PATH_NEW" 2>/dev/null || true
ok "运行时目录已创建"

# ── 构建镜像（透传代理给 docker build）────────────────────
step "构建 Docker 镜像"
if [ -n "$PROXY_URL" ]; then
    ok "构建通过代理：$PROXY_URL"
fi
echo ""
echo -e "  正在拉取基础镜像（redis）..."
docker compose pull redis 2>/dev/null || true
echo ""
echo -e "  正在构建应用镜像（首次约需 3-5 分钟，请耐心等待）..."
echo -e "  ${CYAN}构建日志如下：${NC}"
echo ""

BUILD_ARGS=""
if [ -n "$PROXY_URL" ]; then
    BUILD_ARGS="--build-arg HTTPS_PROXY=${PROXY_URL} --build-arg HTTP_PROXY=${PROXY_URL} --build-arg https_proxy=${PROXY_URL} --build-arg http_proxy=${PROXY_URL}"
fi

# shellcheck disable=SC2086
if docker compose build --no-cache $BUILD_ARGS; then
    ok "镜像构建完成"
else
    err "镜像构建失败，请查看上方错误信息"
fi

# ── 启动 ─────────────────────────────────────────────────
step "启动服务"
docker compose up -d
echo -e "  等待服务启动..."
sleep 5

for svc in bot worker web redis; do
    STATUS=$(docker compose ps "$svc" --format "{{.State}}" 2>/dev/null || echo "unknown")
    if echo "$STATUS" | grep -qi "running"; then
        ok "NDBot_${svc}：运行中"
    else
        warn "NDBot_${svc}：$STATUS"
    fi
done

# ── 完成 ─────────────────────────────────────────────────
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "服务器IP")

echo ""
echo -e "${BOLD}${GREEN}"
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║        🎉  NDBot 安装/更新完成！          ║"
echo "  ╚══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  📁 安装目录 ：${CYAN}${INSTALL_DIR}${NC}"
echo -e "  💾 下载目录 ：${CYAN}${DOWNLOAD_PATH_NEW}${NC}"
echo -e "  🌐 Web UI   ：${CYAN}http://${SERVER_IP}:${WEB_PORT_NEW}${NC}"
echo ""
echo -e "  ${BOLD}常用命令：${NC}"
echo -e "  ${YELLOW}cd ${INSTALL_DIR}${NC}"
echo -e "  ${YELLOW}docker compose logs -f          ${NC}# 查看日志"
echo -e "  ${YELLOW}docker compose logs -f bot      ${NC}# 仅看 Bot 日志"
echo -e "  ${YELLOW}docker compose restart          ${NC}# 重启所有服务"
echo -e "  ${YELLOW}docker compose pull && docker compose up -d --build  ${NC}# 更新"
echo ""
echo -e "  ${BOLD}卸载方法：${NC}"
echo -e "  ${YELLOW}cd ${INSTALL_DIR}${NC}"
echo -e "  ${YELLOW}docker compose down --rmi all --volumes${NC}  # 停止并删除容器和镜像"
echo -e "  ${YELLOW}cd .. && rm -rf ${INSTALL_DIR}${NC}           # 删除项目目录（含配置）"
echo -e "  ${RED}注意：卸载前请备份 ${INSTALL_DIR}/downloads 中的已下载文件！${NC}"
echo ""
echo -e "  ${BOLD}下一步：${NC}"
echo -e "  1. Telegram 向你的机器人发送 ${CYAN}/start${NC}"
echo -e "  2. 打开 Web UI：${CYAN}http://${SERVER_IP}:${WEB_PORT_NEW}${NC}"
echo -e "  3. 如需下载会员内容，上传 cookies 到：${CYAN}${INSTALL_DIR}/cookies/${NC}"
[ "$RCLONE_ENABLE_NEW" = "true" ] && \
    echo -e "  4. 确认云盘配置：${CYAN}${INSTALL_DIR}/rclone/rclone.conf${NC}"
echo ""
