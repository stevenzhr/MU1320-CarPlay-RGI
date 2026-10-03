# 安装、使用与回滚

前提：搭载 **MU1320** 的奥迪 MHI2Q 主机；root SSH 可用（先用车载热点验证一次冷启动登录）；FAT 格式 SD 卡；有线 CarPlay；
[building.md](building.md) 里的构建输入。停车并保持稳定供电。**不要运行 `dmdt ts`。**

## 1. 准备 SD 卡

```sh
python3 tools/assemble_toolbox_v1.py --output build/mu1320-toolbox-v1
python3 tools/assemble_f8.py --inputs <你的输入目录> --output build/mu1320-f7-daily-v2.1
```

- 把 `build/mu1320-toolbox-v1/` 的**内容**复制到 SD 根目录（替换旧的 `Toolbox/` 和 `metainfo2.txt`，`Custom/`、`Backup/`、`Log/` 不动）。
- 把 `mu1320-f7-daily-v2.1/` 整个文件夹复制到 SD 根目录。带 `TOOLBOX-ENTRY` 的 `mu1320-f7-*` 文件夹**只能有一个**，否则菜单显示 `2 F7 FOLDERS`。
- macOS 上清理元数据：`dot_clean -m /Volumes/<SD>`，再 `find /Volumes/<SD> -name '._*'` 应无输出。

## 2. 安装 Toolbox v1（一次）

按住 **MENU** 进服务界面 →「Software updates/versions」→「Update」→ 选 SD →「MQB Coding MIB2 Toolbox」，让它完整跑完（会重启几次）。
之后 `Customization > MU1320 RGI` 里有五个按钮。更新不影响 SSH，请确认仍能登录。

## 3. 安装补丁

1. **1 Status**：应为 `SI: BASELINE/BASELINE`、`JAVA: ABSENT`、`RESULT: OK`。出现任何 `UNKNOWN` 就停止。
2. **2 Install**：等到 `F7_install_FILES_PASSED` 和 `RESULT: OK`（30–60 秒）。
3. **完整重启** MMI。**1 Status** 应显示 `SI: F7_TRIAL/F7_TRIAL`、`JAVA: F7_INSTALLED`、`LISTENER: F7_READY`。
4. USB 连接 CarPlay，在 Apple Maps 或 Google Maps 里开始导航。

监测运行期间 SD 卡一直插着。取卡只在锁车、MMI 屏幕关掉以后，拷完 `out/` 马上插回。

## 按钮

| 按钮 | 作用 | 说明 |
| --- | --- | --- |
| 1 Status | 只读摘要 | 完整输出在 SD 的 `out/action-*.txt` |
| 2 Install | 安装，之后**完整重启** | 不是原厂基线则拒绝 |
| 3 Uninstall | 恢复原厂文件，当场停 renderer 和 BAP，之后**完整重启** | |
| 4 Collect | 快照到 `out/snapshot-<pid>/` | 觉得有异常时，锁车前先按一次 |
| 5 EMERGENCY STOP | 关 BAP、停 renderer，几秒内回原厂显示 | 重启后补丁恢复 |

屏幕最多显示约 10 行，最后是 `Log:` 和 `RESULT: OK|FAILED`。看到 `RESULT` 再离开页面。一个动作运行时再按会显示 `BUSY`。

## 回滚与恢复

- 正常：**3 Uninstall** → 完整重启 → **1 Status** 显示基线。要同时删除工作目录，**重启后**用 SSH：`/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh purge`（没重启会拒绝）。
- 菜单不可用：SSH 执行 `/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh rollback`。
- 箭头或地图框错乱、VC 黑块：**5 EMERGENCY STOP**，再正常重启。
- HMI 黑屏、循环重启、CarPlay 反复重连、音频/倒车影像异常：不要再连 USB；能按就先 **4 Collect**，再 **3 Uninstall** 并重启。
  HMI 完全起不来时用 SSH（测试车上冷启动热点登录可用）——这条路径在 HMI 损坏时**没有验证**。
- 怀疑监测有影响：`f7.sh off monitor`（永久），或 `touch /tmp/mu1320-f8-mon-off`（本次开机）。

## SSH 命令

```sh
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh status|install|stop|rollback|purge
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh collect live|snapshot|restored
/bin/sh /fs/sda0/mu1320-f7-daily-v2.1/f7.sh off|on native|render|bap|touchpad|monitor
```

（SD 在第二个卡槽时用 `/fs/sdb0`。）`stop` 和 `rollback` 会写 `/tmp/mu1320-f5-bap-off`，所以 BAP 到重启前都不会恢复。
