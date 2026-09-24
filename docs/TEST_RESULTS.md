# 测试结果与验收状态

记录日期：2026-09-24。测试时的源码基线：`e152f91`，并包含测试生成器的 `wbtest` 导入修复。环境：Windows 11 64 位（10.0.26200）、Intel Core i9-14900HX；MoonBit、minimp3、FFmpeg 和 Node 的精确版本与哈希见 [`tools/toolchain.lock.json`](../tools/toolchain.lock.json)。

## 结论速览

| 要求 | 本次可确认的结果 | 验收状态 |
| --- | --- | --- |
| 正确性：minimp3 ISO Layer III 子集全部通过，PCM RMS 达标 | 固定 minimp3 README 表中的 **11 项已全部列入并实际执行**；7 项完整 PCM 通过，4 项被当前严格解码接口拒绝。另有 24/24 个选取的完整兼容文件通过。 | **未完成**：11 项中只有 7 项通过完整 PCM 验收。 |
| 鲁棒性：FFmpeg 差分覆盖版本、码率、声道模式；损坏/截断/随机字节无 panic | 九种采样率、三种 MPEG 版本、CBR/VBR/ABR、free-format，以及有限的损坏、截断和固定种子随机输入已经执行。24 个完整文件中，20 个满足独立 FFmpeg 普通比较规则，4 个命中冻结例外。没有覆盖全部码率与声道模式组合；16 个异常语料文件当前只在主流程校验哈希。 | **部分满足**：已测输入无 panic，覆盖矩阵和异常语料执行门槛不足。 |
| 性能：native ≥10×、wasm ≥1× 实时 | 单个 0.384 秒 MPEG-1 双声道样本的 release 测试：native 中位数 **225.2×**，wasm 中位数 **125.5×**。 | **样本达标，整项未验收**：只测 `decode_mpeg1` 的一个短样本，尚无跨版本性能门槛断言。 |

这里的“通过”仅指列出的输入和配置；固定种子测试不能证明任意字节都不会触发 panic。

## 正确性

