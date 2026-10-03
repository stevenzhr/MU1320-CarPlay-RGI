# F4 Renderer 独立试验审阅（v1，离线）

日期：2026-09-25。状态：`F4_RENDER_TRIAL_READY`（离线通过，**未上车**）。
SD 文件夹：`mu1320-rgi/mu1320-f4-render-v1/`。源码：`f4-src/`（`f4_feed.c`、SD README/观察表）。
脚本：`scripts/build_f4_render.py`、`scripts/prepare_f4_trial.py`、模板 `scripts/f4_control.sh.in`、
`scripts/f4_sd.sh.in`。测试：`tests/test_f4_trial.py`。构建/准备报告：`reports/f4-render-build.json`、
`reports/f4-render-prepare.json`。

## 1. 与 F3 的关系

用户要求（2026-09-25）：F4 与 F3 并行准备、**不整合**，各自独立上车，一项回滚后再做另一项。

- F4 包不含 Java、hook、SI/DIO 配置，也不检查 F3 的文件；F3 包也不含 renderer。两者没有共享的车上文件。
- F4 不安装任何东西：程序从 SD 运行，证据写 SD `out/`；车机只在 DisplayManager 内存中多一个 context 80
  （正常重启清除）。所以 F4 的"回滚"就是：试验结束切回原厂 context + 一次正常重启。
- 顺序建议：F3 v2 → rollback → 完整重启 → 确认正常 → F4。反过来也可以。

## 2. 方案：native-only，dmdt 组合 context

上游在 Java 中声明 `dc[80]={98,101,102,33}` 并由 `ScreenModule` 切换；renderer 本身只创建托管窗口 98。
F4 v1 不引入 Java，改用原厂 `dmdt`（`/mnt/app/eso/bin/apps/dmdt`，本车文件 cksum `2992755173 34464`）。
它的用法字符串写明支持：

- `dc cid did1 did2 ...` 声明 context；`sc display cid` 切换 context；
- `ts display path` 截图；`gs`/`gc`/`gd` 查询（本车以前采集过 `gs`/`gd`）。

测试 context 80 = `{98, 102, 101, 33}`：以本车原厂 74 `{20, 102, 101, 33}` 为基础，用 98 替换原车 KDK
机动图 20（同为 328×181，同处最前）。102/101 顺序照抄本车 74（上游 MU1316 是 101/102）。
仪表在 dmdt 中的 display id 为 **4**（displaymanager 内部编号，见第 10 节；最初误用 1）。

renderer 是 TCP **客户端**（连 127.0.0.1:19800，上游由 Java 监听）。F4 新增 `f4_feed`：每个场景一个进程，
监听 19800、等 `EVT_READY`、发送场景命令、保持连接 HOLD 秒后关闭；renderer 断链后自动清空（透明）并
每秒重连，下一个场景的 `f4_feed` 接上。

## 3. 构建（离线已验证）

- `maneuver_render`：固定上游 `f36790d` 源码**未修改**，固定工具链镜像 `sha256:e52565b1…`（GCC 4.9.4）。
  产物 120056 字节，SHA `9fccf76c…0fc7`，与 2026-09-22 native-probe 构建**逐字节相同**（可复现）。
- `f4_feed`：`-O2 -std=gnu99 -Wall -Wextra -Werror`，只依赖 libc/libsocket，13274 字节。
- 静态审计（`audit_native_probe.check_binary`，对照本车采集库）：两者 `STATIC_PASS`，无缺失依赖、
  无未解析强符号、无 emutls。renderer 直接依赖 `libEGL.so.1`、`libGLESv2.so.1`、`libscreen.so.1`
  （本车 `/proc/boot`）。
- 车上运行环境：`LD_LIBRARY_PATH=/proc/boot:/lib`、`GRAPHICS_ROOT=/proc/boot`（上游 supervisor 同款），
  cwd 为 SD `out/run-*/`（内含 `flag_atlas.rgba`）。control 启动前核对 dmdt、libc、libm、libsocket、
  libscreen、libEGL、libGLESv2 的 cksum 与采集件一致。

## 4. 车上流程（`f4_trial.sh run`，约 7 分钟，全自动）

| # | 步骤 | 机器判定 | 照片 |
| ---: | --- | --- | ---: |
| P | preflight：LVDS2 context 含 33、gd 含 16/33/101/102、无 98、无 context 80、无残留 renderer；记录基线 context | 不满足即 STOP，**未改任何状态** | 1 |
| 1 | 启动 renderer | 日志 `ready`；`gd` 出现 98（记录类型/尺寸，预期 328×181）；仪表 context 不变 | – |
| 2 | `dc 80 98 102 101 33`，`sc 1 80` | `gc` 有 80 且列表一致；`gs` 为 80 与该列表 | – |
| 3 | 闲置 | 截图 + 照片：应为地图、无黑块 | 2 |
| 4 | grid / 右转+进度条 / 左转 / 环岛 / 掉头 / 到达 | 每个场景 `EVT_FRAME_READY`；`gs` 仍为 80 | 3–8 |
| 5 | 发送端断开 | renderer 自清空 | 9 |
| 6 | `CMD_SHUTDOWN` | renderer 退出码 0；98 从 `gd` 消失 | 10 |
| 7 | 在 80 上重启 renderer，再 SIGKILL | 98 重新注册且箭头出现；强杀后 98 消失 | 11–12 |
| 8 | `sc` 回基线 context | `gs` 与基线一致，无 98 | 13 |

