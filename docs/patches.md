# 补丁清单

合集：`patches/all-changes.patch`（36 个文件，+4423 / -99，包含 0001–0016）
应用：`git apply patches/all-changes.patch`
按提交拆分的版本：`patches/0001-*.patch`（5 个提交）+ `patches/0002-*.patch`（2026-11-14 评审修复，1 个提交）
+ `patches/0003-*.patch`（2026-11-15 类型映射 / 队列 / 单次下载，1 个提交）
+ `patches/0004-*.patch`（2026-11-15 研究用：能力位 dump / 类型字节扫描 / dict 睡眠，1 个提交）
+ `patches/0005-*.patch`（2026-11-16 链路静默死亡的检测，1 个提交）
+ `patches/0006-*.patch`（2026-11-16 保活闹钟：15 分钟只做重连，1 个提交）
+ `patches/0007-*.patch`（2026-11-16 只在通道真的安静时才重发开流，1 个提交）
+ `patches/0008-*.patch` 到 `patches/0016-*.patch`（2026-11-16 到 11-22，各 1 个提交，说明见下面各节），
用 `git am` 按顺序套，结果与合集逐字节一致（2026-11-22 重新生成合集时验证过）。
注意：`0004` 文件里的第 1 个提交就是 `0003`，套到这里会报冲突，用 `git am --skip` 跳过它再继续。

基线是上游 `master` 的提交 `6a322305eae857436e77b3a0f5b3ebc438b047e9`（不是 `0.95.1` tag，见
[`upstream-baseline.md`](upstream-baseline.md)）。已在这个提交上验证 `git apply --check` 通过。

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
- 完成后发广播（也 `setPackage("com.evolve.mailuo")`，常量 `CONSUMER_PACKAGE`）
- 常量：`SCHEMA_VERSION=6`（见文末「2026-11-14 评审修复」）、`KEEP_SNAPSHOTS=7`（只管 `.db` 快照）、
  `KEEP_BATCH_DAYS=14`（manifest 和 CSV）、`FULL_DB_EVERY_MS=24h`

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
| `HuaweiSupportProvider.enqueueProbeDownloads()` | 每次同步用 0x2C 把 17 个文件 id 全请求一遍，只打日志、丢弃数据 | ❌ 2026-11-14 评审时发现**仍在每次同步里无条件运行**，已用 `RESEARCH_FILE_PROBES = false` 关掉（见文末） |
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

---

## 2026-11-14 评审修复（`patches/0002-*.patch`，export schema = 6）

完整的评审记录、验证方法和还没解决的问题见 [`review-2026-11-14.md`](review-2026-11-14.md)。这里只列代码改了什么。

### 采集侧

| 文件 | 改动 | 为什么 |
|---|---|---|
| `HuaweiSupportProvider.onFetchRecordedData()` | `enqueueProbeDownloads()` 用 `RESEARCH_FILE_PROBES = false` 关掉 | 这个 17 文件扫描里有 `sleep_state.bin`、`sleep_data.bin`、`rrisqi_data.bin`，回调只打日志就把数据丢了。每次同步真实数据被多下载一遍，还多发 14 个设备会回错误或 0 字节的请求。本文档上面写着「探针会把数据抢走」「同一个文件只允许一个消费者」，它正好违反了这两条 |
| `HuaweiSupportProvider.enqueueFullSleepDump()` | 空数据不存；和最新一份逐字节相同就不再存；`files/dump/` 只留最新 5 份 | 原来每次同步存一份约 100 KB 的副本，永不清理；`fr.getData()` 为 null 时在 try 外面抛空指针 |
| `HuaweiSupportProvider` 忙碌看门狗 | 只对同一个 busy 任务累计分钟数；`dispose()` 里停掉看门狗和探针定时器 | 原来不同任务接力占用 busy 也会被累计，10 分钟后误清；每次重连都多留一个在已销毁对象上空转的定时器 |
| `ResponseManager.appendRriToFile()` | TLV 长度按 VarInt 读；`sqi = 0` 的拍也写入 | 一包 15 条记录（135 字节）时长度占 2 字节，原来的解析会把整包丢掉；丢掉 sqi=0 的拍会打断逐拍序列，过滤应该留给下游 |
| `GBApplication.onCreate()` | 定时同步的启动挪到 `prefs` 初始化之后；监听器存进静态字段 | 原来启动时 `getPrefs()` 还是 null，异常被吞掉后永远按默认 6 小时排，「关闭」设置在每次进程重启后失效；监听器没有强引用会被回收，改设置不再生效 |

