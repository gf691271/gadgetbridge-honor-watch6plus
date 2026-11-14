# 补丁清单

合集：`patches/all-changes.patch`（27 个文件，+3049 / -87）
应用：`git apply patches/all-changes.patch`
按提交拆分的版本：`patches/0001-local-research-patches-for-HONOR-Watch-6-Plus-GB-0.9.patch`

已用 `git apply --check` 在上游 2026-11-01 快照上验证可干净套用。

每个条目都标了 **生产必需** 还是 **研究脚手架**。
升级上游时，把「研究脚手架」全部删掉再重新实现。

---

## 生产必需（升级时也要保留）

### `database/DatabaseExportWorker.kt`
把数据库按表导出成 CSV + manifest，写到外部目录。

- 列名从 `PRAGMA table_info` 动态读取，**不硬编码**
- BLOB 列跳过；没有时间列的表也支持（`timeColumn = null`）
- manifest 带 `column_dictionary`（类型/非空数/基数/范围）、`data_quality`、
  `unique_keys`、`row_time_base`、`file_name_timezone`
- 游标存在 `<extFiles>/export_state.txt`（**不要用 SharedPreferences，Worker 里写不进去**）
- 完成后发广播（也 `setPackage("com.example.consumer")`）
- 常量：`SCHEMA_VERSION=5`（见下文 2026-11-14 的归档改造）、`KEEP_SNAPSHOTS=7`、`FULL_DB_EVERY_MS=24h`

**踩过的坑**：早期用 SharedPreferences 存游标，Worker 进程里写入不生效，
导致每次全量重导。

### `externalevents/PeriodicSyncScheduler.java` + `PeriodicSyncReceiver.java` + `res/xml/preferences_periodic_sync.xml`
定时同步，锚点 08:00，间隔 0/6/12/24 小时（pref `pref_periodic_sync_interval`）。

```java
Math.floorDiv(now - anchor, interval) + 1   // 算下一次触发
```

**踩过的坑**：GB 自带的 `TimeChangeReceiver` 每 ~43 分钟触发一次，
但它只调 `onSetTime()`，**不会拉数据**。所以必须自己实现同步调度。

### `activities/automations/AbstractAutoExportSettingsFragment.kt`
自动导出目录选择改成 `ACTION_OPEN_DOCUMENT_TREE`（可用），
每次导出生成带时间戳的新文件（`DocumentsContract.createDocument`），
不再覆盖同一个文件。

### `devices/huawei/packets/Workout.java`
修正 workout pace 表的字段映射（原来 `HUAWEI_WORKOUT_PACE_SAMPLE` 没有时间列，
导出成 0 字节）。

### `service/devices/huawei/HuaweiFileDownloadManager.java`
`createNotification` 里把 `sleepDataFileRequest` 的窗口放宽到 48 小时。

**为什么**：1.5 小时窗口返回 `size=0`，48 小时才返回真实数据。

---

## 研究脚手架（升级时删掉）

这些是为了搞清协议而加的，不是长期需要的。**它们会干扰正常下载流程**（见 pitfalls A2/A4）。

| 文件 | 作用 | 现状 |
|---|---|---|
| `requests/SendListCategoryProbeRequest.java` | 0x0A 按类别列文件名 | ❌ 已停用（会 NPE） |
| `requests/SendDebugFileListRequest.java` | 0x0A 列 debug 文件 | ❌ 已停用 |
| `requests/SendFileInfoProbeRequest.java` | 0x0A 问文件大小 | ❌ 已停用（返回值恒 0，不可信） |
| `requests/SendFileParametersProbe.java` | 0x0A 拿块参数 | ❌ 已停用 |
| `requests/SendBlockProbeRequest.java` | 0x0A 读块 0 | ❌ 已停用（ACK 成功但无数据） |
| `requests/SendRawFileProbeRequest.java` | 0x0A 原始取文件 | ❌ 已停用 |
| `requests/Send0ABlockSizeProbe.java` | 0x0A 全序列 init→params→block | ❌ 已停用（29 次以上，0x05 零返回） |
| `requests/SendUnknownServiceProbeRequest.java` | 探测设备支持但 GB 未实现的服务 | ❌ 已停用（返回错误码 100003/100007） |
| `service/devices/huawei/HuaweiSupportProvider.java` 里的 `probe*()` 方法 | 上述探针的入口 | 全部注释掉 |
| `service/devices/huawei/ResponseManager.java` 里的 `HRRRI_RAW` / `FILEDL0A_RAW` / `BLOCKACK` 等日志 | 抓原始包 | 保留无害，但会刷屏 |

