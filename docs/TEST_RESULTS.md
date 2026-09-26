# 测试结果与验收范围

2026-09-26 验证。Windows 11 / Intel Core i9-14900HX 的完整参考环境见 [`tools/toolchain.lock.json`](../tools/toolchain.lock.json)。Linux/WSL 的独立工具链与执行范围见 [CI 说明](CI.md)；浏览器、native、wasm 的逐批性能及进程内存测量见 [性能记录](PERFORMANCE.md)。以下均为所列输入和配置的实测，不构成完整 ISO 认证或任意损坏字节安全性的证明。

## 验收门槛

| 范围 | 结果 | 含义 |
| --- | --- | --- |
| minimp3 README 的 ISO Layer III 子集 | 兼容模式 **11/11** 完整 PCM 通过 | 每帧偏移/采样率/声道/样本数与未修改的固定 minimp3 一致；全部 f32 RMSE 为 0，随附 s16 参考达标 |
| 同一子集的严格模式 | **7** 项完整 PCM + **4** 项预期拒绝 | 严格错误契约保持不变，拒绝不计入 PCM 成功 |
| 原完整语料 | **24/24** minimp3 PCM 通过 | FFmpeg 普通差分 **20/24**，另 4 项冻结例外保持；两个分母不混用 |
| 仓库回归 | 四后端各 **95/95** | 原 90 项加 5 项兼容模式边界与回调状态测试 |
| 原生成兼容性工作区 | 四后端各 **83/83** | 参考 PCM、连续内部检查点、分块等价性及限定的结构检查 |
| 新 ISO 完整输入工作区 | 四后端各 **11/11** | 整段及单字节/混合/大块输入，双滚动哈希核验每帧 PCM 位模式，另核对元数据、恢复事件 |
| 异常与模糊回归 | 四后端各 **31/31** suites | 16 个固定异常文件、256 个随机输入、384 次位翻转、384 次截断、7 个 1 MiB 输入及四类已知恢复向量 |
| 码率/声道矩阵 | 四后端各 **558/558** | 504 个完整语法流 + 54 个编码音频流，均比较 minimp3 和 FFmpeg；包含 126 个 Dual Channel 流 |

四后端为 `native`、`wasm`、`wasm-gc`、`js`。上表的完整集成门槛已在 Windows 与同机 WSL2 Ubuntu 24.04 各通过一次；WSL 是另一操作系统环境，不代表独立硬件或裸机 Linux。默认 `python tools/validate_compatibility.py` 串行执行原参考门槛以及新增 ISO、鲁棒性和矩阵门槛；任一失败或超时均使整个命令失败。

## ISO 子集与恢复

[`tests/iso_layer3_manifest.json`](../tests/iso_layer3_manifest.json) 固定 minimp3 提交 `ea99364f61c14656440e8d77e9c233ccf3124633` README 表中的 11 个名称；脚本核对清单、上游来源和输入/随附 PCM 哈希。新参考适配器 [`tools/reference_frames.c`](../tools/reference_frames.c) 调用未修改的 minimp3，逐帧记录格式，允许保留混合声道；不修改第三方实现。

| 向量 | 严格模式 | 兼容 f32 RMSE | 随附 s16 PSNR | 恢复记录数 |
| --- | --- | ---: | ---: | ---: |
| `compl.bit` | `TruncatedFrame(41472, 192)` | 0 | 120.84 dB | 1 |
| `he_32khz.bit` | PCM 通过 | 0 | 127.74 dB | 0 |
| `he_44khz.bit` | PCM 通过 | 0 | 132.13 dB | 0 |
| `he_48khz.bit` | PCM 通过 | 0 | 127.74 dB | 0 |
| `hecommon.bit` | `InvalidHeader(4179)` | 0 | 123.64 dB | 1 |
| `he_free.bit` | PCM 通过 | 0 | 127.28 dB | 0 |
| `he_mode.bit` | `FormatChange(4179)` | 0 | 116.91 dB | 2 |
| `si.bit` | PCM 通过 | 0 | 107.76 dB | 0 |
| `si_block.bit` | PCM 通过 | 0 | 111.63 dB | 0 |
| `si_huff.bit` | PCM 通过 | 0 | 100.02 dB | 0 |
| `sin1k0db.bit` | `DecodeFailure(215, InsufficientHistory(461, 0))` | 0 | 111.01 dB | 3 |

浮点门槛为 RMSE ≤ `1e-6`、最大绝对误差 ≤ `1e-4`、PSNR ≥ 96 dB；s16 PSNR ≥ 96 dB。[`tests/reference_policy.json`](../tests/reference_policy.json) 与所有原语料哈希保持不变。8 个历史随附 s16 文件的短尾差异仅按既有 `legacy_pcm_extra_interleaved_samples` 比较批准的范围；f32 始终比较完整输出。

兼容模式报告 EOF 丢弃字节、保留 emphasis、初始 reservoir 历史不足和声道变化。`sin1k0db` 的 215 字节起始非音频区域仍受既有初始扫描策略控制；两个缺历史帧保留 main data 而不产生 PCM。`he_mode` 保留每帧声道格式，不执行统一声道转换。诊断期望从压缩头和参考帧边界独立推导，不能以被测输出自行定义通过。

native 对每个浮点样本执行数值比较。四后端附加测试按每帧两个独立 UInt 滚动哈希核验参考的全部 f32 位模式，且独立核对每帧偏移、采样率、声道、样本数和恢复事件顺序；它不替代 native 的逐样本误差门槛。

