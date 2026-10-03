# MU1320 preload-probe v1.1 实车审计

结论：`children.carplay.envs` 中的绝对路径 `LD_PRELOAD` 已在真实 `dio_manager` 中生效。当前证据验证的是测试库加载，不是导航 hook 的拦截能力。

marked 阶段两个 SI 配置均为候选 CRC `2782255039`、大小 `7484`。存活的 DIO PID `3317787` 是 SI PID `925747` 的直接子进程，启动时间为 00:01，采集前后身份不变。其原始环境同时包含：

```
MU1320_SI_PROBE=mu1320_preload_v1_b81d024a
LD_PRELOAD=/mnt/app/root/mu1320-preload-probe-v1/libmu1320_preload_probe.so
```

同一进程的 constructor 凭据为 `MU1320_PRELOAD_V1_LOADED pid=3317787 ppid=925747`，PID 和父 PID 与当前进程表完全吻合；`pidin mem` 还列出被列宽截断的 `0_preload_probe.so` 映射，大小为 code/data 各 4096。环境、库内代码生成的凭据和进程内存映射三条独立证据一致，因此可以排除“只有 env 传入但库未加载”。CarPlay 在本阶段能够正常使用的用户反馈，则支持这个 load-only 库没有破坏已观察到的基本功能。

before 阶段 DIO PID `2990218` 同样是 SI 的直接子进程，但没有 marker、LD_PRELOAD、凭据或测试库映射，是有效阴性对照。安装前的独立加载也通过；install/rollback 均验证 app/system 初始为 ro、结束恢复 ro，文件操作成功。

撤销方面，第一次 restored（`restored-2228365`）确认两个 SI 配置都恢复原件 CRC `535418540`、大小 `7359`，两个 RAM witness 消失，SI PID 变为 `925775`，支持 rollback 后发生过完整启动；但当时尚无 DIO，所以只作为启动早期快照保留。

补采的 `restored-2482322` 完成运行时对照：children PID 文件指向 `2138241`，该 DIO 是同一 SI `925775` 的直接子进程，身份查询前后稳定；其环境没有本轮 marker 和 LD_PRELOAD，凭据为 `NO_RECEIPT`，完整内存映射没有 `0_preload_probe.so`。双配置仍为原件，witness 仍不存在。由此排除“文件已恢复但 SI 仍向新 DIO 传递缓存 preload”的情况。

当前状态为 `PRELOAD_LOADING_AND_RUNTIME_ROLLBACK_VERIFIED`。本轮无需再采集或操作车机，安装目录保留供追溯。

这轮阳性已经解决原 Stage3 最核心的接入不确定性：无需 wrapper，也无需替换 `dio_manager`，真实 hook 可通过 SI 的 `carplay.envs` 注入。下一阶段仍需要对导航专用 `libcarplay_hook.so` 做受控实车加载和拦截验证；preload-probe 本身没有导出 Cinemo/NME interposer，也没有处理 0x52xx 导航消息，不能据此宣称 Stage3 原目标完成或 VC/HUD 已可部署。