**唯一要保留的「脚手架」**：

`HuaweiSupportProvider.enqueueFullSleepDump()` —— 每次同步把 `sleep_data.bin`
归档一份到 `files/dump/`。上游不会保存这个原始文件，而没有它就没法做逐拍分析。

它必须满足两条：
1. **在 `onFetchRecordedData()` 里调用**（不只是连接时），否则一天只抓一次
2. 真实数据文件**不能**出现在 `DEBUG_DL_CANDIDATES` 里，否则被探针抢走

---

## 补丁里被改动的文件总表

```
app/src/main/AndroidManifest.xml                                        改（注册 PeriodicSyncReceiver）
app/src/main/java/.../GBApplication.java                                改（启动并监听定时同步设置）
app/src/main/java/.../activities/automations/AbstractAutoExportSettingsFragment.kt   改
app/src/main/java/.../database/DatabaseExportWorker.kt                  改（重写归档逻辑）
app/src/main/java/.../devices/huawei/packets/FileDownloadService2C.java              改
app/src/main/java/.../devices/huawei/packets/Workout.java                            改
app/src/main/java/.../externalevents/PeriodicSyncReceiver.java                       新
app/src/main/java/.../externalevents/PeriodicSyncScheduler.java                      新
app/src/main/java/.../service/devices/huawei/requests/GetFileDownloadInitRequest.java 改
app/src/main/java/.../service/devices/huawei/requests/Request.java                   改（0x0A 发送侧旁路日志）
app/src/main/java/.../service/devices/huawei/requests/Send*Probe*.java               新 ×8
app/src/main/java/.../service/devices/huawei/requests/SetTimeRequest.java            改（记录设备时钟）
app/src/main/java/.../service/devices/huawei/HuaweiFileDownloadManager.java          改
app/src/main/java/.../service/devices/huawei/HuaweiSupportProvider.java              改
app/src/main/java/.../service/devices/huawei/ResponseManager.java                    改
app/src/main/java/.../util/DeviceClockTracker.java                                   新
app/src/main/res/values/arrays.xml                                                   改（定时同步选项）
app/src/main/res/values/strings.xml                                                  改
app/src/main/res/xml/preferences.xml                                                 改（定时同步入口）
app/src/main/res/xml/preferences_periodic_sync.xml                                   新
```

`Send*Probe*.java` 共 8 个，全部是**研究脚手架**，默认不参与运行（见下表）。


---

## 2026-11-13 新增（生产必需）

### 连接时重下发健康开关

`HuaweiSupportProvider.pushHealthSwitches()`，在每次连接后调用：

```
setHeartrateAutomatic()   → 自动心率
setSpoAutomatic()         → 自动血氧
setSleepBreath()          → 睡眠呼吸（与呼吸暂停直接相关）
```

**为什么需要**：Gadgetbridge 只在设置界面被改动时才下发这些开关。
如果 prefs 被清空或写了一半，数据会静默停止，而且没有任何提示。

日志标记：`HEALTHSW ... pushed`

### 忙碌状态看门狗

`HuaweiSupportProvider.startBusyWatchdog()`，每 60 秒检查一次 `gbDevice.isBusy()`。

一次失败的下载会把 busy 标记永久挂住，之后**所有同步都被
`Ignoring fetch activity data because we're busy` 挡掉**——实测挂过 2 小时。
看门狗在连续 10 分钟 busy 后强制 `unsetBusyTask()`。

日志标记：`BUSY_WATCHDOG task=... minutes=...`

### RRI 逐拍数据落盘与导出

`ResponseManager` 把 0x19/0x05 的实时包追加写入 `files/rri/rri_<yyyyMMdd>.csv`：

