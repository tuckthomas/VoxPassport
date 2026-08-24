FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY services/account-api/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY services/account-api/ ./

EXPOSE 8780
CMD ["sh", "-c", "alembic upgrade head && uvicorn account_api.main:app --host 0.0.0.0 --port 8780"]
