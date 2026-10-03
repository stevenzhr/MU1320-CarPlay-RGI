# MU1320 Toolbox v0 实车结果

- 日期：2026-09-27
- 包：`mu1320-toolbox-v0`（SWDL 安装后在绿色菜单 `Customization > MU1320 RGI` 中运行）
- 证据：`resource/private/vehicle-dump/toolbox-v0/`（7 个运行目录）
- 屏幕照片：`images/IMG_6952`–`6959.HEIC`（8 张）。用户说明观察记录与预期一致，没有另外填写；`Log/install_final.txt` 没有取回

## 用户观察（2026-09-27）

- 按钮 3 的 tick 行每 10 秒陆续出现，屏幕是**逐行实时显示**脚本输出的。
- 第一次按按钮 5：`match=17 changed=0 absent=0 ._ files=2`。
- 退出后重新进入绿色菜单，Lanye 的两个页面已经消失，MU1320 RGI 仍在；SSH 可以正常连接。
- 照片显示输出在 `<GEM 4.12s> mqbcoding/customization/mu1320 rgi/Console` 页，一屏约 12 行、每行约 60 个字符，超出部分要向下翻（按钮 2 的 `SD back to ro`、`Saved:` 两行就被挤到了下一屏）。

## 结果总览

7 次运行全部 `RESULT: DONE`，SD 每次都恢复为 ro。

| 按钮 | 结果 |
| --- | --- |
| 1 环境探测 | 运行在 `mmx` 上，uid 0；父进程为 HMI JVM `ifs/jre/bin/j9`；F7 用到的命令全部存在；`pidin`（136 行）、`sloginfo`（3482 行）、`dmdt gs`/`gd` 均 rc=0；`/tmp` 可写 |
| 2 写入探测 | `/mnt/app`、`/mnt/system` 都能从 ro 切到 rw；`/mnt/app/root`、`lsd/jars`、`production` 均可写入、读回、删除；`/mnt/app/root` 可以 mkdir/rmdir；最后两个挂载都恢复为 ro |
| 3 后台 + 60 秒 | 6 个 tick 全部出现，脚本没有被切断；60 秒后两个后台进程仍在（`bin/sleep`） |
| 4 检查 | 离开页面、退出菜单后回来，两个进程都还活着（`alive=yes`），都被结束（`stopped=yes`） |
| 5 核对 | `match=17 changed=0 absent=0`，`._` 文件 2 个（`sbin/._bc`、`._cmp`） |
| 6 删除 | 19 个文件逐个备份后删除，`left=0`；`/mnt/app` 恢复为 ro |
| 5 复查 | `match=0 absent=17 ._=0` |

## 绿色菜单脚本的执行环境（F7 v2 调度脚本据此设计）

- **启动方式**：`$_=/bin/on`，工作目录为 `/mnt/app/eso`，stdin 和 stdout 都不是 tty，`HOME=/var`，`TERM=vt100`。
- **PATH 以 `.` 开头**：`.:/armle/bin:/armle/scripts:/proc/boot:...:/root/bin-target`。
- **LD_LIBRARY_PATH 以 `.` 开头**，还包含 `/root/lib-target`、`/ifs/jre/bin`、HMI 目录等。F7 现有的 `f7.sh` 只清除了 `LD_PRELOAD` 等变量，没有处理 `LD_LIBRARY_PATH`。
- **umask 为 `000`**：不显式设置的话，新建文件对所有人可写。
- **路径**：`/fs/sda0` 可见，所以 F7 `f7.sh` 对 `/fs/sda0`、`/fs/sdb0` 的检查可以原样使用。`/eso` 是指向 `/mnt/app/eso` 的链接；`/tmp` 是指向 `/dev/shmem` 的链接，这也解释了之前发现的「`/tmp` 下不能建目录」。
- **时钟**：刚开机时系统时间是 1970-01-01，所以日志里的日期不可靠，应该用 PID 或序号区分记录。
- **命令**：`kill` 是 shell 内建命令，`nohup` 是 ksh 别名，`on`、`use`、`find`、`sed`、`awk` 都存在。
- **dio_manager 不在进程列表中**：测试时没有连接手机，这是正常的，它只在手机连接时才启动。

## 更正：SIGTERM 结论无效

按钮 1 报告了 `child SIGTERM: IGNORED`，但同一次运行的 `pidin ... signals` 显示，脚本 shell 和父进程 j9 的忽略掩码都是 `0x6801006`，
也就是只忽略 INT、QUIT、PIPE、TSTP、TTIN、TTOU，**SIGTERM 没有被忽略**，阻塞掩码里也没有 TERM。

`IGNORED` 这个结果很可能来自探测本身的竞态：`kill -TERM` 发出时，子 shell 还带着父脚本的 `exit 143` trap，信号被记为待处理；
紧接着 `trap - 15` 清掉了这个待处理的信号，之后 exec 出的 `sleep` 就再也收不到 TERM，最后被 3 秒看门狗用 SIGKILL 结束。

结论：**从绿色菜单启动的脚本不会继承被忽略的 SIGTERM**。这和 F7 之前「从 HMI JVM 启动的 context helper 继承了被忽略的 SIGTERM」
的观察不矛盾，因为那是另一条启动路径。F7 继续使用 SIGKILL 看门狗，两种情况都能处理。探测脚本今后如果复用，应该在 fork 之后先等待再发 TERM，或者只根据 `pidin signals` 的掩码判断。

## 对 F7 v2 的结论

1. **调度脚本可以直接调用 SD 上的 F7 `f7.sh`**：节点、root 权限、SD 路径、重新挂载、所有写入目标目录、`dmdt` 路径都已经实车验证。
2. **调度脚本在调用前必须清理环境**：执行 `cd /`；设置固定的 PATH（去掉 `.`）；清除或固定 `LD_LIBRARY_PATH`（去掉 `.` 和 `/root/lib-target`）；`umask 022`。
   这些同样应该补进 `f7.sh`，因为它也可能在 SSH 以外的环境下运行。
3. **后台进程在脚本结束、退出菜单后都会存活**，所以调度脚本可以启动较长的后台任务，但必须自己负责清理，不能指望菜单替它结束进程。
4. **60 秒的脚本不会被切断，输出逐行实时显示**。因此较长的操作（安装、采集）可以在前台运行，并逐步显示进度，不需要拆成「后台启动 + 另一个按钮查结果」。
   屏幕摘要要控制在约 10 行以内，把 `RESULT` 和保存目录放在一屏之内。
5. Lanye 的 RGI/Mirror 菜单文件已经从车上删除，备份在 `lanye-remove-6078532/backup/`。
