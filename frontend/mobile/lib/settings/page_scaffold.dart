import 'package:flutter/material.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/theme/tokens.dart';

/// A settings page on a phone (styles.css `.sd-page-head` + `.sd-page-body`, <=768px): the head (title, actions, description,
/// toolbar) stays put and only the body under it scrolls. The head keeps 44px free on the right for the frame's close button.
class PageScaffold extends StatelessWidget {
  const PageScaffold({
    super.key,
    required this.page,
    this.action,
    this.toolbar,
    required this.body,
    this.scrollable = true,
    this.showDescription = true,
  });

  final SettingsPageDef page;
  final Widget? action;
  final Widget? toolbar;
  final Widget body;

  /// false: [body] fills the space under the head and lays out its own scrolling (lock card, full-height panes).
  final bool scrollable;

  /// false: no description line under the title (styles.css `#page-logs .sd-page-head p {display:none}` on a phone).
  final bool showDescription;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
          decoration: const BoxDecoration(
            color: JTokens.bg,
            border: Border(bottom: BorderSide(color: JTokens.border)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 40),
                child: Padding(
                  padding: const EdgeInsets.only(right: 44),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          page.label,
                          style: const TextStyle(
                            fontSize: JTokens.fsTitle,
                            fontWeight: FontWeight.w600,
                            color: JTokens.text,
                            height: 1.25,
                          ),
                        ),
                      ),
                      if (action != null) ...[
                        const SizedBox(width: 8),
                        action!,
                      ],
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 4),
              if (showDescription)
                Padding(
                  padding: const EdgeInsets.only(right: 44),
                  child: Text(
                    page.description,
                    style: const TextStyle(
                      fontSize: JTokens.fsUi,
                      color: JTokens.muted,
                    ),
                  ),
                ),
              if (toolbar != null) ...[const SizedBox(height: 10), toolbar!],
            ],
          ),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: scrollable
              ? SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                  child: body,
                )
              : body,
        ),
      ],
    );
  }
}
