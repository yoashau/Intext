# Intext

**Windows 全局划词与截图翻译，让译文留在阅读的位置。**

选中文字，按下快捷键，译文就会出现在鼠标旁。遇到图片或无法选中的文字，可以框选截图翻译；也可以直接粘贴多段文本。接口和模型由你选择。

[**下载 Windows 安装包**](https://github.com/yoashau/Intext/releases/latest/download/Intext-Setup.exe) · [查看版本](https://github.com/yoashau/Intext/releases) · [反馈问题](https://github.com/yoashau/Intext/issues)

| 浅色模式 | 深色模式 |
| --- | --- |
| ![Intext 浅色翻译浮层](docs/images/popup-light.png) | ![Intext 深色翻译浮层](docs/images/popup-dark.png) |

## 功能与特点

- **在原处读译文**：选中文字后呼出翻译浮层，原文与译文一起显示，保留段落格式，无需复制到另一个网页。
- **选不到，也能翻译**：框选图片、扫描件或其他无法选中文字的区域，在本机识别文字后翻译。
- **使用自己的模型**：支持兼容 Chat Completions 的接口，自行填写服务地址、API key 和模型名称。
- **适合连续阅读**：浮层可固定、拖动和复制译文，直接切换语种、对调翻译方向，或重新翻译当前内容。
- **减少重复请求**：已翻译内容保存在本机，重启后仍可复用；相同内容在翻译完成前重复触发时，共用一次请求。
- **融入桌面**：跟随系统深浅色，日常驻留托盘，支持自定义快捷键与开机静默启动。

## 下载与开始使用

适用于 **Windows x64**。安装包已包含 Python 运行环境，无需单独安装 Python；界面依赖系统中的 Microsoft Edge WebView2 Runtime。

1. 下载 [Intext-Setup.exe](https://github.com/yoashau/Intext/releases/latest/download/Intext-Setup.exe)，安装后启动 Intext。
2. 在设置中填写完整的接口地址、API key 和模型名称，选择目标语言。设置会自动保存。
3. 选中一段文字，按 **Ctrl + Alt + Q** 查看翻译。

需要自行准备翻译服务的接口与模型；服务费用按你所用服务的规则计算。升级时直接运行新版安装包，已有配置和缓存会保留。

## 三种翻译方式

| 方式 | 操作 | 适合的内容 |
| --- | --- | --- |
| 划词翻译 | 选中文字，按 **Ctrl + Alt + Q** | 网页、文档、邮件中可以选中的文字 |
| 截图翻译 | 按 **Ctrl + Alt + E**，拖动框选区域 | 图片、扫描件和无法选中的文字 |
| 输入翻译 | 右键托盘图标 → **输入翻译** | 粘贴的多段文本或手动输入的内容 |

两个全局快捷键都可以在设置中修改。输入翻译支持 **Ctrl + Enter** 提交。

浮层中可以复制、固定或重新翻译；点击语言名称切换语种，点击对调按钮做反向翻译。未固定时，点击外部会收起浮层；固定后仍可通过关闭圆点或 **Esc** 关闭。

左键托盘图标打开设置，右键可进入输入翻译、设置开机启动或退出。

## 接口配置

填写服务提供的 **Chat Completions 完整地址**，例如 `https://api.example.com/v1/chat/completions`，以及对应的 API key 和模型名称。

温度、思考强度等高级参数默认不发送。确实需要且模型支持时再启用；设置页底部会显示将要发送的请求内容，不显示密钥。

## 数据与隐私

API key、配置和翻译缓存保存在本机的 `%APPDATA%\Intext`。翻译时，选中的文字会发送到你配置的服务。截图由本机 Windows OCR 识别，翻译接口接收识别出的文字。

本机缓存按原文、语言方向、接口、模型与已启用参数区分。点击「再译」会重新请求服务；相似但不同的句子不会直接套用旧译文。

## 常见问题

**选中文字后没有取得内容？**

部分应用不支持读取选区，可以改用截图翻译。

**截图无法识别文字？**

识别依赖 Windows OCR 和本机可用的识别语言。可以先检查 Windows 语言组件，或改用输入翻译。

**接口提示参数不支持？**

先关闭已启用的高级参数，再核对服务地址和模型名称。浮层提示旁的问号可查看完整失败原因。

## 从源码运行

需要 Windows 和 Python 3.11 或更新版本。在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[windows]"
.\.venv\Scripts\python.exe -m intext
```

运行单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
