# mp3.mbt

纯 MoonBit 的 MP3（MPEG-1/2/2.5 Layer III）解码库。输入压缩字节，输出原始采样率的交织 `Float`（f32）PCM；解码核心没有第三方运行时依赖。

提供整段与同步增量解码 API，以及独立的 MP3→WAV 命令和浏览器播放示例。

提供默认严格模式和显式兼容模式；验收范围、固定参考 PCM 对照及性能实测见[测试结果](docs/TEST_RESULTS.md)。

[English](README.en.md)

## 支持范围

- MPEG-1、MPEG-2、MPEG-2.5 Layer III 的九种采样率，单声道与双声道。
- 普通立体声、Mid/Side 和 Intensity Joint Stereo；长块、短块与混合块。
- CBR、VBR、ABR、有界 free-format 和跨帧 bit reservoir。
- `native`、`wasm`、`wasm-gc`、`js` 四个目标后端。

库只负责解码，不读取文件或播放音频。输出是按帧顺序排列的交织采样：双声道时依次为左、右、左、右。

## 示例

### MP3→WAV 命令

从仓库根目录运行；输出为原采样率、原声道数的 16 位小端 PCM WAV：

```sh
moon run examples/mp3-to-wav --target native --release -- input.mp3 output.wav
```

Windows 上使用本仓库锁定的 MinGW 工具链时，先在 PowerShell 设置：

```powershell
$env:MOON_CC = (Resolve-Path tools/moon-cc-mingw.cmd).Path
$env:MOON_AR = (Get-Command ar).Source
```

原因见下方“开发与验证”。命令不会覆盖已有输出文件。若解码或写入失败，会返回非零状态并删除本次生成的未完成 WAV。WAV 使用普通 RIFF 格式，单文件最大约 4 GiB；PCM 不做 gapless 首尾裁剪。

### 浏览器播放

```sh
moon build examples/browser --target js --release
python -m http.server 9010
```

