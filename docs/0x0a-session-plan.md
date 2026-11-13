# 0x0A 会话式文件下载：从 0x2C 时序反推的实施方案

> 依据：`D:\deepseek\gb-orig\gadgetbridge`（上游未修改快照，只读）。
> 设备：HONOR Watch 6 Plus / Rome-B19C / 固件 20.1.0.114。客户端：GB 0.95.1 + 本仓补丁。
> 目标：把 `beat_raw_ecg.log` / `beat_raw_scisports.log` / `beat_raw_dataa.log` / `audio*.log` / `gps.bin` / `pdr.bin` 从 0x0A 的 38 个槽位里取出来。
> 本文只写可操作内容。所有行号对应当前 `gb-orig` 快照。

代号（表格里的短标签都链到源码行）：

| 代号 | 文件 |
|---|---|
| `MGR` | [HuaweiFileDownloadManager.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java) |
| `P0A` | [FileDownloadService0A.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService0A.java) |
| `P2C` | [FileDownloadService2C.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java) |
| `REQ` | [Request.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/Request.java) |
| `RM` | [ResponseManager.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/ResponseManager.java) |
| `ASY` | [AsynchronousResponse.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/AsynchronousResponse.java) |
| `PKT` | [HuaweiPacket.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/HuaweiPacket.java) |
| `TLV` | [HuaweiTLV.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/HuaweiTLV.java) |
| `INITQ` | [GetFileDownloadInitRequest.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/GetFileDownloadInitRequest.java) |
| `PARQ` | [GetFileParametersRequest.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/GetFileParametersRequest.java) |
| `INFOQ` | [GetFileInfoRequest.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/GetFileInfoRequest.java) |
| `BLKQ` | [GetFileBlockRequest.java](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/GetFileBlockRequest.java) |

---

## 0. 结论先行

1. 0x2C 能跑通，不是因为命令本身，而是因为 `MGR` 是一个**显式状态机**：`0x01 init → 0x03 fileInfo → 0x04 block → 0x05 ×N → 0x04 … → 0x06 complete`，每一步的回调都把下一步需要的状态（`fileId`/`fileSize`/`maxBlockSize`/`timeout`）填进同一个 `FileRequest` 对象。
2. 单发 0x04 之所以"成功但没数据"，最可能是**没有注册 0x05 的接收者**：0x0A/0x05 到达 `ResponseManager` 后找不到 handler，被丢进 `AsynchronousResponse`，而 `AsynchronousResponse` 只处理 0x2C，不处理 0x0A —— 数据被静默丢弃（`RM:146-152`、`ASY:870-880`）。之前所有 0x0A 探针类都写了 `addToResponse = false`，等于**主动放弃了接收**。
3. 第二层原因：上游 0x0A 流程在 `0x03 FileInfo` 处就断了 —— 固件恒返 `fileLength = 0`，`MGR:763-766` 直接跳 `fileComplete()`，**永远不会发 0x04**。所以"单发 0x04"其实是绕过上游 size 门的手工操作，它拿不到 `maxBlockSize`/`timeout`，也没有 EOF 语义。
4. 0x02 FileParameters 不是会话的必要条件（它只提供 `maxBlockSize` 和 `timeout`），可以先硬编码兜底；**真正的会话门槛是"注册 0x05 监听器"+"0x01 init 拿到文件名清单"**。

---

## 1. 0x2C 的完整时序（源码实际调用顺序）

### 1.1 状态机总览

