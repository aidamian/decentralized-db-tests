FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY oss-rqlite/client/scenario.py /app/scenario.py

ENTRYPOINT ["python", "/app/scenario.py"]
