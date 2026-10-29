---
name: whiteboxgrind-setup
description: 在 Windows + Codex 本机检查、安装或修复 Whiteboxgrind Agent，配置独立工具、数据和软件位置，通过固定摘要的离线包或已配置发行入口补齐环境。
---

按用户范围操作。仅检查时只运行 doctor 或只读 prerequisites，不安装、probe 或分析。已授权操作因隔离受限时主动申请平台执行权限，获准后按实际结果核验；受限记录不是最终验收失败，不绕过拒绝。

工具根优先使用用户指定目录或 WBG_PROJECT_ROOT，再查已安装工具的 current.json 指针、当前目录及 whiteboxgrind-agent 子目录。有效根含 scripts/wbg.ps1、src/wbg；新源码 checkout 不等于已安装引擎。通过本插件 scripts/invoke-wbg.ps1 -ToolRoot 实际根 -CliArgs @('doctor','--json') 调用。首发支持 Windows x64 + Docker/WSL2；不从本机成功推定 Linux、另一宿主或干净机通过。

未安装时调用本插件 scripts/bootstrap.ps1，明确 Destination、DataRoot 和 AppsRoot。公开预发布版通过 scripts/release-source.json 提供固定 GitHub Releases URL 和摘要，默认在线安装；离线需 -Archive 和受信 -ExpectedSha256。未配置时如实报告，不猜 URL，不要求用户先手动装好全部引擎。

包解压后使用 scripts/install.ps1 -Action Check|Install|Repair，显式传 -DataRoot、-AppsRoot。入口检查 WSL 前置条件、配置私有 PowerShell、必要时安装 Docker、导入固定镜像并 doctor，不启动分析，不要求宿主 Python。需要管理员权限时申请实际平台权限；系统要求重启或固件虚拟化设置时保存状态并交代继续步骤，不自动重启。

新用户首次安装 Docker 先说明并取得官方服务协议选择，再传 -AcceptDockerTerms。已有明确同意不重复询问。离线可传未修改的官方 -DockerInstaller，仍校验固定摘要和 Docker Inc 签名。已有 Docker 服务停止时可在授权配置范围内启动并复核，不据此判断镜像丢失。

既有安装只补所缺。Repair 保留旧运行时；Upgrade 须显式选择并保存旧镜像选择；Rollback 针对明确的 PowerShell 选择历史，不宣称是完整镜像回退。数据、历史和累计消耗不得被新安装或搬迁重置。只使用本进程 WBG_POWERSHELL 等覆盖，不改全局 Python 或默认终端。

报告实际 PowerShell/.NET、Docker/引擎、宿主物理卷与容器资源检查及调用方退出码。ready 仅证明环境就绪。小型 probe 必须使用新输出目录，probe_completed 表示未尝试恢复；完整分析仍在 pilot 后等待用户选择。
