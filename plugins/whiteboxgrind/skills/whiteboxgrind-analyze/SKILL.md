---
name: whiteboxgrind-analyze
description: 使用 Whiteboxgrind Agent 为兼容 AES-128 C 源码建立输入输出任务，执行 pilot 与用户选择后的正式分析，交付密钥和独立验证，并在所有终态询问数据保留策略。
---

先遵循 setup Skill 定位已安装工具，首次先 doctor。Windows 统一通过本插件 scripts/invoke-wbg.ps1 -ToolRoot 实际根 -CliArgs @(...) 调用；用绝对任务路径和新输出目录。首发仅支持兼容 AES-128 C 接口及受控教学预设，不保证陌生目标可恢复，不自动编写适配或修改原题。

每题一个任务文件夹，用户将原始源码和说明放入 input。先调用 case prepare --case-root 路径 --json；多源码时展示候选让用户通过 --source 选择，不猜主文件。--example 只创建公开的普通 AES 教学任务。返回 needs_input/needs_selection/unsupported 时说明所缺材料或边界，不启动分析。task.json 使用相对输入路径，已有身份和种子保持稳定。源码变化时保留原任务，新建任务，不以改名或重新配置重置账本。

用 history query --config task.json --limit 5 --json 查询可比成功和失败，核对目标、方法、规模、引擎及硬件未知项；不输出历史候选，不将源码中已知键、题解或历史密钥作为本次候选来源。

用 analyze --config task.json --out case prepare 返回的新 next_output --json 启动一次分析，以 status --run-id ID --json 查询进度。probe 仅为单条完整诊断。不得减少数量、复用 pilot 替代正式采集或跳过独立验证来取得成功结论。

默认无计算或回复硬截止，显式用户上限和原组消耗仍有效。完整 pilot 后报告从现在起的剩余估计和明确命名的资源，不混入已完成 pilot 成本或内部额度。未知就写未知。收到真实用户选择后才调用 decide --run-id ID --checkpoint TOKEN --choice continue|stop --json；无回复不继续、不终止。不自动重试或扩额。取消调用 cancel 并确认终态。已跳过案例不启动。

在 output 中交付 report.md、result.json、recovery.json、已完成时的 validation.json、evidence 和 logs。明确 AES-128 主密钥为 16 字节/32 位十六进制；candidate、verified 和未恢复分开。成功只依据本次 CPA 候选与 16 个独立留出验证，核对候选来源和摘要。密钥不等于题目 flag 或业务口令。verified/0 与 probe_completed/0 不同；no_key/10、unsupported/20、resource_limit/30、error/40、cancelled/130 分别解释。状态与历史只返回摘要。

所有终态都询问数据保留：all 全部；evidence 保留可复核结果、配置、CPA、输入输出和日志，清理大轨迹；minimal 仅精简结果与账本，并说明失去完整复核能力。先 cleanup plan --run-id ID --json，展示类别、逻辑占用和影响。未回复全部保留；不得替用户选择。

只有收到当次明确选择，才 cleanup apply --run-id ID --plan-id TOKEN --keep all|evidence|minimal --approval-quote 用户选择原话 --json。清单变化要重做，运行中不得清理，不清理其他任务或账本。解释 retention.json 中的有意删除，不能把它误报为原件损坏；逻辑删除量不等于 VHDX 即刻归还的物理空间。