### 导出侧（manifest schema 5 → 6，只加字段，`unique_keys` 的内容被纠正）

| 改动 | 为什么 |
|---|---|
| 一次导出只取一个时间戳 `batch`，manifest 和所有 CSV 共用 | 原来每个文件各调一次 `stamp()`，跨秒时同一批会分成两个时间戳 |
| manifest 先写 `manifest-<stamp>.json.tmp` 再改名；改名失败退回直接写 | manifest 出现就等于整批写完，下游不用靠修改时间猜 |
| 所有表都导出成功且 manifest 写成功，才推进增量游标；`failed_tables` 记进 manifest | 原来某张表失败也照样推进，下一轮只回看 1 小时，这张表更早的行就永远不会再导出 |
| 导出失败的半截 CSV 立即删除 | 不留下不在任何 manifest 里的文件 |
| `files[].table`、`files[].primary_key`、`files[].key_columns`，由 `PRAGMA table_info` 读真实主键；`unique_keys` 改为按它生成 | 手写的键是错的：活动表真实主键是 `(TIMESTAMP, DEVICE_ID, OTHER_TIMESTAMP, SOURCE)`，原来只给了 `(TIMESTAMP, OTHER_TIMESTAMP)`；`workout-summary`、`workout-pace`、`device-attributes` 根本没列。`key_columns` 是同一个键换成 CSV 里的列名（时间列在 CSV 里叫 `epoch_s`） |
| `raw_archive`：每个 raw 文件的 `name / bytes / sha256 / changed / complete` | 原来 `raw_files` 只有文件名。sha256 现在是对「实际写出去的字节」算的（文件只读一次），原来先算哈希再拷贝，中间 RRI 文件被追加就会对不上 |
| `data_quality` 的间隔只在时间戳变化时计数 | 活动表成对行让 `interval_median_s` 恒为 0 |
| manifest 和 CSV 按文件名时间戳保留 14 天（`retention_days` 写进 manifest）；清理残留的 `.json.tmp` | 原来只留最新 7 个 manifest、CSV 从不清理：几小时导出一次时，下游停一天就丢批次，而 CSV 无限堆积 |

`raw_files`、`raw_files_new` 两个旧字段保留不变，schema 5 的消费者不受影响。


---

## 2026-11-15 新增（生产必需）

### 文件类型映射对称化

`GetFileDownloadInitRequest.convertFileTypeTo2C()` 早先被改成按字节映射，但
`convertFileTypeFrom2C()` 没改，还是上游那个只认 7 种的 `switch`。后果是：
设备对其它类型回的完整 answer（name / type / transfer_id / size）被判成
「wrong file received」，异常在打印 `FILEDL_INIT` 之前抛出，**大小和类型字节都丢了**。

由此得出的「固件只认 5 种文件」结论作废。重跑 11-09 日志：26 种类型全部有完整回包，
零拒绝。`0x7F = 0x00023281` 配 `size = 0` = 「接受但没数据」，`0x000186A0` = 正常。

### 下载队列卡死的两个来源

`HuaweiFileDownloadManager` 里有两处 `handleException` 只通知回调、不调 `reset()`：
一处是 init 的（不认识的类型会在 init 上表现为缺 tag），一处是参数请求的。
不 `reset()` 则 `isBusy` 永远是 true，后续所有下载排队不动，直到连接断开。
这是「busy 卡几个小时」的一个确定来源。

### `sleep_data.bin` 每次同步从 3 次降到 1 次

`downloadTruSleepData()` 里为满足 `SleepFileDownloadCallback`（要两个文件都到才
`syncComplete`）额外请求了一遍 `sleep_data.bin`，但 `syncComplete` 只用 `statusData`，
用到 `sleepData` 的两行上游本来就是注释掉的。现在给回调加了 status-only 构造，
只请求 `sleep_state.bin`；归档请求 10 分钟内不重复。

### 探针改成显式开关

`pref_research_file_probes`（设备偏好，默认 false）+ 每进程只跑一次。
探针拿到的内容以前只打一行长度，现在写到 `files/probe/`。
`FILEDL_RAW` 的钩子扩到 `0x2C/0x02`，为 hash 预检铺路。

