# Stage3 精简诊断复核

输入：`resource/private/vehicle-dump/stage3-diag-brief.txt`。BEGIN/END 均完整，无 SECTION_TRUNCATED；这次未发生上一轮系统日志挤掉前半部分的情况。

## 直接证据

- 两个 SI JSON 的 CRC/大小均为 `535418540 7359`，与原件一致，所打印 CarPlay 配置为 `dio_manager`、`/mnt/app/eso/bin/apps`。
- smartphone_integrator 的 real/effective/saved UID/GID 均为 0。
- 其环境为 `IPL_CONFIG_DIR_SMARTPHONE_INTEGRATOR=/etc/eso/production`，全局 `IPL_CONFIG_DIR=/etc/eso/production/`。
- wrapper 文件为 `-rwxr-xr-x 0 0`，`/bin/sh -n` 返回 0。
- 工作目录和 config 目录为 700/root，父目录 `/mnt/app/root` 为 644/root。不能仅凭父目录权限判断根因：已有 root 会话可以访问，SI 本身也是 root，而子进程凭据和启动方式仍待确认。不建议在证据不足时修改父目录权限。
- 本次按参数/名称检索仍只输出 SI，没有识别到 dio。上一轮 slog 明确记录基线 DIO 启动，因此这份快照不能支持“从未启动过 dio”的结论，也不能提供其实际环境。

## 尚不能确认

环境变量表达了配置目录设置，不单独证明 SI 的解析、配置合并、子进程路径构造、启动 API/flags 或失败后回退行为。wrapper 语法通过和可执行位存在也不证明 SI 实际执行过它。

目前没有直接证据确定 ENOEXEC、权限拒绝、配置被忽略或解析顺序中的哪一个是 Stage3 v1 失败原因。不能以任一猜测发行“已修复”的安装包。v1 arm 缺少强制 STAGE3_STOCK 验证仍是明确的独立缺陷。

## 下一份必要输入

本地只有 SI JSON，没有 MU1320 的 SI 可执行程序。下一步应静态检查实际程序的配置加载与子进程启动代码，停止重复同类三轮采集。

- 车机文件：`/mnt/app/eso/bin/apps/smartphone_integrator`
- 保存到工作站：`resource/smartphone_integrator`（不是 .json）
- 此次日志记录大小：798799 字节；QNX/POSIX cksum：3518254750。

通过现有只读文件下载方式提取即可，不执行该程序，不重新安装或 arm。拿到后先验证大小/CRC，再分析导入、配置字符串与启动调用点。
