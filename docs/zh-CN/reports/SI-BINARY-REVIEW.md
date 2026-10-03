# MU1320 SI 二进制复核与下一步

**后续决策更新：** 用户选择先进行 [环境标记对照实验](../env-probe/README.md)，直接验证修改的 carplay.envs 是否进入实际 DIO。下面独立解析探针保留为必要时的辅助路径，目前不要求先运行。标记阴性不等于整个 SI JSON 路线不可行；阳性也不直接授权持续 LD_PRELOAD。

2026-09-23。`resource/smartphone_integrator` 大小 798799、POSIX cksum 3518254750，与车机记录一致。SHA-256 和底层库身份见 `si-analysis-inputs.json`。使用 `scripts/inspect_si_binary.py` 生成带调用符号的 ARM 反汇编证据，不执行车机程序。

## 已确认的静态行为

1. SI 在 0x137f28 调用 `util::config::Provider`，名称为 `smartphone_integrator`，目录参数 NULL、解析参数 500、LoadStrategy=0。`libutil.so` 的 Provider::init 在 0x2be98 开始：先检查 `IPL_CONFIG_FILE_SMARTPHONE_INTEGRATOR`，随后组合组件目录/全局目录，检查 `IPL_CONFIG_STRATEGY`；无覆盖且 strategy=0 时选择 `.json`。这不支持“默认必然忽略 JSON、优先 BCF”的解释。进程环境中已有组件目录 /etc/eso/production。
2. SI 配置表为 CarPlay exec 保存默认 `dio_manager`；0x16ce40–0x16ce60 读取编号 0x5f、0x60、0x61 对应 exec/path/params。通用 getter 0x137a08 在 Provider 可用且键存在时读取 JSON，否则保留初始化默认值，并缓存已经读取的项。文件后来显示 Stage3，不等于运行中 SI 缓存也已变化；但现有日志也不能证明发生过回退。
3. SI 的启动路径包含 `osal::ProcessTNG::setExecutable` (0x189fe8) 和 `start` (0x18a3e0)。所采集 `libosal.so` 的 startChild 在 0x51ef0–0x51efc 初始化 flags=0x00040002，再按需要 OR 其他位，0x51ff8 调用 spawn。工具链 QNX spawn.h 定义 SPAWN_CHECK_SCRIPT=0x00040000，因此“底层完全不允许 shell 脚本”的猜测不成立。官方语义见 [QNX 6.5 spawn](https://www.qnx.com/developers/docs/6.5.0SP1/neutrino/lib_ref/s/spawn.html)。仍不能据此证明某次 wrapper 成功运行。
4. 不能单凭 /mnt/app/root 的目录权限认定根因，不修改该目录权限，不替换原 dio_manager，不增加全局 LD_PRELOAD。

## 当前结论

尚未确定 Stage3 v1 无 wrapper 日志的根因，不能发行声称修复成功的 Stage3 v2 安装包。可能需要区分：原生解析失败/默认值回退、SI 进程使用既有缓存、真实子进程启动失败或日志观察缺口。静态证据已排除部分过早假设，但不能代替进程运行时证据。

下一步提供 `MU1320-RGI-si-config-probe-v1.zip`：只在 /tmp 独立运行小型读取器，使用本车 libutil 分别解析基线与候选文件，不启动 SI/DIO，不 install/arm。同时读取 SI 子进程 PID 文件，避免继续完全依赖 argv 名称筛选。操作见 `si-probe/README.md`。

探针的私有 ABI 来自固定库：Provider 分配 28 字节，valid 在 +4、Dictionary 在 +8、format 在 +24；Dictionary 和 ValueString 校验具体 vtable，再调用导出的查找/字符串复制方法。ValueString::get 在 0x2f0a0–0x2f17c 返回的是 0 表示成功，不是布尔 true。原生探针经过交叉编译和 ELF/导出检查，尚未在车机运行。

若两份文件都能正确解析，解析器兼容性将得到独立验证，仍需在下一版安装试验中强制执行“未 arm 时先观察 STAGE3_STOCK”的门槛，并记录安装前后 SI/PID 与实际子进程。若候选失败，先修配置再制作安装包。无论哪种情况，不将采集脚本 exit=0 计作 hook 成功。

Stage3 v1 缺少强制 STAGE3_STOCK 的 arm 门槛仍属明确缺陷；旧包和旧结果保留，不在当前未安装状态运行 arm。
