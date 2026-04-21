import Cocoa
import Darwin
import FlutterMacOS

@main
class AppDelegate: FlutterAppDelegate {
  private let lifecycleChannelName = "rc_client/desktop_agent_lifecycle"
  private let keepRunningKey = "rc_desktop_keep_agent_running"
  private let managedAgentPidKey = "rc_desktop_managed_agent_pid"
  private let logPath = "/tmp/rc_desktop_exit.log"

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
      case "setKeepRunningInBackground":
        guard
          let arguments = call.arguments as? [String: Any],
          let value = arguments["value"] as? Bool
        else {
          result(FlutterError(code: "bad_args", message: "Missing keep-running value", details: nil))
          return
        }
        UserDefaults.standard.set(value, forKey: self.keepRunningKey)
        self.log("setKeepRunningInBackground=\(value)")
        result(nil)
      case "setManagedAgentPid":
        guard
          let arguments = call.arguments as? [String: Any],
          let pid = arguments["pid"] as? Int
        else {
          result(FlutterError(code: "bad_args", message: "Missing pid", details: nil))
          return
        }
        UserDefaults.standard.set(pid, forKey: self.managedAgentPidKey)
        self.log("setManagedAgentPid=\(pid)")
        result(nil)
      case "clearManagedAgentPid":
        UserDefaults.standard.removeObject(forKey: self.managedAgentPidKey)
        self.log("clearManagedAgentPid")
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  override func applicationWillTerminate(_ notification: Notification) {
    let defaults = UserDefaults.standard
    let keepRunning = defaults.object(forKey: keepRunningKey) as? Bool ?? false
    let pid = resolvedManagedAgentPid(defaults: defaults)
    log("applicationWillTerminate keepRunning=\(keepRunning) pid=\(pid)")
    guard !keepRunning else {
      log("skip kill because keepRunning=true")
      return
    }

    guard pid > 0 else {
      log("skip kill because pid<=0")
      return
    }

    let result = kill(pid_t(pid), SIGTERM)
    log("kill(SIGTERM) result=\(result) errno=\(errno)")
  }

  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    log("applicationShouldTerminateAfterLastWindowClosed -> true")
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }
}
