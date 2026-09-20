# Oracle 企业级监控系统（基于 oracle/skills 技能库）

一套完整、可运行的企业级 Oracle 数据库监控栈，**深度集成 Oracle 官方 AI 技能库**

[oracle/skills](https://github.com/oracle/skills)—— 监控 SQL、阈值、诊断流程全部

来自 Oracle 官方 DBA 技能文档，而非临时拼凑。

> 📦 想发布到 GitHub？请看 [PUBLISH.md](PUBLISH.md)（含仓库内容规划、发布步骤、Release 附件流程）。

## 架构



```
┌──────────────┐    ┌──────────────────┐    ┌───────────────────┐

│ Oracle 数据库 │───▶│ oracle\\\\\\\_collector │───▶│    Prometheus     │

│ (oracledb)   │    │ (:9161 /metrics) │    │      (:9090)      │

└──────────────┘    └──────────────────┘    └───┬───────┬───────┘

\\\&#x20;                                               │       │

\\\&#x20;                             ┌─────────────────┘       └──────────────┐

\\\&#x20;                             ▼                                       ▼

\\\&#x20;                      ┌──────────────┐                      ┌─────────────────┐

\\\&#x20;                      │   Grafana    │                      │  Alertmanager   │

\\\&#x20;                      │   (:3000)    │                      │    (:9093)      │

\\\&#x20;                      └──────────────┘                      └───────┬─────────┘

\\\&#x20;                                                                    │ webhook

\\\&#x20;                                                                    ▼

\\\&#x20;                                               ┌─────────────────────────────┐

\\\&#x20;                                               │ alert\\\\\\\_handler (:8080)       │

\\\&#x20;                                               │  + oracle/skills 技能引擎    │

\\\&#x20;                                               │  → 自动生成 DBA 诊断手册      │

\\\&#x20;                                               └─────────────────────────────┘
```



| 组件                | 版本                   | 端口   | 说明                    |
| ----------------- | -------------------- | ---- | --------------------- |
| oracle\_collector | Python + oracledb 26 | 9161 | 指标采集器（demo /real 双模式） |
| Prometheus        | 3.13.3               | 9090 | 时序存储 + 告警规则评估         |
| Alertmanager      | 0.34.0               | 9093 | 告警路由 / 抑制 / 通知        |
| Grafana           | 12.4.2 (Enterprise)  | 3000 | 可视化大盘（admin/admin）    |
| alert\_handler    | Python               | 8080 | Alertmanager → 技能诊断桥接 |
| oracle-skills     | git 最新               | -    | Oracle 官方技能库（本地克隆）    |

## 快速开始

### 一键启动（Windows）



```
.\start-all.ps1      # 启动全部组件（demo 模式，无需真实 Oracle）

.\stop-all.ps1       # 停止全部组件
```

启动后访问：



* Grafana 大盘：[http://localhost:3000](http://localhost:3000) （admin /admin）→ 打开 "Oracle Enterprise Monitor"

* Prometheus：[http://localhost:9090](http://localhost:9090)

* 采集指标：[http://localhost:9161/metrics](http://localhost:9161/metrics)

* Alertmanager：[http://localhost:9093](http://localhost:9093)

### demo 模式说明

当前默认 `demo` 模式：无需真实 Oracle 数据库即可完整演示采集 → 存储 → 可视化 → 告警 →

技能诊断全链路。模拟指标贴近真实分布（表空间使用率、等待事件、Top SQL、ORA 错误、

会话数等），且表空间使用率会随时间缓慢增长，可观察告警从 WATCH → WARNING 的触发过程。

## 切换到真实 Oracle 数据库（real 模式）

**三步接入，推荐先用连接自检工具验证**：



```
1\\. 目标库执行 grants.sql（建最小权限账号）

2\\. 修改 collector\config.json（mode=real + 连接参数）

3\\. 运行 connect-check.py 自检 → 全 PASS 后重启采集器
```



```
py -3.12 .\collector\connect-check.py
```

自检脚本会依次输出：**连接耗时 / 库版本实例 / 12 项视图权限探测 / 指标样例（表空间 TOP5、等待事件 TOP5、会话）**，并给出缺失权限的修复提示（缺什么补什么，无需全量授权）。



1. **初始化监控账号**（在 Oracle 库以 SYSDBA 执行，最小权限）：



```
@collector\grants.sql
```

已包含：表空间、会话、等待事件、Top SQL、Alert 日志、归档、AWR 等全部只读视图授权。



1. **修改采集配置** `collector\config.json`：



```
{

\\\&#x20; "mode": "real",

\\\&#x20; "oracle": {

\\\&#x20;   "host": "192.168.1.100",

\\\&#x20;   "port": 1521,

\\\&#x20;   "service\\\\\\\_name": "ORCLPDB1",

\\\&#x20;   "user": "db\\\\\\\_monitor",

\\\&#x20;   "password": "Monitor@2026"

\\\&#x20; }

}
```



1. **重启采集器**（或直接运行）：



```
py -3.12 .\collector\oracle\\\\\\\_collector.py --mode real --config .\collector\config.json
```

> 真实模式执行的 SQL 全部取自 oracle/skills 技能库：
> `db/monitoring/space-management.md`
> —— 表空间主查询（DBA_TABLESPACE_USAGE_METRICS）
> `db/monitoring/alert-log-analysis.md`
> —— Alert 日志（V
>
> $DIAG_ALERT_EXT） `db/monitoring/top-sql-queries.md`
> —— Top SQL（V$
>
> SQLAREA）
> `db/performance/wait-events.md`
> —— 等待事件（V$SYSTEM_EVENT）

## oracle/skills 技能集成（核心亮点）

技能库已克隆至 `..\oracle-skills\`，由 `collector\skills_engine.py` 消费：



```
\\\\# 列出全部可用技能及对应告警

py -3.12 .\collector\skills\\\\\\\_engine.py --list

\\\\# 生成某类告警的诊断手册（含官方 SQL、最佳实践、常见坑）

py -3.12 .\collector\skills\\\\\\\_engine.py --alert tablespace --context "{\\\\\\\\"tablespace\\\\\\\\":\\\\\\\\"USERS\\\\\\\\",\\\\\\\\"used\\\\\\\_pct\\\\\\\\":92}"

\\\\# JSON 输出（供程序化调用）

py -3.12 .\collector\skills\\\\\\\_engine.py --alert wait\\\\\\\_events --json
```

**告警自动诊断链路**：Prometheus 告警 → Alertmanager → webhook → `alert_handler.py`

→ 按告警名路由到对应技能 → 生成 DBA 诊断手册落盘 `collector\reports\`。

告警 → 技能映射：



| Prometheus 告警                          | 技能文件                                  | 诊断内容                             |
| -------------------------------------- | ------------------------------------- | -------------------------------- |
| OracleTablespaceCritical/Warning/Watch | `db/monitoring/space-management.md`   | 使用率分级（95/85/75）、自动扩展、HWM、碎片、扩容建议 |
| OracleAlertLogCriticalError            | `db/monitoring/alert-log-analysis.md` | ORA 错误分级、trace 关联、ADR 分析         |
| OracleInstanceDown                     | `db/monitoring/alert-log-analysis.md` | 实例崩溃根因、监听、alert.log              |
| OracleSlowSQL                          | `db/monitoring/top-sql-queries.md`    | Top SQL 定位、执行计划、AWR 对比           |
| OracleTopWaitEvent                     | `db/performance/wait-events.md`       | 等待事件分类、瓶颈定位                      |
| OracleBufferCacheHitRatioLow           | `db/performance/memory-tuning.md`     | SGA/PGA、命中率调优                    |

## 告警规则（阈值来自技能库最佳实践）



* 表空间：`>=95% CRITICAL`（立即处理）、`>=85% WARNING`（当日处理）、`>=75% WATCH`（巡检关注）

* Alert 日志：任何 ORA 错误 → CRITICAL（ORA-00600/07445/01578 需立即处理）

* 等待事件：Top 事件累计 > 1h → WARNING

* 慢 SQL：Top SQL 累计耗时 > 30min → WARNING

* Buffer Cache 命中率 < 95% → WARNING

* 归档：归档进程失败 → CRITICAL；24h 归档 > 500 → WARNING

完整规则见 `prometheus\rules\oracle_alerts.yml`。

## WatchAlert 集成（多渠道告警通知）

本项目已集成 [WatchAlert](https://github.com/opsre/WatchAlert)（开源多数据源告警引擎），用于替代/补充 Alertmanager 的通知能力：

- **多渠道通知**：微信 / 钉钉 / 飞书 / 企微 / 邮件 / Webhook
- **告警聚合**：自动收敛同类告警，避免告警风暴
- **告警静默**：维护窗口期间屏蔽指定告警
- **值班管理**：支持值班表与升级策略
- **前端可视化**：告警列表 / 历史记录 / 规则管理

### 部署方式（Docker Compose）

```bash
cd oracle-monitoring
docker compose up -d watchalert-mysql watchalert-redis watchalert watchalert-web
```

启动后访问：
- **WatchAlert Web**：http://localhost:9004 （首次用初始化密码登录）
- **WatchAlert API**：http://localhost:9002

### 配置 Prometheus 双发告警

编辑 prometheus/prometheus.yml，取消注释 WatchAlert 的 alertmanager 配置：

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]     # 现有 Alertmanager（本地诊断）
    - static_configs:
        - targets: ["watchalert:9001"]       # WatchAlert（多渠道通知）
```

### WatchAlert 里配置通知渠道

1. 登录 WatchAlert Web → **通知对象** → 添加微信/钉钉/飞书机器人 Webhook
2. **规则** → 创建接收组，关联 Prometheus 数据源
3. **告警策略** → 配置聚合/静默/升级规则

> 文档：https://cairry.github.io/docs/

## 组件清单



| 组件                | 端口       | 说明                                                  |
| ----------------- | -------- | --------------------------------------------------- |
| Grafana           | 3000     | Oracle Enterprise Monitor 大盘（18 面板），admin/admin     |
| **Skill Console** | **8090** | **oracle/skills 技能选择前端（路由地图 / 角色路由 / 任务诊断 / 告警联动）** |
| Prometheus        | 9090     | 指标与 11 条告警规则                                        |
| Collector         | 9161     | Oracle 双模采集器（demo /real），`/metrics`                 |
| Alertmanager      | 9093     | 告警分发（webhook → 8080）                                |
| AlertHandler      | 8080     | 告警 → 技能诊断桥接（生成诊断手册落盘 reports/）                      |

## Skill Console —— 技能选择前端

基于 Oracle 博客《Route, Don't Flood》（db/SKILL.md 即路由地图）实现：



* **技能地图**：解析 db/SKILL.md 的 19 个分类路由表 + 170 个技能文件，点击查看官方 SQL / 最佳实践 / 常见坑（SQL 一键复制）

* **按角色路由**：DBA / 应用开发 / AI 工程师 / 迁移负责人，各推荐官方技能路径

* **按任务诊断**：慢查询、表空间、RAG、Agent 变更、SQLcl MCP 等任务序列；选择告警类型一键运行诊断（复用 skills\_engine），手册实时展示并落盘

* **告警联动**：Prometheus 告警 ↔ 技能文件映射表，顶部实时显示采集器与告警状态

访问：[http://localhost:8090](http://localhost:8090)

## 指标维度（41 个系列，对应技能库）

| 维度 | 指标 | 技能来源 |
|---|---|---|
| 实例 / HA | up、instance_info、uptime、redo 切换、DB Time、硬解析率 | db/admin、performance/optimizer-stats |
| 空间 | 表空间 used%/total/used/free/max/autoextend/free_days、TEMP%、UNDO% | db/monitoring/space-management.md |
| 内存 | Buffer Cache 命中、Library Cache、SGA（按池）、共享池空闲、PGA | db/performance/memory-tuning.md |
| 会话 / SQL | sessions（按状态）、阻塞、长事务、Top SQL（elapsed/cpu/executions） | db/monitoring/top-sql-queries.md、db/admin |
| 等待事件 | 累计秒 / 等待次数 / 平均 ms（按事件） | db/performance/wait-events.md |
| Alert / ADR | ORA 错误计数、开放 Incident | db/monitoring/alert-log-analysis.md、adrci-usage.md |
| 归档 / 备份 | archiver、24h 归档量、归档滞后、备份年龄、损坏块 | db/backup-recovery/ |
| 健康检查 | health check issues | db/monitoring/health-monitor.md |

告警规则 22 条、Grafana 面板 38 个（6 个分组）。

## 打包与移植到其他平台

### 生成可移植包（Windows）



```
.\package.ps1
```

生成 `oracle-monitoring-portable.zip`（约 450MB，含全部二进制与技能库，自包含）。

**已验证**：解压到全新路径后 `start-all.ps1` 一键启动，Grafana 大盘 / Prometheus 抓取 / 技能诊断链路全部正常（无任何本机路径依赖）。

### 目标机器部署（三选一）



| 目标平台            | 步骤                                                                                                                                | 依赖                 |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| **Windows 服务器** | 解压 zip → 装 Python 3.10+ 并 `.\collector\install-driver.ps1` → 运行 `start-all.ps1`                                                   | Python 3.10+       |
| **Linux 服务器**   | `linux/download-linux.sh` 下载 Linux 二进制 → `chmod +x linux/*.sh` → `./linux/start.sh`；开机自启用 `linux/oracle-monitor.service`（systemd） | python3 + oracledb |
| **Docker 环境**   | `docker compose up -d`（镜像自动拉取，采集器镜像内置 oracledb）                                                                                   | Docker + Compose   |

> 说明：
> Windows 包内已含 Windows 二进制，Linux/Docker 方式无需携带大体积包
> 接入真实 Oracle 库：三平台统一修改
> `collector/config.json`
> （mode=real + 连接信息），先执行
> `collector/grants.sql`
> 授权
> 换机器后首次启动若端口被占，修改各组件
> `--web.listen-address`
> 即可

## 目录结构



```
oracle-monitoring/

├── start-all.ps1 / stop-all.ps1    一键启停

├── README.md                       本文件

├── prometheus/

│   ├── prometheus.yml              主配置

│   └── rules/oracle\\\\\\\_alerts.yml     告警规则（11 条）

├── alertmanager/alertmanager.yml   告警路由（webhook → 技能诊断）

├── grafana/

│   ├── provisioning/               数据源 + 面板自动加载

│   └── dashboards/oracle\\\\\\\_enterprise.json   企业大盘（18 面板）

├── collector/

│   ├── oracle\\\\\\\_collector.py         指标采集器（demo/real）

│   ├── skills\\\\\\\_engine.py            oracle/skills 技能消费引擎

│   ├── alert\\\\\\\_handler.py            告警→技能 桥接服务

│   ├── grants.sql                  监控账号最小权限授权

│   ├── config.json                 采集配置

│   ├── requirements.txt / install-driver.ps1

│   └── reports/                    自动生成的诊断手册

└── bin/extracted/                  Prometheus / Alertmanager / Grafana 二进制
```

## 常见问题



* **oracledb 未安装**：`.\collector\install-driver.ps1`（PyPI 被拦截时改用公司内部镜像源）

* **告警一直 pending 不 firing**：告警规则设了 `for` 持续时间（如表空间 WARNING 需持续 5 分钟），属正常行为

* **切换到 real 模式后 oracle\_up=0**：检查连接信息 / 监听 / 防火墙 / 监控账号权限

* **接入钉钉 / 企业微信通知**：在 `alertmanager\alertmanager.yml` 的 receiver 中填入 webhook 地址
