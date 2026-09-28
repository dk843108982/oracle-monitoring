# 安全加固说明

以下为本监控栈当前的安全状态与建议加固项，按风险从高到低排列。

## 当前状态

| 组件 | 当前配置 | 风险 |
|---|---|---|
| Grafana (3000) | admin / admin（compose 环境变量） | 中——局域网内任何人均可登录改面板 |
| Collector /metrics (9161) | 已改 **127.0.0.1 绑定**（仅本机访问） | 低——局域网不可直读指标 |
| Prometheus (9090) | 无认证，本机绑定 | 中低——本机测试环境 |
| Alertmanager (9093) | 无认证 | 低——仅接收 Prometheus 告警 |
| RAC 节点 node_exporter (9100) | 容器内 0.0.0.0:9100，仅 rac_pub1_nw 内可达 | 低——Docker 内部网络 |
| 数据库账号 | db_monitor / ChangeMe_2026 | 中——应改为强密码 |

## 建议加固（生产环境必做）

### 1. Grafana 管理员密码
```yaml
# docker-compose.yml
grafana:
  environment:
    - GF_SECURITY_ADMIN_USER=admin
    - GF_SECURITY_ADMIN_PASSWORD=<强密码>        # 替换默认 admin
    - GF_SECURITY_DISABLE_GRAVATAR=true
    # 可选：开启匿名只读
    # - GF_AUTH_ANONYMOUS_ENABLED=true
    # - GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer
```
改后 `docker compose up -d grafana`。

### 2. Collector /metrics 加 Basic Auth（可选）
在 Prometheus 采集端加认证：
```yaml
# prometheus.yml 对应 job 加 basic_auth
scrape_configs:
  - job_name: "oracle"
    basic_auth:
      username: monitor
      password: <password>
    static_configs:
      - targets: ["collector:9161"]
```
配合 collector 端反向代理（如 nginx）校验认证。

### 3. 数据库监控账号强密码
- 修改 `collector/config.json` 中三个实例的密码
- 同步执行 SQL 修改数据库账号密码：
  ```sql
  ALTER USER db_monitor IDENTIFIED BY "<新密码>";
  ALTER USER C##DB_MONITOR IDENTIFIED BY "<新密码>";
  ```

### 4. 仅内网访问
- 若 Grafana/Prometheus 仅需内网访问，端口绑定 `127.0.0.1`（本机）或内网 IP：
  ```yaml
  ports:
    - "127.0.0.1:3000:3000"
  ```
- 开启防火墙，限制 3000/9090/9093 只对运维网段开放

### 5. TLS（可选）
- Grafana 官方支持 HTTPS（GF_SERVER_PROTOCOL=https + 证书）
- Prometheus `--web.config.file` 支持 TLS 与认证

## 风险提示
- **本仓库默认配置面向本地开发/演示**，切勿直接用于生产暴露公网
- RAC 节点 node_exporter 无认证，但其仅存在于 Docker 内部网络（rac_pub1_nw），公网不可达
