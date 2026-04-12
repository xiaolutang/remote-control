import 'package:flutter/material.dart';

/// 终端控制字符常量
class TerminalChars {
  static const String backspace = '\x7f';
  static const String carriageReturn = '\r';
  static const String tab = '\t';
  static const String escape = '\x1b';
}

/// 移动端输入代理组件
///
/// 使用可见的输入框接收 IME 输入，然后转发到终端。
/// 这是解决 xterm.dart IME 支持不完善的可靠方案。
class MobileInputDelegate extends StatefulWidget {
  final void Function(String text) onInput;
  final void Function() onSubmit;
  final FocusNode? focusNode;

  const MobileInputDelegate({
    super.key,
    required this.onInput,
    required this.onSubmit,
    this.focusNode,
  });

  @override
  State<MobileInputDelegate> createState() => MobileInputDelegateState();
}

class MobileInputDelegateState extends State<MobileInputDelegate> {
  late final FocusNode _internalFocusNode;
  final TextEditingController _controller = TextEditingController();
  String _committedText = '';

  FocusNode get _effectiveFocusNode => widget.focusNode ?? _internalFocusNode;

  @override
  void initState() {
    super.initState();
    _internalFocusNode = FocusNode();
  }

  @override
  void dispose() {
    _controller.dispose();
    _internalFocusNode.dispose();
    super.dispose();
  }

  void requestFocus() {
    _effectiveFocusNode.requestFocus();
  }

  void unfocus() {
    _effectiveFocusNode.unfocus();
  }

  /// 用于测试：模拟 IME 组合开始
  ///
  /// 设置一个虚拟的组合状态，使 [_syncCommittedText] 在组合期间不发送输入。
  /// 仅应在测试环境中调用。
  @visibleForTesting
  void onComposeStart() {
    _isComposing = true;
  }

  /// 用于测试：模拟 IME 组合结束
  ///
  /// 清除组合状态，允许 [_syncCommittedText] 继续发送输入。
  /// 仅应在测试环境中调用。
  @visibleForTesting
  void onComposeEnd() {
    _isComposing = false;
  }

  /// 组合状态标志，仅用于测试模拟
  @visibleForTesting
  bool _isComposing = false;

  void _syncCommittedText(TextEditingValue value) {
    final currentText = value.text;
    final composing = value.composing;

    // 中文输入法在组合态时不应立刻发送拼音，否则会破坏候选词选择。
    // _isComposing 用于测试模拟组合状态
    if (_isComposing || (composing.isValid && !composing.isCollapsed)) {
      return;
    }

    if (currentText.length > _committedText.length) {
      final newText = currentText.substring(_committedText.length);
      if (newText.isNotEmpty) {
        widget.onInput(newText);
      }
    } else if (currentText.length < _committedText.length) {
      final deleteCount = _committedText.length - currentText.length;
      for (var i = 0; i < deleteCount; i++) {
        widget.onInput(TerminalChars.backspace);
      }
    }

    _committedText = currentText;
  }

  void _resetInputBuffer() {
    _controller.clear();
    _committedText = '';
  }

  void _onSubmitted(String value) {
    widget.onSubmit();
    _resetInputBuffer();
    Future.delayed(const Duration(milliseconds: 100), () {
      if (mounted) {
        _effectiveFocusNode.requestFocus();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    // 可见的输入框，放在底部
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      color: Colors.grey[900],
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                focusNode: _effectiveFocusNode,
                keyboardType: TextInputType.text,
                maxLines: 1,
                textInputAction: TextInputAction.send,
                enableSuggestions: true,
                autocorrect: false,
                decoration: InputDecoration(
                  hintText: '输入命令...',
                  hintStyle: TextStyle(color: Colors.grey[600]),
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 8),
                  filled: true,
                  fillColor: Colors.grey[800],
                ),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                ),
                cursorColor: Colors.green,
                onChanged: (_) => _syncCommittedText(_controller.value),
                onSubmitted: _onSubmitted,
                onEditingComplete: () => _onSubmitted(_controller.text),
              ),
            ),
            const SizedBox(width: 8),
            IconButton(
              icon: const Icon(Icons.send, color: Colors.green),
              onPressed: () {
                _onSubmitted(_controller.text);
              },
            ),
          ],
        ),
      ),
    );
  }
}
