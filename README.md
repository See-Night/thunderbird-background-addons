# Thunderbird 后台运行（Linux 本地扩展）

为本机 Thunderbird **158.x / GNOME Wayland** 编写。包含一个 Thunderbird Experiment 扩展和一个 Python/Gio 托盘程序，无需 root。兼容范围暂时锁定 158.x，避免 Thunderbird 升级后在未经验证的内部 API 上继续运行。

## 安装

1. 在项目目录运行 `python install.py`，安装当前用户的托盘程序并生成 XPI。如果已经由助手执行过，可跳过这一步。
2. 打开 Thunderbird → **附加组件和主题** → 齿轮 → **从文件安装附加组件**，选择 `dist/thunderbird-background-1.1.1.xpi`。
3. 接受扩展权限，安装后检查顶栏是否出现 Thunderbird 托盘图标。

扩展使用 Experiment API 拦截主窗口关闭和控制原生窗口可见性，因此 Thunderbird 会要求“完全、不受限制地访问 Thunderbird 和您的计算机”。这是内部 API 的权限提示；本项目代码不读取邮件、账户或密码，也不发起网络请求。安装脚本不修改 Thunderbird 首选项，不关闭签名校验，不启用登录自启动，也不替换系统 Thunderbird。

GNOME 需要启用 AppIndicator 扩展。本机已检测到 `appindicatorsupport@rgcjonas.gmail.com` 在启用列表中；仍需在实际桌面上确认它正常工作。托盘不可用时，关闭按钮只会最小化窗口。

## 使用

- 点最后一个邮件主窗口的 **×**：有托盘时隐藏窗口并保留 Thunderbird 进程，后台收信、已有通知设置继续由 Thunderbird 负责；没有托盘时最小化。
- 其他邮件主窗口仍可正常关闭；写信窗口和草稿提示不受关闭拦截影响。
- 点击托盘图标或选择“显示 Thunderbird”恢复窗口；右键菜单还提供“隐藏到后台”和“退出 Thunderbird”。
- 菜单“退出”、`Ctrl+Q`、托盘“退出 Thunderbird”均请求正常退出，保留 Thunderbird 自身的草稿确认流程。
- 应用列表新增 **Thunderbird 后台运行**，用于打开或恢复隐藏窗口。原来的 Thunderbird 图标也仍然保留。
- 禁用/卸载扩展、托盘消失或本地程序断开时，扩展会尝试恢复它隐藏的窗口。
- 这不会让 Thunderbird 在关机、注销、睡眠时收信，也不会替你修改账户的自动收信或新邮件通知设置。

恢复命令：

```sh
~/.local/share/thunderbird-background/host.py --show
```

多 Thunderbird 实例同时运行时，恢复命令会恢复所有已连接的实例。托盘各自控制其对应的实例。托盘图标暂不显示未读数量。

## 登录后静默启动

1.1.1 修复登录后的静默启动。本机自启动文件 `~/.config/autostart/thunderbird-background.desktop` 执行 `~/.local/share/thunderbird-background/autostart.py`。

该启动器设置进程环境变量 `THUNDERBIRD_BACKGROUND_AUTOSTART=1`，并正常启动 `/usr/bin/thunderbird`。扩展的早期启动钩子在正常邮件主窗口加载时关闭自动显示，并在 Thunderbird 完成异步界面准备后主动触发邮件初始化，避免一直等待隐藏窗口无法产生的首次绘制。待托盘就绪后保持隐藏；托盘在 15 秒内不可用时退回最小化。点击托盘恢复窗口会取消本次启动的自动隐藏。

手动启动 Thunderbird 不携带这个环境变量，仍然正常显示窗口。实际桌面自启动不使用 `-headless` 或 `-silent`，托盘可以恢复正常桌面窗口。启动输出保存在 `~/.cache/thunderbird-background/autostart.log`，方便排查后续启动问题。

1.1.0 的 `-silent` 方案会在扩展完成启动前退出；上次手工更新与清除缓存后，后台扩展和中文语言包的注册记录也丢失了。现已更新为 1.1.1，并在持有配置目录锁时恢复这两个原有扩展的注册记录和对应启动缓存。原文件及注册数据备份位于 `~/.local/share/thunderbird-background/backups/`，其中 `*-registration` 是本次恢复前的备份。账户首选项和邮件文件未修改。

## 检查与限制

```sh
node tests/window.test.cjs
python -m unittest discover -s tests -p 'test_*.py' -v
python install.py --build-only
python tests/runtime_startup.py
```

自动检查覆盖关闭拦截、托盘丢失恢复、多窗口、取消退出、卸载恢复、失败回退、Native Messaging 分帧、DBusMenu 序列化和菜单命令。测试中的桌面服务使用替身，不能代替 Thunderbird 实机检查。

原版关闭到托盘功能已由用户确认正常运行。1.1.1 已使用真实 Thunderbird、一次性本地账户配置通过首次启动和已注册扩展的再次启动测试：只有一个邮件主窗口，保持隐藏，且邮件初始化完成。测试不使用真实账户或邮件。开发沙箱不能连接实际桌面 D-Bus，因此真实 GNOME 托盘的登录显示仍需在桌面确认。通知还取决于现有账户设置和 GNOME 通知设置。

依赖：系统 `/usr/bin/python3`、PyGObject/Gio（Arch 包 `python-gobject`，本机已有）、桌面 StatusNotifierWatcher。仅适用于非 Flatpak/Snap 的原生 Linux Thunderbird；本机为 `/usr/bin/thunderbird`。

参考：[Thunderbird Experiment API](https://developer.thunderbird.net/add-ons/mailextensions/experiments)、[Native Messaging 协议](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging)、[Mozilla 官方关闭到托盘说明](https://support.mozilla.org/en-US/kb/close-tray-starting-154)。

## 卸载

先在 Thunderbird 中禁用/移除“Thunderbird 后台运行”，再运行：

```sh
python install.py --uninstall
```

只移除本项目安装的本地程序、两个 Native Messaging 清单、新增应用入口和本项目的登录自启动项。源码、备份与 XPI 保留。