### 逐拍 blob 的解码可信度

新增 `decoders/check_trusleep_framing.py`（C1–C6 判据）。在 11-09 那份真实 blob 上：
记录边界 100%、记录间无非零字节、峰值无符号差分单调 100%（有符号只有 94.5%）、
ACC 时间戳 100% 递增、拍间隔 100% 落在 300–2000 ms。
**结论：无符号差分正确，Python 解码器的时间轴可信，可以做信号级分析。**
顺带修正：那份 blob 是 6.02 小时 / 20513 拍 / 平均 **56.8 bpm**，不是文档里写的 72。

### 研究用开关（0004，默认全关）

| 设备偏好 | 作用 | 日志标记 |
|---|---|---|
| `pref_research_file_probes` | 扫 17 个已知文件类型（已验证全部 size=0） | `FILEDL_INIT` / `FILEDL_DONE` |
| `pref_research_raw_types` | 对 0x1A–0x40、0x7F、0xFF 发 `0x2C/0x01`，判断 `0x23281` 的含义 | `RAWTYPE`、`FILEDL_RAW` |
| `pref_research_dict_sleep` | 强行请求 dict 睡眠序列（`SLEEP_DETAILS_CLASS=700013`），原始字节先落盘 | `DICTSLEEP`、`files/probe/` |

每次连接还会打一行 `CAPS ...` 说明手表实际声明了哪些能力（没声明的能力，功能不工作
和「设备从没声明」在日志里长得一样，这行用来分开）。

---

## 2026-11-16 新增（生产必需）

### 链路静默死亡的检测

11-15 实测：RFCOMM socket 在 **21:34** 之后就没有任何收发，但 Gadgetbridge **一直认为设备连着**
——`AutoConnectIntervalReceiver` 到 23:58 还在打 `all devices are initialized`。
状态停在 `CONNECTED`，而重连只从 `WAITING_FOR_RECONNECT` 触发，于是：

- 20:04 那次定时同步正常（那时链路还活着）
- 00:00 窗口打开，`openRriStream()` 往死 socket 写，异常被 catch 吞掉，**整夜零数据**
- 00:14 手动点设备卡片才连上，`capture` 里只有 `session_start_in_window` + `open_requested`

修法：`rriRepeat`（本来每 15 s 一次、本来就有 `lastRriPacketMs`）加两条判据：

| 条件 | 动作 |
|---|---|
| 窗口内、开流后 5 分钟一个包都没有 | `brSupport.dropConnection()`，重置窗口计时 |
| 窗口内、`lastRriPacketMs` 超过 15 分钟 | 同上 |
| `openRriStream()` 写失败 | 立刻 `dropConnection()`，不等 15 分钟 |
| 冷却 | 10 分钟内只掉一次（实测最长停顿 719 s = 12 分钟，不能当断线） |

为什么用 `dropConnection()` 而不是 `disconnect()`：前者关 socket，让读线程像丢链一样失败，
从而走正常重连；后者只是把设备标成未连接，不会触发重连。

日志标记：`RRI_LINKSTALE ... dropping connection`

### 保活闹钟（0006，补 0005 补不到的那一半）

0005 的看门狗只在「socket 还开着但没流量」时有用。11-15 那晚的实际原因是另一种：
**22:01 被 `am force-stop` 之后重启，进程起来了但没去连**——`general_autoconnectonbluetooth`
缺省 false，而 GB 自己的重连只从 `WAITING_FOR_RECONNECT` 触发。设备一直停在 `NOT_CONNECTED`。

| 组件 | 作用 |
|---|---|
| `KeepAliveReceiver` | 每 15 分钟检查所有设备，有任何一个既没连也没初始化就调一次 `deviceService.connect()`；**不做同步** |
| `KeepAliveScheduler` | 链式 `setAndAllowWhileIdle`，`GBApplication.onCreate` 里启动，偏好 `pref_keepalive_connect`（默认 true） |

为什么不复用 `PERIODIC_SYNC`：它每 6 小时一次且每次都触发 `TYPE_SYNC` 全量同步，
15 分钟一次太重，而 8 小时的窗口里 6 小时的间隔本身就可能整夜落空。