打开 [本地浏览器示例](http://127.0.0.1:9010/examples/browser/)。选择或拖入本地 MP3 后，MoonBit 的 JS 后端先解码为 PCM，再交给 Web Audio 播放；页面提供播放、暂停、进度、音量和波形。示例不调用浏览器原生 MP3 解码，也不上传文件。单文件上限 16 MiB，解码后上限 1000 万个交织采样；超过限额会显示错误。浏览器页面需要通过 HTTP 服务访问，不能直接打开 `index.html`。

## 引入模块

如果模块已发布到 mooncakes.io，可在使用方项目运行 `moon add enanandesu/mp3`。本地开发可在两个模块的共同父目录建立 `moon.work`，例如：

```text
members = ["myapp", "mp3.mbt"]
```

在使用方的 `moon.mod` 中声明模块依赖，并在使用方包的 `moon.pkg` 中导入根包：

```text
// myapp/moon.mod
import {
  "enanandesu/mp3@0.1.0",
}

// myapp/moon.pkg
import {
  "enanandesu/mp3",
}
```

`members` 路径按实际目录调整；工作区内会使用本地模块。包导入后默认别名为 `@mp3`。

公开类型、方法、限额和错误语义见 [API 文档](docs/API.md)。

正确性、鲁棒性和性能的实测结果见 [测试结果](docs/TEST_RESULTS.md)。

## 整段解码

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
let sample_rate = audio.sample_rate
let channels = audio.channels
let samples = audio.samples
```

`mp3_bytes` 是调用方提供的 `Bytes`；`samples` 为交织 `Array[Float]`。`decode_all` 在没有音频、输入损坏或触及资源限额时抛出 `Mp3Error`。`decode_mpeg1` 是只接受普通码率 MPEG-1 Layer III 的旧入口，不是兼容模式。

## 增量解码

`Decoder::new(limits?, mode?, on_recovery?)` 创建独立的解码状态和固定容量输入缓冲。调用顺序如下：

1. 用 `push(input, offset?)` 提交字节，并保存未被接收的部分；返回值是实际接收的字节数。
2. 反复调用 `next_frame()`：`Frame(frame)` 提供一帧 PCM；`NeedMoreInput` 表示需要更多字节；`EndOfInput` 表示已结束。
3. 全部字节被接收后调用 `finish_input()`，继续读取直到 `EndOfInput`。

`push` 返回 0 表示背压，应先消费 `next_frame()` 的输出再重试。`PcmFrame` 含 `sample_rate`、`channels`、`source_offset` 和交织的 `samples`。已返回的采样数组归调用方所有；`reset()` 会清除输入和解码历史，保留限额配置。致命解码错误后需 `reset()` 才能复用该实例。

默认限额由 `Limits::default()` 提供：输入缓冲 8192 字节、单个前置 ID3v2 标签 16 MiB、开头非标签扫描 65536 字节、free-format 帧长上限 2304 字节。整段接口最多输出 67108864 个交织采样；增量接口不累计已输出的 PCM。

## 已知边界

- 不自动裁剪 Xing 帧、encoder delay 或 padding；CRC 字段会跳过，但不会校验。
- 严格模式遇到历史不足、不完整帧或格式变化会报错。兼容模式仅恢复下述四类情况；中途损坏、开始输出后的历史不足、采样率或 MPEG 版本变化仍报错。
- 8 kHz mixed block 使用有界频带布局，与未修改的 minimp3 在该路径有已知差异；证据范围见 [Layer III 说明](internal/layer3/README.md)。

## 开发与验证

以下验证命令需要完整仓库检出；本地发布归档不包含参考语料与验证脚本。

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

该脚本需要 Python 3.11+、GCC/MinGW（含 `ar`）、FFmpeg/FFprobe 和 Node；固定工具版本见 [`tools/toolchain.lock.json`](tools/toolchain.lock.json)。Windows 上的验证脚本会通过 [`tools/moon-cc-mingw.cmd`](tools/moon-cc-mingw.cmd) 为当前 MoonBit 运行时编译预定义 `_CRT_RAND_S`。直接运行 native 测试时，需将 `MOON_CC` 指向该脚本，并将 `MOON_AR` 指向 `ar.exe`。`moon package --list` 可预览本地归档，`.moonignore` 会排除仅供仓库验证的语料和工具。

两个示例的独立验收命令：

```sh
python tools/test_mp3_to_wav.py
node tools/test_browser_decode.mjs
```

浏览器交互测试可选：按 [CI 说明](docs/CI.md#浏览器依赖与运行) 将固定的 Playwright 依赖安装到 `target/browser-test/`，然后运行 `python tools/test_browser_ci.py`；脚本自动启停临时 HTTP 服务。默认使用 Windows Edge；其他系统可通过 `EDGE_PATH` 指定 Chromium 可执行文件。以上安装仅进入被忽略的 `target/`，不是库的运行时依赖。Linux 工具链准备和独立锁文件也见 [CI 说明](docs/CI.md)。

## 严格模式与兼容模式

`decode_all`、`decode_mpeg1` 和未指定模式的 `Decoder`、`decode_frames` 均使用严格模式。需要兼容模式时使用逐帧整段结果：

```moonbit
let stream = @mp3.decode_frames(mp3_bytes, mode=Compatible)
let frames = stream.frames
let recoveries = stream.recoveries
```

`DecodedStream` 保留每个 `PcmFrame` 的格式和原始偏移，不隐式转换声道。增量接口使用 `Decoder::new(mode=Compatible, on_recovery=event => println(event))`；回调同步消费恢复事件，解码器不累计事件。输入分块不会改变 PCM、偏移或恢复记录。

| 向量 | 兼容模式行为 |
| --- | --- |
| `compl.bit` | 确认 EOF 后丢弃不完整尾帧，记录偏移和丢弃字节数；EOF 前继续等待输入。 |
| `hecommon.bit` | 接受保留 emphasis 值 2，校验其他帧头字段并记录所在帧；不执行去加重处理。 |
| `sin1k0db.bit` | 初始缺少 reservoir 历史的帧不输出 PCM，但保留可用历史和 main data；记录所需/已有历史及帧偏移。首次输出后的历史不足仍为致命错误。尾帧按 EOF 规则处理。 |
| `he_mode.bit` | 保留每个 `PcmFrame.channels` 并记录声道变化；整段用 `decode_frames` 返回逐帧数组，`decode_all` 仍拒绝声道变化。 |

验收分别统计严格模式的完整 PCM 通过与预期拒绝，以及兼容模式的完整 PCM 通过。完整 PCM 需同时符合固定 minimp3 浮点参考及随附 s16 参考的冻结规则。该清单是 minimp3 README 的 11 项 ISO 子集，不是完整 ISO 官方认证。

## 维护与后续方向

每次修改运行四后端回归、异常语料、差分矩阵与兼容模式验收。自动化配置及平台工具链说明见 [CI](docs/CI.md)，浏览器与其他操作系统的实测方法见 [性能测量](docs/PERFORMANCE.md)。验证脚本将生成语料、失败复现输入和机器可读报告保存在被忽略的 `target/`。

可按实际需求继续评估 gapless 裁剪、CRC 校验、seek/索引、更完整的 ID3 读取及异步输入适配。MP3 编码、Layer I/II、SIMD 和定点实现属于独立范围。发布前复核支持边界、许可证、打包清单和使用方导入验证。

## 许可证

项目代码采用 [Apache-2.0](LICENSE)。解码实现参考固定版本的 minimp3；其原始代码采用 CC0-1.0，许可文本保留在 [`third_party/minimp3/LICENSE`](third_party/minimp3/LICENSE)。仓库中复制的上游测试向量来自该版本的 `vectors/`，逐项来源和 SHA-256 见 [`tests/corpus/manifest.json`](tests/corpus/manifest.json)；它们不属于本项目原创代码。
