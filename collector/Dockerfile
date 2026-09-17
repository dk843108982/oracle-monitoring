# 采集器镜像（Docker Compose 用）
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY oracle_collector.py alert_handler.py skills_engine.py /app/
COPY config.json /app/config.json
CMD ["python", "/app/oracle_collector.py", "--mode", "demo", "--config", "/app/config.json"]
