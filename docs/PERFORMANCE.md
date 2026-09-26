# 跨环境性能与内存实测

此页记录 2026-09-26 的 release 构建实测，保留该次源码和产物的标识；后续浏览器限额设置变更未在本页重新计时。计时、进程峰值常驻内存和 JavaScript 堆占用是不同指标；这些短语料的结果不外推到所有设备、长音频、持续播放或兼容模式恢复路径。性能脚本检查固定语料哈希及输出规模；浏览器额外检查全部 PCM 值有限，native/wasm 微基准消费抽样 PCM 校验和。完整 PCM 差分正确性由另外的验证脚本检查。

## 复现

仓库根目录运行：

```sh
python tools/benchmark_release.py
python tools/benchmark_memory.py
```

浏览器测试使用固定的 `playwright-core@1.63.0`，将 [`tools/browser-test/package.json`](../tools/browser-test/package.json) 与其锁文件复制到 `target/browser-test/`，运行 `npm ci --prefix target/browser-test --ignore-scripts` 后执行：

```sh
node tools/benchmark_browser.mjs
```

Windows 默认使用 Edge；也可用 `--browser /absolute/path/to/chromium` 或 `BROWSER_PATH` 指定 Chromium 系浏览器。`PLAYWRIGHT_CORE_PATH` 可指定已安装包的目录，默认仍是 `target/browser-test/node_modules/playwright-core`。脚本自行启停只绑定 `127.0.0.1` 的临时 HTTP 服务；不需要运行演示网页服务器。`--output` 必须位于忽略的 `target/` 下。

Linux native 峰值测试另需 `/usr/bin/time`，报告记录其版本与二进制 SHA-256。所有结果分别写入 `target/performance-validation/results.json`、`target/performance-memory/results.json` 和 `target/performance-browser/results.json`。native 测试先验证对应平台的完整工具链锁；浏览器脚本验证固定 MoonBit 版本，另记录实际 Node、Playwright、浏览器版本和构建模块 SHA-256。

## 固定语料

| ID | MPEG / 采样率 / 声道 | 音频时长 | 输入字节 | SHA-256 |
| --- | --- | ---: | ---: | --- |
| `l3-he_32khz` | MPEG-1 / 32 kHz / 1 | 5.400 s | 95760 | `965065cdcac3f45a61a9f54b4f94d59d0334f4b5cb74840a5aec7d405e2e050f` |
| `M2L3_compl24` | MPEG-2 / 24 kHz / 1 | 5.088 s | 81408 | `856df786497a394091212086edbb77cc5f5c5572f0381f96be4273d2a7dccabf` |
| `generated-8000-2ch-cbr` | MPEG-2.5 / 8 kHz / 2 | 0.504 s | 1512 | `043751caf47378b05afcd1e384725e1038821ae75a18ab421d55f4a60c97dbb7` |

哈希来自固定 [`tests/corpus/manifest.json`](../tests/corpus/manifest.json)，元信息来自 [`tests/reference_policy.json`](../tests/reference_policy.json)。三个脚本都会拒绝变更后的语料字节。

## Windows 浏览器 JS

环境：Intel(R) Core(TM) i9-14900HX，32 个逻辑处理器；Windows 11 `10.0.26200` x64；Edge `153.0.4234.48` 无头模式；Node `v20.17.0`；Moon `moon 0.1.20260920 (914d7da 2026-09-20)`。该次串行实测记录于 `2026-09-26T14:52:50.851Z`，构建 JS 模块 SHA-256 为 `3052d4d2e180a459fade4fcdd5f505281c27a056e36b8dd78570ce0050290b69`。

[`tools/benchmark_browser.mjs`](../tools/benchmark_browser.mjs) 直接调用真实浏览器中的 release `decode_mp3`，包含 MoonBit 解码和桥接层的 PCM 复制，不调用浏览器原生 MP3 解码。先加载输入，再预热 3 次；测 7 批、每批 5 次，每次仅给 `decode_mp3` 计时。输入获取、输出校验、绘图、Web Audio 和播放不在计时区内。门槛为每项中位数达到 1× 实时。

