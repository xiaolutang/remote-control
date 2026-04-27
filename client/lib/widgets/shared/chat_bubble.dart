import 'package:flutter/material.dart';

/// A chat-bubble container used in conversation-style UIs.
///
/// Aligns itself according to [alignment] – pass [Alignment.centerRight]
/// for the current user and [Alignment.centerLeft] for the assistant / system.
///
/// The corner radii create the classic "tail" effect:
/// - opposite-bottom corner is tighter (8 px) for the tail side.
/// - all other corners are wider (22 px).
class ChatBubble extends StatelessWidget {
  const ChatBubble({
    super.key,
    required this.alignment,
    required this.backgroundColor,
    required this.child,
    this.maxWidth,
  });

  /// [Alignment.centerRight] for user, [Alignment.centerLeft] for assistant.
  final Alignment alignment;

  /// Bubble background colour.
  final Color backgroundColor;

  /// Content inside the bubble.
  final Widget child;

  /// Maximum width constraint. Defaults to 560.
  final double? maxWidth;

  @override
  Widget build(BuildContext context) {
    final isUser = alignment == Alignment.centerRight;
    final bubbleRadius = BorderRadius.only(
      topLeft: const Radius.circular(22),
      topRight: const Radius.circular(22),
      bottomLeft: Radius.circular(isUser ? 22 : 8),
      bottomRight: Radius.circular(isUser ? 8 : 22),
    );
    return Align(
      alignment: alignment,
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: maxWidth ?? 560),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: backgroundColor,
            borderRadius: bubbleRadius,
            border: Border.all(
              color: Colors.black.withValues(alpha: isUser ? 0.02 : 0.035),
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}