日志标记：`KEEPALIVE connecting <设备> (state ...)`、`KEEPALIVE all devices already connected`

三种断法现在各有人管：

| 现象 | 谁来管 |
|---|---|
| 重启后没连、`NOT_CONNECTED` 无人触发 | **0006 保活闹钟** |
| socket 半开、状态仍 `CONNECTED` | **0005 看门狗** |
| 深度 Doze 下闹钟被推迟 | 系统限制，只能靠白名单（本机已豁免） |

### 重发改成「只在通道真的安静时」（0007）

11-16 夜实测（5,644 个 `0x19/0x05` 帧）：

| 事实 | 值 |
|---|---|
| 相邻两帧**最大**间隔 | **42 秒**（整夜从未超过 60 秒） |
| 62 分钟「停顿」期间实际收到的帧 | 148 个，其中 110 个是 ts=0 的空包 |
| 整夜 15 秒重发产生的写 | **1,304 次** |
| `0x1E84A`（125002）错误应答 | 236 次，**其中 194 次在我们重发后 10 秒内** |
| 该错误占比最高的小时 | 02:00（25%，与空包最多的小时重合） |

结论：**流开着时再发 `0x19/0x01 type=3` 会被设备拒绝**，重发是无效动作。
（「停顿」不是丢包，是设备继续发空包 —— 那段时间 PPG 没有脉搏。）

现在的规则：

| 条件 | 动作 |
|---|---|
| 窗口内**从没收到过任何帧**且过了 5 分钟宽限 | `dropConnection()` |
| 距上一帧 > 15 分钟 | `dropConnection()` |
| 距上一帧 > **90 秒**，或窗口内还没收到过 | 发一次 open |
| 其余 | **什么都不做** |

90 秒取实测最大间隔（42 秒）的两倍余量。空包也算「收到帧」——
`markRriPacket()` 在 `ResponseManager` 里与时间戳无关，所以只看「有没有帧」，不看「有没有拍」。

### 没戴表时停流（0009）

用户的实际作息：**充电必须摘下**、洗澡摘下、入睡时间在 **00:00–03:00 之间浮动**。
所以任何固定时间窗都对不上。

`ResponseManager` 现在会告诉 provider「这个包有没有真实拍」（`countRriPairs` → `markRriBeat`），
15 秒调度据此决策：

| 条件 | 动作 |
|---|---|
| 最近 8 分钟内有真实拍 | 戴在手上，保持开流 |
| 8 分钟没有真实拍 | **驻留**：关流，然后每 15 分钟探测一次、每次 3 分钟 |
| 驻留中且 45 分钟没有任何包 | 掉线重连，重新开始 |

45 分钟这条边界是必须的：驻留时是我们主动关流，15 分钟的存活规则会打自己的脸。
探测期间一旦收到真实拍，立刻回到正常状态。

| 场景 | 预计耗电 |
|---|---|
| 6 小时佩戴 + 2 小时充电 | ~17%（原 26%） |
| 整夜没戴 | ~5%（原 21%） |

`tools/simulate-rri-scheduler.py` 可以离线验证状态机（不接设备）：
整夜佩戴 → 1 次探测后稳定；整夜没戴 → 8 小时 32 次探测（20% 占空比）；充电 2 小时再戴 → 能恢复。

### 实时流总开关（0010）

设备偏好 `pref_rri_stream_enabled`，默认 true。`insideRriWindow()` 第一行检查它：
关掉后开流、看门狗、驻留、重发全部失效。

用途：怀疑实时流会占用光学传感器、影响手表自己录睡眠文件时，
可以在单变量条件下测 TruSleep，不必临时改常量再改回来。
`tools/rri-stream-switch.py` 负责切换并**读回校验**。

### blob 归档：每晚一份（0011）

原来是稳定名 `raw-sleep_data.bin`，**每晚覆盖上一晚**。blob 现在是逐拍主数据源，
一份只能留一晚是不可接受的。

现在按抓取时间命名 `raw-sleep_data_<epoch_ms>.bin`（唯一且可排序，内容解出来就是睡眠时段），
并按 sha256 去重。`removeLegacySnapshots()` 只清 `raw-sleep_data.bin` 这类旧稳定名，
不再删带时间戳的快照。

### blob 会继续长（0013，真机验证）

同一晚两个时刻读到的两份：

