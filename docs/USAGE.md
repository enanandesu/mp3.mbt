# 实际用例：把本地 MP3 交给剪辑与分析工具

[English](USAGE.en.md) · [返回 README 示例](../README.md#示例)

假设你有一段录音或播客的 MP3，需要先确认内容，再把 PCM 交给剪辑软件或自己的分析程序。本例用仓库自带的短提示音走完流程；之后只需换成自己的文件路径。

[示例音频](../examples/browser/sample.mp3) 是原创数学合成的 3 秒三音提示音，采用 44.1 kHz 双声道、128 kbps CBR，文件大小 48483 字节；按项目 Apache-2.0 许可提供，不含外部录音。需要重新生成时可运行 [生成脚本](../tools/generate_demo_audio.py)。

MP3→WAV 命令和浏览器页面都使用本库解码，文件不会上传到远端。按下面两步即可完成转换与试听。

## 1. 把 MP3 转为 WAV

从仓库根目录运行。需要 MoonBit 和 native 后端所用的 C 编译器、`ar`；固定工具链见 [CI 说明](CI.md)。转换本身不需要 FFmpeg。

Windows 使用本仓库的 MinGW 工具链时，先在同一个 PowerShell 窗口设置：

```powershell
$env:MOON_CC = (Resolve-Path tools/moon-cc-mingw.cmd).Path
$env:MOON_AR = (Get-Command ar).Source
```

创建输出目录，转换内置示例：

```sh
python -c "from pathlib import Path; Path('target/usage-demo').mkdir(parents=True, exist_ok=True)"
moon run examples/mp3-to-wav --target native --release -- examples/browser/sample.mp3 target/usage-demo/sample.wav
```

该内置文件的实际输出为：

```text
WAV: 44100 Hz, 2 channel(s), 267264 samples
```

生成的 WAV 为 534572 字节，包含每声道 133632 个采样，解码时长约 3.03 秒。

将生成的 `target/usage-demo/sample.wav` 导入支持 PCM WAV 的剪辑软件即可。输出保留原采样率和声道数，采用 16 位小端 PCM；`samples` 表示所有声道合计的交织采样数，不是每声道的采样数。

处理自己的文件时替换两个路径；包含空格的路径要加引号：

```sh
moon run examples/mp3-to-wav --target native --release -- "recording.mp3" "target/usage-demo/recording.wav"
```

命令逐帧读取、解码和写出，不会累计整段 PCM，适合较长录音。输出使用普通 RIFF WAV，最大约 4 GiB。已有输出不会被覆盖；再次试跑请换一个输出文件名。输入损坏或写入失败时，命令以非零状态退出，并删除本次未完成的 WAV。

这里使用默认严格模式，不自动修补损坏的 MP3；也不自动去除编码延迟和尾部 padding。因此精确剪辑时应按实际波形确认起止位置，不能假定解码时长恰好等于编码前时长。

## 2. 在浏览器试听并看波形

仍在仓库根目录运行：

```sh
moon build examples/browser --target js --release
python -m http.server 9010 --bind 127.0.0.1
```

打开 [本地演示页面](http://127.0.0.1:9010/examples/browser/)，点击 **Load demo audio**。看到波形与采样率、声道、时长后，点击 **Play**，拖动进度条定位，再暂停。也可选择或拖入自己的 MP3；结束后在服务终端按 `Ctrl+C`。

页面先由 MoonBit JS 后端完成整段解码，再由 Web Audio 播放 PCM；没有调用浏览器原生 MP3 解码。它接受 MP3 输入；第一步生成的 WAV 用于后续剪辑或分析工具。

较长文件需在加载前调整两项设置：

- **File size limit (MiB)** 限制压缩输入大小，默认 16 MiB；页面标注的桌面建议上限为 512 MiB，允许继续调高。
- **Decoded PCM limit (samples)** 限制所有声道合计的输出采样数，默认 1000 万，通过 `Limits.max_output_samples` 生效。时长约为 `samples / channels / sample_rate`；例如 44.1 kHz 双声道的 5 分钟音频约需 2646 万个采样，还应留出 MP3 帧与编码 padding 的余量。

输入小不代表解码占用小。页面会显示 f32 PCM 大小和参考时长，但复制、播放缓冲等还要额外内存；可输入的最大整数不等于浏览器能实际容纳的输出。整段浏览器播放适合试听；长录音转 WAV 可优先使用上面的增量命令。

## 3. 在自己的 MoonBit 程序里使用 PCM

按 [README 的引入模块说明](../README.md#引入模块) 导入根包后，将文件、网络或其他输入层取得的 `Bytes` 交给本库。例如，计算音频时长和采样峰值：

```moonbit
fn summarize_mp3(mp3_bytes : Bytes) -> Unit raise @mp3.Mp3Error {
  let defaults = @mp3.Limits::default()
  let limits = { ..defaults, max_output_samples: 30000000 }
  let audio = @mp3.decode_all(mp3_bytes, limits~)
  let seconds = audio.samples.length().to_double() /
    audio.channels.to_double() /
    audio.sample_rate.to_double()
  let mut peak : Float = 0.0
  for sample in audio.samples {
    let magnitude = if sample < 0.0 { -sample } else { sample }
    if magnitude > peak {
      peak = magnitude
    }
  }
  println("duration: \{seconds} s, peak: \{peak}")
}
```

将内置 `sample.mp3` 的字节传给该函数，实测输出为：

```text
duration: 3.030204081632653 s, peak: 0.3119922876358032
```

这里的 3000 万是本次调用的采样上限，约 114.4 MiB 的 f32 PCM，不是预分配大小；实际还有运行时及解码开销。函数会向调用方传播 `Mp3Error`，包括超过上限的 `OutputLimit`。文件读取、错误展示和后续分析由调用方负责。

需要处理长文件或边读边分析时，可参照 [WAV 示例源码](../examples/mp3-to-wav/main.mbt) 使用增量 `Decoder`，每得到一个 `PcmFrame` 就处理并释放它；避免积累所有帧。完整的背压、EOF 和限额语义见 [API 文档](API.md#增量解码)。
