import Cocoa
import Darwin
import FlutterMacOS

@main
class AppDelegate: FlutterAppDelegate {
  private let lifecycleChannelName = "rc_client/desktop_agent_lifecycle"
  private let keepRunningKey = "rc_desktop_keep_agent_running"
  private let managedAgentPidKey = "rc_desktop_managed_agent_pid"
  private let logPath = "/tmp/rc_desktop_exit.log"
  private let managedAgentConfigRelativePath =
    "Library/Application Support/com.aistudio.rcClient/managed-agent/config.json"
  private var managedAgentTerminationAttempted = false

  private func log(_ message: String) {
    let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
    fputs(line, stderr)
    if let data = line.data(using: .utf8) {
      if FileManager.default.fileExists(atPath: logPath) {
        if let handle = FileHandle(forWritingAtPath: logPath) {
          handle.seekToEndOfFile()
          handle.write(data)
          handle.closeFile()
        }
      } else {
        FileManager.default.createFile(atPath: logPath, contents: data)
      }
    }
  }

  private func resolvedManagedAgentPid(defaults: UserDefaults) -> Int {
    defaults.integer(forKey: managedAgentPidKey)
  }

  private func managedAgentConfigPath() -> String {
    "\(NSHomeDirectory())/\(managedAgentConfigRelativePath)"
  }

  // Mirror: DesktopAgentSupervisor._isManagedConfigCommand — 修改匹配规则时必须同步
  private func isManagedAgentRunCommand(_ command: String) -> Bool {
    let configArgument = "--config \(managedAgentConfigPath()) "
    guard command.contains(configArgument) else {
      return false
    }
    guard command.contains("rc-agent") || command.contains("-m app.cli") else {
      return false
    }

    let tokens = command.split(whereSeparator: { $0 == " " || $0 == "\t" })
    return tokens.last == "run"
  }

  private func listManagedAgentPids() -> [Int] {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/bin/ps")
    task.arguments = ["axo", "pid=,command="]

    let pipe = Pipe()
    task.standardOutput = pipe
    task.standardError = Pipe()

    do {
      try task.run()
    } catch {
      log("fallback ps failed error=\(error)")
      return []
    }

    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    task.waitUntilExit()

    guard task.terminationStatus == 0 else {
      log("fallback ps exit=\(task.terminationStatus)")
      return []
    }

    guard let output = String(data: data, encoding: .utf8) else {
      log("fallback ps output decode failed")
      return []
    }

    var pids: [Int] = []
    for rawLine in output.split(separator: "\n") {
      let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
      guard let firstSpace = line.firstIndex(where: { $0 == " " || $0 == "\t" }) else {
        continue
      }
      let pidText = line[..<firstSpace]
      let command = line[firstSpace...].trimmingCharacters(in: .whitespacesAndNewlines)
      guard let pid = Int(pidText), pid > 0 else {
        continue
      }
      if isManagedAgentRunCommand(command) {
        pids.append(pid)
      }
    }

    log("fallback managed agent scan pids=\(pids.map(String.init).joined(separator: ","))")
    return pids
  }

  private func commandLineForPid(_ pid: Int) -> String? {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/bin/ps")
    task.arguments = ["-p", "\(pid)", "-o", "command="]

    let pipe = Pipe()
    task.standardOutput = pipe
    task.standardError = Pipe()

    do {
      try task.run()
    } catch {
      log("saved pid ps failed pid=\(pid) error=\(error)")
      return nil
    }

    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    task.waitUntilExit()

    guard task.terminationStatus == 0 else {
      log("saved pid ps exit=\(task.terminationStatus) pid=\(pid)")
      return nil
    }
    return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
  }

  private func isManagedAgentPid(_ pid: Int) -> Bool {
    guard pid > 0, let command = commandLineForPid(pid) else {
      return false
    }
    return isManagedAgentRunCommand(command)
  }

