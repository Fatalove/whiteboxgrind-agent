# Whiteboxgrind Agent

通过 Codex 在本机检查环境、准备白盒 AES 赛题、调用 Whiteboxgrind 工具链，并交付带独立验证证据的分析结果。

**首发支持 Windows x64 + Codex 本地执行 + Docker Desktop/WSL2，输入为兼容接口的 AES-128 C 源码。** 它是上游 [Whiteboxgrind](https://gitlab.lrz.de/tueisec/whiteboxgrind) 的自动化封装。它不保证陌生赛题可恢复，不支持直接分析任意 ELF、其他算法或自动改写题目。

当前版本 **0.3.0-rc.1，本地发布候选**。尚未公开发布、配置在线下载地址或通过干净机验收。不要将下方未来的 GitHub 安装流程理解为已经上线。

[English quickstart](README.en.md) · [安装与排错](docs/setup.md) · [任务与结果](docs/tasks.md) · [验收范围](docs/validation.md) · [组件许可](THIRD_PARTY_NOTICES.md)

## 使用流程

1. 获取插件并在 Codex 安装。公开发布后，仓库 marketplace 将提供插件；当前使用本地目录或受信的离线包。
2. 在新聊天中调用 `whiteboxgrind-setup`，让 Agent 检查和补齐环境。缺失 Docker 时先阅读并接受其协议；系统需要提权或重启时按提示处理。安装不启动分析。
3. 让 Agent 建立一个赛题任务目录，把源码和相关材料放进 `input`。
4. 调用 `whiteboxgrind-analyze`。Agent 识别支持的接口、生成配置，执行完整 pilot 后报告剩余估计，等待你选择是否继续正式分析。
5. 在 `output/本次运行/` 查看报告、密钥结果和验证证据。结束后选择保留全部、保留复核包或仅保留精简结果；未选择时全部保留。

```text
题目名/
├─ input/                  原始 C 源码、题目说明和相关材料
├─ task.json               工具生成的可移动配置
└─ output/
   └─ 本次运行/
      ├─ report.md         先读这里
      ├─ result.json       运行终态
      ├─ recovery.json     密钥候选、类型、编码和验证状态
      ├─ validation.json   完成验证时的独立留出记录
      ├─ evidence/         CPA、配置、输入输出和校验材料
      └─ logs/             执行日志
```

## 当前离线安装

需要受信渠道提供的发行 ZIP 和 SHA256。以下路径仅为示例，安装位置和数据位置可分别指定；无需宿主 Python 或独立 Git。

```powershell
# 在插件 scripts 目录调用；SHA256 必须取自受信摘要。
.\bootstrap.ps1 -Action Install -Destination 'D:\Apps\Whiteboxgrind\0.3.0-rc.1' `
  -DataRoot 'D:\AIGC\whiteboxgrind-data' -AppsRoot 'D:\Apps' `
  -Archive 'D:\Downloads\whiteboxgrind-0.3.0-rc.1-windows-local.zip' -ExpectedSha256 '<受信的64位SHA256>'
```

包内包含私有 PowerShell、固定 Docker 镜像及对应构建源码。Docker Desktop 本身不随包分发，缺失时使用固定官方安装包并验证摘要和签名。当前在线发行描述未配置，工具会明确报出此状态。

## 命令行示例

在已安装工具根执行。Agent 通常负责这些命令，不要求用户手写配置。

```powershell
.\scripts\wbg.ps1 doctor --json
.\scripts\wbg.ps1 case prepare --case-root 'D:\AIGC\whiteboxgrind-data\cases\我的题目' --json
# 多个 C 文件时增加 --source '主文件.c'；普通 AES 教学任务可使用 --example。
.\scripts\wbg.ps1 analyze --config 'D:\AIGC\whiteboxgrind-data\cases\我的题目\task.json' `
  --out 'D:\AIGC\whiteboxgrind-data\cases\我的题目\output\一个尚不存在的新目录' --json
.\scripts\wbg.ps1 status --run-id '<本次ID>' --json
```

`case prepare --example` 创建受控教学材料；它的公开已知键只用于样例，不能作为新赛题恢复结果的来源。实际分析候选只来自本次 CPA，并用 16 个与采集输入不重合的留出输入独立验证。

`verified/0` 表示本次验证通过；`probe_completed/0` 只表示诊断完成。其他终态包括 `no_key/10`、`unsupported/20`、`resource_limit/30`、`error/40`、`cancelled/130`。环境就绪、命令退出 0 和恢复成功是不同的结论。

## 源码与本地数据

本仓库只保存代码、插件、测试、构建材料和用户文档。赛题、候选密钥、运行原件、账本、个人授权、虚拟磁盘和发行 ZIP 放在仓库外。部署路径保存在被 Git 忽略的 `config/deployment.json`；不要提交这个文件。

构建入口为 `scripts/release/prepare_context.ps1`，使用固定摘要的上游源码归档；发行入口为 `scripts/release/prepare_release.ps1`。详细研究档案不随源码仓库分发。

原创且可独立授权的代码采用 MIT；上游组件及派生补丁保持原许可证。完整边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