| 输入 | 七批单次平均耗时，按执行顺序，ms | 中位数 | 中位实时倍数 | 最慢批次实时倍数 |
| --- | --- | ---: | ---: | ---: |
| MPEG-1 / 32 kHz | 25.620, 26.060, 24.460, 24.640, 23.660, 23.520, 24.460 | 24.460 ms | 220.8× | 207.2× |
| MPEG-2 / 24 kHz | 18.360, 17.820, 18.240, 17.600, 18.680, 17.640, 18.220 | 18.220 ms | 279.3× | 272.4× |
| MPEG-2.5 / 8 kHz | 1.600, 1.420, 1.440, 1.240, 1.060, 1.240, 1.020 | 1.240 ms | 406.5× | 315.0× |

短输入仍能看到 JIT 和 GC 变化，3 次预热不证明完全稳态；`performance.now()` 的浏览器计时精度也会影响短输入。JSON 同时保留全部 35 次调用与 7 个批次均值。浏览器计时独立于内存测试；后者每个语料新启一个浏览器，只解码一次并保留输出，避免其他语料或重复解码抬高进程历史峰值。

| 输入 | 解码前 renderer 常驻内存 | 截至解码完成的 renderer 生命周期峰值 | JS 堆：解码前 / 完成后 / 强制 GC 后 |
| --- | ---: | ---: | ---: |
| MPEG-1 / 32 kHz | 58.82 MiB | 83.97 MiB | 0.75 / 8.49 / 2.46 MiB |
| MPEG-2 / 24 kHz | 58.64 MiB | 79.21 MiB | 0.75 / 8.95 / 2.07 MiB |
| MPEG-2.5 / 8 kHz | 61.34 MiB | 78.29 MiB | 0.75 / 2.83 / 1.18 MiB |

进程峰值来自 Windows `PeakWorkingSet64`，是内核记录的真实高水位，包含 renderer 启动、JS 引擎、输入、PCM 与原生存储；不包含浏览器主进程/GPU进程，也不是纯解码器分配峰值。脚本要求恰好一个 renderer，避免把多个进程各自的峰值错误相加。JS 堆三列是 CDP `Runtime.getHeapUsage.usedSize` 的时点值，**不是**瞬时 JS 堆峰值；额外的 backing storage 和 embedder 字段保存在 JSON 中。保留内存包含输出和热化后的代码，不能将差值当作泄漏量。

## Windows 与 Linux native / wasm

Windows 与 Linux 使用同一台 i9-14900HX 主机。Linux 是 **Ubuntu 24.04.5 LTS / WSL2**，实测内核环境为 `Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`，并非另一台设备或独立 Linux 裸机。两者使用相同版本的 MoonBit，外部工具分别按 [`Windows 锁`](../tools/toolchain.lock.json) 与 [`Linux 锁`](../tools/toolchain.linux-x86_64.lock.json) 检查。该次生产库源码 SHA-256 均为 `898b6f648b4cce59bbf7f9e6ad3d07887c44708594603d9dd12d7505f9b7dda1`；测量前另外逐文件比对了 20 个生产 `.mbt` 文件（含示例），内容一致。

该次记录时间：Windows `2026-09-26T14:52:26.312118+00:00`；Linux `2026-09-26T14:54:05.277890+00:00`。完整正确性回归结束后按 Windows release、browser、memory、Linux release、memory 顺序执行，未并行运行本项目验证负载；没有锁定 CPU 频率或隔离所有系统后台活动。这是分环境可复现的基线，不用来断言操作系统之间的性能优劣。

[`tools/benchmark_release.py`](../tools/benchmark_release.py) 对 `decode_all`（整段）与 `Decoder`（增量）预热 3 次，再测 7 批、每批 5 次；计时包含解码和抽样 PCM 校验和，排除文件 I/O 与测试输入构造。native 每项中位数门槛为 10× 实时，wasm 为 1×。wasm 使用 MoonBit 测试运行器，不能标为浏览器性能。

