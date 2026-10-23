# Thunderbird Background add-ons

[English](README.md) | 简体中文

## 简介

Thunderbird Background add-ons 是一款 Thunderbird（雷鸟）后台运行控制插件，用于使 Thunderbird 支持后台运行，并通过本地 Linux 托盘程序，实现窗口的隐藏、显示和退出功能。

本项目由 Thunderbird Experiment 扩展和 Python/Gio Native Messaging 程序组成，在用户环境安装，无需 root 权限。

## 环境要求与兼容性

| 组件          | 要求                                                              |
| ----------- | --------------------------------------------------------------- |
| Thunderbird | 原生 Linux 安装，版本 **156.0 及以上**                                    |
| Python      | 系统 Python 3；安装后的辅助脚本使用 `/usr/bin/python3`                       |
| Python 绑定   | PyGObject 及 Gio/GLib；X11 启动通知处理还会使用 Gdk 3                       |
| 桌面托盘        | StatusNotifierWatcher；GNOME 需要启用 AppIndicator/StatusNotifier 扩展 |
| 开发测试        | 窗口测试需要 Node.js；Python 测试需要 Python 和 PyGObject                   |

主要面向 **GNOME Wayland**，不支持 Flatpak 和 Snap 安装。静默启动器和运行时测试会直接调用 `/usr/bin/thunderbird`。

清单允许安装到 Thunderbird `156.0` 及以上版本，未设置版本上限。这仅表示允许安装，不保证未来所有版本都兼容：扩展使用的内部 Experiment API 可能发生变化。

> [!NOTE]
>
> 理论上本扩展也支持 `156.0` 以下的版本，但受到开发环境的限制，无法提供这些测试环境。

## 安装

1. 安装 `python-gobject` 。

   - Debian / Ubuntu

     ```bash
     sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0
     ```

   - RedHat / CentOS

     ```bash
     sudo yum install python3X-gobject.x86_64
     ```

     > [!NOTE]
     >
     > 请确认系统的 Python 版本

   - Fodora

     ```bash
     sudo dnf install python3-gobject
     ```

   - Arch

     ```bash
     sudo pacman -S python-gobject
     ```

2. Gnome 桌面环境需要安装 `AppIndicator and KStatusNotifierItem Support` 扩展。

3. 在项目目录运行：

   ```bash
   python3 install.py
   ```

4. 在 Thunderbird 中打开 **附加组件和主题 → 齿轮图标 → 从文件安装附加组件**，选择：

   ```text
   dist/thunderbird-background-1.0.0.xpi
   ```

5. 接受权限请求，确认托盘图标出现。正式依赖后台运行前，请测试关闭和恢复最后一个邮件主窗口。

安装器会自动构建 XPI、复制辅助脚本、注册 Native Messaging 程序，并创建当前用户的桌面入口。

### 权限与隐私

由于 Experiment API 需要控制原生窗口并拦截关闭请求，Thunderbird 会要求**完全、不受限制地访问 Thunderbird 和您的计算机**。这是一项高权限，请在安装前审阅源代码。

## 使用

| 操作                             | 效果                            |
| ------------------------------ | ----------------------------- |
| 关闭最后一个邮件主窗口                    | 隐藏到托盘；托盘不可用时最小化               |
| 点击托盘图标或选择 **Show Thunderbird** | 恢复窗口                          |
| 选择 **Hide to Background**      | 托盘可用时隐藏邮件主窗口                  |
| 选择 **Quit Thunderbird**        | 请求正常退出，保留草稿确认                 |
| 点击程序入口                         | 恢复已连接的实例，否则正常启动 Thunderbird   |
| 点击需要在主窗口打开邮件的通知                | 恢复目标邮件主窗口，再由 Thunderbird 打开邮件 |

通知中的“标为已读”“删除”等操作按钮保持原有行为。通知能否出现仍取决于 Thunderbird 账户首选项和桌面通知设置。

使用默认安装路径时，也可以从终端发送命令：

```bash
~/.local/share/thunderbird-background/host.py --show
~/.local/share/thunderbird-background/host.py --hide
~/.local/share/thunderbird-background/host.py --quit
```

这些命令会作用于**所有已连接的实例**；每个托盘菜单只控制它对应的 Thunderbird 实例。

> [!NOTE]
>
> 托盘图标不显示未读数量。
>
> 后台运行不能让电脑在关机、注销或睡眠时继续收信。

### 桌面集成

找到原始桌面入口时，安装器会为 `org.mozilla.Thunderbird.desktop` 创建用户级覆盖入口。普通点击通过 `show.py` 处理，优先恢复已有后台实例，没有可用实例时正常启动。`mailto:` 链接、邮件文件、写信命令等显式参数会继续传给 Thunderbird。

原始入口的名称、翻译、图标、文件关联和操作菜单均会保留。`/usr/share/applications/` 下的系统文件不会被修改。已有的同名用户入口会先备份，在卸载时恢复；如果用户之后手动替换了入口，卸载时不会删除这个替换版本。

## 可选：登录自启动

安装器**不会自动启用登录自启动**。如需启用，请创建 `~/.config/autostart/thunderbird-background.desktop`，内容如下：

```ini
[Desktop Entry]
Type=Application
Name=Thunderbird Background
Exec=/home/YOUR_USER/.local/share/thunderbird-background/autostart.py
Terminal=false
StartupNotify=false
```

将 `Exec` 替换为已安装 `autostart.py` 的**绝对路径**。桌面入口不会展开 `~` 或 Shell 变量；路径包含空格时需要使用引号。如果设置了 `XDG_CONFIG_HOME`，请使用该目录下的 `autostart`，而不是 `~/.config/autostart`。

