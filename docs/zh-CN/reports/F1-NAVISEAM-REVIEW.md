# F1 NaviSeam v1 离线审阅（2026-09-24）

状态：**试验包就绪，未上车**。包 `MU1320-RGI-f1-naviseam-v1.zip`，SD 目录 `mu1320-f1-naviseam-v1/`，
身份见 [f1-trial-package.json](f1-trial-package.json)。

## 旧 NavActiveIgnore.jar 的实际作用（字节码核对）

两个类，与本车 JXE 转换的 `MU1320-base.jar` 对比：

- `org/dsi/ifc/carplay/AppState`：`getAppStateID()`、`getOwner()` 均为 `iconst_0; ireturn`。全库只有三处调用：
  `CarPlayAppState(AppState)` 构造、`DSICarplayListenerImpl.convertAppState`、`AppStateSerializer`。
  因此 CarPlay 进来的 **全部** app state（PHONE/NAVI/SPEECH）变成 ID 0，而 HMI 发给手机的
  `responseUpdateMode` 序列化时也被归零。
- `AndroidAuto2NavHandler`：`navFocusRequestNotification` 不再 `requestDSIUpdate(NAVI, DEVICE)`，直接回复
  PROJECTED；`updateNavFocus` 转回 NATIVE 时不再通知手机。用户不使用 Android Auto，F1 不携带此类（原厂）。

HMI 侧 ID（`IAppState`）：1 PHONE、2 NAVIGATION、3 SPEECH；`CarPlayAppState.mapAppIdCarplay2HMI` 对 1–3 为恒等。
`TMState.updateCurrentAppState` 跳过 null 和 ID 0（`aconst_null/if_acmpeq`、`iconst_0/if_icmpeq`）。
HMI 的 JAR 与 `lsd.jxe` 同在 `-Xbootclasspath`，`jars/` 在前（`lsd.sh` 392–434 行），同一加载器，因此单独覆盖
一个静态嵌套类不产生跨加载器的包访问问题。

## 替代实现

- `DSICarplayListenerImpl`（原厂 class SHA-256 `f7e92eec…1546`，major 49）只改 `convertAppState`：循环体开头
  插入 23 字节 `filter(appState[i])`，非 null 则存入结果并跳到自增，否则走原厂循环体。
  `max_locals` 5→6，仅两条跨插入点的跳转重定位，常量池只在末尾追加 6 项；其余方法逐字节不变
  （[f1-naviseam-bytecode.diff](f1-naviseam-bytecode.diff)，`tests/test_f1_seam.py` 复现校验）。
  采用字节码补丁而非重编译，是因为重编译外层类会重编号合成访问器与匿名类，必须整族替换。
- `NaviAppStateSeam`（Java 1.4，major 48）：ID 2 → `CarPlayAppState(0,0,0)`，其余返回 null；与上游 Stage2
  `convertAppState` 窄屏蔽语义相同。首次调用用 `new AppState(2,2,0)` 自检 getter 是否原厂并记录
  `stock_appstate_getters`；日志 `/tmp/mu1320-f1-naviseam.log` 上限 1000 行，异常全部吞掉。
- 不改 SI/DIO，不加载 native，不写 `/mnt/system`；安装 = 备份 → 新 JAR 提交 → 旧 JAR 同分区改名移入
  私有 `quarantine/`。每个中间态都等价于旧行为（有旧 AppState 时 seam 永不触发）或原厂行为。

## 主机验证

- HotSpot 1.8 `-Xverify:all` 差分测试 2681 项：400 组随机输入，非 NAVI 元素与原厂逐项相同，NAVI 为 (0,0,0)；
  原厂“设备占用 PHONE 时丢弃 SPEECH”语义保留；null 元素保持原厂 NPE；日志决策与输出一致、上限生效；
  旧 AppState 残留时输出与“仅旧 JAR”完全一致并记录 `stock_appstate_getters=0`。
- 事务测试 10 项：安装/采集/回滚/再采集、隔离副本损坏时从备份恢复、JAR 提交中断、隔离改名中断后续装或回滚、
  未知归档或旧 JAR 被改时写入前停止、残留 native 试验标记或非基线 SI 拒绝安装、payload 损坏、采集器识别残留旧 JAR。
  全项目 124 项通过。

## 限制

- 未在 J9 上验证；转换出的原厂 class 能否被 J9 按 jar 覆盖加载，由首行日志在车上证明。日志缺失即 F1 不成立，
  但此时车机行为退化为原厂（CarPlay 导航会接管 NAVI），属可回滚的功能差异。
- 原车 NAVI 行为是否与旧 JAR 相同、电话/Siri 在原厂 PHONE/SPEECH 处理下的表现，只能由实车人工观察确认。
- Android Auto 未测试（用户不使用）；恢复路径仍会放回旧 JAR 的 AA 修改。
