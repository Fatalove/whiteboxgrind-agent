# Whiteboxgrind Agent

通过 Codex 在本机检查环境、准备白盒 AES 赛题、调用 Whiteboxgrind 工具链，并交付带独立验证证据的分析结果。

**首发支持 Windows x64 + Codex 本地执行 + Docker Desktop/WSL2，输入为兼容接口的 AES-128 C 源码。** 它是上游 [Whiteboxgrind](https://gitlab.lrz.de/tueisec/whiteboxgrind) 的自动化封装。它不保证陌生赛题可恢复，不支持直接分析任意 ELF、其他算法或自动改写题目。

当前版本 **0.3.0-rc.1，预发布版**，面向 Windows x64 + Codex。发行包和固定镜像见 [GitHub Releases](https://github.com/Fatalove/whiteboxgrind-agent/releases/tag/v0.3.0-rc.1)。本机隔离安装已验收，真实干净 Windows 首次补齐环境的完整流程仍待验收，详见 [验证范围](docs/validation.md)。

[English quickstart](README.en.md) · [安装与排错](docs/setup.md) · [任务与结果](docs/tasks.md) · [验收范围](docs/validation.md) · [组件许可](THIRD_PARTY_NOTICES.md)

## 目录关系

建议在任意位置建立一个项目主目录，将源码与私有数据并列放入其中：

```text
whiteboxgrind/
├─ whiteboxgrind-agent/     本仓库：代码、插件、测试和用户文档
└─ whiteboxgrind-data/      私有数据：任务、运行状态、缓存、发行包和档案
```

相对于本仓库，默认数据目录为 `../whiteboxgrind-data`。实际工具、数据和软件位置由安装参数指定，保存到不纳入 Git 的部署配置；不要求用户采用某个盘符。Docker 与专用 PowerShell 可安装到用户选择的软件目录。

## 使用流程

1. 在 Codex 插件页选择添加 GitHub marketplace，输入 `Fatalove/whiteboxgrind-agent`，再安装 Whiteboxgrind Agent。也可使用下面的 CLI 入口。
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

## 从 GitHub 安装

在 Codex 插件页添加仓库 `Fatalove/whiteboxgrind-agent`，安装后开启新聊天并调用 `whiteboxgrind-setup`。CLI 等效入口：

```powershell
codex plugin marketplace add https://github.com/Fatalove/whiteboxgrind-agent.git
codex plugin add whiteboxgrind@whiteboxgrind-local
```

向 Agent 说明工具、数据和软件目录后，setup 会使用插件内固定版本的发行描述下载 ZIP、核对 SHA256，并检查环境。无需宿主 Python。Docker 首次协议、管理员权限及系统重启按实际需要由用户处理，安装器不自动重启。

也可下载源码或 clone 仓库后手动引导。以下从项目主目录执行，软件目录只是可选示例：

```powershell
git clone https://github.com/Fatalove/whiteboxgrind-agent.git whiteboxgrind-agent
$DataRoot = Join-Path (Get-Location).Path 'whiteboxgrind-data'
$AppsRoot = 'D:\Apps'
$ToolRoot = Join-Path $AppsRoot 'Whiteboxgrind/0.3.0-rc.1'
& .\whiteboxgrind-agent\plugins\whiteboxgrind\scripts\bootstrap.ps1 `
  -Action Install -Destination $ToolRoot -DataRoot $DataRoot -AppsRoot $AppsRoot
```

离线用户从 Releases 下载 ZIP 和 `SHA256SUMS.txt`，增加 `-Archive` 与 `-ExpectedSha256`；具体步骤见 [安装指南](docs/setup.md)。包内含私有 PowerShell、固定 Docker 镜像、对应构建源码及许可证。Docker Desktop 本身不重新分发。

## Docker 镜像

镜像发布到 GitHub Container Registry：

```powershell
docker pull ghcr.io/fatalove/whiteboxgrind-agent:0.3.0-rc.1
```

镜像仅支持 `linux/amd64`，供 Windows Docker Desktop/WSL2 使用。安装器默认从发行 ZIP 导入已锁定镜像，无需用户手动 pull。GHCR 用于独立分发同一运行环境；其仓库摘要见发行附件 `registry.json`。镜像公开层只包含程序及受控样例，不含本地赛题、密钥、历史、授权或账本。

## 命令行示例

在已安装工具根执行。Agent 通常负责这些命令，不要求用户手写配置。

```powershell
# 在已安装工具根执行，读取安装时保存的数据位置。
$DataRoot = (Get-Content .\config\deployment.json -Raw | ConvertFrom-Json).data_root
$CaseRoot = Join-Path $DataRoot 'cases/我的题目'
.\scripts\wbg.ps1 doctor --json
$Task = .\scripts\wbg.ps1 case prepare --case-root $CaseRoot --json | ConvertFrom-Json
# 多个 C 文件时增加 --source '主文件.c'；教学任务可使用 --example。
# 只有 prepared 才启动；缺少材料或需选择源码时先按返回信息处理。
if ($Task.status -eq 'prepared') {
  .\scripts\wbg.ps1 analyze --config $Task.config --out $Task.next_output --json
}
.\scripts\wbg.ps1 status --run-id '<本次ID>' --json
```

`case prepare --example` 创建受控教学材料；它的公开已知键只用于样例，不能作为新赛题恢复结果的来源。实际分析候选只来自本次 CPA，并用 16 个与采集输入不重合的留出输入独立验证。

`verified/0` 表示本次验证通过；`probe_completed/0` 只表示诊断完成。其他终态包括 `no_key/10`、`unsupported/20`、`resource_limit/30`、`error/40`、`cancelled/130`。环境就绪、命令退出 0 和恢复成功是不同的结论。

## 源码与本地数据

本仓库只保存代码、插件、测试、构建材料和用户文档。赛题、候选密钥、运行原件、账本、个人授权、虚拟磁盘和发行 ZIP 放在仓库外。部署路径保存在被 Git 忽略的 `config/deployment.json`；不要提交这个文件。

构建入口为 `scripts/release/prepare_context.ps1`，使用固定摘要的上游源码归档；发行入口为 `scripts/release/prepare_release.ps1`。详细研究档案不随源码仓库分发。

原创且可独立授权的代码采用 MIT；上游组件及派生补丁保持原许可证。完整边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
