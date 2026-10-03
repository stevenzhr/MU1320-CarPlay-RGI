# MU1320 Toolbox v1（F7 绿色菜单）

内容 = 上游 `mib2-toolbox`（固定版本 `af244e7`，与 v0 相同）+ F7 菜单页。`metainfo2.txt` 和 `Toolbox/final/` 与上游完全一致，
安装流程就是上游 Toolbox 自己的更新流程（与 2026-09-27 装 v0 时相同）。

页面仍在 `Main > MQBCoding > Customization > MU1320 RGI`，**替换**掉 v0 的诊断页（同一个文件名），有 5 个按钮：

| 按钮 | 调用 SD 上 F7 文件夹的 | 说明 |
| --- | --- | --- |
| 1 Status (read-only) | `f7.sh status` | 只读状态摘要 |
| 2 Install (then full restart) | `f7.sh install` | 安装后要完整重启 |
| 3 Uninstall (then full restart) | `f7.sh rollback` | 卸载后要完整重启 |
| 4 Collect logs to SD | `f7.sh collect snapshot` | 停车后、锁车前点一次 |
| 5 EMERGENCY STOP | `f7.sh stop` | 立即回原厂，到下次重启为止 |

菜单本身不含 F7 的任何逻辑：它只在 SD 根目录（`/fs/sda0` 或 `/fs/sdb0`）找**唯一一个**带 `TOOLBOX-ENTRY` 文件的
`mu1320-f7-*` 文件夹，运行里面的 `f7.sh`。F7 换版本时只换 SD 上的文件夹，不需要重刷 Toolbox。
屏幕显示 10 行以内的摘要，最后是 `Log: out/...` 和 `RESULT: OK` / `RESULT: FAILED`；完整输出在 F7 文件夹的 `out/`。
同一时间只能运行一个按钮（前一个没结束会显示 `BUSY`）。菜单脚本自己不写 SD、不改 `/mnt`，环境（PATH、LD_LIBRARY_PATH、umask、工作目录）先清理再调用。

v0 的诊断脚本（`probe_*.sh`、`bg_*.sh`、`lanye_*.sh` 等）仍留在车上 `scripts/mqb/mu1320/`，但没有页面再调用它们；Toolbox 更新只会新增和覆盖文件。

**SSH 不受影响**：与 v0 相同，Toolbox 更新不碰 `scripts/ssh/`、`/mnt/system`、`/mnt/app/root`。

## 准备 SD 卡

1. SD 上现在的 `Toolbox/` 和 `metainfo2.txt` 是 v0，可以直接删除（Mac 上的 `mu1320-toolbox-v0/` 就是它的副本）。
   `Custom/`、`Backup/`、`Log/` 留着不动。
2. 把 `mu1320-toolbox-v1` 文件夹**里面的全部内容**复制到 SD **根目录**（不是文件夹本身）。
3. 同时把 `mu1320-f7-daily-v2/` 文件夹（整个文件夹）复制到 SD 根目录，以后菜单要用。
4. 在 Mac 终端清掉 `._*` 文件，第二条命令应没有输出：

   ```sh
   dot_clean -m /Volumes/<SD卷名>
   find /Volumes/<SD卷名> -name '._*'
   ```

## 安装（与 v0 相同的更新流程）

1. 停车，稳定供电。按住 MENU 键进服务界面 →「Software updates/versions」→ 右上角「Update」→ 选 SD →「MQB Coding MIB2 Toolbox」。
2. 让更新完整跑完（中间重启几次，最后 Toolbox 一行为 Y，点返回；提示清故障码时点「Cancel」）。
3. 进 `Customization > MU1320 RGI`：应看到 5 个 F7 按钮，v0 的 6 个诊断按钮不见了。
4. 按 **1 Status**：应显示 `Folder: mu1320-f7-daily-v2` 和 `SI: BASELINE/BASELINE`、`RESULT: OK`（车上是原厂基线时）。
5. SSH 连一下车机，确认仍然正常。

之后按 `mu1320-f7-daily-v2/README.md` 做 F7 v2 的安装和各场次。

## 屏幕上可能出现的提示

| 提示 | 含义 |
| --- | --- |
| `NO F7 FOLDER` | SD 根目录没有带 `TOOLBOX-ENTRY` 的 `mu1320-f7-*` 文件夹（或 SD 没插） |
| `2 F7 FOLDERS` | 有多个，只留一个 |
| `BUSY` | 上一个按钮还在运行，等它显示 `RESULT` |
| `STOP: ...` | F7 脚本拒绝执行（原因同 SSH 时），什么都没改或已恢复；看 `Log:` 指向的文件 |
| `NEXT: full restart of the MMI` | 安装/卸载的文件已完成，完整重启后生效 |
