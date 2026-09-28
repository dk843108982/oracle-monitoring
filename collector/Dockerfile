# 采集器镜像（Docker Compose 用）
FROM python:3.12-slim
WORKDIR /app
# 先升级 pip
RUN pip install --no-cache-dir --proxy http.docker.internal:3128 --upgrade pip
# 再安装 oracledb
RUN pip install --no-cache-dir --proxy http.docker.internal:3128 oracledb
COPY oracle_collector.py alert_handler.py skills_engine.py /app/
COPY config.json /app/config.json
CMD ["python", "/app/oracle_collector.py", "--mode", "real", "--config", "/app/config.json"]
