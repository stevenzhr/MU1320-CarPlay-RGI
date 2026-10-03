# F1 v2 实车审计（2026-09-25）

结论：**F1 通过（附限制）**。状态 `F1_V2_NAVI_SEAM_AND_ROLLBACK_VERIFIED`，判定由
`scripts/audit_f1_v2_vehicle.py` 从原始文件重算，输出 [f1-v2-vehicle.json](f1-v2-vehicle.json)（含全部输入 SHA-256）。
输入目录 `resource/private/vehicle-dump/f1-navi-v2/`。

## 文件事务

- 安装前 status 为 `INSTALLATION_BASELINE`；install 在全新工作目录 `/mnt/app/root/mu1320-rgi-f1-v2` 完成备份 →
  提交 `CarPlayRGI-MU1320-F1NaviV2.jar` → 旧 JAR 移入 `quarantine/`，`CONTROL_EXIT=0`。
- rollback 走“隔离件移回”路径，再把 F1 JAR 移出扫描树，`CONTROL_EXIT=0`；终端尾部各动作 `OUTER_EXIT: 0`、SD 恢复 ro。

## F1 安装后（完整重启后的启动）

- install witness 不存在，说明安装后完整重启过；`HMI_ARCHIVES` 中有 F1 JAR（cksum 3095502315/23735），没有
  `NavActiveIgnore.jar`；SI 双路径为原件；DIO 4038725（父 SI 917586）无 `LD_PRELOAD`；无 javacore，sloginfo 中无
  VerifyError/LinkageError/NoClassDefFound 等。
- CarPlay 会话正常建立（`session started`、SI `STARTED`），Audi smartphone 未卡住。v1 的故障没有复现。
- AirPlay `Modes changed` 时间线（开机后计时）：
  - 03:47 `turns controller`：CarPlay 开始导航。用户观察：原车导航/VC 地图未被接管。旧 JAR 已不在加载路径，若替代
    未生效，原厂 `TMState` 会把 NAVI 交给设备，因此该观察即窄替代生效的证据。
  - 04:16 `turns accessory`：原车新开路线，CarPlay 导航被收回；与用户记录的旧 JAR/回滚后行为一致（F5 议题）。
  - 04:35 `turns controller`：原车有路线时 CarPlay 再次开始导航，用户观察原车路线继续。
  - 04:51–04:57 `speech controller (speaking/recognizing)`：Siri；HMI 现按原厂处理 SPEECH，用户观察正常。
  - 05:03 USB 拔插，05:13 新会话，导航所有权恢复为 `controller`。
- 用户观察 1–6 项全部正常，与旧 JAR 基线一致。

## 回滚后

- 开机计时从 328 s 回到 185 s，SI PID/父进程均变化，rollback witness 不存在，说明完整重启过。j9 PID 两次都是 782375，
  本机 PID 分配高度确定，不以 PID 判断是否重启。
- 归档集合恢复为安装前（含原 `NavActiveIgnore.jar`，无 F1 JAR）；CarPlay 会话正常；DIO 3227786 无 preload。

## 限制

- 窄替代没有逐次日志；NAVI 行为依据人工观察 + AirPlay 所有权时间线 + 重启后的归档集合。
- 采集的 F1 启动内没有 AirPlay `phone` 模式记录；电话项只有用户确认，可能在采集窗口之外进行。
- 回滚后只记录到一段短会话；回滚列观察为用户确认。
- Android Auto 未测试（用户不使用）。
- 采集器小问题：车机 `grep -c ''` 未输出行数（`lines=` 为空），不影响文件保存。
