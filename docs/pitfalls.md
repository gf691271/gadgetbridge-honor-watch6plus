# 踩坑清单（do / don't）

每条都写清：**现象 → 原因 → 解法**。按「会不会浪费你一整天」排序。

---

## A. 会浪费一整天的坑

### A1. `trusleep` 开关把睡眠数据堵死

**现象**
睡眠数据卡在某一天不再更新，`sleep_data.bin` 每次都是同一个哈希。

**事实**

| `trusleep` | `sleep_state.bin` | `sleep_data.bin` |
|---|---|---|
| `true` | 0 字节 | 0 字节 |
| `false` | 32 字节 | 105716 字节 |

**原因**
TruSleep 打开后手表切到「newSync」协议（`NEWSYNC truSleep=true`），
Gadgetbridge 这条路径没有实现完整，两个文件都返回 0。

**解法**
设备设置里 `华为 TruSleep™` 必须保持**关闭**。
改完 `prefs` 后必须让 GB **重新连接**才会下发（`SetTruSleepRequest` 在连接流程里）。

**别被误导**：这个开关名字听起来是"提升睡眠监测质量"，实际上会让你**一个字节都拿不到**。

---

### A2. 探针抢走一次性数据

**现象**
`FILEDL_INIT name=sleep_data.bin size=105716` 明明成功过一次，
但归档目录里永远是 0 字节。

**原因**
`DEBUG_DL_CANDIDATES` 里包含 `sleep_data.bin` / `sleep_state.bin` / `rrisqi_data.bin`，
而 `enqueueProbeDownloads()` 排在归档路径**之前**。探针先把数据下走，归档只能拿到空。

**解法**
真实数据文件从探针候选列表里移除，**只允许一个消费者**请求它们。
当前分工：归档路径独占 `sleep_data`，GB 自己只拿 `sleep_state`（算分期）。

---

### A3. 手表蓝牙栈卡死 → 永远"认证中"

**现象**
GB 设备卡片一直显示「认证中」，日志里：

```
java.io.IOException: read failed, socket might closed or timeout, read ret: -1
```

**先别怀疑代码**。检查这两项，通常都是好的：

```
蓝牙绑定: bredr_linkkey_known:T  bredr_authenticated:T  BOND_TYPE_PERSISTENT  ✅
认证密钥: authkey / huawei_pake_* 都在 prefs 里                              ✅
```

**解法**
**重启手表**（长按表冠 ~10 秒）。恢复后日志立刻出现
`STS reconnect complete - mutual auth OK`。

不需要重新配对、不需要卸载 App、不需要重启手机。

---

### A4. 0x0A 探针会把 GB 的下载流程搞崩

**现象**
同步卡在「正在获取活动数据」永不结束，日志：
`NullPointerException ... HuaweiTLV.serialize() on null`
`at GetFileParametersRequest.createRequest`

**原因**
我们发的 0x0A 文件清单请求，其响应被 GB **正在进行的下载会话误认领**，
状态机错乱后 NPE，`busy` 标记再也不清 → 之后所有同步都被
`Ignoring fetch activity data because we're busy` 挡掉。

**解法**
不要在同步期间发 0x0A 的探针请求。研究完就关掉。

**注意**：这个 NPE 在**上游最新版已修**（`FileParameters.Request` 的构造参数从
`byte fileType` 改成 `boolean truSleep`，tlv 永远非 null）。我们这份旧快照没有。

---

## B. 编译与安装

### B1. Windows 下目录删不掉

**现象**
```
Unable to delete directory 'D:\...\build\intermediates\...'
AccessDeniedException: ...debug.keystore.lock
Could not update timestamp for ...gc.properties
```

**原因**
`D:\` 下的目录带拒绝删除的 ACL，Gradle 的清理动作一律失败。

**解法（关键）**
**重命名而不是删除。** 把各模块的 `build` 目录改名，Gradle 就会全新编译：

```powershell
cmd /c "move app\build app\build_old_<timestamp>"
```

`tools\build-gb.ps1` 已经实现了自动重试：遇到 `Unable to delete directory 'X'`
就 `rd X` 后重试，最多 N 次。

（`rd /s /q` 对某些目录也无效，但 `move` 总是有效。）

---

### B2. 签名不匹配装不上

**现象**
```
INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match
```

**原因**
`ANDROID_USER_HOME` 指向了一个**没有原 debug.keystore** 的目录，
Gradle 自动生成了新密钥。

**解法**
把以前的 keystore 复制进新的 home 后再编译：

```powershell
Copy-Item D:\...\android-home4\debug.keystore D:\...\android-home5\debug.keystore
```

本机可用密钥的 SHA256 前缀：`7885FD5C29D0B58E`。
**密钥丢了就再也装不上覆盖版**（只能卸载重装，但蓝牙绑定是 PERSISTENT，不会丢配对）。

---

### B3. `adb install` 挂住

**现象**
命令一直不返回，手机上也看不到确认弹窗。

**解法**
改用 push + pm install：

```powershell
adb push app.apk /data/local/tmp/gb.apk
adb shell pm install -r -d /data/local/tmp/gb.apk
```

`tools\install-gb.ps1` 会循环重试直到 `lastUpdateTime` 发生变化。

---

### B4. adb 频繁掉线

**现象**
`daemon not running` / `adb server version (39) doesn't match this client (41)` /
`protocol fault (couldn't read status): connection reset`

**解法**
每次操作前都跑一遍重置循环（脚本里已经内建）：

```powershell
adb kill-server; adb start-server; # 然后轮询 adb devices 直到出现 <serial> device
```

---

## C. UI 自动化

### C1. 盲点坐标会点进别的应用

**现象**
本意是点 GB 的「同步」，结果打开了微信 / 小红书 / 飞书。

**解法**
每次点击前**必须校验前台 Activity**：

```powershell
adb shell "dumpsys activity activities | grep topResumedActivity"
# 必须是 nodomain.freeyourgadget.gadgetbridge 才点
```

`mCurrentFocus` 在这台机器上经常返回 null，用 `topResumedActivity`。
`tools\gb_action.ps1` 就是按这个规则写的。

---

### C2. `uiautomator dump` 会失败

**现象**
`uiautomator dump` 返回成功但拉不到文件，或文件只有几十字节。

**解法**
重试 4~6 次，每次之间重启 adb；文件小于 200 字节视为失败。见 `tools\dump_ui.ps1`。

---

## D. 数据与解析

### D1. 一半的行是重复的

`HUAWEI_ACTIVITY_SAMPLE` 里同一 `TIMESTAMP` 出现两次，两条只差 `OTHER_TIMESTAMP`（±60 秒）。
**唯一键是 `(TIMESTAMP, OTHER_TIMESTAMP)`**，只用 `TIMESTAMP` 去重会丢掉一半数据。

### D2. 缺失值有两种写法

`-1` 和 NULL 都表示"没有数据"。下游必须统一当 null 处理。

### D3. 不同表的时间单位不一样

`activity` 用 epoch **秒**，`workout-base` 用 epoch **毫秒**。
不要相信全局声明，按表看。

### D4. 逐拍 blob 长度不固定

同一晚 78052 字节，另一晚 105716 字节（拍数 20513 vs 27406）。
解析器必须按记录结构读到结尾，**不能假设固定长度**。
