# ============================================================
# Oracle 监控账号最小权限授权脚本
# 在目标 Oracle 数据库以 SYSDBA 执行（CDB 或 PDB 均可）
# 权限范围 = oracle/skills 技能库中监控/性能诊断 SQL 所需视图
# ============================================================

-- 1. 创建监控账号（请按需修改密码）
CREATE USER db_monitor IDENTIFIED BY "Monitor@2026" DEFAULT TABLESPACE users;
-- 如需只读远程访问：
-- CREATE USER db_monitor IDENTIFIED BY "Monitor@2026" DEFAULT TABLESPACE users
--   QUOTA 0 ON users;

-- 2. 基础角色（只读）
GRANT CONNECT TO db_monitor;
GRANT SELECT_CATALOG_ROLE TO db_monitor;

-- 3. 空间管理（db/monitoring/space-management.md）
GRANT SELECT ON dba_tablespace_usage_metrics TO db_monitor;
GRANT SELECT ON dba_tablespaces            TO db_monitor;
GRANT SELECT ON dba_data_files             TO db_monitor;
GRANT SELECT ON dba_free_space             TO db_monitor;
GRANT SELECT ON dba_segments               TO db_monitor;
GRANT SELECT ON dba_tables                 TO db_monitor;
GRANT SELECT ON dba_lobs                   TO db_monitor;

-- 4. 会话/锁/性能（db/performance/*）
GRANT SELECT ON v_$session       TO db_monitor;
GRANT SELECT ON v_$session_wait  TO db_monitor;
GRANT SELECT ON v_$system_event  TO db_monitor;
GRANT SELECT ON v_$event_histogram TO db_monitor;
GRANT SELECT ON v_$sqlarea       TO db_monitor;
GRANT SELECT ON v_$sql           TO db_monitor;
GRANT SELECT ON v_$lock          TO db_monitor;
GRANT SELECT ON v_$locked_object TO db_monitor;
GRANT SELECT ON v_$sysstat       TO db_monitor;
GRANT SELECT ON v_$sgastat       TO db_monitor;
GRANT SELECT ON v_$instance      TO db_monitor;
GRANT SELECT ON v_$sort_usage    TO db_monitor;
GRANT SELECT ON v_$temp_space_header TO db_monitor;

-- 5. Alert 日志 / ADR（db/monitoring/alert-log-analysis.md）
GRANT SELECT ON v_$diag_alert_ext   TO db_monitor;
GRANT SELECT ON v_$diag_info        TO db_monitor;
GRANT SELECT ON v_$diag_incident    TO db_monitor;
GRANT SELECT ON v_$database_block_corruption TO db_monitor;

-- 6. 归档 / 备份（db/backup-recovery/）
GRANT SELECT ON v_$archive_dest        TO db_monitor;
GRANT SELECT ON v_$recovery_file_dest  TO db_monitor;
GRANT SELECT ON v_$rman_backup_job_details TO db_monitor;

-- 7. AWR / ASH 历史（db/performance/awr-reports.md, ash-analysis.md）
GRANT SELECT ON dba_hist_snapshot      TO db_monitor;
GRANT SELECT ON dba_hist_sqlstat       TO db_monitor;
GRANT SELECT ON dba_hist_tbspc_space_usage TO db_monitor;
GRANT SELECT ON dba_hist_sysstat       TO db_monitor;

-- 7.5 新增指标（实例/重做/归档/内存）
GRANT SELECT ON v_$log_history       TO db_monitor;
GRANT SELECT ON v_$archived_log      TO db_monitor;
GRANT SELECT ON v_$pgastat           TO db_monitor;

-- 8.（可选）允许查看告警日志目录信息
GRANT SELECT ON v_$parameter          TO db_monitor;

-- ============================================================
-- 生产安全建议：
--  1. 监控账号严禁授予 DBA 角色
--  2. 建议在 sqlnet.ora 中配置 tcp.validnode_checking 白名单，
--     仅允许监控服务器 IP 访问 1521
--  3. AWR 快照配置检查（保留 15 天、间隔 1 小时）：
--     SELECT snap_interval, retention FROM dba_hist_wr_control;
--     EXEC DBMS_WORKLOAD_REPOSITORY.MODIFY_SNAPSHOT_SETTINGS(RETENTION=>21600, INTERVAL=>60);
-- ============================================================