固定 [minimp3 README 的符合性表](https://github.com/lieff/minimp3/blob/ea99364f61c14656440e8d77e9c233ccf3124633/README.md) 列出 11 个向量。这是 minimp3 自称的 ISO 符合性测试子集，**不是 ISO 官方测试包的完整清单**。[`tests/iso_layer3_manifest.json`](../tests/iso_layer3_manifest.json) 保存这 11 个名称；[`tools/validate_iso_layer3.py`](../tools/validate_iso_layer3.py) 核对它与固定 README 表逐项一致，并检查输入及随附 PCM 哈希，然后用 native 测试适配器逐项运行当前 `decode_all`。只有完整解码成功且 f32 与固定 minimp3 标量参考、s16 与随附 PCM 均达标才计为通过。

| minimp3 表中向量 | 完整 PCM | f32 RMSE / s16 PSNR，或失败原因 |
| --- | --- | --- |
| `compl.bit` | 未通过 | `TruncatedFrame(41472, 192)` |
| `he_32khz.bit` | 通过 | 0 / 127.74 dB |
| `he_44khz.bit` | 通过 | 0 / 132.13 dB |
| `he_48khz.bit` | 通过 | 0 / 127.74 dB |
| `hecommon.bit` | 未通过 | `InvalidHeader(4179)` |
| `he_free.bit` | 通过 | 0 / 127.28 dB |
| `he_mode.bit` | 未通过 | `FormatChange(4179)` |
| `si.bit` | 通过 | 0 / 107.76 dB |
| `si_block.bit` | 通过 | 0 / 111.63 dB |
| `si_huff.bit` | 通过 | 0 / 100.02 dB |
| `sin1k0db.bit` | 未通过 | `DecodeFailure(215, InsufficientHistory(461, 0))` |

`hecommon` 含保留的 emphasis 位，`he_mode` 在同一输入中切换声道数，`compl` 末尾有不完整帧，`sin1k0db` 开头缺 reservoir 历史。这四项目前在错误处停止；“按现有 API 错误契约通过”不能替代 minimp3 的完整符合性结果。7 项成功文件的随附 s16 参考有已冻结的短尾差异时，仅比较明确批准的共同样本范围；详情见 `legacy_pcm_extra_interleaved_samples`。

另一个语料清单 [`tests/corpus/manifest.json`](../tests/corpus/manifest.json) 自述为“Selected Layer III inputs, not a count of ISO conformance cases”。其中有 15 个来自固定 minimp3 提交的 `normal` 条目、9 个 FFmpeg/libmp3lame 生成的 `normal` 条目，以及 1 个 `alignment` 条目。`l3-hecommon` 虽归为 `normal`，但完整流按错误契约拒绝，前 10 帧另作对照。因此此前的完整 PCM 结果是 **14 个上游 + 9 个生成 + 1 个 alignment = 24/24**；它与上面的 **7/11** 是两个不同的分母。

固定比较规则见 [`tests/reference_policy.json`](../tests/reference_policy.json)：f32 RMSE ≤ `1e-6`、最大绝对误差 ≤ `1e-4`、PSNR ≥ 96 dB；s16 PSNR ≥ 96 dB。2026-09-24 复跑 `python tools/validate_compatibility.py --skip-foundation`，24 个完整文件的 f32 RMSE、最大误差均为 **0**。脚本也核对采样率、声道数、样本数、语料哈希、连续 C 解码器检查点和分块解码等价性。8 kHz mixed block 在主流程只做结构检查；其修正路径另由 [`tools/verify_mixed_8000.py`](../tools/verify_mixed_8000.py) 的限定参考验证，不能计入未修改 minimp3/FFmpeg 的逐样本一致结果。

| 后端 | 仓库测试 | 生成的兼容性工作区测试 |
| --- | ---: | ---: |
| native | 90/90 | 83/83 |
| wasm | 90/90 | 83/83 |
| wasm-gc | 90/90 | 83/83 |
| js | 90/90 | 83/83 |

## FFmpeg 与异常输入

独立 FFmpeg 比较在 24 个完整文件上执行。**20/24** 满足普通 f32 比较规则；另外 4 个用例按事先冻结的原因验证其差异仍存在：`l3-he_free`（FFmpeg 不输出可比 PCM）、`l3-test45` 和 `l3-test46`（数值误差）、`generated-gapless-tagged`（样本数/延迟处理）。另外两个边界文件 `l3-compl`、`l3-sin1k0db` 也有冻结的 FFmpeg 样本数差异。例外不会放宽 minimp3 主参考阈值，详见 [`tests/reference_policy.json`](../tests/reference_policy.json) 的 `ffmpeg_exceptions`。

生成语料横跨 8、11.025、12、16、22.05、24、32、44.1、48 kHz；实测输入涵盖 MPEG-1/2/2.5、单/双声道、CBR/VBR/ABR 和 free-format。附加语法样本检查了 joint stereo 的 MS/intensity 与 12/24 kHz mixed 路径。它们不是“所有版本 × 所有码率 × 所有声道模式”的笛卡尔覆盖：完整差分语料没有专门的 Dual Channel 全流样本，也没有逐码率覆盖声明。

[`streaming_wbtest.mbt`](../streaming_wbtest.mbt) 对一帧的每个字节前缀、64 次固定种子位翻转、7 种噪声长度，以及 **一个固定种子生成的 256 个、长度 0–4096 字节**的伪随机输入检查整段与不同分块方式的结果一致；上述四后端测试均通过，没有出现测试进程 panic。异常语料目录另有 16 个条目，兼容性脚本目前校验其哈希，但未逐个执行解码断言。仍需把这些文件接入实际解码门槛，并增加更长输入和持续模糊测试，才能提高“任意损坏输入无 panic”这一表述的证据强度。

鲁棒性尚未验收的原因是**覆盖范围和执行门槛**：目前缺少专门的 Dual Channel 全流差分样本及完整码率/声道模式矩阵；16 个已保存的异常文件没有全部作为解码输入执行；固定种子与有限长度测试只能证实已测输入没有 panic。FFmpeg 的 4 个完整文件例外是两套解码器的已记录差异，不能统计为普通差分通过，也不是本次新发现的 panic。

## 性能

`python tools/validate_mpeg1.py --skip-foundation` 生成并运行 release 测试。固定输入为 `generated-48000-2ch-abr`：48 kHz、双声道、每声道 18,432 个采样，即 **0.384 秒**。计时使用 `decode_mpeg1`；预热 3 次，随后 7 批、每批 5 次，报告每批单次平均耗时的中位数及最慢一批。计时排除文件 I/O 和测试数据构造，包含解码及其分配。实时倍数 = `0.384 秒 / 单次平均耗时`。

| 后端 | 中位耗时 | 中位实时倍数 | 最慢批平均耗时 | 对应实时倍数 |
| --- | ---: | ---: | ---: | ---: |
| native | 1,705.14 µs | **225.2×** | 1,793.30 µs | 214.1× |
| wasm | 3,060.16 µs | **125.5×** | 3,352.60 µs | 114.5× |
| wasm-gc | 2,298.58 µs | 167.1× | 2,672.46 µs | 143.7× |
| js | 4,974.32 µs | 77.2× | 5,298.04 µs | 72.5× |

这些是本机 MoonBit 测试运行时的一次测量，不代表浏览器或其他设备。当前用例不测 `decode_all`、MPEG-2/2.5、长音频、增量解码，也没有自动断言 10×/1× 目标；上表只能证明该样本超过目标，不能作为整库性能验收。

性能尚未验收的原因是**测量口径不足**，不是已测样本低于速度目标。目标要求固定环境下的代表性解码速度；当前只有一段 0.384 秒的 MPEG-1 `decode_mpeg1` 输入，wasm 数据来自本机测试运行时，尚未覆盖目标浏览器/宿主，也未设立会因低于 10×/1× 而失败的自动门槛。

## 复现与待补

从仓库根目录运行：

```sh
python tools/validate_mpeg1.py
python tools/validate_compatibility.py --skip-foundation
python tools/validate_iso_layer3.py
```

第二条命令的 `--skip-foundation` 仅适用于第一条已经在同一轮执行中通过的情形；单独运行时使用 `python tools/validate_compatibility.py`。第三条命令将机器可读结果写到被忽略的 `target/iso-layer3/results.json`；加 `--require-all` 可将当前 7/11 的缺口转为非零退出码。性能输出以 `PERF audio_seconds=... median_us=... slowest_batch_us=...` 开头。Windows 上脚本会按锁文件设置 native 编译器和归档器。

要将三项要求标为“完成”，仍需：让 11 项符合性向量都达到完整 PCM 验收（需决定如何支持或另行定义严格 API 对四类边界输入的符合性范围）；给 FFmpeg 差分语料补齐目标码率/声道模式矩阵并对 16 个异常文件实际解码；对代表性的三版本长音频及 `decode_all`/增量路径建立固定环境性能门槛，并单独确认 wasm 的目标运行时。
