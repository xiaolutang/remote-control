# Remote Control 项目规格

## 当前范围：R060 多终端导航 UX 重构

将桌面端顶部 Tab Bar 替换为左侧窄栏（48px 折叠/hover 160px 展开），移动端底部 CompactTabStrip 替换为紧凑页码指示器 `< 1/3 >`（32px）+ BottomSheet 终端列表。

### 背景

R059 验收后用户反馈多终端交互"感觉怪异"。终端场景与浏览器 Tab 有本质区别：用户通常只有 1-3 个终端、切换频率低、核心操作是"输入命令"而非"切换 Tab"。需要将导航模式改为更适合终端应用的设计。

### 范围

- 纯客户端 UI 改造，后端零改动
- 桌面端：左侧窄栏替代顶部 Tab Bar，终端区域获得全宽
- 移动端：页码指示器替代底部 Tab Strip，释放垂直空间（48px→32px）
- 旧组件清理（TerminalTabBar、CompactTabStrip）
- Widget 测试

### R060 范围（5 个任务）

- **F001**: TerminalSidebar 桌面端侧边栏组件（P0）— pending
- **F002**: TerminalPageIndicator 移动端页面指示器组件（P0）— pending
- **F003**: 桌面端侧边栏集成（P1）— pending，依赖 F001
- **F004**: 移动端页面指示器集成（P1）— pending，依赖 F002 + F003
- **F005**: 清理旧组件 + 更新测试（P2）— pending，依赖 F003 + F004

### R059 范围（已归档）

R059（终端操作体验优化）10 个任务已全部完成并归档到 `_archive/R059_terminal-tab-bar-ux/`。

## 用户路径

### 桌面端用户（核心路径）

1. 下载 `Remote-Control-macOS.dmg`
2. 双击打开 → 拖拽 rc_client.app 到 Applications
3. 从 Launchpad 启动 App
4. 选择直连模式，输入服务器地址和端口
5. 注册/登录
6. App 自动发现内嵌 Agent 并启动 → Agent 自动在线
7. 左侧边栏点击终端图标切换，hover 展开查看标题
8. 点击 + 创建新终端，右键触发上下文菜单

### 远程服务器用户

1. Docker 部署 Server：`./deploy/deploy.sh --dev`
2. 在目标机器运行 Agent：`python -m app.cli login && python -m app.cli run`
3. 从桌面端/手机端连接

### 移动端首用路径（0 终端→首次创建）

1. 打开 App → 连接远程设备 → WorkspaceEmptyState 空状态页面
2. 点击空状态区域创建按钮 → 首个终端创建
3. 创建成功 → 页码指示器出现 '1/1' → 左右箭头均禁用
4. 创建更多终端 → 页码更新为 '1/N'，箭头可用

## 目标平台

- macOS arm64（Apple Silicon M1/M2/M3/M4）
- 仅 PyInstaller 单平台打包

## 技术约束

- PyInstaller spec 文件需处理隐式依赖：log-service-sdk（editable install）、cryptography（动态库）
- 打包产物 < 50MB
- DesktopAgentSupervisor 优先使用内嵌 Agent，回退到 python3 源码模式
- build-desktop.sh 联合构建：PyInstaller → Flutter build → 复制到 .app bundle → 生成 .dmg
