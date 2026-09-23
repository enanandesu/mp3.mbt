# mp3.mbt

纯 MoonBit MP3 → PCM 解码库，模块名为 `enanandesu/mp3`。

提供 MPEG-1/2/2.5 Layer III 整段与同步增量解码：全部九种采样率、单/双声道、
普通立体声、Mid/Side 与 Intensity Joint Stereo、长/短/混合块、CBR/VBR/ABR、
有界 free-format 和跨帧 reservoir。
实现使用 Float（f32），面向 native、wasm、wasm-gc、js 四个后端。
核心库不引入第三方运行时依赖。

## 工程结构

- `moon.mod.json`：模块配置，默认后端为 wasm-gc。
- `moon.pkg.json`：根目录库包配置。
- `internal/bitstream`：有界 MSB-first 读位，失败不改变位置。
- `internal/header`：三版本 Layer III 帧头、长度及兼容性检查。
- `internal/tags`：有界 ID3v2 跳过与 EOF 下 ID3v1/TAG+ 尾边界。
- `internal/framing`：有界 free-format 长度发现及完整帧边界。
- `internal/layer3`：Side Info、reservoir、频谱、立体声、IMDCT 及连续合成滤波。
- `streaming.mbt`：固定容量输入缓冲、背压、EOF 和持久解码状态。
- `third_party/minimp3`：固定提交的原始源码、说明和许可证。
- `tests/corpus`：带 SHA-256 的分类语料及既有参考 PCM。
- `tests/reference_policy.json`：冻结的长度、数值和参考差异规则。
- `tools`：参考驱动、PCM 比较器、C 对照向量生成器及本地验收。
- `pkg.generated.mbti`：由 `moon info` 生成的公开接口描述。

## 本地开发

本次初始化使用的工具链：

- moon `0.1.20251222`（`3f6c70c`）
- moonc `v0.6.36+607dbed8f`

验证工具另需 Python、GCC、FFmpeg/FFprobe、Node；固定版本和二进制哈希见
`tools/toolchain.lock.json`。不需要第三方 Python 包。

完整离线验收：

```powershell
python tools/validate_compatibility.py
```

它先运行 `validate_stage1.py` 验证固定环境、参考基线和比较器，再检验三版本完整
PCM、九种采样率、free-format、四后端连续帧检查点、分块一致性和公开入口边界。
原 MPEG-1 验证与 release 性能测量仍可运行 `python tools/validate_mpeg1.py`：
固定 48 kHz 双声道样本，预热 3 次，7 轮各解码 5 次，计时包含解码及分配，
不含文件 I/O。结果只打印到终端；不改写冻结规则或访问 GitHub。

开发约定：不生成或提交阶段总结、执行记录汇总等报告。验证所需的临时数据只放在
已忽略的 `target/` 中；持久化诊断文本应隐藏本机绝对路径、用户目录和进程地址。
源码对应关系保留在实现注释及包说明中，已知参考差异见 `tests/reference_policy.json`。

日常 MoonBit 开发：

```powershell
moon check
moon build
moon test
moon info
moon fmt --check
```

四后端验证命令：

```powershell
foreach ($backend in @("native", "wasm", "wasm-gc", "js")) {
  moon check --target $backend
  if ($LASTEXITCODE -ne 0) { throw "$backend check failed" }
  moon build --target $backend
  if ($LASTEXITCODE -ne 0) { throw "$backend build failed" }
  moon test --target $backend
  if ($LASTEXITCODE -ne 0) { throw "$backend test failed" }
}
```

测试包含基础解析的 3298 条 C 对照、64 个连续帧的 Side Info/reservoir 对照、
561 个频谱用例、66 个立体声/IMDCT 用例及 22 个连续合成 granule。
验收脚本另在 `target/` 生成跨后端的完整 PCM 和逐层检查点测试；
反量化、立体声、IMDCT、PCM、读位位置及保留状态均与固定 C 源码对应。
C 参考程序和文件 I/O 适配器只用于开发验证，不参与 MoonBit 核心库运行。

## 使用与边界

