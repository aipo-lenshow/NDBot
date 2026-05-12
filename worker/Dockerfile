FROM python:3.11-slim

# ffmpeg：yt-dlp 合并视频/转码用
# rclone：云盘同步
# nodejs 20 LTS：yt-dlp 解密 YouTube n challenge 需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    rclone \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-u", "main.py"]
