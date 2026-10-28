# 组件与许可边界

根 LICENSE 只适用于本项目原创且可独立授权的控制代码、插件、脚本和文档，不覆盖镜像中的全部软件，也不改变上游代码或派生修改的许可证。

| 组件 | 固定来源 | 许可证 |
|---|---|---|
| Whiteboxgrind Valgrind tracer | 上游提交 b4f5b78a415aaf4a864f31b9d85c3305a4970b4f 的 valgrind 子树 | GPL-2.0-only |
| Whiteboxgrind C++ analysis tools | 同一提交的 cpp 子树 | GPL-3.0-or-later |
| y5 及相关工具 | 同一上游提交及归档内组件 | MIT |
| Asynchronous | 提交 2584d9c314451d7afb318d36bd8c86bf57aa945a | Boost Software License 1.0 |
| tiny-AES-c | 提交 23856752fbd139da0b8ca6e471a13d5bcc99a08d | Unlicense |
| PowerShell | 官方 7.6.6 Windows ZIP | 保留 ZIP 中 LICENSE.txt 和 ThirdPartyNotices.txt |
| Ubuntu 系统包与 Python 依赖 | container 的固定清单与镜像内组件清单 | 各组件原许可证 |

`patches/0001-tracer-close-input-pipe.patch` 修改上游 `cpp/tracer.cpp`，按 GPL-3.0-or-later 分发，不能按根 MIT 重新授权。上游仓库为 https://gitlab.lrz.de/tueisec/whiteboxgrind 。

本地发行包同时提供固定上游源码归档、补丁、构建脚本、依赖锁、许可证原文和组件清单；镜像内保留系统和 Python 组件声明。发行源码材料必须与实际二进制匹配。Docker Desktop 不被重新分发，由用户取得并接受官方协议。

教学样例和测试中的公开已知 AES 向量需明确标为测试资料。真实赛题及其恢复密钥不随仓库或发行包分发。
