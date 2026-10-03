# navjava-ingress v1 实车审计（2026-09-24）

结论：**`NATIVE_TO_JAVA_INGRESS_AND_ROLLBACK_VERIFIED`**。native hook 收到的 CarPlay 导航数据已经过 TCP bus 到达 MU1320 的 Java/J9 进程，并被最小监听器严格解析通过（14 条 `PARSE_OK`，0 条 `PARSE_REJECT`）；文件回滚与完整重启后的运行时回滚均通过。

- 输入：`resource/private/vehicle-dump/navjava-ingress-v1/`（22 个文件，逐文件 SHA-256 见 `navjava-ingress-vehicle-v1.json` 的 `inputs`）。
- 审计：`scripts/audit_navjava_vehicle.py` 从原始 action log、进程文件和 hook/Java 日志重新计算全部 45 项判定，collector 摘要只作交叉核对。报告不复制路名和目的地。
- 车上运行的是原地修正后的 SD 目录（`control.sh` cksum `3051520410 21912`）：install 日志逐步打印 `install_STEP`，是全新工作目录，所有文件均为写入而非复用。

## 文件事务

| 动作 | 结果 |
| --- | --- |
| status（安装前） | 双 SI `BASELINE`，`JAVA_ARCHIVE: ABSENT`，`NAV_ACTIVE_IGNORE: RETAINED_BASELINE`，`TOKEN: ABSENT` |
| install | 独立 loader 通过；Java JAR、SI 依次 pending→校验→rename 提交；`MOUNTS_RESTORED: app=ro system=ro`；`NAVJAVA_install_FILES_PASSED` |
| status（完整重启后） | 双 SI `NAVJAVA_TRIAL`，`INGRESS_INSTALLED` |
| arm | `LISTENER_READY` 门禁通过，`ARMED_ONCE` |
| rollback | SI 恢复、新 JAR 移出扫描树、挂载恢复 ro，`NAVJAVA_rollback_FILES_PASSED` |

所有 action log 中 `CONTROL_EXIT=0`、`OUTER_EXIT_BEFORE_SD_CLEANUP=0`、`SD_INITIAL=ro`；两次 collect `COLLECT_EXIT=0`。

## armed（SI 917586 → DIO 4386877）

- 双 SI 为候选 `4083375225/7502`；`NavActiveIgnore.jar` 保持 `2960431692/2645`；新 JAR `2635590041/27941` 在位。
- DIO 原始环境含准确 marker、`LD_PRELOAD` 与私有 DIO 配置目录；`pidin mem` 有 `libcarplay_hook.so` 映射；SI 自身无 marker/preload/hook。SI 与 DIO 在采集前后身份一致，DIO 为 SI 直接子进程。
- 全局 gate receipt 恰好 1 个（修复后的枚举有效），内容 `ACTIVE_TOKEN_CONSUMED pid=4386877 ppid=917586`；token 已消费。
- hook：Identify 538→624 字节，`0x1D02` 接受，`0xAA05` 认证；5 次 `0x5200` 后首个 `0x5201` 停止重试；8 条 Update（状态 0/3/6）、6 条 Maneuver；Update 窗口 00:02:21.8–00:03:16.8。本路线无 Lane（`0x5204`）消息。
- 关联：hook bus `owner-pid=4386877` 并 `connected to Java server pid=4386877`，与 gate receipt 同一 DIO。
- Java：`SUBSCRIBED event=0x20` → `LISTENER_READY`（早于任何帧）→ `CARPLAY_ACTIVATION_OBSERVED` → frame 1–14 连续、`replay=0`、全部 `PARSE_OK`。route_state 0/3/6 与 hook 一致，最终为 6；frame 12 起目的地和转向距离字段存在；frame 13–14 有 2 个列出且带类型的转向槽位；`lane_slots` 始终为 0。

## restored（SI 933967 → DIO 1536120）

- 双 SI 回到原件 `535418540/7359`；新 JAR 不存在；`NavActiveIgnore.jar` 未变（rollback 另以 `cmp` 与备份逐字节比较通过）。
- 新 SI PID 与 armed 不同，父进程也变化，`/tmp` 下 verbose 标记、Java 与 hook 日志均不存在，采集时钟 00:00:44，符合完整重启。
- DIO 原始环境无 marker、无任何 `LD_PRELOAD`，无 hook 映射，全局 receipt 为 0。
- DIO PID 1536120 与 navhook 轮 restored 的 DIO 相同，说明本机启动过程 PID 分配高度确定；身份判定仍依赖环境、映射与父 SI，而非 PID。

## 与原通过条件的差异

合同审计要求“native `EMIT` 行”。hook 源码对 `EVT_RGD_UPDATE` 仅调用 `bus_send_text`，即使 verbose 也不记录逐帧日志，因此该条件本身不可满足。本审计以同一受控 DIO 的 bus owner/连接证据、Java 连续帧号与状态序列一致作为替代关联，不能做到逐帧 ID 对应。

## 仍未验证

- 车道信息经 Java 解析（本路线无 `0x5204`；仅 harness 覆盖）。
- 行驶中距离递减、改道、到达（本轮停车，仅 0/3/6）。
- 终端 `SD_MOUNT_RESTORED`/`OUTER_EXIT` footer 未随文件返回。
- 电话、Siri、音频、触控、Android Auto 回归仅为用户口头确认，日志无法证明。
- 替代 DIO 被动转发；arm 时存活 DIO 守卫修正（本轮 arm 时无 DIO，新检测路径未在车上触发）。
- BAP、renderer、VC/HUD 输出，NavActiveIgnore 隔离。
