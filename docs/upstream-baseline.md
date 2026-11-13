# 上游基线与升级

## 当前基线

| 项 | 值 |
|---|---|
| 版本名 | **0.95.1** |
| versionCode | 255 |
| 源码快照时间 | 2026-11-01 |
| 上游主仓 | https://codeberg.org/Freeyourgadget/Gadgetbridge |
| GitHub 镜像 | https://github.com/Freeyourgadget/Gadgetbridge |

本地源码树没有 git 元数据（是压缩包解压的），所以**没有精确 commit**。
要精确复现，用版本号 0.95.1 去 upstream 打 tag。

---

## 上游已经修了、但我们这份没有的

### `FileParameters.Request` 构造参数变了

**我们这份（旧）**
```java
public Request(ParamsProvider paramsProvider, byte fileType) {
    if (fileType != 0x0) {                    // ← type=0 时 tlv 保持 null
        this.tlv = new HuaweiTLV().put(0x06, fileType);
        if (fileType == 0x02) this.tlv.put(0x07, (byte) 0x03);
    }
    this.complete = true;                     // → serialize() 空指针
}
```

**上游 master**
```java
public Request(ParamsProvider paramsProvider, boolean truSleep) {
    if (truSleep)
        this.tlv = new HuaweiTLV().put(0x06, (byte) 0x01);
    else
        this.tlv = new HuaweiTLV().put(0x06, (byte) 0x02).put(0x07, (byte) 0x03);
    this.complete = true;                     // ← tlv 永远非 null
}
```

`GetFileParametersRequest` 也跟着改成 `boolean truSleep`。

**影响**：我们旧版在 `fileType=0` 时会 NPE，进而把「正在获取活动数据」永久挂住。
上游这个改动顺手治好了。**所以不需要给上游提 PR。**

---

## 升级步骤（下次必须改代码时再做）

1. 新 clone 一份上游，checkout 到当时最新 tag
2. **不要**直接 `git apply all-changes.patch`（上下文会冲突）
3. 按 [`patches.md`](patches.md) 的「生产必需」清单，逐个文件重新实现：
   - `DatabaseExportWorker.kt` —— 整份替换最省事，它基本独立
   - `PeriodicSyncScheduler` / `PeriodicSyncReceiver` / xml —— 新增文件，直接拷
   - `AbstractAutoExportSettingsFragment.kt` —— 小心，上游可能改过这块
   - `Workout.java`、`HuaweiFileDownloadManager.java` —— 小改动，手工合
4. 「研究脚手架」**一个都不要带过去**
5. 只保留 `enqueueFullSleepDump()`（在 `onFetchRecordedData` 里调用）
6. 重新编译、装机、连手表，按 [`docs/pitfalls.md`](pitfalls.md) 逐条验收：
   - 能认证（`mutual auth OK`）
   - 同步能结束（`sync complete`，不卡「正在获取活动数据」）
   - `FILEDL_INIT name=sleep_data.bin size=105716`（不是 0）
   - `files/dump/` 有新文件且大小 > 60KB

---

## 升级前先问自己

- 这次改代码是**必须**的吗？（现在这套是能跑的）
- 如果只是为了一个新特性，能不能用**读导出文件**的方式绕开？
- 升级后要重测多久？（连接、同步、导出、逐拍解析，至少一整晚）
