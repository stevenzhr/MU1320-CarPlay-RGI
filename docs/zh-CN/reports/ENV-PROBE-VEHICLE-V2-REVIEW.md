# SI 环境标记实车结果：传递与运行时撤销均已确认

输入为 `resource/private/vehicle-dump/env-probe-v2-out/` 三个子目录及 env-probe-install.txt、env-probe-rollback.txt。审计脚本 `scripts/audit_env_probe_vehicle.py` 对比原始环境文件与 collect 中的完整环境，验证身份查询前后一致、父子关系、配置校验值；机器报告为 `env-probe-vehicle-v2.json`。

| 阶段 | 双路径 SI JSON | SI PID | DIO PID | DIO 标记 |
|---|---|---:|---:|---|
| before | 原件 535418540 / 7359 | 933942 | 1937532 | 无 |
| marked | 候选 2914261538 / 7401 | 925749 | 3829828 | 有 |
| 第一次 restored | 原件 535418540 / 7359 | 925749 | 5980228 | 仍有 |
| 完整启动后 restored | 原件 535418540 / 7359 | 925776 | 3784842 | 无 |

标记为 `MU1320_SI_PROBE=mu1320_env_v2_a7f907b7`。三轮 SI 父进程自身均无该项，DIO 的父 PID 都对应 SI，原始环境与 collect 完全一致，查询成功且身份稳定。因此 marked 是有效的 env 传递阳性；不能再把“MU1320 完全不用 SI JSON”作为结论。当前无需替换 dio_manager，也无需先跑独立解析探针。

## restored 为什么仍有标记

- 文件安装/撤销的日志均显示成功并恢复 app/system 为 ro；restored 的两个文件校验值也确实已恢复原件。
- marked 与 restored 的 SI 均为 925749、父进程 667703、启动时间显示 Jan 01 00:00。
- marked 采集时钟为启动后的显示值 00:03:13；restored 为 00:06:52。车机显示 1970 年，不能视为可靠绝对日期，只作为连续性辅助。
- restored 的 rollback RAM witness 仍存在；children.pid 中保留旧 DIO 3829828 和新 DIO 5980228。实际进程表只证明新 DIO 当前活着；PID 文件不是纯粹的当前存活名单。
- 新 DIO 的启动时间显示 00:06，仍收到标记。

这些证据支持：文件撤销后，旧 SI 仍使用已经读取的内存配置，即使 DIO 重建也会继承旧环境。完整启动后的补采中，双配置仍为原件，两个 witness 均消失；SI 变为 925776，DIO 3784842 于 00:03 启动，两者均无标记。运行时撤销闭环通过。

用户补充第一次 rollback 时可能没有断开 USB。它可能影响 DIO 的停止/重建时序，但不能完整解释旧结果：marked 的 DIO 是 3829828，第一次 restored 的存活 DIO 已变为 5980228，却仍从同一个 SI 925749 收到标记。关键证据仍是 SI 没有完整重启并保留了内存配置；这次完整启动后的无标记结果验证了该判断。

这个现象也提示原 Stage3 wrapper 试验的“文件已更新但 SI 仍用旧配置”值得重新考虑；它没有单独证明旧试验失败的根因。完整启动后的 restored 已补齐，无需重复本轮实验。

## 当前结论与下一步

普通 `carplay.envs` 的配置读取、SI→DIO 传递和撤销后的完整启动均已实车确认。无需再运行 env probe 或独立解析探针，也不需要替换 dio_manager。下一步可以设计只通过 `carplay.envs` 注入 `LD_PRELOAD` 的受控首测，但普通环境变量阳性并不等于动态库必然加载；首测仍需独立的加载证据、失败回退与文件撤销后完整重启要求。

## SD 卡采集的判断与后续约定

采集目录移到 SD 卡不改变 SI→DIO 环境传递，当前阳性判断不依赖日志存放位置。实际日志均记录 /fs/sda0/mu1320-env-probe-v2/out/...，完整性校验通过。车机 /tmp 是 shmem，不能建目录；之前要求在 /tmp 建日志目录是方案缺陷，后续不用这种布局。

用户报告 mount -uw /fs/sda0 后可写、结束 mount -ur 恢复只读。本地 Toolbox 的 util_mountsd.sh 确实对 /net/mmx/fs/sda0 或 sdb0 做 mount -uw；但它本身不包含只读恢复。后续采集默认采用 SD 卡保存，并在写入前处理该卡挂载状态、结束或失败时 sync 和恢复；不混同 SD 与 /mnt/app、/mnt/system 的挂载处理。

本次日志没有 SD remount 前后输出，不能声称已从日志验证恢复只读。工作站现有解压脚本与 v2 ZIP 一致，没有另外返回一份车机修改版，所以只能确认日志布局和结果完整，不能完整审计所述所有脚本修改。已发布 ZIP 保留不改，不为补一次采集重新发行安装包。

后续进入 [Stage4 加载验证](../preload-probe/README.md)；普通标记阳性不等于库已加载，且移除配置后必须让 SI 重新读取，不能只断开重连手机。
