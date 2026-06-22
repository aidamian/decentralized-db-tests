FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY custom /app/custom

ENTRYPOINT ["python", "-m", "custom.client.scenario"]
