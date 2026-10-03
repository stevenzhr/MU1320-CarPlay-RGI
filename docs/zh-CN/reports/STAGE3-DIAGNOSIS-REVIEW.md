# Stage3 基线诊断日志复核

核对文件：`stage3-diag-before-connect.txt`、`stage3_diag-connected.txt`（此文件用下划线）、`stage3-diag-disconnected.txt`。三份均找到了，未改名或覆盖用户输入。

## 可以确认

- 连接日志第 208 行：约 00:05:05.979，SI 记录 `First connect`、CARPLAY。
- 第 209 行：约 00:05:06，DIO_MAIN 明确报告 `DIOManagerApp with pid=4784250 started`。
- 第 412 行：约 00:05:08.758，AirPlay 记录 session started。
- 第 421 行：SI 记录 STARTED/CARPLAYVERIFIED。
- 断开日志第 373、482、504 行：约 00:07:10–12，停止屏幕会话、tear down、SI DISCONNECTED。

这些是 rollback 后基线测试的证据，支持用户所述 USB CarPlay 正常。不能将其当作此前 Stage3 已加载 hook 的证据。此前一次 pidin 快照没有 dio_manager，也不能解释成整个测试期间从未启动该进程。

## 缺少的证据

三份文件全部缺少 `STAGE3_READONLY_DIAG_BEGIN`、权限/校验、进程快照、SI/DIO 身份及环境等标记，却保留结束标记。连接文件开头为半截文本 `quested for rdiserverApp`。现有文件因此只包含系统日志的尾部，而非完整脚本输出；很可能是完整 sloginfo 输出挤掉了终端滚动缓冲，但仅凭文件无法确定截断发生在何种工具里。

旧采集器一次输出完整 sloginfo，输出设计不合适。不能声称已经确定 SI 配置来源、wrapper 启动权限、spawn 的脚本支持方式或实际错误码。系统日志中未找到能直接归因 wrapper 启动失败的错误；日志另有 dropped-messages 提示，错误缺席也不能排除失败。

EHCI 和 mDNS 错误出现于用户报告正常的基线连接过程中，现有证据不能把这些行当作 Stage3 故障根因。

## 最小下一步

当前保持已恢复的原配置。只需在 USB CarPlay 正在运行时执行 `preflight/stage3_diagnose_brief.sh` 一次，保存 BEGIN 到 END；不必再采集三个阶段，不 install、不 arm、不 remount、不重启。新脚本只保留相关进程、身份、配置环境和权限，不输出 sloginfo，并给长段设置行数上限。

Stage3 v1 缺少强制 stock-wrapper 证明的 arm 检查仍是已确认的独立脚本缺陷，但它解释的是为何误放行，尚不能解释 wrapper 为何没被观察到。定位前不发行声称已经解决启动问题的 v2 安装包。
