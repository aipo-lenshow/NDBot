#!/usr/bin/env python3
"""
NDBot v1.01.0512 TUI 安装向导

Author: AiPo
"""
import os, re, shutil, subprocess, sys, time
from pathlib import Path


def ensure_deps():
    try:
        import questionary, rich  # noqa
        return
    except ImportError:
        pass
    print("正在安装向导依赖（questionary, rich）...")
    # Step 1: ensure pip exists
    pip_ok = subprocess.run([sys.executable,"-m","pip","--version"],
                            capture_output=True).returncode == 0
    if not pip_ok:
        for mgr,cmd in [("apt-get",["apt-get","install","-y","python3-pip"]),
                        ("yum",    ["yum","install","-y","python3-pip"]),
                        ("dnf",    ["dnf","install","-y","python3-pip"])]:
            if shutil.which(mgr):
                subprocess.run(cmd, check=False)
                break
        if not pip_ok:
            subprocess.run([sys.executable,"-m","ensurepip","--upgrade"], capture_output=True)
        pip_ok = subprocess.run([sys.executable,"-m","pip","--version"],
                                capture_output=True).returncode == 0
    if not pip_ok:
        print("❌ 无法安装 pip，请手动执行：\n  Ubuntu/Debian: sudo apt-get install python3-pip")
        print("  或直接使用 Shell 向导：bash install.sh")
        sys.exit(1)
    # Step 2: install packages
    pkgs = ["questionary","rich"]
    for extra in [["--break-system-packages"],["--user"],[]]:
        r = subprocess.run([sys.executable,"-m","pip","install","-q"]+pkgs+extra,
                           capture_output=True)
        if r.returncode == 0: break
    else:
        print("❌ 依赖安装失败，请运行：pip install questionary rich")
        print("  或使用 Shell 向导：bash install.sh")
        sys.exit(1)
    print("✅ 依赖就绪，启动安装向导...\n")
    os.execv(sys.executable, [sys.executable]+sys.argv)


ensure_deps()

import questionary
from questionary import Style
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich import box

console = Console()
STYLE = Style([
    ("qmark","fg:#818cf8 bold"),("question","fg:#dde1f0 bold"),
    ("answer","fg:#4ade80 bold"),("pointer","fg:#818cf8 bold"),
    ("highlighted","fg:#818cf8 bold"),("selected","fg:#4ade80"),
    ("separator","fg:#444466"),("instruction","fg:#888888"),
    ("text","fg:#dde1f0"),("disabled","fg:#666666 italic"),
])


def banner():
    console.clear()
    console.print(Panel(
        "[bold #818cf8]NDBot[/] [bold white]v1.01.0512 安装向导[/]\n"
        "[#888888]统一资源下载机器人 · by AiPo[/]\n"
        "[#555577]YouTube / X.com / Bilibili / Telegram 等[/]",
        border_style="#1e1e40", padding=(1,4)))
    console.print()

def check_env():
    console.print("[bold #818cf8]▶ 检查系统环境[/]\n")
    issues = []
    if shutil.which("docker"):
        r = subprocess.run(["docker","--version"], capture_output=True, text=True)
        console.print(f"  [green]✅[/] {r.stdout.strip()}")
    else:
        issues.append("Docker 未安装")
        console.print("  [red]❌[/] Docker 未安装")
    r = subprocess.run(["docker","compose","version"], capture_output=True, text=True)
    if r.returncode == 0:
        console.print("  [green]✅[/] Docker Compose：已就绪")
    else:
        issues.append("Docker Compose Plugin 未安装")
        console.print("  [red]❌[/] Docker Compose 未安装")
    console.print()
    if issues:
        console.print("[bold red]请先解决以下问题：[/]")
        for i in issues: console.print(f"  • {i}")
        console.print("\n安装命令：[yellow]curl -fsSL https://get.docker.com | sh[/]")
        sys.exit(1)


def load_env(d: Path) -> dict:
    ev = {}
    f = d / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k,_,v = line.partition("="); ev[k.strip()] = v.strip()
    return ev


def copy_project(script_dir: Path, install_dir: Path):
    if (install_dir/"docker-compose.yml").exists(): return True
    if not (script_dir/"docker-compose.yml").exists():
        console.print(f"  [red]❌[/] 找不到项目文件，请将 NDBot 解压到 {install_dir}")
        return False
    for item in script_dir.iterdir():
        if item.name in (".env","sessions","downloads","cookies","rclone"): continue
        dest = install_dir/item.name
        if item.is_dir(): shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
        else: shutil.copy2(str(item), str(dest))
    return True


