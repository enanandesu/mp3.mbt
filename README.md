# mp3.mbt

纯 MoonBit 的 MP3（MPEG-1/2/2.5 Layer III）解码库。输入压缩字节，输出原始采样率的交织 `Float`（f32）PCM；解码核心没有第三方运行时依赖。

目前提供整段与同步增量解码 API。命令行播放器、浏览器示例和最终性能目标验收尚未完成。

## 支持范围

- MPEG-1、MPEG-2、MPEG-2.5 Layer III 的九种采样率，单声道与双声道。
- 普通立体声、Mid/Side 和 Intensity Joint Stereo；长块、短块与混合块。
- CBR、VBR、ABR、有界 free-format 和跨帧 bit reservoir。
- `native`、`wasm`、`wasm-gc`、`js` 四个目标后端。

库只负责解码，不读取文件或播放音频。输出是按帧顺序排列的交织采样：双声道时依次为左、右、左、右。

## 引入模块

如果模块已发布到 mooncakes.io，可在使用方项目运行 `moon add enanandesu/mp3`；本地开发可在使用方的 `moon.mod.json` 添加路径依赖：

```json
{
  "deps": {
    "enanandesu/mp3": { "path": "../mp3.mbt" }
  }
}
```

再在使用方包的 `moon.pkg.json` 中导入根包：

```json
{
  "import": ["enanandesu/mp3"]
}
```

依赖路径按使用方项目的位置调整。模块导入后默认别名为 `@mp3`。

公开类型、方法、限额和错误语义见 [API 文档](docs/API.md)。

## 整段解码

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
let sample_rate = audio.sample_rate
let channels = audio.channels
let samples = audio.samples
```

`mp3_bytes` 是调用方提供的 `Bytes`；`samples` 为交织 `Array[Float]`。`decode_all` 在没有音频、输入损坏或触及资源限额时抛出 `Mp3Error`。兼容入口 `decode_mpeg1` 只接受普通码率的 MPEG-1 Layer III。

## 增量解码

`Decoder::new(limits?)` 创建独立的解码状态和固定容量输入缓冲。调用顺序如下：

1. 用 `push(input, offset?)` 提交字节，并保存未被接收的部分；返回值是实际接收的字节数。
2. 反复调用 `next_frame()`：`Frame(frame)` 提供一帧 PCM；`NeedMoreInput` 表示需要更多字节；`EndOfInput` 表示已结束。
3. 全部字节被接收后调用 `finish_input()`，继续读取直到 `EndOfInput`。

`push` 返回 0 表示背压，应先消费 `next_frame()` 的输出再重试。`PcmFrame` 含 `sample_rate`、`channels`、`source_offset` 和交织的 `samples`。已返回的采样数组归调用方所有；`reset()` 会清除输入和解码历史，保留限额配置。致命解码错误后需 `reset()` 才能复用该实例。

默认限额由 `Limits::default()` 提供：输入缓冲 8192 字节、单个前置 ID3v2 标签 16 MiB、开头非标签扫描 65536 字节、free-format 帧长上限 2304 字节。整段接口最多输出 67108864 个交织采样；增量接口不累计已输出的 PCM。

## 已知边界

- 不自动裁剪 Xing 帧、encoder delay 或 padding；CRC 字段会跳过，但不会校验。
- 遇到中途损坏、历史不足、不完整帧或音频格式变化会报错，不自动跳过坏帧。
- 8 kHz mixed block 使用有界频带布局，与未修改的 minimp3 在该路径有已知差异；证据范围见 [Layer III 说明](internal/layer3/README.md)。

## 开发与验证

日常检查：

```sh
moon check
moon test
moon fmt --check
```

跨后端和参考 PCM 验证：

```sh
python tools/validate_compatibility.py
```

该脚本需要 Python、GCC、FFmpeg/FFprobe 和 Node；固定工具版本见 [`tools/toolchain.lock.json`](tools/toolchain.lock.json)。这些工具只用于开发验证。`moon package --list` 可预览发布归档。

## 许可证

项目代码采用 [Apache-2.0](LICENSE)。解码实现参考固定版本的 minimp3；其原始代码采用 CC0-1.0，许可文本保留在 [`third_party/minimp3/LICENSE`](third_party/minimp3/LICENSE)。
