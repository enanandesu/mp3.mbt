# mp3.mbt

纯 MoonBit MP3 → PCM 解码库，模块名为 `enanandesu/mp3`。

当前仅完成库工程初始化，尚未实现解码功能或公开 API，也没有测试用例。
计划支持 MPEG-1/2/2.5 Layer III，并在 native、wasm、wasm-gc、js 四个后端运行。
核心库不引入第三方运行时依赖。

## 工程结构

- `moon.mod.json`：模块配置，默认后端为 wasm-gc。
- `moon.pkg.json`：根目录库包配置。
- `mp3.mbt`：后续解码实现的源码入口。
- `pkg.generated.mbti`：由 `moon info` 生成的公开接口描述。

## 本地开发

本次初始化使用的工具链：

- moon `0.1.20251222`（`3f6c70c`）
- moonc `v0.6.36+607dbed8f`

在项目根目录执行：

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

当前 `moon test` 的用例数为 0；这些命令用于验证工程和工具链。
后续按实施方案补充解码代码、参考对照及真实测试，再验证解码正确性。
