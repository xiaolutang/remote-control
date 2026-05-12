# Remote Control 项目规格

## 当前范围：R061 客户端代码收敛

基于 4 轮全项目 xlfoundry-simplify 审查发现的 17 类问题，系统性地修复架构违规、模式收敛、效率优化、复用提取和大文件拆分。纯客户端重构，后端零改动。

### 背景

R057-R060 连续 4 个需求包快速迭代后，simplify 审查发现架构层（services→screens 反向依赖、models 依赖 UI）、模式层（字符串分派 vs enum）、效率层（SP 无缓存、串行 await、双重 notify）和复用层（对话框重复、设计 token 散落）积累了显著技术债。

### 范围（5 个 Phase，15 个任务）

- **Phase 1** — 架构违规修复（F001-F004）：services→screens 反向依赖、UI 代码泄漏到 services/models
- **Phase 2** — 模式收敛（F005-F006）：字符串分派→enum、@Deprecated 清理
- **Phase 3** — 效率优化（F007-F011）：SP 缓存、双重 notify、串行→并行、dispose、节流
- **Phase 4** — 复用提取（F012-F013）：重命名对话框、SnackBar、设计 token
- **Phase 5** — 大文件拆分（F014-F015）：side panel 3570 行、workspace 1100 行

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