```
startDownload (MGR:527)
  └─ sendFileDownloadInit           0x2C/0x01  {01:filename, 02:fileId, 05:start, 06:end, [0c:dictId]}
       ├─ timeout → 辅通道重试一次 → 仍失败则抛 TimeoutException + reset   (MGR:642-657)
       └─ resp {01:name, 02:type, 03:fileId, 04:size}
            ├─ size == 0 → fileComplete() 直接发 0x06                        (MGR:590-593)
            └─ size > 0 → getFileInfo
                 └─ getFileInfo        0x2C/0x03  {01:fileId, 02..05: 空 tag}
                      └─ resp {01:fileId, 02:timeout, 03:burstSize, 04:maxBlockSize, 05:noEncrypt}
                           └─ downloadNextFileBlock                             (MGR:756-769)
                                ├─ addInProgressRequest(fileDataReceiver)        (MGR:808)
                                ├─ arm timeout = timeout * 1000 ms               (MGR:810-811)
                                ├─ GetFileBlockRequest            0x2C/0x04  {01:fileId, 02:offset, 03:size}
                                └─ 设备连发 0x2C/0x05（每包 {fileId, offset, unknown, data}）
                                     ├─ 累计 < maxBlockSize → 继续等 0x05
                                     ├─ 累计 ≥ maxBlockSize → 再发 0x04            (MGR:855-857)
                                     └─ 累计 == fileSize    → fileComplete()      (MGR:847-854)
                                          └─ 0x2C/0x06 {01:fileId, 02:status}     (MGR:920, P2C:264-266)
```

### 1.2 逐步表