```
epoch_s,rri_ms,sqi
1794561784,745,100
```

`DatabaseExportWorker.copyRawBlobs()` 增加 `rri/` 目录，导出时复制为 `raw-rri_<date>.csv`。

**关键发现**：RRI **不走文件通道**。`rrisqi_data.bin` 恒为 0 字节，
数据只在实时流里出现（每次 143 字节）。所以必须自己落盘。

---

## 2026-11-14 新增（生产必需）

### RRI 只在 00:00–08:00（本地时区）开流

`HuaweiSupportProvider.insideRriWindow()` + `rriRepeat`：

```java
private static final int RRI_WINDOW_START_HOUR = 0;
private static final int RRI_WINDOW_END_HOUR = 8;
// Calendar.getInstance() 用设备默认时区，出国自动跟着走，不做 UTC 偏移换算
```

**为什么不是全天开**：实测开流白天 **2.5%/小时**，整夜只掉 **3%**。
白天开流等于每小时白扔 2.5% 电，换来的却是不戴表时的噪声数据。

**出窗口要主动关**：设备不会自己停流，到 08:00 必须发 `0x19/0x01 type=4` 关流
（`closeRriStream()`），否则光学传感器会继续跑一整天。
判断"流还活着"用的是 `lastRriPacketMs`（`ResponseManager` 每收一包就 `markRriPacket()`），
只有最近 120 秒真的收到过数据才发关闭命令，且 5 分钟内不重复发 —— 这样白天冷启动
不会发一个无人应答的关闭包。

日志标记：`RRI_STREAM_OPEN requested` / `RRI_STREAM_CLOSE requested` / `RRI_WINDOW outside window, closing live stream`

### 采集状态时间线 `files/rri/capture_<yyyyMMdd>.csv`

```
epoch_s,event
1794561784,session_start_outside_window
1794600002,open_requested
1794628803,close_requested
```

四个事件：`session_start_in_window` / `session_start_outside_window`（每次连接一行）、
`open_requested`、`close_requested`。

**为什么需要**：logback 的 appender 是 `lazy` + `immediateFlush=false`，进程被 `force-stop`
时最后几 KB 日志会丢；而这个文件每次 `write` 立即落盘。更关键的是它给了下游**"这段时间
本来应该在采"** 的证据 —— 没有它，RRI 序列里的空洞分不清是"没戴表"还是"没开流"。

### 原始文件归档改成内容寻址（export schema = 5）

原来的逻辑有三个坑，一次修完：

| 坑 | 现象 | 修法 |
|---|---|---|
| 靠目录列表判断"已归档" | 列表偶尔返回空 → 同名文件被 `createDocument` 建第二份 → `raw-rri_20261109.csv (1)` | 用 `treeId/name` 直接构造 document URI 探测，列表只当辅助 |
| 用文件大小判断"没变" | `sleep_data.bin` 每晚都是 105716 字节，换一夜也不变 → 归档永远是旧数据 | 改成 **SHA-256** 比较（`export_archive.json` 记 `name → sha256`） |
| 归档名带 per-request 时间戳 | 每次请求都是新名字 → 导出目录无限堆积，`pruneOld` 又被我来回删 | dump 快照名去掉 `_\d{10,}` 后缀 → `raw-sleep_data.bin` 稳定名，内容变了原地重写 |

另一个坑：`pruneOld("raw-", ".bin", 7)` 会把刚写好的稳定名文件当成"旧快照"删掉，
所以这行**删掉了**；旧格式 `raw-sleep_data_<epoch_ms>.bin` 由 `removeLegacySnapshots()`
一次性清理。

manifest 因此升到 **schema = 5**：新增 `raw_files`（当前归档全集，稳定命名），
`raw_files_new` 只列本次真正写过的。

### 0x0A 块读实验已关闭

`Send0ABlockSizeProbe.start(this)` 那行**注释掉了**。

`init → params → block` 全序列跑过 29 次以上，`0x0A/0x05` 一包都没回来；
而 0x0A 请求有可能被 0x2C 下载会话误认领，把那次同步整个搞崩（历史上的 NPE + 卡 busy 数小时）。
一次性的数据额度不值得再赌，留作手工实验。

