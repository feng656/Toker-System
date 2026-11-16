FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /app
# Chromium 只用于可选的平台官方扫码登录适配器；不预下载 Playwright 自带浏览器。
# 构建机在国内访问 deb.debian.org 很慢，先切到阿里云镜像；海外构建可覆盖该 ARG。
ARG APT_MIRROR=mirrors.aliyun.com
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk ffmpeg chromium && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# 构建机在国内访问 pypi.org 也慢；阿里云 PyPI 镜像可用时优先，海外构建可覆盖该 ARG。
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir -i "${PIP_INDEX_URL}" -r requirements.txt
RUN useradd --create-home --uid 10001 toker
COPY --chown=toker:toker . .
RUN mkdir -p var/video_out var/uploads var/browser_state && chown -R toker:toker /app
USER toker
EXPOSE 8300
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/api/v1/health',timeout=4)"
CMD ["sh", "scripts/start_platform.sh"]
