# MU1320 Toolbox v0（诊断版）离线审阅

- 日期：2026-09-27
- 包：`mu1320-toolbox-v0/`（由 `scripts/prepare_toolbox_v0.py` 生成，`--replace` 可重建；构建在临时目录完成后才替换）
- 源：`tbv0-src/`（页面、6 个按钮脚本、`lib.sh.in`、SD 说明与观察表）
- 测试：`tests/test_toolbox_v0.py` 13 项，`/bin/sh` 与 `/bin/ksh` 均通过
- 状态：**未上车**

## 包的构成

| 部分 | 来源 | 说明 |
| --- | --- | --- |
| `metainfo2.txt`、`Toolbox/`（149 个文件） | 上游 `jilleb/mib2-toolbox` `af244e7`，只取已跟踪文件，逐字节复制 | `metainfo2.txt` 与 `Toolbox/final/` 与上游相同，SWDL 元数据和最终脚本都是车上已经接受过的版本（Lanye 版也没有改动它们） |
| `Toolbox/GEM/mqb-mu1320.esd` | 本项目 | `screen "MU1320 RGI" Customization`，按 Lanye 页面的挂载写法，不修改任何现有页面 |
| `Toolbox/scripts/mu1320/` | 本项目 | 上游 `install_scripts.sh` 把它装到 `/eso/hmi/engdefs/scripts/mqb/mu1320/` |
| `mount_state` | `mu1320-f3-bap-v2`，逐字节相同 | 已在车上运行过 |
| `f4_unbuf.so` | `mu1320-f7-daily-v1`，逐字节相同 | F4/F5 车上 dmdt 路径 |
| `lanye_manifest.txt` | Lanye `441c150` 相对上游新增的 17 个文件的 cksum | 生成时与 `toolbox-inventory-v1` 的车上清单逐项核对，全部一致 |
| `LICENSE-mib2-toolbox.txt` | 上游 MIT 许可 | |

另外，上次清点里车上比上游多出的 19 个文件，实际是 Lanye 的 17 个文件加上 2 个 macOS `._*` 文件（`sbin/._bc`、`._cmp`）；清点报告已更正。

## 按钮

| # | 脚本 | 改动车机 | 要回答的问题 |
| --- | --- | --- | --- |
| 1 | `probe_ro.sh` | 否（SD + `/tmp` 一个临时文件） | 节点、UID、启动时 PATH 与环境、父进程、子进程是否继承被忽略的 SIGTERM、F7 用到的命令是否都在、`/fs/sda0` 等路径是否可见、`pidin`/`sloginfo`/`dmdt gs`/`dmdt gd` 能否执行 |
| 2 | `probe_write.sh` | 临时 | `/mnt/app`、`/mnt/system` 能否改为可写；在 `/mnt/app/root`、`lsd/jars`、`production` 中写入、读回并删除点文件；在 `/mnt/app/root` 中创建并删除空目录；最后恢复只读并核对 |
| 3 | `bg_start.sh` | 否 | 后台进程（普通与 nohup）在脚本结束、离开菜单后是否存活；60 秒脚本会不会被切断；输出是逐行显示还是结束后一起显示 |
| 4 | `bg_check.sh` | 否 | 核对按钮 3 的进程，只结束 PID 与进程名都对得上的；按钮 3 没跑完则不结束任何进程 |
| 5 | `lanye_check.sh` | 否 | Lanye 文件逐个核对 cksum，并列出 `._*` 文件 |
| 6 | `lanye_remove.sh` | 是 | 只删除 cksum 一致的 Lanye 文件和 `._*` 文件；删除前逐个备份到 SD 并核对，任何一份备份失败都不删除；`/mnt/app` 只在删除期间可写 |

公共部分（`lib.sh`）：

- 固定 PATH。
- 核对 `mount_state`、`f4_unbuf.so`、清单的 cksum。
- 选 SD、按需切换可写，并建立运行目录 `mu1320-toolbox-v0-out/<动作>-<pid>/`。
- EXIT trap 依次撤销本次做过的 `/mnt` 重挂，然后把 SD 恢复原状；屏幕末行固定为 `RESULT: DONE/FAILED` 与 `Saved:`。
- `rm` 目标一律用 `${VAR:?}` 保护。

## 测试覆盖

测试在模拟的车机目录树中，按上游 `install_scripts.sh` 的方式「安装」本包，再放入 Lanye 的 17 个文件和一个 `._bc`：

- 按钮 1：车机目录树完全不变，摘要各项正确；以忽略 SIGTERM 的方式启动时报告 `IGNORED`。
- 按钮 2：车机目录树不变，两个挂载都恢复为 ro；`/mnt/system` 重挂失败时报告 FAILED，`/mnt/app` 和 SD 仍然恢复。
- 按钮 3/4：6 个 tick、两个后台进程存活、重复按按钮 3 被拒绝、按钮 4 结束两者并清除记录；记录里没有进程名时不结束任何进程。
- 按钮 5：只读，`match=17 changed=0 absent=0 ._=1`。
- 按钮 6：人为改动 1 个 Lanye 文件后，只删除 16 个一致的文件和 `._bc`，改动过的文件保留；备份与原件逐字节相同；上游 Toolbox、本页面、`scripts/ssh`、`/mnt/app/root`、`/mnt/system` 都不变；再次运行显示 `nothing to remove`。
- 清单被篡改时拒绝执行，不删除任何文件；没有 SD 或 `mount_state` 被改动时失败退出，且不写 SD。
- 静态检查：
  - 包可以复现；`metainfo2.txt` 与 `final/` 与上游一致，包里没有 `._*` 文件；
  - 页面按钮指向的脚本都存在；
  - 脚本里没有裸 `&&`、`IFS= read`、`grep -c ''`、`dmdt ts`，也没有未加保护的 `rm`。

主机测试中发现并修正了两处问题：

- SIGTERM 检测原先会被脚本自己的 TERM trap 干扰：子进程在 exec 之前沿用了父进程的 trap。现在子进程先执行 `trap - 15`；启动时就被忽略的信号仍保持忽略，所以 HMI 继承下来的忽略状态依然能测出来。
- 后台进程名原先在 fork 之后立即记录，可能记成 shell 或 nohup；现在改为 60 秒后再记录。

## 未知与风险（要靠实车回答）

- **GEM 脚本跑在哪个节点、能否看到 `/fs/sda0`**：看不到时每个按钮都会显示 `FAIL: no SD card`，这本身就是结果，说明 F7 调度脚本要改用 `/net/mmx/fs/...` 或 `on -f mmx`。
- **屏幕如何显示脚本输出**：由按钮 3 回答。
- **esd 语法**：照搬上游和 Lanye 页面已经在车上显示过的元素（`screen`、`keyValue`、`script`）。
- **Mac 拷卡产生的 `._*` 文件**：说明中要求拷卡后执行 `dot_clean`；即使有残留，按钮 6 也会清除 `scripts/mqb` 下的这类文件。
- **SWDL 本身**：流程与车上已经做过的 Toolbox 安装相同（元数据未改），只是多了 13 个文件（1 个页面和 12 个脚本/辅助文件）。
