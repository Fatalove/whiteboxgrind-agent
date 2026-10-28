# 安装与排错

支持 Windows x64、Codex 本机执行、Docker Desktop 的 WSL2 Linux 后端。浏览器或无本机执行器的 Agent 不能直接使用这套本机程序。

安装顺序：检查宿主前置条件 → 选择工具、数据和软件位置 → 验证发行摘要 → 配置私有 PowerShell → 必要时安装 Docker → 导入固定镜像 → doctor。安装、Check、Repair 都不自动启动分析。

解压后可从 Windows PowerShell 5.1 调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Action Install `
  -DataRoot 'D:\AIGC\whiteboxgrind-data' -AppsRoot 'D:\Apps'
```

首次安装 Docker 需先接受官方协议，再传 `-AcceptDockerTerms`。也可用 `-DockerInstaller` 提供未修改的固定官方安装包。缺失的 WSL/系统功能需要管理员权限，固件虚拟化或重启需要用户参与；安装器不得自动重启机器。

部署配置位于工具根的 config/deployment.json，数据状态在所选数据根的 state 下。可用 WBG_PROJECT_ROOT 指明工具根，WBG_DATA_ROOT/WBG_APPS_ROOT 覆盖本次进程路径；WBG_POWERSHELL 可选择现有兼容解释器。不修改全局 Python 或默认终端。

| 问题 | 处理 |
|---|---|
| 在线发行未配置 | 使用受信的离线包和 SHA256；不要猜 URL |
| Docker 服务未运行 | 启动既有 Docker Desktop 后重新检查；不据此判断镜像丢失 |
| WSL 缺失、虚拟化未启用 | 按 prerequisites 检查返回的具体原因配置；系统需要重启时保存现场后再继续 |
| PowerShell 损坏或版本不符 | 使用 Repair 建立独立副本，保留旧选择和修复记录 |
| 镜像摘要不符 | 停止使用该包，核对受信版本；不自动拉取 latest |
| 输出目录已存在 | 选择新的运行目录，不覆盖原结果 |
| 磁盘不足 | 保留物理卷至少 20 GiB；由用户决定清理或增加空间 |

升级需显式选择 Upgrade，保留旧版本及容器选择。Rollback 仅针对明确的私有 PowerShell 选择记录，不宣称它完成全部软件与镜像回退。

旧 RC3 数据布局需先明确迁移历史和累计账本；检测到旧状态时不会直接创建一个空的新数据卷。插件 bootstrap 也支持显式 -Action Upgrade。