| 输入 | API | 后端 | Windows 中位 / 最慢批次实时倍数 | Linux 中位 / 最慢批次实时倍数 |
| --- | --- | --- | ---: | ---: |
| MPEG-1 / 32 kHz | 整段 | native | 637.5× / 525.7× | 805.0× / 797.0× |
| MPEG-1 / 32 kHz | 增量 | native | 729.5× / 673.0× | 844.6× / 696.0× |
| MPEG-2 / 24 kHz | 整段 | native | 834.2× / 814.7× | 942.0× / 856.0× |
| MPEG-2 / 24 kHz | 增量 | native | 893.2× / 825.3× | 1000.8× / 871.4× |
| MPEG-2.5 / 8 kHz | 整段 | native | 1376.2× / 1232.7× | 2087.7× / 1956.1× |
| MPEG-2.5 / 8 kHz | 增量 | native | 1420.8× / 1305.6× | 2157.4× / 2049.2× |
| MPEG-1 / 32 kHz | 整段 | wasm | 286.9× / 279.6× | 294.0× / 290.5× |
| MPEG-1 / 32 kHz | 增量 | wasm | 295.2× / 288.5× | 301.8× / 292.4× |
| MPEG-2 / 24 kHz | 整段 | wasm | 360.1× / 341.4× | 356.8× / 334.2× |
| MPEG-2 / 24 kHz | 增量 | wasm | 368.1× / 357.1× | 371.6× / 347.7× |
| MPEG-2.5 / 8 kHz | 整段 | wasm | 693.6× / 647.4× | 697.6× / 662.2× |
| MPEG-2.5 / 8 kHz | 增量 | wasm | 742.7× / 629.7× | 705.0× / 670.1× |

### Windows 原始七批耗时

单位为微秒，每个值是一批 5 次解码的单次平均值，保持执行顺序；下表不是另外一次测量。

| 输入 | API | 后端 | 七批单次平均耗时，μs |
| --- | --- | --- | --- |
| MPEG-1 / 32 kHz | 整段 | native | 8603.300, 8470.080, 7989.040, 10272.920, 9269.040, 8323.560, 8243.100 |
| MPEG-1 / 32 kHz | 增量 | native | 7446.580, 7215.740, 7402.200, 7402.660, 8023.880, 7122.080, 6974.840 |
| MPEG-2 / 24 kHz | 整段 | native | 6236.160, 6153.760, 6245.060, 6099.540, 6079.560, 5989.940, 5693.260 |
| MPEG-2 / 24 kHz | 增量 | native | 5621.060, 5680.440, 5406.820, 5696.100, 5861.700, 5921.140, 6164.700 |
| MPEG-2.5 / 8 kHz | 整段 | native | 360.000, 366.220, 363.080, 359.780, 408.860, 369.820, 372.040 |
| MPEG-2.5 / 8 kHz | 增量 | native | 386.020, 344.660, 342.580, 354.720, 356.360, 355.860, 339.860 |
| MPEG-1 / 32 kHz | 整段 | wasm | 18998.340, 19204.420, 18823.640, 19310.080, 18492.360, 18461.140, 18238.660 |
| MPEG-1 / 32 kHz | 增量 | wasm | 18720.260, 18292.660, 17618.580, 17923.680, 17750.920, 18715.020, 18628.780 |
| MPEG-2 / 24 kHz | 整段 | wasm | 14127.640, 14903.680, 14116.980, 14778.420, 14141.700, 13953.000, 13994.120 |
| MPEG-2 / 24 kHz | 增量 | wasm | 14045.520, 13794.240, 14081.640, 13823.020, 13668.480, 14247.040, 13821.240 |
| MPEG-2.5 / 8 kHz | 整段 | wasm | 778.440, 726.600, 770.200, 718.820, 700.040, 688.240, 772.720 |
| MPEG-2.5 / 8 kHz | 增量 | wasm | 685.000, 673.060, 681.860, 800.320, 674.440, 651.960, 678.600 |

### Linux / WSL2 原始七批耗时

单位为微秒，每个值是一批 5 次解码的单次平均值，保持执行顺序；下表不是另外一次测量。

