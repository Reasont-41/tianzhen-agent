FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/tianzhen

COPY app/requirements.txt /srv/tianzhen/app/requirements.txt

# 先安装与既有实验一致的 CPU 版 Torch 配对，再安装其余依赖。
RUN python -m pip install \
      torch==2.12.0+cpu torchvision==0.27.0+cpu \
      --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install -r app/requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

COPY app /srv/tianzhen/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