  private func terminateManagedAgentPids(_ pids: [Int]) {
    var seen = Set<Int>()
    for pid in pids where seen.insert(pid).inserted {
      guard isManagedAgentPid(pid) else {
        log("skip kill because pid is no longer managed pid=\(pid)")
        continue
      }
      errno = 0
      let termResult = kill(pid_t(pid), SIGTERM)
      log("kill(SIGTERM) pid=\(pid) result=\(termResult) errno=\(errno)")
      guard termResult == 0 else {
        continue
      }

      // applicationWillTerminate 中 Flutter engine 可能已不可用，无法使用 Dart 端的轮询逻辑
      // 改为固定等待（对比 Dart 端 TimingConstants.agentGracePeriod 的轮询模式）
      usleep(500_000)
      if kill(pid_t(pid), 0) == 0 {
        errno = 0
        let killResult = kill(pid_t(pid), SIGKILL)
        log("kill(SIGKILL) pid=\(pid) result=\(killResult) errno=\(errno)")
      }
    }
  }

  private func terminateManagedAgentsIfNeeded(defaults: UserDefaults) {
    if managedAgentTerminationAttempted {
      log("skip kill because termination already attempted")
      return
    }
    managedAgentTerminationAttempted = true

    let keepRunning = defaults.object(forKey: keepRunningKey) as? Bool ?? false
    let pid = resolvedManagedAgentPid(defaults: defaults)
    log("terminateManagedAgentsIfNeeded keepRunning=\(keepRunning) pid=\(pid)")
    guard !keepRunning else {
      log("skip kill because keepRunning=true")
      return
    }

    if isManagedAgentPid(pid) {
      terminateManagedAgentPids([pid])
      return
    }

    let pidsToTerminate = listManagedAgentPids()
    guard !pidsToTerminate.isEmpty else {
      log("skip kill because no managed agent pids found")
      return
    }

    terminateManagedAgentPids(pidsToTerminate)
  }

  override func applicationDidFinishLaunching(_ notification: Notification) {
    super.applicationDidFinishLaunching(notification)
    log("applicationDidFinishLaunching")

    guard let flutterViewController = mainFlutterWindow?.contentViewController as? FlutterViewController else {
      log("missing FlutterViewController, skip lifecycle channel setup")
      return
    }

    let channel = FlutterMethodChannel(
      name: lifecycleChannelName,
      binaryMessenger: flutterViewController.engine.binaryMessenger
    )

    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else {
        result(FlutterError(code: "app_delegate_missing", message: nil, details: nil))
        return
      }

      switch call.method {
      case "syncTerminationSnapshot":
        guard let arguments = call.arguments as? [String: Any] else {
          result(FlutterError(code: "bad_args", message: "Missing termination snapshot", details: nil))
          return
        }
        let keepRunning = arguments["keepRunningInBackground"] as? Bool ?? false
        let pid = arguments["managedAgentPid"] as? Int
        UserDefaults.standard.set(keepRunning, forKey: self.keepRunningKey)
        if let pid = pid, pid > 0 {
          UserDefaults.standard.set(pid, forKey: self.managedAgentPidKey)
        } else {
          UserDefaults.standard.removeObject(forKey: self.managedAgentPidKey)
        }
        self.log("syncTerminationSnapshot keepRunning=\(keepRunning) pid=\(pid ?? 0)")
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
    log("lifecycle channel registered")
  }

  override func applicationWillTerminate(_ notification: Notification) {
    let defaults = UserDefaults.standard
    let keepRunning = defaults.object(forKey: keepRunningKey) as? Bool ?? false
    let pid = resolvedManagedAgentPid(defaults: defaults)
    log("applicationWillTerminate keepRunning=\(keepRunning) pid=\(pid)")
    terminateManagedAgentsIfNeeded(defaults: defaults)
  }

  override func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    log("applicationShouldTerminate")
    terminateManagedAgentsIfNeeded(defaults: UserDefaults.standard)
    return .terminateNow
  }

  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    log("applicationShouldTerminateAfterLastWindowClosed -> true")
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }
}