每步保存 `gs`/`gd`（及可用时 `dmdt ts` 截图）到 `out/run-*/sN-*/`。原厂 HMI 若把仪表切走，记
`STOCK_CONTEXT_CHANGE` 并最多重新切回 3 次。任何失败/信号：停止 feeder 和 renderer；**只有本次 run
切到过 80** 才切回基线 context（否则报告 `UNCHANGED`）。`restore` 动作用于脚本外的恢复，只在仪表处于 80
时切回（基线来自 `/tmp/mu1320-f4-v1.base`，缺失时为 74）。

对应 roadmap F4 验收：图层注册（步骤 1）、位置/尺寸/方向/裁剪（3–4 的照片与截图）、闲置透明（3、5）、
退出与崩溃后的恢复（6–8）、独立回滚（8 + 重启后 `collect restored`）。

## 5. 主机验证

`tests/test_f4_trial.py` 22 项通过（`reports/f4-render-host-tests.txt`；全项目 206 项通过）：

- 协议：`f4_feed.c` 的命令/事件/图标常量与上游 `protocol.h`、`maneuver.h` 逐项一致；各场景的 48 字节包
  逐字节核对（方向、角度大端、环岛 4 条路角度、进度条标志/等级、grid 开→转向→grid 关→CLEAR）；
  参数错误与端口占用的退出码。
- 事务（真实 shell + 假 dmdt/renderer/pidin/mount）：完整 run 13 张照片提示、14 个快照、8 个 feeder 全部
  rc=0、renderer 退出码 0 与 137、截图格式探测（png/bmp/不支持）、结束时仪表回到基线且无残留进程、
  `/tmp` 无残留、SD 恢复只读。
- 失败路径：preflight 各项 STOP 且不发 `dc`/`sc`、不启动 renderer；renderer 初始化失败不切换；切换后失败
  自动切回；基线为 72 时记录并切回 72；中断后的 `restore` 用记录的基线；只在 context 80 时切回；残留
  renderer 被停止；dmdt 挂起受 10 秒看门狗限制；wrapper 拒绝被改动的 control.sh；
  `collect restored` 能发现残留 context 80。
- 静态：SD 文件集合、SHA256SUMS、prepare 可逐字节复现；`mount_state` 与车上用过的 F3 v2 包逐字节相同；
  脚本无裸 `&&`（QNX ksh `set -e` 陷阱）、无 `IFS= read`、无 awk/sed/tee、不写 `/mnt/app`/`/mnt/system`、
  不在 `/tmp` 建目录（本车 `/tmp` 不支持目录）。

写测试时发现并修正的问题：已退出但未回收的子进程是僵尸，`kill -0` 仍成功——原先的 dmdt 超时轮询和
renderer/feeder 退出检测都会误判。现改为监视子 shell 回收进程并写退出码文件，dmdt 用看门狗 kill。

## 6. 未知项与风险（本轮要回答的问题）

1. **98 是否真的到达 VC**。上游说明 context 切换时由 DisplayManager 把 MOST 编码器指向最前的 displayable，
   但上游 Java 还会 `setUpdateRate(1, 30)`，并在进入 80 前经 72 "弹跳"一次。dmdt 无 update-rate 命令。
   若 `dmdt ts` 截图里有网格而 VC 照片没有，说明问题在编码器/更新率，v2 需要 Java/DSI。
2. **98 的位置/裁剪是 DisplayManager 默认值**（上游由 Java `ClusterLayerController` 设置
   `setPosition/setCropping`）。位置不对不算失败：grid 照片就是 F5 几何设置的测量依据。
3. **原厂 HMI 是否会把仪表切回**（`STOCK_CONTEXT_CHANGE` 次数）——F5 需要知道原厂写者。
4. `dmdt ts` 的文件格式未知，按 png→bmp→无扩展名探测；不支持时只靠照片。
5. EGL 初始化依赖 `GRAPHICS_ROOT=/proc/boot`（上游 MU1316 做法）；失败会在切换前 STOP。
6. renderer 以优先级 15 运行，渲染最多约 7 分钟；失败或断开 SSH 时自动停止。
7. context 80 的声明在重启前一直留在 DisplayManager 内存中（不被原厂引用）。试验后必须正常重启并
   `collect restored`。

## 7. 上车判定

可以上车（在 F3 v2 回滚并正常重启之后，或者在 F3 之前）。操作见 SD 文件夹内 `README.md`，
回传到 `resource/private/vehicle-dump/f4-render-v1/`。回传后写 `audit_f4_vehicle.py`，核对：
各步 `gs`/`gd` 序列、renderer 退出码、reversion 次数、截图与照片是否一致、重启后 `F4_RESTORED_BASELINE: PASS`。