def install_rclone(proxy_url: str) -> bool:
    """安装 rclone，实时显示进度，自动透传代理"""
    # 代理已在 os.environ 里设置，curl/bash 自动继承
    console.print("  正在下载 rclone 安装脚本...")
    if proxy_url:
        console.print(f"  [cyan]（通过代理：{proxy_url}）[/]")

    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w")
    tmp_path = tmp.name
    tmp.close()

    # 下载安装脚本
    dl = subprocess.run(
        ["curl", "-fsSL", "--progress-bar",
         "https://rclone.org/install.sh", "-o", tmp_path],
        env=os.environ,
    )
    if dl.returncode != 0:
        console.print("  [red]❌[/] 脚本下载失败" +
                      (f"，请检查代理：{proxy_url}" if proxy_url else ""))
        Path(tmp_path).unlink(missing_ok=True)
        return False

    console.print("  正在安装 rclone（实时输出）...")
    console.print()
    # 实时流式输出安装过程
    proc = subprocess.Popen(
        ["bash", tmp_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ,
        text=True,
    )
    for line in proc.stdout:
        console.print(f"  [dim cyan]│[/] {line.rstrip()}")
    proc.wait()
    Path(tmp_path).unlink(missing_ok=True)

    if proc.returncode == 0 and shutil.which("rclone"):
        console.print()
        console.print(f"  [green]✅[/] rclone 安装完成：{subprocess.run(['rclone','--version'],capture_output=True,text=True).stdout.split()[1] if shutil.which('rclone') else ''}")
        return True
    else:
        console.print("  [red]❌[/] rclone 安装失败，请手动安装：curl https://rclone.org/install.sh | sudo bash")
        return False


def print_rclone_guide():
    """启动 rclone config 前打印完整中文操作说明"""
    lines = [
        "[bold #818cf8]rclone 云盘配置 · 中文操作说明[/]",
        "",
        "[bold]【第1步 主菜单】[/] 看到 n/s/q 选项时：",
        "  输入 [bold green]n[/] 新建云盘连接",
        "",
        "[bold]【第2步 输入名称】[/] 看到 [yellow]name>[/] 时：",
        "  输入英文名称，例如：",
        "  OneDrive [yellow]onedrive[/]   Google [yellow]gdrive[/]   AList中转 [yellow]alist[/]",
        "  家用NAS [yellow]mynas[/]",
        "  [dim]注：百度/阿里/夸克无原生支持，通过 AList 转 WebDAV 后名称随意起[/]",
        "  [bold red]⚠ 记住这个名称！后面 .env 的 RCLONE_REMOTE 要填它[/]",
        "",
        "[bold]【第3步 选择类型】[/] 看到 [yellow]Storage>[/] 时，直接输入关键词：",
        "",
        "[bold cyan]  ★ 直接支持的云盘[/]",
        "  [cyan]onedrive[/]       微软 OneDrive",
        "  [cyan]drive[/]          Google Drive",
        "  [cyan]s3[/]             S3兼容（Cloudflare R2 / 腾讯COS / 阿里OSS）",
        "",
        "[bold yellow]  ⚠ 国内云盘（百度/阿里/夸克）无原生 rclone 支持[/]",
        "  需先部署 [cyan]AList[/]（https://alist.nn.ci）作为 WebDAV 中转",
        "  AList 支持：百度网盘 / 阿里云盘 / 夸克 / 迅雷 / 115 等",
        "  配置好 AList 后，rclone 用 [cyan]webdav[/] 类型连接：",
        "  地址示例：[dim]http://服务器IP:5244/dav[/]（AList 默认）",
        "",
        "[bold green]  ★ 家用 NAS[/]",
        "  [green]smb[/]            Samba（群晖/威联通/Windows 最通用）",
        "  [green]sftp[/]           SFTP（群晖 DSM / 威联通 QTS）",
        "  [green]webdav[/]         WebDAV（群晖 DSM 支持）",
        "  [green]ftp[/]            FTP",
        "  [green]s3[/]             S3（MinIO / Cloudflare R2 / 腾讯COS）",
        "",
        "[bold]【第4步 应用密钥】[/] 看到 [yellow]client_id>[/] / [yellow]client_secret>[/]：",
        "  直接按 [bold]回车[/] 使用默认值即可",
        "",
        "[bold]【第5步 高级设置】[/] 看到 [yellow]Edit advanced config[/]：",
        "  输入 [bold red]n[/] 跳过",
        "",
        "[bold]【第6步 OAuth授权】[/] 看到 [yellow]Use web browser[/]：",
        "  服务器有图形界面 → 输入 [bold green]y[/]（浏览器自动打开）",
        "  纯命令行服务器   → 输入 [bold yellow]n[/]，复制链接到本地浏览器授权，将授权码粘贴回来",
        "",
        "[bold]【第7步 确认保存】[/] 看到 [yellow]Yes this is OK[/]：",
        "  输入 [bold green]y[/] 保存",
        "",
        "[bold]【完成】[/] 看到云盘列表后：",
        "  输入 [bold]q[/] 退出，记住 Name 列的名称，填入 .env 的 RCLONE_REMOTE",
    ]
    content = "\n".join(lines)
    console.print()
    console.print(Panel(content, border_style="#818cf8", padding=(1, 2)))
    console.print()
    console.print("  [bold]即将启动 rclone config，请对照上方说明操作...[/]")
    console.print()


def run_rclone_config(install_dir: Path):
    """引导用户配置 rclone，代理从 os.environ 自动继承"""
    choice = questionary.select(
        "是否现在运行 rclone config 配置云盘？",
        choices=[
            questionary.Choice("1. 现在配置（有中文说明）", value="now"),
            questionary.Choice("2. 稍后手动配置", value="later"),
        ],
        style=STYLE,
    ).ask()

    if choice == "now":
        # 先打印中文说明，再运行 rclone config（两者完全隔离，不互相干扰）
        print_rclone_guide()
        # 代理已在 os.environ，rclone 自动继承
        subprocess.run(["rclone", "config"], env=os.environ)
        cfg = Path.home() / ".config/rclone/rclone.conf"
        if cfg.exists():
            (install_dir / "rclone").mkdir(exist_ok=True)
            shutil.copy2(str(cfg), str(install_dir / "rclone/rclone.conf"))
            console.print()
            console.print("  [green]✅[/] rclone.conf 已复制到项目目录")
        else:
            console.print("  [yellow]⚠️[/]  未找到配置文件，请稍后手动复制")
    else:
        console.print(Panel(
            "[bold]稍后手动配置步骤：[/]\n\n"
            "1. 运行：[yellow]rclone config[/]\n"
            f"2. 复制：[yellow]cp ~/.config/rclone/rclone.conf {install_dir}/rclone/rclone.conf[/]\n"
            "3. 修改 .env：RCLONE_REMOTE=你的远端名称\n"
            f"4. 重启：[yellow]cd {install_dir} && docker compose up -d[/]",
            border_style="#444466", padding=(0, 2)))


def main():
    banner()
    check_env()

    # ── 安装目录 ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第一步：安装位置[/]\n")
    default_dir = str(Path.home()/"NDBot")
    install_dir_str = questionary.text("安装目录", default=default_dir, style=STYLE).ask()
    if install_dir_str is None: sys.exit(0)
    install_dir = Path(install_dir_str.strip())
    install_dir.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).parent
    if not copy_project(script_dir, install_dir): sys.exit(1)
    existing = load_env(install_dir)
    update_mode = bool(existing)
    if update_mode:
        console.print("  [yellow]⚠️  检测到已有配置，进入更新模式[/]")
    console.print()

    # ── 代理（最先收集）─────────────────────────────────
    console.print("[bold #818cf8]▶ 第二步：代理配置（重要）[/]\n")
    console.print(Panel(
        "[bold]如果服务器在中国大陆，必须配置代理才能：[/]\n"
        "  • 拉取 Docker 镜像（python / redis 等）\n"
        "  • 连接 Telegram 服务器\n"
        "  • 下载 YouTube / X.com 等平台内容\n\n"
        "[dim]不使用代理直接按回车跳过[/]",
        border_style="#444466", padding=(0,2)))
    console.print()

    existing_proxy = ""
    if existing.get("PROXY_HOST"):
        existing_proxy = f"{existing['PROXY_HOST']}:{existing.get('PROXY_PORT','7890')}"

    proxy_str = questionary.text(
        "代理地址（格式 IP:端口，如 <你的代理IP>:7890，留空不使用）",
        default=existing_proxy,
        validate=lambda v: True if not v or re.match(r"^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$",v)
                          else "格式错误，应为 IP:端口",
        style=STYLE,
    ).ask()
    if proxy_str is None: sys.exit(0)

    proxy_host,proxy_port,proxy_url = "","7890",""
    if proxy_str:
        proxy_host = proxy_str.rsplit(":",1)[0]
        proxy_port = proxy_str.rsplit(":",1)[1]
        proxy_url  = f"http://{proxy_host}:{proxy_port}"
        for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"):
            os.environ[k] = proxy_url
        console.print(f"  [green]✅[/] 代理已设置：{proxy_url}")
    else:
        console.print("  [yellow]⚠️  未设置代理[/]")
    console.print()

    # ── Telegram ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第三步：Telegram Bot 配置[/]\n")
    console.print(
        "  [cyan]Bot Token[/]  → @BotFather 发 /newbot\n"
        "  [cyan]API ID[/]     → https://my.telegram.org/apps\n"
        "  [cyan]API Hash[/]   → 同上（32位）\n"
        "  [cyan]User ID[/]    → @userinfobot\n"
    )
    bot_token = questionary.text("Bot Token", default=existing.get("BOT_TOKEN",""),
        validate=lambda v: True if re.match(r"^\d+:[A-Za-z0-9_-]{30,}$",v)
                          else "格式错误（如 1234567890:ABCdef...）",
        style=STYLE).ask()
    if bot_token is None: sys.exit(0)

    tg_api_id = questionary.text("TG_API_ID", default=existing.get("TG_API_ID",""),
        validate=lambda v: True if v.isdigit() and len(v)>=5 else "应为5位以上纯数字",
        style=STYLE).ask()
    if tg_api_id is None: sys.exit(0)

    tg_api_hash = questionary.text("TG_API_HASH（32位）", default=existing.get("TG_API_HASH",""),
        validate=lambda v: True if len(v)==32 else f"应为32位（当前{len(v)}位）",
        style=STYLE).ask()
    if tg_api_hash is None: sys.exit(0)

    allowed_users = questionary.text(
        "允许的 User ID（逗号分隔，留空=所有人）",
        default=existing.get("ALLOWED_USERS",""),
        validate=lambda v: True if not v or all(p.strip().isdigit() for p in v.split(",") if p.strip())
                          else "应为数字，多个用逗号分隔",
        style=STYLE).ask()
    if allowed_users is None: sys.exit(0)
    console.print()

    # ── 下载路径 ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第四步：下载保存位置[/]\n")
    download_path = questionary.text("文件保存路径",
        default=existing.get("DOWNLOAD_PATH", str(install_dir/"downloads")),
        validate=lambda v: True if v.strip() else "路径不能为空",
        style=STYLE).ask()
    if download_path is None: sys.exit(0)
    console.print()

    # ── 下载参数 ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第五步：下载参数[/]\n")
    max_conc = questionary.text("最大并发下载数",
        default=existing.get("MAX_CONCURRENT_DOWNLOADS","3"),
        validate=lambda v: True if v.isdigit() and 1<=int(v)<=20 else "请输入 1-20 的整数",
        style=STYLE).ask() or "3"
    max_size = questionary.text("单文件最大体积（MB，超过则跳过）",
        default=existing.get("MAX_FILE_SIZE_MB","2000"),
        validate=lambda v: True if v.isdigit() else "请输入整数",
        style=STYLE).ask() or "2000"
    console.print()

    # ── Web UI ───────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第六步：Web UI 配置[/]\n")
    web_port = questionary.text("Web UI 端口",
        default=existing.get("WEB_PORT","5000"),
        validate=lambda v: True if v.isdigit() and 1<=int(v)<=65535 else "请输入有效端口",
        style=STYLE).ask() or "5000"
    web_secret = questionary.password("Web UI 访问密码（留空无需密码）", style=STYLE).ask() or ""
    console.print()

    # ── Cookies 引导 ─────────────────────────────────────
    console.print("[bold #818cf8]▶ 第七步：Cookies 配置说明[/]\n")
    console.print(Panel(
        "[bold]以下情况需要配置 Cookies：[/]\n"
        "  • YouTube 会员专属视频\n"
        "  • X.com 登录后才能看的内容\n"
        "  • B 站大会员视频\n\n"
        "[bold]获取方法：[/]\n"
        "  1. 浏览器安装扩展 [cyan]Get cookies.txt LOCALLY[/]\n"
        "     [dim]chromewebstore.google.com/detail/cclelndahbckbenkjhflpdbgdldlbecc[/]\n"
        "  2. 登录对应网站后导出 Cookie 为 .txt 文件\n"
        "  3. 上传到服务器：\n"
        f"     [cyan]{install_dir}/cookies/[/]\n"
        "     [yellow]youtube.txt[/]  / [yellow]xcom.txt[/]  / [yellow]bilibili.txt[/]  / [yellow]cookies.txt[/]\n\n"
        "[dim]安装完成后随时可以添加，无需重启[/]",
        border_style="#444466", padding=(0,2)))
    questionary.press_any_key_to_continue("  按任意键继续...").ask()
    console.print()

    # ── 云盘同步 ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 第八步：云盘同步（可选）[/]\n")
    enable_rclone = questionary.select(
        "是否启用 rclone 云盘同步？",
        choices=[
            questionary.Choice("1. 启用", value=True),
            questionary.Choice("2. 不启用（默认）", value=False),
        ],
        style=STYLE,
    ).ask()
    if enable_rclone is None: sys.exit(0)

    rclone_remote = existing.get("RCLONE_REMOTE","")
    rclone_dest   = existing.get("RCLONE_DEST","NDBot")
    rclone_delete = existing.get("RCLONE_DELETE_AFTER","false")=="true"
    rclone_mode   = existing.get("RCLONE_MODE","auto")

    if enable_rclone:
        # 检查 / 安装 rclone（代理从 os.environ 自动继承）
        if not shutil.which("rclone"):
            console.print("  [yellow]⚠️  未检测到 rclone，正在安装...[/]")
            install_rclone(proxy_url)

        if shutil.which("rclone"):
            run_rclone_config(install_dir)

        rclone_remote = questionary.text("rclone 远端名称（与 rclone.conf 里 [xxx] 一致）",
            default=rclone_remote, style=STYLE).ask() or rclone_remote

        rclone_dest = questionary.text("云盘目标目录", default=rclone_dest, style=STYLE).ask() or rclone_dest

        rclone_delete = questionary.select("上传后是否删除本地文件？",
            choices=[questionary.Choice("1. 删除（节省磁盘）",True),
                     questionary.Choice("2. 保留（默认）",False)],
            style=STYLE).ask()

        rclone_mode_sel = questionary.select("触发方式",
            choices=[questionary.Choice("1. 下载完成后自动上传","auto"),
                     questionary.Choice("2. 手动发送 /sync 命令触发","manual")],
            style=STYLE).ask() or "auto"
        rclone_mode = rclone_mode_sel
    console.print()

    # ── 确认配置 ─────────────────────────────────────────
    console.print("[bold #818cf8]▶ 配置确认[/]\n")
    t = Table(box=box.ROUNDED, border_style="#1e1e40", show_header=False)
    t.add_column("项目", style="#888888", width=18)
    t.add_column("值", style="#dde1f0")
    t.add_row("安装目录",    str(install_dir))
    t.add_row("Bot Token",   f"{bot_token[:20]}...")
    t.add_row("API ID",      tg_api_id)
    t.add_row("允许用户",    allowed_users or "（所有人）")
    t.add_row("代理",        proxy_str or "（不使用）")
    t.add_row("下载目录",    download_path)
    t.add_row("并发数",      max_conc)
    t.add_row("最大文件",    f"{max_size} MB")
    t.add_row("Web 端口",    web_port + ("（有密码）" if web_secret else ""))
    t.add_row("云盘同步",    f"{'启用 → '+rclone_remote if enable_rclone else '禁用'}")
    console.print(t)
    console.print()

    if not questionary.confirm("确认以上配置，开始安装？", default=True, style=STYLE).ask():
        console.print("[yellow]安装已取消[/]"); sys.exit(0)

    # ── 写入 .env ─────────────────────────────────────────
    console.print()
    env_txt = (
        f"# NDBot 配置 - 生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# 修改后执行：docker compose up -d 即可生效\n\n"
        f"BOT_TOKEN={bot_token}\nTG_API_ID={tg_api_id}\nTG_API_HASH={tg_api_hash}\n"
        f"ALLOWED_USERS={allowed_users}\nPROXY_HOST={proxy_host}\nPROXY_PORT={proxy_port}\n"
        f"DOWNLOAD_PATH={download_path}\nMAX_CONCURRENT_DOWNLOADS={max_conc}\n"
        f"MAX_FILE_SIZE_MB={max_size}\nWEB_PORT={web_port}\nWEB_SECRET={web_secret}\n"
        f"RCLONE_ENABLE={'true' if enable_rclone else 'false'}\nRCLONE_REMOTE={rclone_remote}\n"
        f"RCLONE_DEST={rclone_dest}\n"
        f"RCLONE_DELETE_AFTER={'true' if rclone_delete else 'false'}\nRCLONE_MODE={rclone_mode}\n"
    )
    (install_dir/".env").write_text(env_txt)
    console.print("  [green]✅[/] 配置文件已写入")
    for d in [download_path, str(install_dir/"sessions"),
              str(install_dir/"cookies"), str(install_dir/"rclone")]:
        Path(d).mkdir(parents=True, exist_ok=True)
    console.print("  [green]✅[/] 运行时目录已创建")

    # ── 构建镜像 ─────────────────────────────────────────
    console.print()
    build_args = []
    if proxy_url:
        for k in ("HTTPS_PROXY","HTTP_PROXY","https_proxy","http_proxy"):
            build_args += ["--build-arg", f"{k}={proxy_url}"]
        console.print(f"  [green]✅[/] 构建将通过代理：{proxy_url}")

    with Progress(SpinnerColumn(style="bold #818cf8"),
                  TextColumn("[bold]{task.description}"),
                  TimeElapsedColumn(),
                  console=console) as prog:
        task = prog.add_task("构建 Docker 镜像（首次约需 3-10 分钟，根据个人网络情况）...", total=None)
        result = subprocess.run(
            ["docker","compose","build","--no-cache"]+build_args,
            cwd=str(install_dir), capture_output=True, text=True, env=os.environ)
        if result.returncode != 0:
            prog.stop()
            console.print(f"[red]❌ 构建失败：[/]\n{result.stderr[-2000:]}")
            sys.exit(1)
        prog.update(task, description="启动服务...")
        subprocess.run(["docker","compose","up","-d"], cwd=str(install_dir),
                       capture_output=True, env=os.environ)
        time.sleep(5)
        prog.update(task, description="✅ 完成")

    # ── 状态检查 ─────────────────────────────────────────
    console.print()
    for svc in ["bot","worker","web","redis"]:
        r = subprocess.run(["docker","compose","ps",svc,"--format","{{.State}}"],
                           cwd=str(install_dir), capture_output=True, text=True)
        st = r.stdout.strip().lower()
        icon = "[green]✅[/]" if "running" in st else "[yellow]⚠️[/] "
        console.print(f"  {icon} NDBot_{svc}：{st or '检查中...'}")

    # ── 完成 ─────────────────────────────────────────────
    ip = ""
    try:
        ip = subprocess.run(["hostname","-I"], capture_output=True, text=True).stdout.split()[0]
    except Exception:
        ip = "服务器IP"

    console.print()
    console.print(Panel(
        f"[bold green]🎉 NDBot 安装完成！[/]\n\n"
        f"  📁 安装目录：[cyan]{install_dir}[/]\n"
        f"  💾 下载目录：[cyan]{download_path}[/]\n"
        f"  🌐 Web UI  ：[cyan]http://{ip}:{web_port}[/]\n\n"
        f"  [bold]常用命令：[/]\n"
        f"  [yellow]cd {install_dir}[/]\n"
        f"  [yellow]docker compose logs -f bot[/]    # Bot 日志\n"
        f"  [yellow]docker compose restart[/]         # 重启\n\n"
        f"  [bold]卸载方法：[/]\n"
        f"  [yellow]cd {install_dir}[/]\n"
        f"  [yellow]docker compose down --rmi all --volumes[/]  # 删除容器和镜像\n"
        f"  [yellow]cd .. && rm -rf {install_dir}[/]            # 删除项目目录\n"
        f"  [red]注意：卸载前请备份 {install_dir}/downloads 中的已下载文件！[/]\n\n"
        f"  [bold]下一步：[/]\n"
        f"  1. Telegram 发 [bold]/start[/] 给机器人\n"
        f"  2. 打开 Web UI：[cyan]http://{ip}:{web_port}[/]\n"
        f"  3. 如需下载会员内容，上传 cookies 到：\n"
        f"     [cyan]{install_dir}/cookies/[/]\n"
        + (f"  4. 确认云盘配置：[cyan]{install_dir}/rclone/rclone.conf[/]\n"
           if enable_rclone else ""),
        border_style="green", padding=(1,2)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]安装已中断[/]")
        sys.exit(0)