导入 `enanandesu/mp3` 后，以完整 MP3 字节调用：

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
// audio.sample_rate / audio.channels / audio.samples（交织 Float）
```

错误通过 `Mp3Error` 抛出。输出保留原始采样率、声道数和所有解码帧，不自动裁剪
Xing 帧、encoder delay 或 padding。CRC 正确跳过但不校验；中途损坏、历史不足、
不完整帧、采样率或声道数变化都报错。输出样本总数、开头扫描和标签大小有上限。
`decode_mpeg1` 保留为仅接受 MPEG-1 普通码率的兼容入口，内部使用相同的状态机。
CLI、浏览器示例及最终性能目标属于后续范围。

增量 API：

| 操作 | 契约 |
| --- | --- |
| `Decoder::new(limits?)` | 创建固定容量输入缓冲和独立 DSP 状态；非法配置报 `InvalidLimits` |
| `push(input, offset?) -> Int` | 复制能接收的字节并返回数量；从 `offset` 开始，默认 0；返回 0 时先消费输出再重试 |
| `next_frame() -> DecodeResult` | 返回 `Frame(PcmFrame)`、`NeedMoreInput` 或 `EndOfInput`；错误抛 `Mp3Error` |
| `finish_input()` | 所有输入被接收后确认 EOF；可重复调用，随后继续消费帧直到结束或错误 |
| `reset()` | 清空输入、EOF、错误、reservoir、overlap 和合成历史；保留限额 |
| `buffered_bytes() -> Int` | 当前未消费的输入字节数 |

调用者须保存尚未被 `push` 接收的部分；每次输入后可持续调用 `next_frame`，直到
`NeedMoreInput`。不要把背压下未接收的字节丢弃，也不要提前确认 EOF。
`PcmFrame` 含 `sample_rate`、`channels`、`source_offset: Int64` 和交织
`samples: Array[Float]`。PCM 归调用者所有，后续解码或 reset 不会覆盖它；修改
已返回的数组也不会改变后续解码结果。偏移包括跳过的标签及开头垃圾。

数据暂不足时不修改半帧 DSP 状态；只有确认 EOF 才将不完整帧报告为截断。
致命解析或解码错误后，`push`、`next_frame`、`finish_input` 均报 `FailedDecoder`，
直到 reset。越界的 push 参数和 EOF 后 push 属于调用错误，不破坏原状态。
空增量流结束返回 `EndOfInput`；`decode_all` 对没有音频的输入报 `NoAudio`。
最初从第一个合法帧头开始解码，之后不自动跳过坏帧；合法形态的伪帧头仍可能造成
结构化解码错误。不能检测所有仍构成合法码流的位翻转。

默认资源限额：

| `Limits` 字段 | 默认值 | 含义 |
| --- | ---: | --- |
| `max_buffer_bytes` | 8192 | 输入环形缓冲容量；允许 2885..1048576，且须满足 free-format 前看空间 |
| `max_tag_bytes` | 16777216 | 每个前置 ID3v2 标签总长，包含头和可选 footer；大标签分段跳过 |
| `max_initial_scan` | 65536 | 最多跳过的开头非标签字节数 |
| `max_free_format_bytes` | 2304 | 无 padding 的总帧长上限，配置范围 4..2304；实际帧还须容纳 side info |
| `max_output_samples` | 67108864 | 仅整段接口的交织样本数量上限；增量接口不累计输出 |

free-format 初次发现要求三个兼容帧头及一致间距；EOF 时也接受恰好两个完整帧，
不猜测孤立帧长度。帧头发现默认最多前看 4614 字节，另预留 355 字节等待可能的
ID3v1/TAG+ 尾标签；输入缓冲至少需要 `2 * (max_free_format_bytes + 1) + 4 + 355`
字节（默认限额下为 4969）。这样两帧后接尾标签也能等待 EOF，不会因背压卡住。
长度已确定后可以直接输出最后一帧。
增量解码不保存已输出 PCM；环形缓冲、reservoir（至多 511 字节）、overlap、合成
状态与帧内工作区的规模都与音频时长无关，输出的保留量由调用者决定。

测试中的随机种子、次数和范围写在可执行测试中，验证不生成阶段报告。原始语料、
确定性生成器与固定种子的失败输入可重复运行；有限测试不构成对任意输入的证明。

固定参考语料中的 `l3-hecommon` 在偏移 4179 使用保留 emphasis 值，因此按严格
帧头契约拒绝；其前 10 个未修改的合法帧仍参与连续 PCM 对照。
`l3-sin1k0db` 的初始历史不足、`l3-compl` 的末帧截断也以明确错误验收。
这些边界不会通过跳帧或修改误差阈值转为成功。数值比较仍使用
`tests/reference_policy.json` 的固定规则。
