# Toolbox 只读清点 v1 实车结果

- 日期：2026-09-27
- 包：`mu1320-toolbox-inventory-v1`（只读，未改动车机）
- 证据：`resource/private/vehicle-dump/toolbox-inventory-v1/`（`action-run-3063834.txt`，`tbinv-3162251/`）

## 运行结果

`TOOLBOX_INVENTORY_COMPLETE`，`CONTROL_EXIT=0`，SD 原为 `ro`。`manifest.txt` 共 1874 行。
拷出 829 个文件（1.1 MB），`COPY_ERRORS=0`、`COPY_SKIPPED=0`。节点为 `mmx`，训练版本 `MHI2Q_US_AUG22_P4246`，MU 1320。
`MANIFEST_LINES` 本次用 `while read` 计数，正常输出。

## 车上的 Toolbox 是哪一版

车上装的不是上游 `mib2-toolbox` 原版，而是 **Lanye 的 `MHI2Q-CarPlay-RGI-MMI-Mirror` 发行版**。换行统一后逐字节比对：

| 比对对象 | 相同 | 不同 | 车上多出 |
| --- | --- | --- | --- |
| 本地 `MHI2Q-CarPlay-RGI-MMI-Mirror`（HEAD `441c150`）的 `Toolbox/GEM` + `Toolbox/scripts` | 143 | 0 | 2（`scripts/mqb/sbin/._bc`、`._cmp`，macOS 拷卡留下的 AppleDouble 文件） |
| 本地上游 `mib2-toolbox`（`af244e7`） | 126 | 0 | 19（Lanye 的 17 个 RGI 与 MMI Mirror 页面和脚本，加上 2 个 `._*` 文件） |

两个仓库里的文件车上都有，没有缺失。所以车上状态 = 上游 `af244e7` + Lanye 的 17 个文件 + 2 个 macOS `._*` 文件。（初稿写成「Lanye 的 19 个文件」，把 2 个 `._*` 也算了进去，已更正。）
`mqb-main.esd` 版本行为 `4.2A`，与上游相同。`engdefs` 下共 152 个 `.esd`，其中 36 个 `mqb-*`，其余为原车页面；`scripts/` 下 510 项为原车脚本。

Lanye 的功能只有菜单，**没有安装过**：`/mnt/app/root/hooks/` 为空，没有 `/mnt/app/root/mmi-mirror/`，`scripts/mqb/` 下没有
`.mmi_mirror_autostart` 标记，进程里也没有 Mirror 或 RGI 进程。

SWDL 记录 `FileCopyInfo/Toolbox.info` 只有一条：`mqb-main.esd` 的路径和 CRC。其他 `.info`（Eggnog、NavDB、Speech、Truffles）属于原车。

## SSH 的实际装法

与上游 `sshd_install.sh` 完全一致：

- `scripts/ssh/`（2 项：`etc`、`usr`），sshd 和主机密钥在这里；只列清单，没有拷贝。
- `inetd.conf` 与 `.bu` 相比只多了一行 `ssh ... scripts/ssh/usr/sbin/start_sshd in.sshd`。
- 四个 `pf*.conf` 都加了 22 端口规则。`pf.ecm0.conf` 里有两段，原因是原文件有两处 `port domain`，上游的 sed 在两处都插入了；不影响使用。
- `/mnt/app/root` 下有 `.profile`、`scp`、`.ssh/authorized_keys`。
- 进程：`inetd` 常驻，本次 SSH 会话由 inetd 拉起 `start_sshd` → `sshd -i`。

结论：Toolbox 的 SWDL 更新只向 `scripts/mqb/` 和 `engdefs/*.esd` 增量复制，**不会碰到这台车的 SSH**。只有 Toolbox 的「Uninstall」会移除 SSH。

## SD 卡

- Toolbox 安装包在 `/fs/sda0`（`Toolbox/`、`metainfo2.txt`、`Custom/`、`Backup/`、`Log/`），`/fs/sdb0` 不存在。
- SD 根目录有 macOS 留下的 `._*`、`.Spotlight-V100`、`.Trashes`，这就是 `._bc`/`._cmp` 被装到车上的原因。
- 还有一个 0 字节、类型为 `n`（QNX 具名特殊文件）的 `=TOOLBOX`，来源不明，本次不处理。

`/mnt/app/root` 下还留着 `mu1320-rgi-f5-v1`…`v5` 和 `mu1320-rgi-f6-v2` 工作目录（阶段回滚会留下），以后清理时要重新清点。

## 对 F7 v2 的影响

1. **页面挂载方式**：从 Lanye 页面的写法看，GEM 页面靠自己文件里的 `screen "<名称>" <父页面>` 挂到父菜单下（例如 Lanye 页为
   `screen "CarPlay Route Guidance" Customization`），不需要修改任何现有页面。F7 页面只需要新增一个 `.esd` 和脚本。
2. **底版**：按计划用上游 `mib2-toolbox`（固定 `af244e7`）+ 本项目叠加层。因为 SWDL 是增量复制，以上游或 Lanye 版为底，
   车上结果相同：Lanye 的 17 个文件都会留在车上。
3. **Lanye 的 RGI 页面有冲突风险**：「CarPlay Route Guidance」里的安装按钮会把 MU1316 hook 装到 `/mnt/app/root/hooks`，
   并用 awk 改 `dio_manager.json`，与本项目冲突。要不要在自制 Toolbox 里移除 Lanye 的两个页面及其脚本，需要用户决定。
4. **拷卡前清理**：制作 SD 时要去掉 AppleDouble 文件（`dot_clean` 或组装脚本检查），避免 `._*` 被装进车。
5. **回退**：车上已装的文件与本地 `MHI2Q-CarPlay-RGI-MMI-Mirror` 克隆一致，所以用这个克隆可以重新做出回退包（SD 上的安装包本身未比对）。
   `tbinv-3162251/copy/` 里另有车上 Toolbox 文件和 `inetd.conf`、`pf*.conf` 的完整备份。

## 用户决定（2026-09-27）

- 起点是上游 `mib2-toolbox`。Lanye 版只参考它怎样借 Toolbox 部署（SWDL 包结构、`metainfo2.txt`、页面挂载），不照搬它的 CarPlay Route Guidance 页面和脚本。
- 以后用一次自制 Toolbox 的更新覆盖车上的 Lanye 版。
- 没有使用 MMI Mirror 的计划。

SWDL 只增量复制，所以覆盖本身不会删掉 Lanye 的 17 个文件。要清掉它们，自制 Toolbox 的安装脚本需要单独删除：按本次清单锁定文件名和 cksum，只删除校验一致的文件，同时删除 `._*` 文件；不碰 `scripts/ssh/`、`/mnt/system` 和 `/mnt/app/root`。