| 读取 | 大小 | 拍数 | 覆盖到 |
|---|---|---|---|
| 08:58 | 112,632 | 27,156 | 08:11 |
| 14:08 | **119,548** | **29,073** | **08:46** |

两条推论都已验证：**文件在第一次可读之后还在追加**；**读一次不销毁**
（08:58 读过，14:08 仍能读到更多）。所以上午重试不因成功而停止，继续每小时一次到 13:00，
每次的不同版本都归档，相同字节按 sha256 去重。

顺带修掉：`.stale`（schema 让位后的旧 manifest）此前永远不被清理，因为不匹配批次的 `\.json$`。

### 睡眠段重新写行 + 看门狗清同步状态（0015，真机验证）

**睡眠段不写行。** 0012 把 `sleep_state` 的下载回调换成只存档的匿名类，它的 `syncComplete()`
是基类的空方法，所以 11-17 下午起睡眠段只存成原始文件，不再写成 SOURCE 10 / kind 6 的行。
现在匿名类里恢复写行；活动同步已经由 fitness-totals 的收尾结束，这里不再结束第二次。

**同步卡死 34 小时。** 11-18 14:00 一次定时同步拉活动数据时手表没回应。10 分钟后看门狗清了忙碌标记，
但 `HuaweiSyncState` 的 `activitySync` 和队列没清，之后 6 次定时同步、2 次手动同步全部以
`Activity type sync already queued, ignoring` 被丢掉；中途断开重连也不清，只有重启 GB 才恢复。
现在看门狗清忙碌时同时调用新加的 `HuaweiSyncState.resetStuck()`。

真机验证（11-20 02:30）：覆盖安装后两次同步正常结束，日志 `SLEEPSTATE_ROWS segments=5`，
导出表里有 SOURCE 10 的睡眠段行；补回的数据已经过脉络上传到服务器。看门狗那一半要等再遇到无回应的同步才能实测。

### 同步卡住能自己恢复、逐拍下载排到同步之后、心率 ≥128 不再变负数（0016，真机部分验证）

来源：2026-11-22 的独立审核，现象都在 11-21 测到。

**看门狗只清标记不够。** 11-21 02:00 那次同步，第 4 个 0x07/0x0d 没有回应；看门狗 02:28 清掉标记后，
08:00 那次又卡住，这次连 0x07/0x0c 都没有回应。直到 11:54 手机重启，14:01 的同步才恢复正常；11-18 那次卡了 34 小时。
现在看门狗清标记的同时会关掉 socket，交给正常的重连流程；重连后再补一次同步（30 分钟内最多一次）。
另外，看门狗改成按实际时间计算：原来是数满 10 次 60 秒的定时器，息屏时定时器被拉长，实际用了 27 和 32 分钟。

**逐拍下载不再和活动同步同时跑。** 两次卡住时，`sleep_data.bin` 都在和 0x07 请求同时下载。
是不是同时跑导致的卡住，还没有证实（20:00 那次也是同时跑，但正常结束了），不过分开跑不会丢任何东西。
现在同步只记下“欠一次下载”，等 `HuaweiSyncState` 空闲时再下载；连接后的那次下载推迟 60 秒，
让随连接一起到的同步先跑；两分钟内的两次请求只下载一次。

**心率 ≥128 存成负数。** 0012 让 `FitnessData` 按无符号读单字节值，但 `GetStepDataRequest` 又把它转回 `byte`，
130 bpm 又变成 -126。服务器上 11-14 到 11-21 有 6 行（-127 到 -109）。现在按 `int` 保存，0xFF 仍记为 -1（未测量）。

**其他。** 晨间重试的计数改成每天清零（以前跨天累加，进程不重启时会用完）；`pref_rri_stream_enabled` 缺省改为 false
（逐拍 blob 已经取代实时流，偏好文件被清掉时不能自己重新开流，开一夜要掉 20% 以上的电）。

真机验证（11-22 04:37 覆盖安装）：下一次同步结束后日志先出现 `FULLDUMP sync idle, downloading now`，逐拍文件这时才下载；
28 秒后的第二次同步记了 `FULLDUMP skipped`。`TestFitnessDataSignHandling` 4/4、新增的 `TestStepDataUnsignedSamples` 2/2 通过。
看门狗重连要等真的卡住一次才能验证，心率修复要等一次运动。