| 输入 | API | 后端 | 七批单次平均耗时，μs |
| --- | --- | --- | --- |
| MPEG-1 / 32 kHz | 整段 | native | 6628.517, 6681.068, 6775.709, 6431.436, 6713.264, 6707.758, 6765.755 |
| MPEG-1 / 32 kHz | 增量 | native | 6393.418, 6218.427, 6179.486, 7758.100, 6671.480, 6194.282, 6556.455 |
| MPEG-2 / 24 kHz | 整段 | native | 5208.354, 5943.718, 5567.639, 5543.442, 5230.955, 5401.306, 5259.426 |
| MPEG-2 / 24 kHz | 增量 | native | 5230.810, 5084.022, 5032.670, 5005.793, 5116.880, 4920.910, 5839.071 |
| MPEG-2.5 / 8 kHz | 整段 | native | 257.659, 243.815, 238.111, 255.330, 241.411, 228.750, 234.547 |
| MPEG-2.5 / 8 kHz | 增量 | native | 220.547, 231.358, 233.612, 233.417, 241.060, 236.799, 245.954 |
| MPEG-1 / 32 kHz | 整段 | wasm | 18520.207, 17897.919, 18370.037, 18586.773, 18309.753, 18480.617, 18205.608 |
| MPEG-1 / 32 kHz | 增量 | wasm | 17891.166, 18167.281, 17801.564, 17898.518, 17639.227, 18466.142, 17827.245 |
| MPEG-2 / 24 kHz | 整段 | wasm | 14150.824, 15225.862, 14565.316, 13788.262, 14260.998, 13933.108, 14386.623 |
| MPEG-2 / 24 kHz | 增量 | wasm | 13681.220, 14634.091, 13935.247, 13693.966, 14180.928, 13649.636, 13497.972 |
| MPEG-2.5 / 8 kHz | 整段 | wasm | 738.709, 722.510, 761.091, 686.554, 705.964, 713.490, 743.259 |
| MPEG-2.5 / 8 kHz | 增量 | wasm | 752.074, 705.429, 680.472, 714.867, 675.027, 722.390, 747.076 |

## native 命令进程峰值

[`tools/benchmark_memory.py`](../tools/benchmark_memory.py) 对 release `mp3-to-wav` 每项启动 3 个新进程，并检查输出 WAV 元信息。数字包括进程启动、读文件、逐帧解码 PCM、转为 s16 和写出 WAV；该命令不累计整段 PCM。与上面的 browser renderer 指标不能直接用于判断语言运行时内存效率。

| 输入 | Windows 三次进程峰值，MiB | Windows 最大值 | Linux 三次进程峰值，MiB | Linux 最大值 |
| --- | --- | ---: | --- | ---: |
| MPEG-1 / 32 kHz | 4.492, 4.492, 4.492 | 4.492 MiB | 1.949, 1.949, 1.641 | 1.949 MiB |
| MPEG-2 / 24 kHz | 4.445, 4.445, 4.445 | 4.445 MiB | 1.652, 1.926, 1.926 | 1.926 MiB |
| MPEG-2.5 / 8 kHz | 4.430, 4.430, 4.426 | 4.430 MiB | 1.949, 1.949, 1.926 | 1.949 MiB |

Windows 记录于 `2026-09-26T14:53:17.508883+00:00`，来自退出后仍有效的进程句柄 `GetProcessMemoryInfo.PeakWorkingSetSize`，没有轮询采样漏峰问题；release 可执行文件 SHA-256 为 `69f5adf73de00b956fed849a932f28ceddec432f90f888b61650b97bef38b1bc`。

Linux 记录于 `2026-09-26T14:54:53.631097+00:00`，release ELF 可执行文件 SHA-256 为 `41bcf6fd4737947429e7b678723a0ff5c4da7f83876068a0c773554bf6bb0af8`。固定 MoonBit 工具链在 Linux 也将该产物命名为 `mp3-to-wav.exe`。Linux 使用 GNU time 的子进程 `ru_maxrss`，工具记录为 `time (GNU Time) UNKNOWN`，二进制 SHA-256 为 `3b11dec50514a8473e9f6efa7a34d584d0657538c09988f61b72d38ad4991a10`。不直接用 Python 启动子进程的 `wait4` 高水位，因为那会包含 Python 在 exec 前继承给子进程的 RSS 下限。

## 证据边界

本页的浏览器性能测量仅覆盖 Windows Edge 的 JS 后端；未测量 Linux 浏览器、Firefox、Safari、浏览器 Wasm、移动设备或音频硬件延迟。浏览器功能与交互的 CI 验证范围另见 [CI 说明](CI.md)。跨操作系统测量覆盖同一台主机的 Windows 与 Linux / WSL2，尚不包括 macOS、ARM 或独立 Linux 裸机。三段输入不足以证明长音频内存上界。
