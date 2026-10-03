# /mnt/app/root 试验残留清理 v1 实车结果

- 日期：2026-09-26
- 包：`mu1320-root-cleanup-v1`（名单来自 [ROOT-INVENTORY-VEHICLE-V1-REVIEW.md](ROOT-INVENTORY-VEHICLE-V1-REVIEW.md)）
- 证据：`resource/private/vehicle-dump/root-cleanup-v1/`（3 份 action 日志、survey 记录、`terminal-output.txt`）

## 结果：通过

| 运行 | 关键输出 |
| --- | --- |
| `status` | `BASELINE_CONFIG: OK`、`NO_PROCESS_REFERENCES: OK`、`VERIFIED: 115 of 115 …, 0 unexpected`、`NOT_STARTED`、`ROOT_CLEANUP_status_PASSED` |
| `delete` | 同样核对通过 → `REMOVED: 115` → `VERIFIED: 0 of 115`、`ROOT_CLEANUP_COMPLETE`、`APP_MOUNT_RESTORED: /mnt/app=ro`、`ROOT_CLEANUP_delete_PASSED` |
| 第二次 `delete`（代替 README 第 3 步的 `status`） | `CLEANUP_STATE: DONE`、`NOTHING_TO_DELETE`，在改挂载之前就退出，等同于 status 复核 |

三次运行的终端末尾都有 `SD_MOUNT_RESTORED: /fs/sda0=ro`、`CONTROL_EXIT: 0`、`OUTER_EXIT: 0`。
`before.txt` 记录了 115 条，删除后的 `after.txt` 和复核时的 `before.txt` 都是 0 条。

12 个试验目录全部删除。保留项未变：`bin-target`、`hooks`、`scp`、`scpr`、`.profile`、`.ssh`。

## 观察

- 车上已有 `mu1320-rgi-f5-v1`，它不在名单内，按设计保留（`KEEP`）。三个基线文件（SI、DIO、NavActiveIgnore）
  都与清点时一致，说明 F5 当前没有安装，只留下了工作目录。这与之前各阶段的情况相同：回滚恢复了配置，但不删除
  自己的工作目录。以后清理时要把它算进去（需另做清点）。
- 车上第一次使用 `rmdir`，38 个目录全部删除成功。
