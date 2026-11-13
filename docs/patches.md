# 补丁清单

合集：`patches/all-changes.patch`（18 个文件，+1766 / -87）
应用：`git apply patches/all-changes.patch`

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
- 常量：`SCHEMA_VERSION=3`、`KEEP_SNAPSHOTS=7`、`FULL_DB_EVERY_MS=24h`

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
app/src/main/java/.../activities/automations/AbstractAutoExportSettingsFragment.kt   改
app/src/main/java/.../database/DatabaseExportWorker.kt                              改
app/src/main/java/.../devices/huawei/packets/FileDownloadService2C.java              改
app/src/main/java/.../devices/huawei/packets/Workout.java                            改
app/src/main/java/.../externalevents/PeriodicSyncReceiver.java                       新
app/src/main/java/.../externalevents/PeriodicSyncScheduler.java                      新
app/src/main/java/.../service/devices/huawei/requests/GetFileDownloadInitRequest.java 改
app/src/main/java/.../service/devices/huawei/requests/Send*Probe*.java               新 ×7
app/src/main/java/.../service/devices/huawei/HuaweiFileDownloadManager.java          改
app/src/main/java/.../service/devices/huawei/HuaweiSupportProvider.java              改
app/src/main/java/.../service/devices/huawei/ResponseManager.java                    改
app/src/main/res/xml/preferences_periodic_sync.xml                                   新
```