启动器会设置 `THUNDERBIRD_BACKGROUND_AUTOSTART=1`，然后正常启动 Thunderbird。扩展会完成隐藏邮件窗口的初始化，托盘就绪后继续保持隐藏。如果 15 秒后托盘仍不可用，则退回最小化。主动恢复窗口会取消尚未完成的自动隐藏。

手动启动不设置该变量，窗口仍会正常显示。登录启动输出默认追加到 `~/.cache/thunderbird-background/autostart.log`。删除自启动桌面入口即可关闭登录自启动。

## 更新

更新源码后，需要重新运行 `python3 install.py`，刷新本地脚本和桌面集成，再通过 Thunderbird 安装新构建的 XPI。

如果只需**更新扩展**，且已安装的配套程序仍然适用，可以运行：

```sh
python3 install.py --build-only
```

然后通过“从文件安装附加组件”安装生成的 XPI。仅执行构建不会更新已安装的扩展或配套程序。

`update_installed.py` 是高级本地维护工具，不是推荐的安装方式。它要求显式指定配置目录和安装包，请求正常退出 Thunderbird，备份并直接更新此扩展的配置注册记录和启动缓存条目，然后重新启动 Thunderbird。它需要系统 LZ4 库，并会拒绝权限变化或已禁用的扩展。在真实配置上使用前，请先审阅脚本并运行 `python3 update_installed.py --help`。

## 故障排查

- **没有托盘图标**：确认 `/usr/bin/python3` 可以使用 PyGObject，桌面的托盘支持已经启用，并且 XPI 和本地配套程序均已安装。没有可用托盘时，关闭最后一个邮件主窗口应退回最小化。
- **找不到隐藏窗口**：尝试打开已安装的 **Thunderbird Background** 应用入口，或使用上述路径执行 `host.py --show`。
- **点击 Dock 无法恢复**：重新运行安装器，并检查固定的启动器是否使用 `org.mozilla.Thunderbird.desktop`。如果找不到原始入口，请使用独立的 **Thunderbird Background** 入口。
- **登录启动失败**：检查 `Exec` 的绝对路径和 `autostart.log`。不要用 Thunderbird 的 `-silent` 参数替代项目提供的启动器。
- **没有新邮件通知**：检查 Thunderbird 账户设置和桌面的通知权限。本扩展不会启用通知或自动收信。
- **升级 Thunderbird 后出现问题**：即使清单允许安装，内部 API 也可能已经变化。请先禁用扩展，确认兼容性后再继续依赖它。

文档中的路径使用默认 XDG 目录。安装器使用 `XDG_DATA_HOME` 定位配套程序和应用入口，使用 `XDG_CONFIG_HOME` 定位配置目录侧的 Native Messaging 清单。日志和命令套接字使用 `XDG_CACHE_HOME`。

## 开发与测试

进行静态类型检查前，请创建复用系统 PyGObject 安装的开发环境：

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements-dev.txt
.venv/bin/basedpyright --pythonpath .venv/bin/python --level error
```

编辑器的 Python 工具链也应选择 `.venv/bin/python`。开发依赖包含官方 PyGObject 类型存根，并选择与启动器一致的 Gdk 3/Gtk 3。`--no-cache-dir` 用于避免复用按其他 API 版本构建的存根 wheel。GI 会动态生成 repository 模块，因此仅在这些导入行上豁免“缺少源码”诊断，仍然检查其类型。检查器保留默认规则；`--level error` 仅显示错误，省略该参数还会显示更严格的类型标注警告。

在项目目录运行自动化测试：

```sh
node tests/window.test.cjs
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 install.py --build-only
```

测试覆盖窗口拦截与恢复、启动回退、通知恢复、Native Messaging 分帧、DBusMenu 序列化、启动参数、桌面入口保留以及启动通知完成处理。涉及桌面交互的单元测试使用测试替身。

使用已安装的 Thunderbird 和一次性本地配置进行运行时检查：

```sh
python3 tests/runtime_startup.py
TBBG_TEST_NOTIFICATION=1 python3 tests/runtime_startup.py
```

运行时检查会以无界面模式启动 Thunderbird，分别验证扩展首次启动和已注册后的再次启动。通知测试使用本地测试邮件调用 Thunderbird 实际的邮件通知回调，不向桌面发送通知。这些测试不使用真实账户或邮件，也不验证可见的桌面交互。

### 项目结构

| 路径                    | 用途                                                  |
| --------------------- | --------------------------------------------------- |
| `addon/`              | 扩展清单、后台脚本和 Experiment API                           |
| `native/host.py`      | StatusNotifierItem/DBusMenu 托盘和 Native Messaging 程序 |
| `native/show.py`      | 恢复或启动入口，以及启动通知处理                                    |
| `native/autostart.py` | 登录静默启动器                                             |
| `install.py`          | 当前用户安装、XPI 打包和卸载                                    |
| `update_installed.py` | 已有配置的高级更新工具                                         |
| `tests/`              | 单元测试和一次性配置运行时检查                                     |
| `dist/`               | 生成的 XPI 安装包                                         |

## 卸载

1. 在 Thunderbird 中禁用或移除 **Thunderbird Background**，以便恢复隐藏窗口。

2. 在项目目录运行：

   ```sh
   python3 install.py --uninstall
   ```

卸载会删除配套脚本、两个 Native Messaging 清单、新增应用入口和本项目的登录自启动入口。对于仍由本项目管理的 Dock 覆盖入口，会按情况删除覆盖入口或恢复原有用户入口。源码、生成的 XPI、日志和其他备份会保留。

## 参考资料

- [Thunderbird Experiment API](https://developer.thunderbird.net/add-ons/mailextensions/experiments)
- [Native Messaging 协议](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging)
- [Mozilla 关闭到托盘说明](https://support.mozilla.org/en-US/kb/close-tray-starting-154)
