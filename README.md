# mp3.mbt

纯 MoonBit MP3 → PCM 解码库，模块名为 `enanandesu/mp3`。

当前提供 MPEG-1 Layer III 整段解码：32/44.1/48 kHz、单/双声道、普通立体声、
Mid/Side 与 Intensity Joint Stereo、长/短/混合块、CBR/VBR/ABR 和跨帧 reservoir。
实现使用 Float（f32），面向 native、wasm、wasm-gc、js 四个后端。
核心库不引入第三方运行时依赖。

## 工程结构

- `moon.mod.json`：模块配置，默认后端为 wasm-gc。
- `moon.pkg.json`：根目录库包配置。
- `internal/bitstream`：有界 MSB-first 读位，失败不改变位置。
- `internal/header`：三版本 Layer III 帧头、长度及兼容性检查。
- `internal/tags`：有界 ID3v2 跳过与 EOF 下 ID3v1/TAG+ 尾边界。
- `internal/layer3`：Side Info、reservoir、频谱、立体声、IMDCT 及连续合成滤波。
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
python tools/validate_mpeg1.py
```

它先运行 `validate_stage1.py` 验证固定环境、参考基线和比较器，再核验全部生成表与
C 对照向量、完整 MPEG-1 PCM、四后端连续帧检查点和公开入口边界。
四后端 release 测量使用固定 48 kHz 双声道样本：预热 3 次，7 轮各解码 5 次，
打印中位耗时和最慢一轮的平均耗时；计时包含解码及分配，不含文件 I/O。
结果只打印到终端；不改写冻结规则或访问 GitHub。

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
let audio = @mp3.decode_mpeg1(mp3_bytes)
// audio.sample_rate / audio.channels / audio.samples（交织 Float）
```

错误通过 `Mp3Error` 抛出。输出保留原始采样率、声道数和所有解码帧，不自动裁剪
Xing 帧、encoder delay 或 padding。CRC 正确跳过但不校验；中途损坏、历史不足、
不完整帧、采样率或声道数变化都报错。输出样本总数、开头扫描和标签大小有上限。
`decode_mpeg1` 暂为整段接口；MPEG-2/2.5、free-format、有背压的增量接口、
CLI、浏览器示例及最终性能目标属于后续范围。

固定参考语料中的 `l3-hecommon` 在偏移 4179 使用保留 emphasis 值，因此按严格
帧头契约拒绝；其前 10 个未修改的合法帧仍参与连续 PCM 对照。
`l3-sin1k0db` 的初始历史不足、`l3-compl` 的末帧截断也以明确错误验收。
这些边界不会通过跳帧或修改误差阈值转为成功。数值比较仍使用
`tests/reference_policy.json` 的固定规则。
