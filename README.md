# mp3.mbt

纯 MoonBit MP3 → PCM 解码库，模块名为 `enanandesu/mp3`。

当前已建立第一阶段的基础解析、参考工具、语料与验证规则，尚未提供完整解码 API。
计划支持 MPEG-1/2/2.5 Layer III，并在 native、wasm、wasm-gc、js 四个后端运行。
核心库不引入第三方运行时依赖。

## 工程结构

- `moon.mod.json`：模块配置，默认后端为 wasm-gc。
- `moon.pkg.json`：根目录库包配置。
- `internal/bitstream`：有界 MSB-first 读位，失败不改变位置。
- `internal/header`：三版本 Layer III 帧头、长度及兼容性检查。
- `internal/tags`：有界 ID3v2 跳过与 EOF 下 ID3v1/TAG+ 尾边界。
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
python tools/validate_stage1.py
```

它验证固定环境、上游哈希、C 对照、四后端测试、参考 PCM 重复生成、数值比较
及缺陷注入，结果只打印到终端；不改写冻结规则或访问 GitHub。

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

当前每个后端 27 项测试，测试内含边界枚举和 3298 条实际 C 对照向量。
C 参考程序只用于开发验证，不参与 MoonBit 库运行。

下一阶段开始 Side Info、reservoir、比例因子、Huffman 与反量化。
完整解码、增量状态机、CLI、浏览器示例和性能验收尚未开始。