| # | 方法 / 触发 | 发送 | 期望响应 | 超时与失败处理 | 源码 |
|---|---|---|---|---|---|
| 1 | `startDownload()`，取队列首元素 | — | — | 队列空 → `downloadQueueEmpty(needSync)` | [MGR:527-553](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L527-L553) |
| 2 | `sendFileDownloadInit()` | `0x2C/0x01` TLV（默认加密，`isEncrypted` 默认 true）：`0x01` filename(str) / `0x02` fileId(byte) / `0x05` startTime(int) / `0x06` endTime(int)；`SEQUENCE_DATA` 另加 `0x0C` dictId | `0x01` fileName / `0x02` fileType / `0x03` fileId / `0x04` fileSize | 双通道激活时 `setupTimeoutUntilNext(5000)`；超时且未走 aux → `setFileDownloadViaAux(true)` 重试一次；再失败 `HuaweiFileDownloadTimeoutException` + `reset()` | [MGR:562-666](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L562-L666) / [P2C:70-115](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java#L70-L115) |
| 3 | 校验响应 | — | `r.filename` 必须等于请求名、`r.fileType` 必须等于请求类型，否则 `HuaweiFileDownloadFileMismatchException` + `reset()` | `fileSize == 0` → 直接 `fileComplete()`（不发 0x03/0x04） | [MGR:571-595](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L571-L595) |
| 4 | `getFileInfo()` | `0x2C/0x03`：`0x01` fileId(byte) + `0x02`/`0x03`/`0x04`/`0x05` 四个**零长** tag（问询式占位） | `0x01` fileId / `0x02` timeout(byte) / `0x03` burstSize(short，每个 0x05 的大小) / `0x04` maxBlockSize(int，一个 0x04 最多能要多少) / `0x05` noEncrypt(bool) | 响应里 fileId 不匹配 → mismatch 异常 + reset | [MGR:744-784](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L744-L784) / [P2C:151-193](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java#L151-L193) |
| 5 | `downloadNextFileBlock()` | — | — | 分配 `ByteBuffer(fileSize)`；`lastPacketNumber=-1`（**每块重置包号**）；`currentBlockSize = min(fileSize - pos, maxBlockSize)` | [MGR:786-806](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L786-L806) |
| 6 | **注册数据接收者** | — | — | `addInProgressRequest(fileDataReceiver)`，必须在发 0x04 **之前** | [MGR:808](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L808) |
| 7 | 起超时表 | — | — | `handler.postDelayed(timeout, timeout * 1000L)`，单位=秒 | [MGR:810-811](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L810-L811) |
| 8 | `GetFileBlockRequest.doPerform()` | `0x2C/0x04`：`0x01` fileId / `0x02` offset(int) / `0x03` size(int)；`isEncrypted = !noEncrypt` | `0x7F` 等 ACK（`RequestBlock.Response` 只解 0x7F，见 `BLKQ:66-69` 的 TODO：不处理数据） | ack 到达后 `finalizeReq` 重置超时；IOException → `HuaweiFileDownloadSendException` + reset | [MGR:813-827](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L813-L827) / [BLKQ:42-69](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/requests/GetFileBlockRequest.java#L42-L69) / [P2C:195-216](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java#L195-L216) |
| 9 | 设备推送 `0x2C/0x05` | — | payload 两种形态：`payload[2..4] == 7C 01 01` → 先 TLV parse 再 `decryptRaw`；否则直接 `payload[2..]`。解出 `fileId(1) + offset(4) + unknown(1) + data(n)` | 解密失败 → `CryptoException`（`ParseException` 子类），包被丢弃 | [P2C:218-253](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java#L218-L253) |
| 10 | `FileDataReceiver` 收包 | — | `handleResponse` 同时匹配 `0x0A/0x05` 和 `0x2C/0x05`；`autoRemoveFromResponseHandler() == false`（**常驻**） | `processResponse` 只搬运数据；`finalizeReq` 里重置超时并 `handleFileData()` | [MGR:394-450](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L394-L450) / [MGR:504-525](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L504-L525) |
| 11 | `handleFileData()` | — | — | 新协议校验 `fileId == number`；老协议校验 `lastPacketNumber == number - 1`（**包号必须从 0 连续**）。满 `fileSize` → `fileComplete()`；满 `maxBlockSize` → 回到步骤 5 | [MGR:830-859](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L830-L859) |
| 12 | `fileComplete()` | `0x2C/0x06`：`0x01` fileId / `0x02` status（1=OK，2=校验通过） | 无强校验响应 | 停掉超时表 → 存 raw → 回调 → `reset()`；老协议同批文件可"抄近路"跳过 init/parameters | [MGR:896-966](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/service/devices/huawei/HuaweiFileDownloadManager.java#L896-L966) / [P2C:255-270](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/devices/huawei/packets/FileDownloadService2C.java#L255-L270) |

### 1.3 三条从源码读出的硬约束

1. **监听器先于请求**：`addInProgressRequest` 在 `doPerform` 之前（`MGR:808` vs `MGR:813`）。反过来做，第一包 0x05 一定丢。
2. **块大小不是自由参数**：`currentBlockSize = min(剩余, maxBlockSize)`（`MGR:802-805`）。`maxBlockSize` 只能来自 `0x03`（0x2C）或 `0x02`（0x0A）。手工填 4096 是越权的。
3. **超时单位是秒**：`timeout * 1000L`（`MGR:811`）。0x0A 的 timeout 是 `short`（`P0A:171`），0x2C 是 `byte`（`P2C:187`），来源不同但用法相同。

---

## 2. 0x0A 的对应时序（init → parameters → fileInfo → block → complete）

### 2.1 逐步表

| # | 命令 | 请求 TLV（逐 tag） | 期望响应 | 备注 |
|---|---|---|---|---|
| 1 | `0x0A/0x01` init（debug） | **空 TLV**：显式 `new HuaweiTLV()`，序列化后 0 字节 | `0x01` = `"name1;name2;..."`（实测 38 个 debug 名，已通） | `P0A:42-53`；`complete = true`，加密发送（`isEncrypted` 默认 true） |
| 1' | `0x0A/0x01` init（sleep 类，备用） | `0x02 = 0x01`，`0x83 = {0x04 startTime(int), 0x05 endTime(int)}` | 同上；若响应走嵌套形式则是 `0x8B/0x8C/0x0D` | `P0A:55-71`、`P0A:118-126` |
| 2 | `0x0A/0x02` parameters | **变体 A（首选）**：空 TLV（0 字节）。**变体 B**：`0x06 = 0x00`（fileType=debug 显式写出）。**变体 C**：`0x06 = 0x01`（把 debug 槽位当 sleep 类协商） | `0x01` version(str) / `0x02` unknown(bool) / `0x03` packetSize(short) / `0x04` maxBlockSize(short) / `0x05` timeout(short) | `P0A:130-174`；`parseTlv` 用 `getString/getBoolean/getShort`，**缺任一 tag 抛 `MissingTagException`**，不等于设备拒绝 |
| 3 | `0x0A/0x03` fileInfo | `0x01 = fileName`（str，必须与第 1 步清单里的名字逐字相同） | `0x02` fileLength(int) / `0x04` transferType(byte) / `0x05` fileCreateTime(int) / `0x06` unknown(byte) | `P0A:176-214`；**本固件恒返 0**，只能当"存在性"用，不能当长度用 |
| 4 | `0x0A/0x04` block | `0x01 = fileName` / `0x02 = offset(int32, 大端)` / `0x03 = size(int32, 大端)` | ACK：`0x7F = 0x000186A0`；可选 `0x01` filename / `0x02` offset | `P0A:216-255`；`size` 取 `min(maxBlockSize, 剩余)`，首次可先取 `min(maxBlockSize, 4096)` |
| 5 | `0x0A/0x05` 数据（设备主动推） | 无请求 | payload 布局：`[number(1)][data(n)]`（若加密则 `payload[2..]` 是 TLV，`decryptRaw` 后再按此布局） | `P0A:257-286`；`number` **每块从 0 重新计**（对应 `MGR:800` 的 `lastPacketNumber = -1`） |
| 6 | `0x0A/0x06` complete | `0x06 = true`（即 `0x06 01 01`） | 无强校验 | `P0A:288-301`；注意它**没有** fileId/status，和 0x2C 不同 |

### 2.2 与 0x2C 的五个差异（照抄会踩坑）

| 项 | 0x2C | 0x0A |
|---|---|---|
| 文件标识 | `fileId`（byte，init 时由设备下发） | `fileName`（str，必须在 init 清单里；`MGR:622-629` 会做 `arrayContains` 校验） |
| 长度来源 | init 响应直接给 `fileSize` | 只能靠 `0x03`，而它恒返 0 → **必须设计"无长度"模式** |
| 协商命令 | `0x03`（同一个命令既问长度又问块参数） | 拆成 `0x02`（块参数）和 `0x03`（长度）两个 |
| 数据包 | `0x05`，`{fileId, offset, unknown, data}` | `0x05`，`{number, data}`，**没有 offset 字段** → 断流就得整块重取 |
| complete | `{fileId, status}` | 只有 `{0x06: true}`，无状态位 |

### 2.3 "无长度"模式的终止条件（必须实现，否则永远不知道该停）

按优先级判 EOF：

1. 收到 `0x05` 且 `data.length == 0` → EOF（最干净的信号）。
2. 收到 `0x05` 且 `number != 上一包 number + 1` → 断流，重发同 offset 的 0x04，连续 2 次失败则放弃。
3. 单次 0x04 后等待超时（用 `0x02` 的 timeout，取不到就用 5 s）→ 视为"该 offset 之后无数据"，EOF。
4. 硬上限（例如 4 MB 或 64 个块）→ 强制 EOF 并记 `P0A_TRUNCATED`，防止死循环把 busy 拖住。

---

## 3. 为什么单发 0x04 会失败

按"最可能 → 次可能"排列，每条都给了**判别方法**。

### M1（最可能）0x05 回来了，但没有接收者，被 `AsynchronousResponse` 静默丢弃

- 事实链：`RM:135-144` 在全局 handler 列表里找第一个 `handleResponse(packet)` 返回 true 的 Request；找不到就走 `RM:146-152` 的 async 分支；`ASY:149` 调 `handleFileDownload`，而 `ASY:870-872` 第一行就是 `if (response.serviceId != FileDownloadService2C.id) return;` —— **0x0A 到此为止**。
- 之前的探针类（`SendBlockProbeRequest` 等）全部写了 `this.addToResponse = false`，等于不注册自己，连 0x04 的 ACK 都没人认领。
- 判别：日志里出现 `BLOCKDATA tlv=null`（现有 hook，见 §4.2）或 `Service: a, command: 5, asynchronous response.` → 证明数据回来了，是客户端丢的。

### M2 没有 `0x02` 协商，块长/超时为 0

- `MGR:802-805`：`maxBlockSize = 0` 时 `currentBlockSize = 0`；`MGR:811`：`timeout = 0` 时 `postDelayed(..., 0)` **立即触发**超时异常。
- 手工发 4096 绕过了客户端限制，但没绕过设备端限制（`packetSize`/`maxBlockSize` 是设备给的）。
- 判别：`P0A_PARAMS packetSize=.. maxBlockSize=.. timeout=..` 是否非 0；0x04 ACK 里 `0x02 offset` 回显是否与请求一致。

### M3 上游根本没走到 0x04（`0x03` 恒返 0 → 直接 complete）

- `MGR:759-767`：老协议的 `fileLength` 来自 `0x03`；`== 0` 就 `fileComplete()`。
- 所以"能发 0x04"这件事本身就是绕过了上游的 size 门；这也解释了为什么上游代码里没有任何"0x0A 取数成功"的先例可抄。
- 判别：日志里 `0x0A/0x03` 之后紧跟 `0x0A/0x06`，中间没有 `0x0A/0x04`。

### M4 0x05 解密路径抛的异常没被 catch

- `P0A:274-280`：`catch (ArrayIndexOutOfBoundsException | HuaweiCrypto.CryptoException e)`；但 `TLV.decryptRaw` 还会抛 `MissingTagException`（`TLV:410-417`，先取 `CryptoTags.cipherText = 0x7E`、再取 `initVector = 0x7D`），它是 `HuaweiPacket.ParseException`，**不在 catch 列表里**，会一路抛到 `REQ:250-257` 的 `Parse TLV exception` → 包被丢。
- 判别：日志出现 `Parse TLV exception` 且原因是 `Missing tag: 7e`（或 `7d`），而不是 `Missing tag: 7c`。

### M5（不能排除）这 38 个槽位是静态清单，设备上根本没有内容

- 依据：`0x03` 对所有文件都返回 0，包括我们**确知有 105716 字节**的 `sleep_data.bin` —— 说明 `0x03` 完全不可信，**不能用它判断"文件为空"**。
- 判别：用一个"必然有内容"的槽位做对照（例如打完一次户外运动后取 `gps.bin`/`pdr.bin`，或录音后取 `audio0.log`）。如果连它都收不到任何 0x05，则 M5 成立，整条 0x0A 路线到此为止。
- 这一步的判断依据只能来自 0x05 是否到达，**不要再看 0x03 的返回值**。

---

## 4. 关键风险：ACK 与数据是两个包

### 4.1 事实

- `0x0A/0x04` 的 Response 只解 `0x7F`：`isOk = tlv.getInteger(0x7f) == 0x000186A0`，此外只**可选**读 `0x01` filename / `0x02` offset（`P0A:244-253`）。它**永远不含数据**。
- 数据只走 `0x0A/0x05` 单独一个包（`P0A:257-286`），由 `HuaweiPacket.parse` 特判为非 TLV：`PKT:422-431` 对 `(0x0a,0x05)`（还有 `0x28/0x06`、`0x2c/0x05`、`0x1c/0x05`）**不建 `tlv`，只保留 `payload`**，直接 return。
- 推论：**任何"看 tlv 是否为空"的日志对 0x05 都无意义** —— 它天然是 null。这也解释了为什么旧的 `BLOCKDATA tlv=null` 容易被误读成"没数据"。

### 4.2 如何确证 0x05 到底回没回来

按可信度从低到高，四种证据：

| 日志 | 含义 | 来源 |
|---|---|---|
| `Service: a, command: 5, asynchronous response.` | 0x05 到达但**无人认领**（即 M1 成立） | `RM:148`，debug 级 |
| `BLOCKDATA tlv=null` | 0x05 到达（现有 hook；因 0x0A/0x05 恒无 tlv，null 即等于"到了"） | 本仓补丁在 `RM.handleData` 里的反射日志 |
| `Parse TLV exception` + `Missing tag: 7e` | 0x05 到达但解密路径失败（M4） | `REQ:250-257` |
| `P0A_DATA num=0 len=1024 head=...` | 我们自己的监听器接到并解出数据（终局证据） | 需新加，见下 |

**过滤器（PowerShell）**：

```powershell
adb pull /sdcard/Android/data/nodomain.freeyourgadget.gadgetbridge/files/gadgetbridge.log gb.log
Select-String gb.log -Pattern 'BLOCKACK|BLOCKDATA|Service: a, command: 4|Service: a, command: 5|Missing tag|Parse TLV exception|P0A_'
```

判定规则：

- 只有 `BLOCKACK` → 设备**没有**发数据（M2/M3/M5）。
- `BLOCKACK` + `BLOCKDATA tlv=null`（或 `Service: a, command: 5`）→ 数据回来了，被丢了（M1）→ 直接上 §5 的 S3。
- `Parse TLV exception` → M4，先修 catch，再看数据。

**前提**：日志级别。`Logging.resolveRootLevel()` 在开启「调试 → 写入日志文件」后根级别是 DEBUG（[Logging.java:167-175](../../gb-orig/gadgetbridge/app/src/main/java/nodomain/freeyourgadget/gadgetbridge/Logging.java#L167-L175)），所以上面那条 `LOG.debug` 是可见的。没开文件日志就只能看 INFO 以上，会漏掉 M1 的直接证据。

**建议补的日志（payload 级，不受 tlv 恒 null 影响）**：在现有 0x0A hook 里加

```java
// Local patch: 0x0A/0x05 carries raw payload, never a TLV (HuaweiPacket.parseData).
java.lang.reflect.Field pf = HuaweiPacket.class.getDeclaredField("payload");
pf.setAccessible(true);
byte[] pl = (byte[]) pf.get(receivedPacket);
LOG.info("P0A_RAW cmd=0x{} payloadLen={} head={}", Integer.toHexString(receivedPacket.commandId & 0xff),
        pl == null ? -1 : pl.length,
        pl == null ? "-" : GB.hexdump(java.util.Arrays.copyOf(pl, Math.min(pl.length, 16))));
```

---

## 5. 可执行实施步骤（5 步，每步独立验证、独立回退）

> 通用约束：所有新代码放在**新文件**里（`requests/Send0A*.java`），唯一改动的既有文件是 `HuaweiSupportProvider`（一处 `if` 调用）和 `ResponseManager`（一处日志）。全部行为挂在设备偏好 `pref_huawei_0a_probe`（默认 `false`）后面，删掉这个 `if` 即完全恢复现状。
> 禁止：把 `sleep_data.bin`/`sleep_state.bin`/`rrisqi_data.bin` 放进 0x0A 候选列表（会抢走 0x2C 归档路径的数据，见 [pitfalls.md](pitfalls.md) A2）。0x0A 实验期间不要和 0x2C 归档同时跑。

### S1 观测层（零行为改动）

- **改动**：只加 §4.2 的 payload 级日志，不加任何请求。
- **验证**：正常同步一次，`Workout sync complete!` 出现；日志里**没有**任何 `P0A_RAW`/`BLOCKDATA`（说明 0x0A 全程未被触碰，0x2C 路径无回归）。
- **失败判据**：同步卡住或 `sleep_data` 大小为 0 → 立刻 `git checkout` 该文件。
- **回退**：日志代码纯附加，`git checkout app/.../ResponseManager.java`。

### S2 只做参数协商（不取数）

- **改动**：新类 `Send0AParametersProbe`，`addToResponse = true`，依次发 `0x0A/0x01`（空 TLV）→ `0x0A/0x02`（先变体 A 空 TLV；若 `MissingTagException` 或 5 s 无响应，改变体 B `0x06=0x00`）。`createRequest` 里必须**显式 `new HuaweiTLV()`**，否则就是历史上那个 NPE。
- **验证**：`P0A_PARAMS version=.. unknown=.. packetSize=.. maxBlockSize=.. timeout=..`，要求 `maxBlockSize > 0 && timeout > 0`。
- **失败判据**：`MissingTagException` → 换变体；5 s 无响应 → 换变体；三种变体都失败 → 记 `P0A_NO_PARAMS`，**跳到 S3 用硬编码 `maxBlockSize=1024, timeout=5`**（0x02 只提供这两个值，缺了不影响取数，见 §0 第 4 条）。
- **回退**：删掉 `Send0AParametersProbe.java` + 调用点。

### S3 单块取数（整个方案的 go/no-go）

- **改动**：
  1. 新类 `ZeroADataListener extends Request`：`handleResponse` **只**匹配 `response.serviceId == 0x0A && response.commandId == 0x05`（务必别写宽，否则会抢走 0x2C/0x05，把当前可用的睡眠同步一起搞挂）；`autoRemoveFromResponseHandler()` 返回 `false`。
  2. **先** `supportProvider.addInProgressRequest(listener)`，**再**发 `0x0A/0x04`（`0x01`=fileName, `0x02`=0, `0x03`=min(maxBlockSize,4096)）。
  3. 5 s 后打印统计：收到几个 0x05、`number` 序列、`data` 总字节、首 16 字节。
- **验证**：`P0A_BLOCKACK ok=true` 且 `P0A_DATA num=0 len=<非零>`。`number` 必须是 0,1,2… 连续。
- **失败判据**：
  - `ok=true` 但零个 0x05 → 换文件重试（`gps.bin` 必须有一次运动记录），仍为零则 M5 成立，**停止投入**。
  - `number` 不连续 → 丢包，改为每收一包就补发一次同 offset 的 0x04（退化模式）。
- **回退**：删两个新类 + 调用点，`addInProgressRequest` 不再被调用即恢复。

### S4 连续块 + EOF 判定

- **改动**：按 §2.3 的规则写循环：每块 `offset += 已收字节`，`size = min(maxBlockSize, 上限-offset)`；实现 4 条 EOF 判据（尤其"`data.length == 0` → EOF"和"单块超时 → EOF"）。
- **验证**：`P0A_EOF reason=empty|timeout|cap total=<n> blocks=<k>`；把字节写进 `files/raw/DEBUG0A/<fileName>`，落盘大小与 `total` 一致。
- **失败判据**：`blocks` 一路涨到 cap 且每块都是满长 → 说明这个槽位是无底洞/流式，记 `P0A_TRUNCATED`，采样 256 KB 就够做波形分析。
- **回退**：同上，只删新类。

### S5 complete + 与 0x2C 共存

- **改动**：取数成功后发 `0x0A/0x06`（`0x06=true`）；整个 0x0A 实验串行化（同一时刻只允许一个 0x0A 会话，用一个 `boolean` 守卫）。
- **验证**：
  1. `P0A_DONE file=beat_raw_ecg.log bytes=<n>`；
  2. **同一次连接里紧接着再同步一次 0x2C**，`FILEDL_INIT name=sleep_data.bin size=105716` + `Download complete for file sleep_data.bin` 仍然出现（证明 0x0A 没污染 0x2C）；
  3. 同步能正常结束，没有卡在「正在获取活动数据」。
- **失败判据**：任何一次 0x2C 失败 → 立刻关掉 `pref_huawei_0a_probe`，回 S1 状态。
- **回退**：关偏好即可，代码可以留着。

---

## 6. 回退方案

### 6.1 正常回退（有序）

1. 关 `pref_huawei_0a_probe`（`run-as` 改 `shared_prefs/devicesettings_<mac>.xml`，改完 `am force-stop` 再启动，见 [protocol-findings.md](protocol-findings.md) §10.4）。
2. 若只是关开关不够（例如已经改到 `MGR`），`git checkout` 以下文件即可：`HuaweiFileDownloadManager.java`、`HuaweiSupportProvider.java`、`ResponseManager.java`，并删除新建的 `Send0A*.java`。
3. 回到 `patches/all-changes.patch` 对应的已知可用构建（见 [patches.md](patches.md)）。

### 6.2 同步已经卡住时的 30 秒急救

症状：设备卡片一直"正在获取活动数据"，日志 `Ignoring fetch activity data because we're busy`。

1. `adb shell am force-stop nodomain.freeyourgadget.gadgetbridge`，重开 GB，重新连接。
2. 仍有 `busy`：检查 `BUSY_WATCHDOG`（每 60 s 检查，连续 10 分钟 busy 会强制 `unsetBusyTask()`，见 [patches.md](patches.md)）；不想等就直接 force-stop。
3. 日志出现 `read failed, socket might closed or timeout` / 卡在「认证中」→ **重启手表**（长按表冠 ~10 s），与代码无关，见 [pitfalls.md](pitfalls.md) A3。
4. 恢复后第一件事：确认 `FILEDL_INIT name=sleep_data.bin size=105716` 能再现，再谈 0x0A。

### 6.3 绝对不要做的四件事

1. 不要在 0x2C 同步进行中发任何 0x0A 请求（历史 NPE 就是这条路，见 [pitfalls.md](pitfalls.md) A4）。
2. 不要把 0x0A 监听器的 `handleResponse` 写成"匹配所有 0x05"——`RM` 的 handler 是全局先进先得，会抢走 0x2C 的数据包，直接毁掉当前唯一可用的通道。
3. 不要用 `0x03` 的返回值判断文件是否存在/为空——它对 `sleep_data.bin` 也返回 0。
4. 不要在 `FileParameters.Request` 的 `tlv` 为 null 时直接 `serialize()`——`PKT:1097/1107` 会 NPE，`busy` 永久挂住。

---

## 附录 A：一次完整验证的取数命令

```powershell
# 1. 清日志、触发同步（tools\gb_action.ps1 里的 <REPO_ROOT>/<USER_HOME> 占位符需先填）
adb shell "run-as nodomain.freeyourgadget.gadgetbridge sh -c 'rm -f files/gadgetbridge.log'"
powershell -File tools\gb_action.ps1

# 2. 拉日志并按 0x0A 相关标记过滤
adb pull /sdcard/Android/data/nodomain.freeyourgadget.gadgetbridge/files/gadgetbridge.log gb0a.log
Select-String gb0a.log -Pattern 'P0A_|BLOCKACK|BLOCKDATA|Service: a, command: 5|Missing tag|FILEDL_INIT' |
    ForEach-Object { $_.Line }

# 3. 确认 0x2C 无回归
Select-String gb0a.log -Pattern 'Download complete for file|Workout sync complete'
```

## 附录 B：已知死路（不要重复）

| 尝试 | 结论 | 依据 |
|---|---|---|
| 单独 `0x0A/0x03` 问长度 | 对所有文件返回 0（含已知 105716 字节的 `sleep_data.bin`） | `P0A:202-212`，实测 |
| 单独 `0x0A/0x02`（空 TLV 且 tlv 为 null） | NPE | `P0A:141-146` + `PKT:1097/1107` |
| 单独 `0x0A/0x04`（offset 0, size 4096） | 只有 `0x7F` ACK，无数据 | 本文 §3（M1 最可能） |
| 靠改 `maxBlockSize` 硬编码解决 | 不解决"没人收 0x05" | 本文 §3 M1 |
