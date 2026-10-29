# Changelog

记录本项目的功能变更与问题修复，最新条目在最上方。

## 🗂 2026-10-29 · 修复网卡误报"未连接"

### 🐞 修复

- `nic_info`: 现代通道（`Get-NetAdapter`）返回的 `MediaConnectState` 被 `ConvertTo-Json` 序列化为数字（`1`/`2`），与 `is_connected` 比较的字符串 `'Connected'` 永远不相等，导致在位且已连接的网卡（如 USB 有线网卡）被误判为"未连接"、跳过网络配置检查。现改为在 PowerShell 端显式映射为 `Connected`/`Disconnected`，并在 Python 侧 `_normalize` 增加数字值的防御性映射，双通道（含 WMI 回退）行为一致。
- 附带场景：网卡处于连接状态但仅有 APIPA 地址（`169.254.x.x`，被 IPv4 查询过滤）时，此前会因 `ip` 为空落入兜底失败；现以媒体连接状态为准正确判定为已连接，网络配置不符时会正常进入配置提示流程而非静默跳过。
