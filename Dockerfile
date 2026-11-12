FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /app
# Chromium 只用于可选的平台官方扫码登录适配器；不预下载 Playwright 自带浏览器。
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk ffmpeg chromium && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 toker
COPY --chown=toker:toker . .
RUN mkdir -p var/video_out var/uploads var/browser_state && chown -R toker:toker /app
USER toker
EXPOSE 8300
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/api/v1/health',timeout=4)"
CMD ["sh", "scripts/start_platform.sh"]
