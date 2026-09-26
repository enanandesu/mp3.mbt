# CI 与平台工具链

仓库提供自动便携检查和手动完整参考验收两套独立门槛。2026-09-27（UTC+8）已核实：提交 [`058c499`](https://github.com/enanandesu/mp3.mbt/commit/058c499bdc1482be77893e5440894dd53a6d570b) 的 [Portable checks 运行 #36256727757](https://github.com/enanandesu/mp3.mbt/actions/runs/36256727757) 成功，包含 Linux 工具链安装、四后端检查与测试、格式、异常输入回归、WAV/JS 示例和 Chrome 交互测试。

这是该提交的远端记录；后续状态以 [Actions 页面](https://github.com/enanandesu/mp3.mbt/actions) 为准。手动完整参考工作流尚无远端运行记录，其 Windows/WSL 本地验收证据见下文和[测试结果](TEST_RESULTS.md)。自动便携检查成功不等于完成了 self-hosted 的全部参考验收。

| 工作流 | 触发方式 | 验证内容 |
| --- | --- | --- |
| `.github/workflows/checks.yml` | push、pull request、手动 | Ubuntu 24.04 上四后端 check/test、格式、固定异常输入及分块模糊回归、MP3→WAV、JS 桥接、Chrome 交互测试 |
| `.github/workflows/reference.yml` | 手动 `workflow_dispatch` | 完整工具链哈希校验、固定 PCM 与 11 项 minimp3 ISO 子集、异常输入、码率与声道矩阵、示例、性能和内存 |

完整参考工作流要求已经配置带有 `self-hosted`、`X64`、`mp3-reference` 及所选 `Windows` 或 `Linux` 标签的 runner。自动 push/PR 不依赖该 runner，也不会因为尚未注册 runner 而排队等待。工作流只读取仓库并上传测试结果，不发布包。两套工作流使用固定提交 SHA 的 GitHub Actions。

## 两种环境验证范围

`python tools/verify_environment.py` 按当前平台选择锁：Windows AMD64 继续使用原有的 `tools/toolchain.lock.json`；Linux x86_64 使用独立的 `tools/toolchain.linux-x86_64.lock.json`。它检查全部列出工具的版本和可执行文件 SHA-256、core 清单，以及未修改的 minimp3 文件哈希。Linux 锁还记录峰值内存测量使用的 GNU time。漂移时立即失败，不自动重写锁或降低 PCM 阈值。

自动 hosted CI 的 C 编译器与 Python 来自 GitHub 的 Ubuntu 镜像，会随镜像维护变化。因此 `validate_robustness.py --portable-tools` 使用明确的独立范围：仍严格检查 Moon、moonc、moonrun、moonfmt、core、Node 及 minimp3 哈希，同时把宿主 GCC、cc、ar 和 Python 的版本及 SHA-256 写入结果。此步骤只执行纯 MoonBit 解码器回归，不调用 FFmpeg/C PCM 参考，也不宣称完整参考环境匹配。完整 PCM 验收始终使用默认的全部工具校验。

`--record` 仅用于主动审阅并建立新平台基线，不能当作绕过现有工具漂移的方法。修改解码器时，参考阈值和已冻结语料哈希仍保持独立约束。

## Linux 本地复现

需要 Linux x86_64、Python 3.12+、GCC/cc、ar、Git；内存测量还需要 `/usr/bin/time`。在仓库根目录运行：

```sh
python3 tools/setup_ci_linux.py --with-reference
source target/ci-portability/environment.sh
python tools/verify_environment.py
python tools/validate_compatibility.py
python tools/test_mp3_to_wav.py
node tools/test_browser_decode.mjs
python tools/benchmark_release.py
python tools/benchmark_memory.py
```

安装器只向被忽略的 `target/ci-portability/` 解包，不修改系统工具。MoonBit/core 固定为 `0.10.14+7d59c7ec9`，Node 固定为 `20.17.0`；`--with-reference` 另外解包固定 SHA-256 的 FFmpeg `7.0.2` 静态构建。所有下载档案与缓存命中都必须先通过校验。解包后按明确清单为 MoonBit 的 13 个原生程序补充执行位，再运行 core bundle；`.wasm` 等数据文件不增加执行位。完整参考命令仍要求宿主工具匹配 Linux 锁，安装器不会自动改变 GCC 或 Python。

MoonBit 版本下载服务可能清理旧档案；CI 会缓存已核验的档案，但缓存本身不是长期归档。若上游文件不可用或字节改变，安装会失败，应提供字节完全相同的归档或经过审阅升级版本，不能静默改用 latest。

## 浏览器依赖与运行

`tools/browser-test/package.json` 和 `package-lock.json` 固定 Playwright Core `1.63.0` 与 npm 完整性哈希。它仅是开发测试依赖。先把这两个文件复制到 `target/browser-test/`，在该目录运行 `npm ci --ignore-scripts --no-audit --no-fund`，然后回到仓库根目录：

```sh
node tools/test_browser_decode.mjs
python tools/test_browser_ci.py
node tools/benchmark_browser.mjs
```

UI 测试助手会创建临时 loopback HTTP 服务并在测试后关闭。Windows 默认使用已安装的 Edge；Linux UI 测试可发现 `google-chrome` 或 `chromium`。可用 `EDGE_PATH` 同时指定 UI 与性能测试的浏览器，或使用 `BROWSER_PATH`。`reference.yml` 的浏览器选项可在没有浏览器的 runner 上关闭。浏览器本身的版本由基准报告记录，其运行环境不等同于 MoonBit wasm 测试运行时。

所有输出保留在 `target/`，工作流上传 JSON、失败日志和浏览器截图。参考工作流的超时、脚本内部的分阶段超时，以及固定种子使失败可定位和复跑；有限模糊回归不能证明任意输入安全。

## 2026-09-26 本地复核

- Windows 原工具链锁校验、完整集成验收、四项环境门槛回归测试、锁定的 `npm ci`、WAV/JS 示例与 Edge UI 测试通过；两个工作流通过 `actionlint 1.7.12`。
- WSL Ubuntu 24.04 在独立 Linux 锁下完成 `python tools/validate_compatibility.py`，退出码为 0。原 `reference_policy.json`、Windows 锁和语料哈希均未改变；FFmpeg 7.0.2 通过原冻结参考门槛。四后端各通过 95 项仓库测试、83 项既有兼容性测试、11 项完整 ISO 子集 PCM/分块检查、31 项严格与兼容鲁棒套件、558 项完整 PCM 矩阵。ISO 的 f32 RMSE 全部为 0，严格模式仍是 7 项 PCM 通过与 4 项预期拒绝。
- Linux 的 WAV 元数据/PCM/失败清理和 JS 桥接示例已执行通过。当时 WSL 没有 Chrome/Chromium，因此该次本地验证未执行 Linux 浏览器 UI；后续 GitHub hosted Ubuntu 上的 Chrome 交互测试已通过，见页首远端运行记录。

Linux 完整日志与机器可读结果位于本次隔离副本的 `target/linux-validation/workspace/target/`，分别为 `linux-compatibility.log`、`iso-layer3/results.json`、`robustness-validation/results.json` 和 `matrix-validation/results.json`；它们均为忽略的本地验证输出。

## 2026-09-27 Linux 安装执行权限修复

固定 MoonBit 归档中的原生程序权限为 `0664`，经 `tarfile` 的 data filter 解压后为 `0644`，均无执行位。此前 `/mnt/d` 的 Windows 挂载盘将这些文件显示为 `0777`，没有覆盖这一权限条件。本次在 WSL 原生 ext4 的临时副本中，先用旧脚本复现 `PermissionError`，再验证修复。

修复仅为清单中的原生程序添加 `0o111`，保留文件内容、原有读写位、归档 SHA-256 与工具链锁。使用同一组经校验的缓存归档，空目录首次提取、缓存重装（含 `--with-reference`）及 core bundle 均通过；没有重新测试网络下载。13 个程序实际具有执行位，3 个 Wasm 数据文件没有执行位；完整工具链哈希检查通过。

原生 ext4 中的 Python 测试 **22/22** 通过，包括真实执行 `0664` 归档内程序和缓存重装的两项回归；四后端各通过 `moon check` 和 **95/95** 测试，格式检查通过。权限回归在 Windows 或忽略 POSIX 权限的挂载盘上会明确跳过，这些跳过结果不能代替 Linux 权限验收。日志与结果位于 `target/ci-permissions/`。
