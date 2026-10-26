# WiFi IP 定位助手 (WiFi-IP-Locator)

基于无线网络指纹定位的 IP 地址自动设置工具。记住每个「地理点」周围 WiFi 环境后，
自动识别当前位置并检查/应用对应的网卡 IP 配置（适配 USB 多网卡场景）。

## 功能

- **地理点管理**：添加地理点并命名，软件扫描周围 WiFi 记录各 AP 的 BSSID(MAC)/信号强度，
  由用户勾选参与定位的 AP；每个点可设置匹配阈值（0~99%，默认 75%）
- **自动定位**：后台按可配置间隔（10~300 秒，默认 30 秒）扫描，与各点指纹做
  「覆盖率 + 信号贴近度」加权相似度匹配；最高分仍低于阈值则显示「无法进行空间定位」。
  位置切换需连续 N 次确认（可配），避免边界抖动
- **网络配置文件**：每个地理点可配置多张网卡（按 MAC 识别，支持 USB 网卡插拔），
  每张卡独立配置 DHCP / IP / 子网掩码 / 网关 / DNS1 / DNS2
- **进入位置自动检查**：配置的多张网卡中，只要有一张**已连接且 IP 配置与档案一致**即放行；
  否则弹窗提示「是否修改 xxx 的网卡配置为 xxx」，由用户选择**其中一张**应用
  （不会多张同时刷同一静态配置，避免路由冲突）
- **开机自启**：软件内开关，写入当前用户注册表 Run 项，自启时最小化到托盘
- **系统托盘**：常驻运行，双击图标恢复主窗口，关闭窗口仅最小化

## 技术要点

- WiFi 扫描：`ctypes` 直调 Windows 原生 WLAN API（`wlanapi.dll` → `WlanGetNetworkBssList`），
  数据来自原生结构体，**不解析命令行文本**，不受系统语言/版本影响
- 网卡信息：PowerShell 结构化 Cmdlet（`Get-NetAdapter` 等）输出 JSON，枚举值为文化无关的 .NET 枚举名
- 改 IP：提权 netsh（UAC），通过 `-EncodedCommand`（UTF-16LE Base64）传递，中文网卡名无编码风险
- 运行时依赖仅 `PySide6`（Python 3.12+），无 psutil/wifi 库

## 运行

```powershell
pip install -r requirements.txt
python run.py
```

## 构建单文件 EXE

```powershell
pip install pyinstaller
build.bat
# 产物: dist\WiFi-IPLocator.exe
```

配置文件位置：`%APPDATA%\WiFi-IP-Locator\config.json`

## 已知限制 / 注意事项

- 仅支持 Windows 10/11（依赖 Native WiFi API 与 Get-NetAdapter Cmdlet）
- 应用静态配置需要管理员权限，会弹出 UAC 确认框；取消 UAC 视为放弃修改
- 定位精度取决于所选指纹 AP 的稳定性，建议勾选信号较强且长期存在的 AP
- 若某点配置的网卡全部未在位，仅托盘提示，不弹修改窗
