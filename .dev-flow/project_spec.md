# Remote Control 项目规格

## 当前范围：R059 终端操作体验优化

将终端创建/切换/关闭从菜单操作升级为 Tab Bar 直达操作。桌面端顶部 Tab Bar + 移动端底部紧凑 Tab 栏。

### 背景

当前终端操作全部通过 BottomSheet 菜单完成（点击 expand_more → 弹菜单 → 选择），高频操作交互层级过深。本轮将终端 CRUD 操作迁移到 Tab 栏一步直达。

### 范围

- 纯客户端 UI 改造，后端零改动
- 桌面端：顶部 Tab Bar 替代菜单切换
- 移动端：底部紧凑 Tab 栏（通过 TerminalScreen bottomChrome slot）
- 菜单瘦身：低频操作迁入设置 PopupMenuButton
- Widget 测试 + 集成测试（真实 Server）

### R059 范围（10 个任务）

- **F001**: TerminalTabBar + CompactTabStrip 核心 widget（P0）— done
- **F002**: 桌面端 Tab Bar 集成（P0）— done，依赖 F001
- **F003**: 移动端底部 Tab 栏集成（P0）— done，依赖 F001
- **F004**: Tab 上下文菜单 + 菜单瘦身（P1）— done，依赖 F002 + F003
- **F005**: 键盘快捷键（P2）— done，依赖 F002
- **F006**: 集成测试 + 手工 Smoke（P1）— done，依赖 F002-F005 + F007-F009
- **F007**: 移动端 CompactTabStrip 样式优化（P1）— done，依赖 F001
- **F008**: IndexedStack 缓存消除终端切换加载圈（P1）— done，依赖 F003 + F004 + F007
- **F009**: 修复刷新终端时选中态乱串（P1）— done，依赖 F008
- **F010**: IndexedStack 多终端隔离与刷新保持测试补充（P1）— done，依赖 F009

## 用户路径

### 桌面端用户（核心路径）

1. 下载 `Remote-Control-macOS.dmg`
2. 双击打开 → 拖拽 rc_client.app 到 Applications
3. 从 Launchpad 启动 App
4. 选择直连模式，输入服务器地址和端口
5. 注册/登录
6. App 自动发现内嵌 Agent 并启动 → Agent 自动在线
7. 创建终端 → 输入命令 → 实时输出

### 远程服务器用户

1. Docker 部署 Server：`./deploy/deploy.sh --dev`
2. 在目标机器运行 Agent：`python -m app.cli login && python -m app.cli run`
3. 从桌面端/手机端连接

## 目标平台

- macOS arm64（Apple Silicon M1/M2/M3/M4）
- 仅 PyInstaller 单平台打包

## 技术约束

- PyInstaller spec 文件需处理隐式依赖：log-service-sdk（editable install）、cryptography（动态库）
- 打包产物 < 50MB
- DesktopAgentSupervisor 优先使用内嵌 Agent，回退到 python3 源码模式
- build-desktop.sh 联合构建：PyInstaller → Flutter build → 复制到 .app bundle → 生成 .dmg
