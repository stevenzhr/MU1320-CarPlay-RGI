# /mnt/app/root 只读清点 v1 实车结果

- 日期：2026-09-26
- 包：`mu1320-root-inventory-v1`（只读，未改动车机）
- 证据：`resource/private/vehicle-dump/root-inventory-v1/`（`action-run-3219591.txt`，`inv-3317899/`）

## 运行结果

`ROOT_INVENTORY_COMPLETE`，`CONTROL_EXIT=0`，SD 原为 `ro`。共拷出 80 个文件（2.4 MB），`COPY_ERRORS=0`。

已知小缺陷：车上 grep 不支持 `grep -c ''`（报 `empty (sub)expression`），所以 `MANIFEST_LINES` 为空。
`manifest.txt` 本身完整，共 383 行。这个问题不影响清点结果。

## /mnt/app/root 顶层（18 项）

| 项 | 判定 |
| --- | --- |
| `mu1320-env-probe-v2`、`mu1320-preload-probe-v1` | 本项目试验残留 |
| `mu1320-rgi-stage1-v2`、`-stage2-v2`、`-stage3-v1` | 本项目试验残留 |
| `mu1320-rgi-navhook-v1`、`-navjava-v1` | 本项目试验残留 |
| `mu1320-rgi-f1-v1`、`-f1-v2`、`-f2-v1`、`-f3-v1`、`-f3-v2` | 本项目试验残留 |
| `bin-target`（5 个原车二进制）、`.profile`、`.ssh/authorized_keys`、`scp`、`scpr` | 原车或 SSH 环境，保留 |
| `hooks/`（空目录） | 不是 mu1320 创建的。上游 `mib2q-carplay-rgi` 与 Lanye 安装脚本使用该路径，保留 |

`mu1320-rgi-stage1-v1` 与 `mu1320-env-probe-v1` 已不在车上。`lib-target` 虽被 LD_LIBRARY_PATH 引用，但车上并没有这个目录。

## 备份与在用文件（SHA-256）

| 文件 | 车上在用 | 各试验目录中的全部备份 | 工作站原件 |
| --- | --- | --- | --- |
| `NavActiveIgnore.jar` | `c962834d…` | 9 份，全部相同 | `resource/jars/NavActiveIgnore.jar` 相同 |
| `smartphone_integrator.json` | `dd7bf223…` | 10 份，全部相同 | `resource/smartphone_integrator.json` 相同 |
| `dio_manager.json` | `79de61f1…` | stage1-v2 的 etc/system 两份相同 | `resource/dio_manager.json` 相同 |
| `lsd.sh`、`carplay_cleanup.sh` | 未清点 | stage1-v2 备份 | `resource/` 中的相同 |

所有试验目录内共 80 个文件，其中 73 个在工作站上已有字节相同的副本。其余 7 个是 `phase.txt`，
内容均为 `INSTALLATION_BASELINE_RESTORED`，这次也已拷回。

## 其他检查

- 在用 SI 和 DIO 配置中没有 `mu1320` 引用，DIO 中没有 LD_PRELOAD。
- SI 中有 `LD_PRELOAD=/eso/lib/libsystemtime_hack.so`（MirrorLink 子进程）。这一项在
  stage1-v2 安装前的基线备份和 `resource/` 原件里都已存在，不是本项目引入的。
- HMI jars 目录有 18 个文件，与 HMI bootclasspath 一致，没有残留的 CarPlayRGI jar 或 `.DISABLED` 文件。
- production 目录没有 `.mu1320-*` 临时文件。
- 没有引用 mu1320 的运行进程（只有清点脚本自身）。
- `/mnt/app` 空闲 223 MB（已用 78%）。试验残留仅约 2.4 MB，清理的目的是整洁和避免混淆，不是释放空间。

## 结论

12 个 `mu1320*` 目录都可以删除：其中的备份与在用文件和工作站原件逐字节相同，当前配置和进程也都不再引用它们。
其余顶层项目一律保留。
