import '../modules/desktop_permissions/secure_storage_service.dart';

class PlannerCredentialsService {
  PlannerCredentialsService({SecureStorageService? secureStorageService})
      : _secureStorage = secureStorageService ?? SecureStorageService.instance;

  static PlannerCredentialsService shared = PlannerCredentialsService();

  final SecureStorageService _secureStorage;

  static String apiKeyStorageKey(String deviceId) =>
      'rc_planner_api_key_$deviceId';

  Future<String?> readApiKey(String deviceId) async {
    return _secureStorage.read(apiKeyStorageKey(deviceId));
  }

  Future<void> saveApiKey(String deviceId, String value) async {
    await _secureStorage.write(
      key: apiKeyStorageKey(deviceId),
      value: value,
    );
  }

  Future<void> clearApiKey(String deviceId) async {
    await _secureStorage.delete(key: apiKeyStorageKey(deviceId));
  }
}
