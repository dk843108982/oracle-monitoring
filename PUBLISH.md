# 发布到 GitHub 指南（PUBLISH.md）

本项目已按「开源发布」标准整理：**源码入库、二进制/运行数据/真实配置不入库、可移植包走 Release 附件**。
本指南面向两种角色：项目维护者（发布）与使用者（clone 后运行）。

---

## 一、仓库内容规划（已通过 .gitignore 落实）

| 内容 | 处理 | 原因 |
|---|---|---|
| 采集器 / Grafana 大盘 / 规则 / 控制台 / 脚本 / 文档 | ✅ 入库 | 全部源码 |
| `collector/config.example.json` | ✅ 入库 | 脱敏示例，clone 后复制为 config.json 即用 |
| `collector/config.json` | ❌ 忽略 | 含真实数据库口令 |
| `bin/downloads`、`bin/extracted` | ❌ 忽略 | Prometheus/Alertmanager/Grafana 二进制约 500MB |
| `prometheus/data`、`grafana/data`、`alertmanager/data`、`logs/`、`collector/reports/` | ❌ 忽略 | 运行时数据 |
| `oracle-monitoring-portable.zip` | ❌ 忽略 | 452MB 构建产物，走 GitHub Release 附件 |
| `oracle-skills/`（oracle/skills 克隆） | ❌ 忽略 | 第三方仓库，见下文「技能库」 |

> clone 本仓库后，首次运行前执行：
> `copy collector\config.example.json collector\config.json`（Windows）
> 或 `cp collector/config.example.json collector/config.json`（Linux/macOS）
> 采集器在缺少 config.json 时也会自动回退默认配置并生成，直接 `start-all.ps1` 也能跑（demo 模式）。

---

## 二、技能库（oracle/skills）说明

本项目深度依赖 [oracle/skills](https://github.com/oracle/skills) 的 `db/` 技能树（约 170 个技能），但**不把它克隆进本仓库**（避免嵌套 git 仓库与许可混乱）。两种用法：

1. **直接 clone（推荐，最简单）**：在项目根目录的上级目录执行
   ```bash
   git clone https://github.com/oracle/skills oracle-skills
   ```
   即保证 `oracle-monitoring` 与 `oracle-skills` 同级。`start-all.ps1` 会自动探测 `.\oracle-skills` 与 `..\oracle-skills` 两级位置。

2. **submodule（可选）**：
   ```bash
   git submodule add https://github.com/oracle/skills oracle-skills
   ```

> 许可说明：oracle/skills 依其自身许可分发（UPL 类）；本仓库自有代码（采集器、控制台、脚本）按仓库根 LICENSE 分发。

---

## 三、发布步骤（维护者）

### 1. 创建远程仓库
GitHub 网页 → New repository → 命名（如 `oracle-monitoring`）→ **不要**勾选 README/.gitignore/LICENSE（本地已有）→ Create。

### 2. 本地初始化并推送
```bash
cd oracle-monitoring
git init                 # 若尚未初始化
git add .
git status               # 确认没有 config.json / bin / zip 等敏感或大文件
git commit -m "Oracle enterprise monitoring with oracle/skills integration"
git branch -M main
git remote add origin https://github.com/<你的账号>/oracle-monitoring.git
git push -u origin main
```

### 3. 发布 Release 附件（可移植包）
GitHub 仓库页 → Releases → Create a new release → 打 tag（如 `v1.0.0`）→ 上传 `oracle-monitoring-portable.zip`（由 `package.ps1` 生成，452MB，未超 2GB 单文件上限）→ Publish。

> 可移植包内含：全部源码 + oracle/skills 技能库 + 三大组件二进制 + 文档，目标机器解压后仅需安装 Python 3.12（含 python-oracledb）即可运行，无需联网下载。

### 4. 后续更新节奏
- 代码更新 → commit + push；
- 包更新 → 重新运行 `package.ps1`，在 Releases 里编辑对应 tag 覆盖附件。

---

## 四、使用者快速开始（clone 之后）

```bash
git clone https://github.com/<账号>/oracle-monitoring.git
git clone https://github.com/oracle/skills oracle-skills   # 技能库（与项目同级或项目内）
cd oracle-monitoring
copy collector\config.example.json collector\config.json    # Windows；Linux 用 cp
.\start-all.ps1
```

访问：
- Grafana：http://localhost:3000 （admin/admin）
- Skill Console：http://localhost:8090
- Metrics：http://localhost:9161/metrics
- Prometheus：http://localhost:9090

接入真实库：编辑 `config.json`（`oracle_instances` 数组）→ `py -3.12 collector\connect-check.py` 自检 → 重启。详见 README「接入真实 Oracle 数据库」。

---

## 五、常见问题

- **push 被拒/超限**：确认没有把 `bin/`、`*.zip`、`config.json` 加入 git（`git status` 核对；必要时 `git rm --cached` 后重新提交）。
- **clone 后启动报找不到技能库**：`start-all.ps1` 会探测 `.\oracle-skills` 和 `..\oracle-skills`，请确认 oracle/skills 克隆在这两个位置之一。
- **二进制下载慢**：仓库内不保存二进制；如需离线，直接下载 Release 附件（可移植包）更省事。
- **许可证**：给自有代码选择一个 LICENSE（如 MIT）放入仓库根目录；oracle/skills 保持其上游许可并注明来源。
