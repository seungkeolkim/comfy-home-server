FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY home_server ./home_server
COPY web ./web
COPY data/workflows ./data/workflows

CMD ["python", "-m", "home_server", "--reload"]
