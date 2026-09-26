# Layer III 帧头基础模块

`parse(Bytes, offset?=0, allow_reserved_emphasis?=false)` 只读取指定位置的四字节帧头，返回
`Result[Header, HeaderError]`；不会扫描同步、消费 CRC 或确认帧数据完整。
不足四字节时返回 `Truncated(available=...)`，由增量解码状态机决定
当前应返回 `NeedMoreInput` 还是 EOF 截断。

支持 MPEG-1/2/2.5 Layer III、九种采样率、全部表内码率及 free-format 标识。
`Header` 保留版本、码率、采样率、padding、CRC 保护标识、声道模式及扩展位、
private/copyright/original 和 emphasis。其方法提供声道数、每帧每声道样本数、
side-info 长度、CRC 长度、主数据相对帧起点的位置、帧总长度及 joint-stereo 标志。

`frame_bytes()` 的长度已经包含四字节帧头、CRC、side-info 与 padding；
CRC 字段不会重复加到帧长度上。free-format 的码率为 `None`，在没有上下文时
返回 `Ok(None)`，不会猜测长度。调用者确认**不含 padding 的整帧长度**后，
可传 `free_format_size=...`，模块检查最小头部开销及加 padding 时的整数溢出。
free-format 搜索、搜索上限和帧长上限由 `internal/framing` 与增量状态机处理。

## 固定来源和差异

主要来源为 minimp3 提交 `ea99364f61c14656440e8d77e9c233ccf3124633`，
许可见项目 `third_party/minimp3/LICENSE`：

| 本模块 | 上游来源 |
| --- | --- |
| 头部字段校验与读取 | `hdr_valid` 与 `HDR_*` 宏 |
| 三版本采样率与码率 | `hdr_sample_rate_hz`、`hdr_bitrate_kbps` 的 Layer III 表 |
| 帧样本数与帧长度 | `hdr_frame_samples`、`hdr_frame_bytes`、`hdr_padding` |
| side-info 字节数 | `L3_read_side_info` 各版本/声道字段总位数 |
| 同步兼容条件 | `hdr_compare` |
| CRC 主数据偏移 | `mp3dec_decode_frame` 先跳过 16 位 CRC，再读 side-info |

实现前还读取了 `mp3d_match_frame`、`mp3d_find_frame` 以及
`mp3dec_decode_frame` 的调用关系。上游 `hdr_frame_bytes` 不含 padding；
上游调用者随后加 `hdr_padding`，本模块将它合并为明确的总帧长度接口。

相对上游更严格或不同的行为：

- 所有读取先检查剩余长度及 offset，不依赖调用者保证可访问四字节。
- 本项目只支持 Layer III；Layer I/II 返回 `UnsupportedLayer`，保留层位返回
  `ReservedLayer`；保留版本、码率和采样率编码分别报错。
- 默认拒绝保留 emphasis 编码 `10`，返回 `ReservedEmphasis`；兼容模式显式传入
  `allow_reserved_emphasis=true` 时保留为 `ReservedValue`。上游 `hdr_valid` 未检查它。
  所有 emphasis 值仅记录，均不执行去加重滤波。
- `sync_compatible` 对已验证的 Layer III 头部保持 `hdr_compare` 的语义：
  版本、采样率、是否 free-format 必须一致，码率、CRC、padding 和声道模式可变。
  `stream_compatible` 另外限制声道数不变，用于默认严格模式；显式兼容模式
  使用 `sync_compatible` 允许声道数变化。双声道的
  Stereo/JointStereo/DualChannel 互换不算声道数变化。
- free-format 用 `None` 表达未知码率/长度；只有调用者提供已确认长度时才计算。
  对明显短于头部开销或加 padding 会溢出的长度返回结构化错误。

## 可重复对照与测试

从项目根目录运行：

```powershell
python tools/generate_header_vectors.py --check
moon test internal/header --target wasm-gc --target-dir target/agents/header
moon test internal/header --target wasm --target-dir target/agents/header
moon test internal/header --target js --target-dir target/agents/header
moon test internal/header --target native --target-dir target/agents/header
```

生成器将 `tools/header_oracle.c` 与固定版本、未经修改的 minimp3 头文件编译，
直接调用上游函数，得到并冻结 2,160 条测试记录：3 版本 × 3 采样率 ×
15 码率索引（含 free-format）× 2 padding × 2 CRC 状态 × 4 声道模式。
每条记录比较码率、采样率、样本数、帧长度、CRC、声道数、side-info 长度、
MS stereo 标志，以及与 `FF FB 90 00` 的同步兼容结果；side-info 长度来自
上游读取零值 side-info 后的真实位位置。
free-format 对照统一传入未 padding 的长度 1000，不能视为其真实码率的证据。
生成文件头记录 minimp3.h 的 SHA-256，`--check` 要求重新编译生成结果逐字节一致。

另有独立边界测试：全部 65,536 个第二/第三字节组合（固定同步首字节及无
emphasis）、0–3 字节短读、offset 边界、非法字段、CRC/padding、16 种
mode/extension 组合、流兼容和 free-format 未知/无效长度。测试只证明上述
记录的输入范围，不声称验证完整帧有效性或任意损坏码流。
