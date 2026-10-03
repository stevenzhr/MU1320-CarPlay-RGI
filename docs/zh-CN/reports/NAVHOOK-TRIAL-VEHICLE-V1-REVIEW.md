# MU1320 navhook oneshot 实车结果审计（2026-09-24）

结论：`NATIVE_RGI_RECEPTION_AND_RUNTIME_ROLLBACK_VERIFIED`。真实 DIO 中的一次性导航 hook 激活、Identify 修改、RGI 数据接收，以及回滚后新 DIO 的运行时恢复均有直接证据。本轮 native 数据接收目标已完成，无需重复 install/arm。Java 联调、renderer、VC/HUD 输出仍未验证。

输入为 `resource/private/vehicle-dump/navhook-v1-out/` 的全部 21 个文件。逐文件 SHA-256、采集核验和消息计数见 [机器可读记录](navhook-trial-vehicle-v1.json)。已用工作站 Python 断言核对两阶段的原始 environment、mem、processes 文件与 collect 内嵌内容完全一致，collect 与 action 日志一致，SI/DIO 查询前后身份一致，且均只观察到一个 DIO。原始输入未修改。

## 安装和一次性激活

- `action-install-20443263.txt`：既有私有工作目录验证通过，独立 loader 及五个符号解析通过，SI pending 写入及 rename 提交完成，`NAVHOOK_install_FILES_PASSED`；app/system 均恢复 ro。此输出符合 v1.2 接续流程；不依赖目录名称判断补丁版本。
- armed 采集时双 SI 配置为 `NAVHOOK_TRIAL`，CRC/大小均为 `458183461 / 7502`，与控制脚本固定候选一致。
- SI `938069` → DIO `4100164`，实时父子关系、children PID 文件及前后身份吻合。DIO 带准确 marker、私有 DIO 配置路径和 hook 的绝对路径 `LD_PRELOAD`，mem 映射含 `libcarplay_hook.so`。SI 自身无 preload 或 hook 映射。
- 该 DIO 的独立 receipt 为 `MU1320_NAVHOOK_V1_GATE mode=ACTIVE_TOKEN_CONSUMED pid=4100164 ppid=938069`，arm token 已不存在，hook BUS owner PID 同为 `4100164`。
- arm 动作开头的 `TOKEN: ABSENT` 是动作前状态输出，末尾的 `ARMED_ONCE` 表示成功；与之后 token 被消费不矛盾。

## 真实导航消息链路

`armed-4661392/carplay_hook.log` 共 57 行，与 collect 内嵌日志一致：

| 启动相对时钟 | 证据 |
| --- | --- |
| 00:02:08.556–00:02:09.027 | 捕获 stock Cinemo IAP；注册 routeguidance；lazy init；BUS owner 为当前 DIO |
| 00:02:09.105 | Identify 从 538 扩为 624 字节 |
| 00:02:09.326 / 00:02:09.678 | Identify accepted `0x1D02` / Auth complete `0xAA05` |
| 00:02:10.028–00:02:18.063 | 5 次 `0x5200` 请求，各有 stock SendIAP2 注入日志，session=1、len=24 |
| 00:02:21.869 | 首个 `0x5201` 到达，停止 `0x5200` 重试 |
| 00:02:22.369–00:02:22.378 | 6 条 Maneuver，3 组 Lane guidance，分别包含 7、3、3 条车道 |
| 至 00:03:40.577 | 共 6 条 Update，最后一条距首条约 78.7 秒 |

构建源 `private/navhook-v1-build/src/hook/routeguidance/rgd_hook.c` 将 Update/Maneuver/Lane 日志分别放在 `0x5201/0x5202/0x5204` 分支；因此三类接收均有证据。不是只有库加载或请求发出。日志已含道路、目的地及车道角度等解析字段；本报告不复制私人路线名称。

状态为 `0 → 3 → 6`；该版本 `rgd_tlv.h` 将 6 定义为 `PROCEED_TO_ROUTE`（前往路线）。当前道路为空与这一状态并不矛盾，不应判为 hook 失败。尚未覆盖实际沿路线行进、距离递减、重规划、到达等动态行为。

`lazy runtime init complete` 虽使用 WRN 等级，但内容是正常初始化完成；`STOP_LOCATION` 在本实现中被明确处理为位置流暂停，不是 CarPlay 断连。已返回日志未见 ERR、初始化重复或重连循环证据；这不等于完整连续稳定性或画面/触控/音频体验已经由日志独立证实。五个入口独立 dlsym 均通过，实际消息链路已运行，但未提供逐入口调用计数，不能宣称每个 interposer 都单独完成覆盖验证。

## 回滚和完整启动后的运行时状态

- `action-rollback-5443611.txt`：原 SI 写入与 rename 完成，`NAVHOOK_rollback_FILES_PASSED`，app/system 恢复 ro。
- restored 采集双配置均为 `BASELINE`，CRC/大小均为 `535418540 / 7359`，与固定原件一致。
- 新 DIO `1536120` 为 SI `938069` 的直接子进程，前后身份一致；原始环境无 marker、无任何 `LD_PRELOAD`，mem 无 hook 映射，该 PID 无 receipt，原厂 DIO 配置路径恢复。
- install/rollback witness、arm token、verbose 标记及 hook 日志均不存在。采集时钟由 armed 的 00:03:52 回到 restored 的 00:01:02，DIO 启动时间也回到 00:00。这些与完整启动一致；两轮 SI PID 恰好相同不能用来否定重启。运行时撤销的关键证据是新 DIO 已恢复干净环境和映射。

## 采集工具缺陷与证据边界

1. collector 顶部 `set -f` 禁用通配符展开，而全局 receipt 枚举仍使用 `/tmp/mu1320-navhook-v1-gate-*`，所以 `ALL_GATE_RECEIPTS` 在 armed 中也为空。按 PID 的直接读取不使用通配符，已正确保存有效 receipt，不影响本次激活及当前 DIO 恢复结论；全局空列表不能证明不存在其他历史 receipt。后续版本应修复枚举，本次保留已测试包及校验清单不变。
2. SD wrapper 的 `SD_MOUNT_RESTORED`、`NAVHOOK_TRIAL_ACTION_PASSED` 和最外层退出码仅打印到终端，不写入 action 日志。因此本批文件证实内部 collect exit=0 和 app/system 恢复 ro，不能单凭这些文件确认 SD 最终挂载状态。
3. 本轮有 token 消费及单次初始化实车证据，没有“启用 DIO 退出后替代 DIO 自动被动转发”的实车样本；该机制仍以既有代码审阅/主机测试为依据。
4. BUS 线程启动不证明 Java 接收，VC/HUD、renderer 和长期安装质量均不在本次通过范围。

下一阶段可进入 native → Java 导航消费与输出的受控联调准备，沿用现有 MU1320 兼容性与回滚约束；本报告不构成完整发行版就绪结论。
