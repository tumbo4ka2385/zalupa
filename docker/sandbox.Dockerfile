# Образ песочницы для агента.
# Сборка:  python main.py build
# Далее в .env:  DOCKER_IMAGE=lmstudio-sandbox:latest

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends bash curl wget git jq build-essential ca-certificates && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install numpy pandas matplotlib requests httpx beautifulsoup4 lxml rich

WORKDIR /workspace
CMD ["sleep", "infinity"]