## 8. 第一次上车：preflight 安全停止，原地修正（2026-09-25）

回传 `resource/private/vehicle-dump/f4-render-v1/`：`status`、`collect before`、`run` 三次中 `dmdt gs`/`gd`
输出都是 **0 字节**，`gc` 三次都**恰好 10240 字节**（截断在 context 77 中间，头部声明 86 个）。run 在 preflight
以 `cluster context is UNKNOWN` 停止，`UNCHANGED`，未声明/切换 context，也未启动 renderer。

原因：dmdt 用 stdio 打印后以 `_Exit(0)` 退出、不刷新缓冲。终端上是行缓冲（以前手动采集正常），重定向到文件时是
全缓冲，只有写满的整块落盘。修正（同一文件夹原地修改，不升版本）：

- 新增 `f4_unbuf.so`（`f4-src/f4_unbuf.c`，5403 字节，只依赖 libc，`STATIC_PASS`）：constructor 中
  `setvbuf(stdout/stderr, _IONBF)`，只通过 `LD_PRELOAD` 给 dmdt。本车 preload-probe v1.1 已证明预加载库的
  constructor 会执行。renderer 与 feeder 不变。
- 完整性判定：`gd` 行数必须等于 `knows N displayables`，`gc` context 数必须等于 `knows N contexts`，否则 STOP
  （之前截断的 gc 恰好含 74 而被当作 parsed，80 的有无其实无法判断）。
- 解析循环也读取无结尾换行的最后一行（以前采集的 `dmdt_gs.txt`/`dmdt_gd.txt` 末行无换行，旧解析会丢 33/102）。
- 测试：假 dmdt 复现"未预加载时只保留 10240 整块"；新增用本车真实 `gs`/`gd`/截断 `gc` 验证解析器。

## 9. 第二次上车：`dmdt ts` 使 displaymanager 卡死、MMI 自动重启（2026-09-25）

回传 `resource/private/vehicle-dump/f4-render-v1-run2/`：`status`、`collect before` 与 run 的 preflight 全部正常
（`f4_unbuf.so` 生效：gs/gd 完整，`gc 86/86`，基线 74 `[20 102 101 33]`）。preflight 通过后第一个动作是截图格式探测
`dmdt ts 1 /tmp/mu1320-f4-v1.ts.png`：10 秒无回应被看门狗杀掉，随后 bmp/raw 探测和 `gs`/`gd` 也全部 `DMDT_TIMEOUT`。
用户观察：VC 黑屏，之后 MMI 自动重启（VC 显示 "The MMI is switched off"），重启后功能正常。`dc`/`sc` 未执行，
renderer 未启动；重启清空了 DisplayManager 内存，无需 restore。

结论与修正（原地）：

- `dmdt ts` 在本车会让 displaymanager 失去响应，HMI 看门狗随后重启 MMI。**永远不再调用**；删除截图功能，照片为唯一画面证据。
  其他 dmdt 查询（gs/gd/gc）已多次安全执行。
- 顺带得到一条恢复证据：displaymanager 挂死时系统会自动整机重启并恢复正常。
- 脚本缺陷：displaymanager 已无响应（`cluster_ctx=UNKNOWN`）时 run 仍继续，下一步会启动 renderer。现改为 run 期间
  任何一次 dmdt 超时立即 STOP；每个快照也要求 gs 有 context、gd 完整。
- 测试：假 dmdt 对 `ts` 挂死并断言脚本从不调用；新增"preflight 后 displaymanager 失声 → 在启动 renderer、拍照提示和 dc/sc 之前停止"。

## 10. 第三次上车：renderer 注册成功；`sc 1` 被静默忽略，改用内部显示号 4（2026-09-25）

回传 `resource/private/vehicle-dump/f4-render-v1-run3/`：

- **renderer 在本车工作**：EGL 1.4 / Adreno 320 初始化成功；`gd` 出现 98（Software 328×181）；sloginfo
  `DisplayManager: new window available 98`，SIGTERM 后 `window closed: 98`，wfd 释放两块 328×181 缓冲。图层注册一项有了客观证据。
- `dc 80 98 102 101 33` 成功（gc 87/87，列表一致）。`sc 1 80` 无输出、无日志，仪表仍为 74，脚本停止并正常清理（STOCK_CLUSTER）。
- 原因（MU1320 `DisplayManager` 字节码）：原厂调用 DSI `switchContext(context, internalTerminal, session)`，
  `getInternalDisplayID` 把外部 0/3→0、2/4→1、**外部 1（仪表）→4**；这也和上游 `setActiveDisplayable(4, 98)` 一致。
  dmdt 直接对 displaymanager，用内部编号；内部 1 在本车不存在，命令被忽略。主屏 context 10 前后未变。
- 修正：仪表用 `sc 4`，主屏为 0。基线同时记录主屏 context；每次切换后若主屏变化立即 STOP，恢复时先仪表后主屏。
- 测试：假 dmdt 只接受 0/4，其他编号静默忽略；新增"sc 4 同时改了主屏 → STOP 并恢复主屏与仪表"。
