import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import '../models/feedback_model.dart';
import '../services/feedback_service.dart';

/// 反馈问题屏幕
///
/// 接收 [serverUrl]、[token]、[sessionId] 参数，可独立使用。
/// 用户选择分类、填写描述后提交反馈。
class FeedbackScreen extends StatefulWidget {
  final String serverUrl;
  final String token;
  final String sessionId;

  const FeedbackScreen({
    super.key,
    required this.serverUrl,
    required this.token,
    required this.sessionId,
  });

  @override
  State<FeedbackScreen> createState() => _FeedbackScreenState();
}

class _FeedbackScreenState extends State<FeedbackScreen> {
  final _descriptionController = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  FeedbackCategory? _selectedCategory;
  bool _isLoading = false;
  String? _errorMessage;

  late FeedbackService _feedbackService;

  @override
  void initState() {
    super.initState();
    _feedbackService = FeedbackService(
      serverUrl: widget.serverUrl,
      token: widget.token,
      sessionId: widget.sessionId,
    );
  }

  @override
  void dispose() {
    _descriptionController.dispose();
    super.dispose();
  }

  /// 获取平台显示文本
  String get _platformDisplayText {
    final os = Platform.operatingSystem;
    // Platform.operatingSystemVersion 在各平台都有值
    final version = Platform.operatingSystemVersion;
    return '$os $version';
  }

  /// 提交反馈
  Future<void> _submit() async {
    // 验证分类
    if (_selectedCategory == null) {
      setState(() {
        _errorMessage = '请选择问题类型';
      });
      return;
    }

    // 验证描述
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      await _feedbackService.submit(
        _selectedCategory!,
        _descriptionController.text.trim(),
      );

      if (!mounted) return;

      // 成功：显示感谢 SnackBar，延迟返回
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('感谢您的反馈')),
      );

      await Future.delayed(const Duration(seconds: 1));

      if (!mounted) return;
      Navigator.of(context).pop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  /// 验证描述长度
  String? _validateDescription(String? value) {
    if (value == null || value.trim().isEmpty) {
      return '请输入问题描述';
    }
    if (value.trim().length < 10) {
      return '描述至少 10 个字符';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final canSubmit = _selectedCategory != null &&
        _descriptionController.text.trim().length >= 10 &&
        !_isLoading;

    return Scaffold(
      appBar: AppBar(
        title: const Text('反馈问题'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: _isLoading ? null : () => Navigator.of(context).pop(),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 问题类型标题
                Text(
                  '问题类型',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 8),

                // 分类 Chip 横向排列
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: FeedbackCategory.values.map((category) {
                    final selected = _selectedCategory == category;
                    return FilterChip(
                      selected: selected,
                      label: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            category.icon,
                            size: 16,
                            color: selected
                                ? Theme.of(context).colorScheme.onPrimaryContainer
                                : Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                          const SizedBox(width: 4),
                          Text(category.displayName),
                        ],
                      ),
                      onSelected: _isLoading
                          ? null
                          : (selected) {
                              setState(() {
                                _selectedCategory =
                                    selected ? category : null;
                                // 选择分类时清除分类相关错误
                                if (selected) {
                                  _errorMessage = null;
                                }
                              });
                            },
                    );
                  }).toList(),
                ),
                const SizedBox(height: 24),

                // 问题描述标题
                Text(
                  '问题描述',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                ),
                const SizedBox(height: 8),

                // 多行描述输入框
                TextFormField(
                  controller: _descriptionController,
                  decoration: const InputDecoration(
                    hintText: '请详细描述您遇到的问题或建议（至少 10 个字符）',
                    border: OutlineInputBorder(),
                  ),
                  maxLines: 5,
                  maxLength: 10000,
                  validator: _validateDescription,
                  enabled: !_isLoading,
                  onChanged: (_) {
                    // 输入时更新按钮状态
                    setState(() {});
                  },
                ),
                const SizedBox(height: 16),

                // 错误提示
                if (_errorMessage != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.errorContainer,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          Icons.error_outline,
                          color: Theme.of(context).colorScheme.error,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _errorMessage!,
                            style: TextStyle(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onErrorContainer,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                // 分割线
                Divider(
                  color: Theme.of(context).colorScheme.outlineVariant,
                ),
                const SizedBox(height: 12),

                // 自动采集信息
                Row(
                  children: [
                    Icon(
                      Icons.info_outline,
                      size: 14,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '自动采集: $_platformDisplayText | v1.0.0',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),

                // 提交按钮
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: canSubmit ? _submit : null,
                    style: FilledButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: _isLoading
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('提交反馈'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
