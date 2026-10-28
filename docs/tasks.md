# 任务、密钥结果与数据保留

把一题的材料放在同一个任务目录的 input 中。主源码必须是当前支持的 AES-128 C 接口：`void AES_128_encrypt(char *out, char *in)` 或两个 `unsigned char *` 参数。当前只接受单主 C 文件及既有教学预设；题目说明和其他材料不会自动变成编译输入。多个 C 文件时选择主文件；缺头文件、多文件构建或其他接口会明确报告限制，不改写原题。

运行 `case prepare --case-root 路径` 后，task.json 保存相对路径、源码摘要、种子与参数。保持任务目录内的相对关系即可搬走。已有任务不会因改名重置实验身份；源码变化应建立新任务。工具在分析时冻结源码和运行器快照。

先检查环境，再执行完整 pilot。pilot 后需用户明确选择 `decide --run-id ID --checkpoint TOKEN --choice continue|stop --json`。无回复不自动继续或终止。正式采集与 pilot 分开，独立验证输入与采集输入不重合。默认无计算或回复硬截止，显式用户限制仍有效；不自动重试或扩额。

## 输出解释

- report.md：结果、限制与下一步数据选择。
- result.json：终态、原因、执行和恢复摘要；不把诊断完成当作恢复。
- recovery.json：`key_type=aes128_master_key`、`encoding=hex`、16 字节密钥，及 `candidate/verified/not_recovered` 状态。未恢复时 key_hex 为空。
- validation.json：已完成的独立留出验证。缺失意味着该阶段未完成，不生成占位的“通过”。
- evidence：本次候选、CPA、请求与实际配置、输入及目标输出、验证和完整性材料。
- logs：命令执行日志。完整轨迹和工作数据仍在本机工具数据卷中。

验证通过说明本次候选在 16 个独立留出输入上匹配目标 AES 输出，并通过验证器自检。它不保证所有输入上等价，也不保证对其他目标或编码方式适用。AES 主密钥不是明文、登录口令或天然的赛题 flag。

## 结束后选择

成功、失败、资源中断、取消和诊断结束后，都先向用户展示保留选项：

| 选择 | 保留内容与影响 |
|---|---|
| all | 全部保留；也是未回复时的默认行为 |
| evidence | 保留结果、配置、CPA、验证输入输出、源码和日志；清理大轨迹与可重建二进制，完整重分析需重新采集 |
| minimal | 保留精简结果、必要元数据和账本；失去完整复核及后续分析能力 |

先运行 `cleanup plan --run-id ID --json` 查看清单，再依据真实用户选择运行 `cleanup apply --run-id ID --plan-id TOKEN --keep all|evidence|minimal --approval-quote '用户选择原话' --json`。Agent 不得代替用户选择，空白回复不执行清理。清单绑定运行和文件摘要，变化后需重新生成。清理不会删除其他任务或重置账本。

原始完整清单会保留，retention.json 说明哪些文件被用户有意清理；检查原件时应同时查看它。逻辑文件大小不等于 Windows 立刻回收的物理 VHDX 空间。

result.json 是计算结束时的不可变快照；当前数据保留选择以 retention.json 为准，status 会合并这项最新状态。
