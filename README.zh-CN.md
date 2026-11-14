# HONOR Watch 6 Plus 的 Gadgetbridge 配置与研究笔记

用 [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) 从
**HONOR Watch 6 Plus（Rome-B19C）** 上取全套健康数据，并导出成其他程序可直接消费的文件。

**英文版见 [README.md](README.md)。** 本文是中文版。

这里不放 Gadgetbridge 源码，也不放 APK，只放补丁、设备笔记和工具。

---

## 设备信息

| | |
|---|---|
| 手表 | HONOR Watch 6 Plus，型号名 `Rome-B19C` |
| 固件 | `20.1.0.114` |
| 手机 | HONOR Magic V6 `PNM-AN20`，Android 17 / SDK 37（MagicOS） |
| 连接方式 | BR/EDR RFCOMM（**不是 BLE**） |
| Gadgetbridge | 0.95.1（versionCode 255），上游 `master` 的提交 `6a322305`（2026-10-31） |

**固件版本很关键。** 下面的协议结论都是针对 `20.1.0.114` 得出的；固件不同，
服务与命令集可能不同。[`docs/reproduction.md`](docs/reproduction.md) 说明了怎么判断。

---

## 五步开始

```powershell
# 1. 取上游源码，切到精确的基线提交。
#    不要用 0.95.1 这个 tag：补丁是从三周后的 master 切出来的，
#    在 tag 上 arrays.xml / strings.xml 套不上。
git clone https://codeberg.org/Freeyourgadget/Gadgetbridge.git
cd Gadgetbridge
git checkout 6a322305eae857436e77b3a0f5b3ebc438b047e9

# 2. 打补丁
git apply --check /path/to/patches/all-changes.patch
git apply         /path/to/patches/all-changes.patch

# 3. 编译（Windows 的特殊处理见 docs/pitfalls.md）
$env:JAVA_HOME         = '<jdk21>'
$env:GRADLE_USER_HOME  = '<gradle-home>'
$env:ANDROID_USER_HOME = '<含正确 debug.keystore 的 android-home>'
tools\build-gb.ps1 -Project . -AndroidHome $env:ANDROID_USER_HOME

# 4. 安装
tools\install-gb.ps1

# 5. 配对，然后按 docs/reproduction.md 的五步验收
```

两个细节决定第 3 步能不能装：

- `ANDROID_USER_HOME` 里的 `debug.keystore` **必须**和手机上已装版本一致，
  否则报 `signatures do not match`。
- Windows 下 Gradle 删不掉某些目录，但**重命名可以**。
  `tools/build-gb.ps1` 已把这个重试逻辑自动化了。

---

## 能取到什么

| 数据 | 量级 |
|---|---|
| 活动样本（步数/卡路里/距离） | 每天约 3000 行 |
| 心率 | 每晚约 1200 行，60 秒一次 |
| 血氧 | 每晚 100～200 行，约 5 分钟一次 |
| 睡眠分期（浅/深/REM） | 每晚 10～30 行 |
| 逐拍 PPG（`sleep_data.bin`） | 每晚 2～3 万拍，60～110 KB |
| 电量、运动、用户与设备属性 | 变化时写入 |

导出结构（由打过补丁的自动导出 Worker 写到用户通过 SAF 选的目录）：

```
manifest-<yyyyMMdd-HHmmss>.json    schema 6：最后落盘；每文件的表名、去重键、列字典、校验和
<kind>-<yyyyMMdd-HHmmss>.csv       单表增量行（时间戳与同批 manifest 相同）
raw-sleep_data.bin                 未解码的 TruSleep 原始数据，稳定文件名，内容变了才重写
raw-rri_<yyyyMMdd>.csv             逐拍心跳流，一天一个文件
raw-capture_<yyyyMMdd>.csv         采集状态时间线（开流 / 关流 / 会话开始）
Gadgetbridge-<yyyyMMdd-HHmmss>.db  每日全量快照（可选）
```

超过 14 天的 manifest 和 CSV 由导出端自己删除；下游程序在这个目录里只读，不写、不删。

**下游程序只需要读这个目录**，不要 import Gadgetbridge 的任何类——
文件布局就是契约。

---

## 三条最值得看的发现

**① 打开 TruSleep 会让所有睡眠文件变成 0 字节**

```
trusleep = true   →  sleep_state.bin = 0 字节,  sleep_data.bin = 0 字节
trusleep = false  →  sleep_state.bin = 32 字节, sleep_data.bin = 105716 字节
```

手表会切到 Gadgetbridge 未实现的 `newSync` 协议，两个文件都返回空。
症状看起来像"睡眠数据不再更新"，而原因是一个名字听起来完全相反的开关。

**② 手表的蓝牙栈会卡死**

Gadgetbridge 一直显示"认证中"，日志里是
`read failed, socket might closed or timeout`。绑定和密钥都是好的。
**重启手表**立刻恢复——不用重新配对，不用重装。

**③ 探针会把数据抢走**

手表每个数据文件只发一次。如果诊断请求先取了 `sleep_data.bin`，
归档路径就只能拿到 0 字节。**同一个文件只允许一个消费者请求。**

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/protocol-findings.md`](docs/protocol-findings.md) | 核心参考：0x0A 与 0x2C 服务、类型字节枚举、能力表、逐拍格式，附证据 |
| [`docs/pitfalls.md`](docs/pitfalls.md) | 踩坑清单，每条给出现象、原因、解法 |
| [`docs/reproduction.md`](docs/reproduction.md) | 哪些值要换成自己的、哪些必须一致、五步验收 |
| [`docs/patches.md`](docs/patches.md) | 哪些补丁是生产必需、哪些是研究脚手架 |
| [`docs/upstream-baseline.md`](docs/upstream-baseline.md) | 0.95.1 基线、上游已修的 bug、如何重新套补丁 |
| [`docs/watch-files.md`](docs/watch-files.md) | 手表上的文件与含义 |
| [`docs/pipeline.md`](docs/pipeline.md) | 分析流水线 |
| [`docs/apnea-analysis.md`](docs/apnea-analysis.md) | 呼吸相关指标的定义与阈值 |
| [`docs/next-steps.md`](docs/next-steps.md) | 未完成事项 |
| [`docs/review-2026-11-14.md`](docs/review-2026-11-14.md) | 补丁代码评审：已修的问题、还要在真机上确认的问题 |

---

## 目录结构

```
docs/       设备笔记、协议发现、踩坑、复现验收
patches/    本地补丁（all-changes.patch 是合集）
tools/      PowerShell：编译、安装、带校验的 UI 自动化
decoders/   Python：逐拍解析、CVHR 与心率骤升分析
```

---

## 范围与免责

- **不是 AHI 测量。** 派生指标（CVHR 谷、心率骤升）只是生理负荷参考，
  不是诊断，也不能当作诊断来呈现。
- **与 Gadgetbridge 项目无关。** 这里的补丁是本地研究改动，不以这个形态提交上游。
- **单设备验证。** 只有一块手表、一台手机验证过。固件不同可能行为不同——
  `docs/reproduction.md` 里的验收步骤就是为了尽早发现这种差异。
- Gadgetbridge 是 AGPL-3.0。本仓库的补丁属于衍生作品，采用同样的许可证（见 [`LICENSE`](LICENSE)）。
