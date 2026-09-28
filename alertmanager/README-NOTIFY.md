# Alertmanager 告警通知启用指南（钉钉 / 企业微信 / 静默窗口）

当前 Alertmanager 已将所有告警转发到本地技能诊断服务（`alert-handler`，:8080）。
要真正"喊到人"，按下面步骤接入钉钉或企业微信机器人。

## 1. 创建机器人（以钉钉为例）

1. 在钉钉群 → 群设置 → 智能群助手 → 添加机器人 → 自定义（webhook）
2. 安全设置建议开启 **加签** 或 **自定义关键词**（如 `Oracle告警`），复制 `access_token`
3. 记录完整 webhook：`https://oapi.dingtalk.com/robot/send?access_token=XXXX`

## 2. 填入 Alertmanager 配置

编辑 `alertmanager/alertmanager.yml`，在 `critical-receiver` / `warning-receiver` 段取消注释并填入：

```yaml
# --- 钉钉机器人 ---
webhook_configs:
  - url: "http://127.0.0.1:8080/alert-handler"
    send_resolved: true
  - url: "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
    send_resolved: true
```

> 注意：两个 webhook 并列写在 `webhook_configs` 列表里即可，Alertmanager 会同时发技能诊断 + 钉钉。

企业微信同理：

```yaml
# --- 企业微信机器人 ---
wechat_configs:
  - api_url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
    send_resolved: true
```

## 3. 校验并重启

```powershell
# 配置校验（在容器内）
docker exec oracle-alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
# 重启生效
docker restart oracle-alertmanager
```

## 4. 测试通知

```powershell
# 手动发送一条测试告警到 Alertmanager
curl -X POST -H "Content-Type: application/json" -d "{\"status\":\"firing\",\"labels\":{\"alertname\":\"TestAlert\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"Oracle 监控测试告警\"}}" http://localhost:9093/api/v2/alerts
```

钉钉群应收到告警；随后再发 `"status":"resolved"` 验证恢复通知。

## 5. 维护静默窗口（夜间/维护时段不打扰）

在 `alertmanager.yml` 底部启用 `mute_time_intervals`（取消注释）：

```yaml
mute_time_intervals:
  - name: maintenance-window
    time_intervals:
      - weekdays: "Mon..Fri"          # 可选 Mon..Fri / Mon,Wed / 不写=每天
        times:
          - start_time: "02:00"       # 24 小时制
            end_time: "04:00"
```

然后在 route 中引用（可叠加 continue）：

```yaml
routes:
  - matchers:
      - severity = "critical"
    mute_time_intervals:
      - maintenance-window
    receiver: critical-receiver
    continue: true
```

重启生效。静默只抑制"通知"，告警仍在 Alertmanager/ Prometheus 中记录。

## 常见问题

- **钉钉收不到**：检查机器人安全设置（加签需在 url 后拼 `&timestamp=...&sign=...`，Alertmanager 原生钉钉 webhook 不支持加签——建议用自定义关键词方式）；或改用企业微信（支持 API 直发）。
- **重复告警太多**：调大 `repeat_interval`（默认 4h）即可。
- **恢复通知没收到**：确认接收器 `send_resolved: true`。