## 差分与鲁棒性

[`tests/differential_matrix.json`](../tests/differential_matrix.json) 声明九种采样率 × 14 个普通码率索引 × Stereo/Joint-MS/Dual Channel/Mono，共 504 个完整语法流。各流有独立编码的非零声道、4 帧和交替 padding；另有九种采样率 × 单/双声道 × CBR/VBR/ABR 的 54 个 FFmpeg/libmp3lame 编码 chirp。合成语法矩阵提供明确的字段覆盖，不代表所有编码工具组合或编码器多样性。

558 个流的 native PCM 对 minimp3 最大 RMSE 为 **0**；对 FFmpeg 最大 RMSE 为 **2.04444e-7**，最大绝对误差 **1.57952e-6**。四后端对两套完整参考逐样本执行冻结的数值门槛，没有新增例外。free-format、joint intensity、mixed/short 等路径仍由原专项语料覆盖；8 kHz mixed 的独立参考范围保持原限制，见 [Layer III 说明](../internal/layer3/README.md)。

原 24 个完整文件的 4 项 FFmpeg 例外仍为 `he_free`（无可比 PCM）、`test45`/`test46`（数值差异）、`generated-gapless-tagged`（延迟/样本数）。它们不计为普通 FFmpeg 差分成功，也不放宽 minimp3 阈值。

异常门槛读取真实文件并校验哈希后执行 MoonBit。16 个文件中 `l3-nonstandard-vbrtag-oob-read` 合法返回 44100 Hz、双声道、2304 个零采样；其余 15 个按 [`tests/robustness_expectations.json`](../tests/robustness_expectations.json) 的完整错误与偏移拒绝。不能把全部异常名称都预设为错误。

四个固定种子从 0–32768 字节区间选取 256 个随机输入；空输入另由固定异常语料覆盖，长输入达到 1 MiB。Strict 比较整段/分块的 Audio 采样率、声道、PCM 或完整错误；Compatible 还比较失败前的部分输出、逐帧元数据和偏移及恢复顺序。两种模式均检查非有限样本、内部缓冲上限与推进次数。后端进程有明确超时；报告记录种子、覆盖、状态和日志，失败时保存生成的复现工作区。有限回归不等于无限持续 fuzz 或任意输入安全性证明。

## 示例与辅助检查

Windows 的 Python 辅助测试 **20/20** 通过；MP3→WAV 示例在三个输入上的 s16 PSNR 分别为 **127.74 / 114.90 / 117.05 dB**，并验证拒绝覆盖现有文件、截断输入失败后清理输出。JS 桥接验证 22050 Hz、双声道、444672 个采样以及无音频错误；Edge 交互验证加载、波形、播放/暂停、seek、错误提示和响应式宽度。

2026-09-26 的浏览器可调文件限额验证默认拒绝、调大后加载、非法值修正、拖放及恰好上限/超出 1 字节的边界。本机 Edge 成功加载 **512 MiB** 的人工输入（32 个有界 ID3v2 标签加固定的 5.4 秒音频），renderer 生命周期峰值约 **624 MiB**；该实验验证输入容量，不代表同体积的长音频解码验收。该次测量的输出限额为 1000 万个交织采样；当前页面也可单独调整这一限额。

2026-09-27 的可调 PCM 限额验证覆盖页面到 `Limits.max_output_samples` 的传参：浏览器使用 172800 个采样的固定输入，上限设为 172799 时拒绝、调到 172800 后重新加载成功，非法值修正后可恢复。JS 桥接另验证 444672/444671 的精确边界，并将固定语料拼接为 **10227456 个采样**：旧默认 10000000 拒绝，提高到完整样本数后成功。该入口拒绝非整数、非数字及 Int 溢出；播放、波形和窄屏检查通过。Windows 完整 `validate_compatibility.py` 再次通过基础参考及四后端各 95/83/11/31/558 项门槛，日志保留在 `target/browser-pcm-compatibility.log`。

mixed 专项在限定补丁的独立 mpg123 参考下 **16/16** 通过，其中 8 kHz 8 例、12/24 kHz 对照各 4 例；全组最大绝对误差约 **1.3e-8**，来自 12/24 kHz 对照。MS 与 intensity 同时启用的组合不属于该独立参考的验收范围。格式检查、工作流 actionlint 静态检查和本地打包清单检查通过；这些不替代首次远程 CI 执行。

## 复现

```sh
moon check
moon test
moon fmt --check
python tools/validate_compatibility.py
python tools/verify_mixed_8000.py
python tools/test_mp3_to_wav.py
node tools/test_browser_decode.mjs
python tools/test_browser_ci.py
python tools/benchmark_release.py
python tools/benchmark_memory.py
node tools/benchmark_browser.mjs
```

完整参考门槛先精确验证工具链和固定源码。`--skip-foundation` 仅用于同一轮已经通过基础验证的情况。也可独立运行 `validate_iso_layer3.py --require-all`、`validate_robustness.py` 和 `validate_matrix.py`；它们默认运行全部四后端。

机器可读结果写入 `target/iso-layer3/results.json`、`target/robustness-validation/results.json`、`target/matrix-validation/results.json` 及性能脚本各自的目录。浏览器依赖、CI 工作流和自托管参考 runner 的准备方式见 [CI 说明](CI.md)。本地执行和工作流静态校验不等于远程 GitHub Actions 已运行。
