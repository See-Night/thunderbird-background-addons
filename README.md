# Thunderbird 后台运行（Linux 本地扩展）

当前版本面向 Thunderbird **156.0 及以上版本 / GNOME Wayland**，扩展版本为 **1.1.3**。包含一个 Thunderbird Experiment 扩展和一个 Python/Gio 托盘程序，无需 root。最低版本为 `156.0`，最高版本设为 `*`，同一个 XPI 可以安装到 156、157、158 及后续版本。原始 158.x 版本保存在 Git 提交 `a833749` 中。

版本上限放开表示允许安装和启用，不代表已验证未来所有版本。扩展依赖 Thunderbird 内部 Experiment API，后续版本可能需要适配。官方的[扩展指南](https://developer.thunderbird.net/add-ons/mailextensions)通常建议此类扩展设置版本上限；本项目按本地使用需求取消上限，实际验证范围见下文。

## 安装

1. 在项目目录运行 `python install.py`，安装当前用户的托盘程序并生成 XPI。如果已经由助手执行过，可跳过这一步。
2. 打开 Thunderbird → **附加组件和主题** → 齿轮 → **从文件安装附加组件**，选择 `dist/thunderbird-background-1.1.3.xpi`。
3. 接受扩展权限，安装后检查顶栏是否出现 Thunderbird 托盘图标。

扩展使用 Experiment API 拦截主窗口关闭和控制原生窗口可见性，因此 Thunderbird 会要求“完全、不受限制地访问 Thunderbird 和您的计算机”。这是内部 API 的权限提示；本项目代码不读取邮件、账户或密码，也不发起网络请求。安装脚本不修改 Thunderbird 首选项，不关闭签名校验，不启用登录自启动，也不替换系统 Thunderbird。

GNOME 需要启用 AppIndicator 扩展。本机已检测到 `appindicatorsupport@rgcjonas.gmail.com` 在启用列表中；仍需在实际桌面上确认它正常工作。托盘不可用时，关闭按钮只会最小化窗口。

若本机已安装本项目的 Python 托盘程序，只需运行 `python install.py --build-only` 生成新 XPI，再从 Thunderbird 中安装。1.1.3 保留原扩展 ID、本地托盘协议和静默启动方式；已有 1.1.1 或 1.1.2 扩展可以直接更新。

## 使用

- 点最后一个邮件主窗口的 **×**：有托盘时隐藏窗口并保留 Thunderbird 进程，后台收信、已有通知设置继续由 Thunderbird 负责；没有托盘时最小化。
- 其他邮件主窗口仍可正常关闭；写信窗口和草稿提示不受关闭拦截影响。
- 点击托盘图标或选择“显示 Thunderbird”恢复窗口；右键菜单还提供“隐藏到后台”和“退出 Thunderbird”。
- 菜单“退出”、`Ctrl+Q`、托盘“退出 Thunderbird”均请求正常退出，保留 Thunderbird 自身的草稿确认流程。
- 点击 Dock 中原来的 **Thunderbird** 图标，会先恢复隐藏窗口；没有已连接的后台实例时正常启动雷鸟。应用列表中的 **Thunderbird 后台运行** 入口也可用于恢复。
- 禁用/卸载扩展、托盘消失或本地程序断开时，扩展会尝试恢复它隐藏的窗口。
- 这不会让 Thunderbird 在关机、注销、睡眠时收信，也不会替你修改账户的自动收信或新邮件通知设置。

恢复命令：

```sh
~/.local/share/thunderbird-background/host.py --show
```

多 Thunderbird 实例同时运行时，恢复命令会恢复所有已连接的实例。托盘各自控制其对应的实例。托盘图标暂不显示未读数量。

## 从 Dock 恢复窗口

更新源码后运行 `python3 install.py` 即可启用，无需重新安装 XPI。安装器在当前用户的应用目录创建 `org.mozilla.Thunderbird.desktop`，保留 Dock 固定的应用 ID，将普通点击接到 `show.py`：先向本地托盘程序发送恢复命令，后台实例不可用时正常启动 Thunderbird。原入口的名称、图标、文件关联以及“写邮件”“通讯录”操作保留，链接和文件参数继续传给 Thunderbird。登录自启动仍使用独立的 `autostart.py`，保持静默。

两个手动启动入口均设置 `StartupNotify=false`。GNOME Wayland 仍可能为 Dock 点击创建激活通知，因此 `show.py` 在恢复已有窗口后还会主动通知桌面结束本次启动等待，避免窗口恢复后鼠标仍长时间显示“加载中”。直接启动 Thunderbird 时保留通知，交给 Thunderbird 自身处理。此修复只需重新运行安装器，无需重新安装 XPI。

系统 `/usr/share/applications/` 内的入口不修改。若用户目录原有同名入口，安装前备份到 `~/.local/share/thunderbird-background/dock-original.desktop`，卸载时恢复；卸载时也会移除本项目创建的 Dock 覆盖入口。如果之后手动换成其他入口，卸载会保留该入口。

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

1.1.3 沿用已核对本机 Thunderbird 156.0 内置实现的静默启动钩子。17 项窗口测试和 9 项 Python 测试全部通过。真实 Thunderbird **156.0** 使用一次性本地账户配置通过首次启动和已注册扩展的再次启动测试：扩展 `isActive=true`、`appDisabled=false`，只有一个邮件主窗口，保持隐藏，且邮件初始化完成。运行时测试使用无桌面模式，不使用真实账户或邮件；测试脚本通过扩展自身的启用状态检查版本兼容性，不再固定要求 156.x。

原版关闭到托盘功能已由用户在 158.x 上确认正常运行，1.1.3 保持相同的窗口控制逻辑。本次没有重新实测 157、158 或更高版本。156.0 的真实 GNOME 托盘显示、点击恢复和登录自启动仍需在桌面确认；无桌面测试不能替代这些交互检查。通知还取决于现有账户设置和 GNOME 通知设置。

依赖：系统 `/usr/bin/python3`、PyGObject/Gio（Arch 包 `python-gobject`，本机已有）、桌面 StatusNotifierWatcher。仅适用于非 Flatpak/Snap 的原生 Linux Thunderbird；本机为 `/usr/bin/thunderbird`。

参考：[Thunderbird Experiment API](https://developer.thunderbird.net/add-ons/mailextensions/experiments)、[Native Messaging 协议](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging)、[Mozilla 官方关闭到托盘说明](https://support.mozilla.org/en-US/kb/close-tray-starting-154)。

## 卸载

先在 Thunderbird 中禁用/移除“Thunderbird 后台运行”，再运行：

```sh
python install.py --uninstall
```

移除本项目安装的本地程序、两个 Native Messaging 清单、新增应用入口和本项目的登录自启动项，并恢复安装前的 Dock 入口。源码、其他备份与 XPI 保留。
