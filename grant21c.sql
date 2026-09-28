-- 创建监控用户（如果不存在）
CREATE USER db_monitor IDENTIFIED BY ChangeMe_2026;
-- 授权
GRANT CREATE SESSION TO db_monitor;
GRANT SELECT ANY DICTIONARY TO db_monitor;
GRANT SELECT ON v_$instance TO db_monitor;
GRANT SELECT ON v_$sysstat TO db_monitor;
GRANT SELECT ON v_$system_event TO db_monitor;
GRANT SELECT ON v_$session TO db_monitor;
GRANT SELECT ON v_$sqlarea TO db_monitor;
GRANT SELECT ON dba_tablespaces TO db_monitor;
GRANT SELECT ON dba_data_files TO db_monitor;
GRANT SELECT ON dba_free_space TO db_monitor;
GRANT SELECT ON v_$datafile TO db_monitor;
GRANT SELECT ON v_$database TO db_monitor;
GRANT SELECT ON v_$sga TO db_monitor;
GRANT SELECT ON v_$pgastat TO db_monitor;
GRANT SELECT ON v_$log TO db_monitor;
GRANT SELECT ON v_$tablespace TO db_monitor;
GRANT SELECT ON v_$temp_space_header TO db_monitor;
GRANT SELECT ON v_$undostat TO db_monitor;
GRANT SELECT ON v_$diag_alert_ext TO db_monitor;
GRANT SELECT ON v_$diag_incident TO db_monitor;
GRANT SELECT ON v_$database_block_corruption TO db_monitor;
GRANT SELECT ON v_$hm_run TO db_monitor;
GRANT SELECT ON v_$archive_dest_status TO db_monitor;
GRANT SELECT ON dba_tablespace_usage_metrics TO db_monitor;
EXIT;
