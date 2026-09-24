# mp3.mbt API

[English](API.en.md)

模块 `enanandesu/mp3` 将 MPEG-1、MPEG-2 和 MPEG-2.5 Layer III 字节流解码为 PCM。导入方法见 [README](../README.md#引入模块)。库不负责读取文件、播放音频或将 PCM 转换成 WAV。

本页只描述根包的公开接口；准确签名也可查看 [`pkg.generated.mbti`](../pkg.generated.mbti)。

## 输出格式

| 类型 | 字段 | 含义 |
| --- | --- | --- |
| `Audio` | `sample_rate: Int` | 整段音频的采样率，单位 Hz |
| | `channels: Int` | 1 或 2 |
| | `samples: Array[Float]` | 按帧顺序排列的交织 f32 PCM |
| `PcmFrame` | `sample_rate: Int` | 当前帧的采样率，单位 Hz |
| | `channels: Int` | 1 或 2 |
| | `source_offset: Int64` | 当前帧头在原始输入中的字节偏移；计入跳过的标签和开头字节 |
| | `samples: Array[Float]` | 当前帧的交织 f32 PCM，归调用方所有 |

双声道采样依次为左、右、左、右；单声道每个采样只有一个通道。MPEG-1 每帧每通道输出 1152 个采样，MPEG-2/2.5 输出 576 个。库保留原始帧的 PCM 范围，不自动去除 Xing 帧、encoder delay 或末尾 padding。

## 整段解码

| 函数 | 用途 |
| --- | --- |
| `decode_all(data: Bytes, limits?: Limits) -> Audio raise Mp3Error` | 解码所有支持的 Layer III 版本，使用增量解码器的同一状态机 |
| `decode_mpeg1(data: Bytes, max_output_samples?: Int, max_initial_scan?: Int) -> Audio raise Mp3Error` | 旧入口；只接受普通码率的 MPEG-1 Layer III，不接受 free-format；不是规划中的兼容模式 |

`data` 是完整的 MP3 字节内容，文件读取由调用方完成。两者均会累计输出，并在没有音频帧时抛出 `NoAudio`。`decode_all` 可通过 `limits` 调整输入与输出限额；`decode_mpeg1` 使用其余默认限额，两个可选参数默认分别为 `67108864` 和 `65536`。`max_output_samples` 计数单位是**交织采样**，因此一帧 1152 采样的立体声会占用 2304 个名额。

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
let sample_rate = audio.sample_rate
let channels = audio.channels
let interleaved_pcm = audio.samples
```

`mp3_bytes` 为调用方提供的 `Bytes`。对长音频或需要持续输入的场景，使用下方的 `Decoder`，以免把全部 PCM 累积在一个 `Audio` 中。

## 增量解码

`Decoder` 是有状态的同步解码器。每个实例拥有自己的输入缓冲、bit reservoir、IMDCT overlap 和合成滤波历史。

| 方法 | 行为 |
| --- | --- |
| `Decoder::new(limits?: Limits) -> Decoder raise Mp3Error` | 创建解码器；非法限额抛出 `InvalidLimits` |
| `push(input: Bytes, offset?: Int) -> Int raise Mp3Error` | 从 `input[offset:]` 复制能接收的字节，返回实际接收数；`offset` 默认 0 |
| `next_frame() -> DecodeResult raise Mp3Error` | 尝试解码下一帧或报告等待输入/结束 |
| `finish_input() -> Unit raise Mp3Error` | 所有字节已被 `push` 接收后声明 EOF；重复调用无害 |
| `buffered_bytes() -> Int` | 尚未消费的压缩输入字节数，不包含已返回的 PCM |
| `reset() -> Unit` | 清空输入、EOF、失败状态和解码历史；保留创建时的限额 |

`DecodeResult` 有三种结果：

| 结果 | 调用方操作 |
| --- | --- |
| `Frame(PcmFrame)` | 处理或保存这一帧，再调用 `next_frame()` |
| `NeedMoreInput` | 若尚有未提交的字节，继续 `push`；否则等候新输入 |
| `EndOfInput` | 在 `finish_input()` 后读取完毕；重复读取仍返回该结果 |

每次输入时要保留未被 `push` 接收的部分。`push` 返回 0 表示背压：先调用 `next_frame()` 消费可用输出，再从原偏移重试；不要丢弃未接收字节。所有输入都被接收后再调用 `finish_input()`，继续读取剩余帧直至 `EndOfInput`。过早确认 EOF 可能把尚未到达的帧视为截断。空增量流可以正常返回 `EndOfInput`，与整段接口的 `NoAudio` 不同。

`push` 复制数据而不持有传入的 `Bytes`。每个 `Frame` 的 `samples` 是新的调用方数组，后续 `next_frame()` 或 `reset()` 不会覆盖它。输入尚不足一帧时，`next_frame()` 返回 `NeedMoreInput`，不会提交半帧的 DSP 状态。发生致命解析或解码错误后，`push`、`next_frame` 和 `finish_input` 都会报 `FailedDecoder`，直到调用 `reset()`。

## 资源限额

使用 `Limits::default()` 获取默认值，再通过结构更新语法覆盖需要的字段：

```moonbit
let defaults = @mp3.Limits::default()
let limits = { ..defaults, max_output_samples: 1048576 }
let audio = @mp3.decode_all(mp3_bytes, limits~)
```

| `Limits` 字段 | 默认值 | 有效范围与作用 |
| --- | ---: | --- |
| `max_buffer_bytes` | 8192 | 输入环形缓冲容量，范围 2885..1048576；还必须满足下述前看公式 |
| `max_tag_bytes` | 16777216 | 单个前置 ID3v2 标签的最大总字节数，含头部和可选 footer；必须非负 |
| `max_initial_scan` | 65536 | 第一个合法帧前最多跳过的非标签字节数；必须非负 |
| `max_free_format_bytes` | 2304 | free-format 无 padding 的总帧长上限，范围 4..2304 |
| `max_output_samples` | 67108864 | 仅用于 `decode_all` 和 `decode_mpeg1` 的交织采样总量上限；必须非负 |

输入缓冲还需满足 `max_buffer_bytes >= 2 * (max_free_format_bytes + 1) + 4 + 355`，默认 free-format 限额下最少为 4969 字节，以容纳帧边界前看和可能的尾标签。增量接口不累计已输出的 PCM，也不会按 `max_output_samples` 限制整个流的总输出；调用方决定保留多少 `PcmFrame`。

## 错误

所有可能的公开错误构造器均属于 `Mp3Error`：

| 构造器 | 含义 |
| --- | --- |
| `InvalidHeader(offset)` | 在该原始字节偏移找不到有效帧头，或已开始的流遇到坏帧头 |
| `InvalidTag` | 前置 ID3v2 标签非法、超限或不完整 |
| `TruncatedFrame(offset, length)` | EOF 时该偏移处的帧不足预期的 `length` 字节 |
| `UnsupportedVersion` | `decode_mpeg1` 遇到非 MPEG-1 帧 |
| `UnsupportedFreeFormat` | `decode_mpeg1` 遇到 free-format 帧 |
| `OutputLimit` | 整段输出超过样本上限；也用于 `decode_mpeg1` 的负数限额参数 |
| `NoAudio` | 整段接口读完后没有音频帧 |
| `DecodeFailure(offset, cause)` | 该帧的 Layer III 解码失败，`cause` 保留底层原因 |
| `FramingFailure(offset, cause)` | 帧长或 free-format 边界判定失败，`cause` 保留底层原因 |
| `FormatChange(offset)` | 同一流中 MPEG 版本、采样率、声道数或普通码率/free-format 形态改变 |
| `InvalidLimits` | `Decoder::new` 收到非法 `Limits` |
| `InvalidInputOffset(offset)` | `push` 的偏移不满足 `0 <= offset <= input.length()` |
| `InputFinished` | `finish_input()` 之后再次 `push` |
| `FailedDecoder` | 致命错误后的解码器尚未 `reset()` |

错误中的 `offset` 是相对原始输入的字节偏移。`InvalidInputOffset` 和 `InputFinished` 是调用方式错误，不会单独将正常解码器置为失败状态；由 `next_frame()` 抛出的解析或解码错误会锁定实例。连续码率变化允许发生，但版本、采样率、声道数与普通码率/free-format 形态必须保持一致。

## 解析边界

- 仅开头允许跳过 ID3v2 和有限的非标签字节；开始解码后不自动跳过损坏帧。
- 帧边界处支持 ID3v1/TAG+ 尾标签；CRC 字段会跳过，但不校验。
- free-format 初次发现通常需要三个间距一致的兼容帧头；确认 EOF 时可接受恰好两个完整帧，不猜测孤立帧长度。
- 8 kHz mixed block 与未修改的 minimp3 存在已记录的参考差异，见 [Layer III 说明](../internal/layer3/README.md)。
