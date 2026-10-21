import 'package:flutter/material.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';

import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/pages/catalog_page.dart';
import 'package:jarvis_mobile/settings/pages/connect_page.dart';
import 'package:jarvis_mobile/settings/pages/graphfy_page.dart';
import 'package:jarvis_mobile/settings/pages/info_page.dart';
import 'package:jarvis_mobile/settings/pages/logs_page.dart';
import 'package:jarvis_mobile/settings/pages/mcp_page.dart';
import 'package:jarvis_mobile/settings/pages/memory_page.dart';
import 'package:jarvis_mobile/settings/pages/overview_page.dart';
import 'package:jarvis_mobile/settings/pages/system_page.dart';
import 'package:jarvis_mobile/settings/pages/user_page.dart';
import 'package:jarvis_mobile/settings/pages/voice_page.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _collapsedKey = 'jarvis.settings.sidebar_collapsed_phone';
const _lastPageKey = 'jarvis.settings.last_page';
const _navEase = Cubic(0.4, 0, 0.2, 1);

final Map<String, Widget Function()> _pageBuilders = {
  'overview': () => const OverviewPage(),
  'connect': () => const ConnectPage(),
  'voice': () => const VoicePage(),
  'user': () => const UserPage(),
  'system': () => const SystemPage(),
  'memory': () => const MemoryPage(),
  'logs': () => const LogsPage(),
  'agents': () => const CatalogPage(category: 'agents'),
  'hooks': () => const CatalogPage(category: 'hooks'),
  'skills': () => const CatalogPage(category: 'skills'),
  'prompts': () => const CatalogPage(category: 'prompts'),
  'commands': () => const CatalogPage(category: 'commands'),
  'plugins': () => const CatalogPage(category: 'plugins'),
  'mcp': () => const McpPage(),
  'graphfy': () => const GraphfyPage(),
  'info': () => const InfoPage(),
};

/// The Dashboard on a phone (settings/index.ts + styles.css <=768px): the menu is a drawer that opens as the 60px icon rail over a
/// scrim, its collapse button slides it out to the names; the page opens in a frame under the island row, from the menu's left
/// edge to the right edge, with the close button on its top right corner.
///
/// Divergence from the web: the home button stays on screen while a page is open. On the web the page frame covers the chat and
/// the button is hidden; here Settings is its own route, so the button is the only way to the menu.
class SettingsShell extends StatefulWidget {
  const SettingsShell({super.key, this.initialPageId = 'overview'});

  final String initialPageId;

  @override
  State<SettingsShell> createState() => _SettingsShellState();
}

class _SettingsShellState extends State<SettingsShell>
    with SingleTickerProviderStateMixin {
  late String _selectedId = widget.initialPageId;
  late final AnimationController _slide = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 200),
  );
  bool _navOpen = false;
  bool _collapsed =
      true; // a phone's first time is the rail (index.ts applyWidth)
  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      final saved = p.getBool(_collapsedKey);
      if (mounted && saved != null) setState(() => _collapsed = saved);

      final savedPage = p.getString(_lastPageKey);
      if (mounted && widget.initialPageId == 'overview' && savedPage != null && _pageBuilders.containsKey(savedPage)) {
        final auth = context.read<AuthController?>();
        final isAdmin = auth?.currentUser?.isAdmin ?? true;
        if (isAdmin || savedPage != 'prompts') {
          setState(() => _selectedId = savedPage);
        }
      }
    });
  }

  @override
  void dispose() {
    _slide.dispose();
    super.dispose();
  }

  void _setNav(bool open) {
    setState(() => _navOpen = open);
    open ? _slide.forward() : _slide.reverse();
  }

  void _toggleCollapsed() {
    setState(() => _collapsed = !_collapsed);
    SharedPreferences.getInstance().then(
      (p) => p.setBool(_collapsedKey, _collapsed),
    );
  }

    void _confirmLogout() {
    showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: JTokens.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: JTokens.border),
        ),
        title: const Text(
          'Đăng xuất',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: JTokens.text,
          ),
        ),
        content: const Text(
          'Bạn có chắc chắn muốn đăng xuất khỏi hệ thống không?',
          style: TextStyle(
            fontSize: 14,
            color: JTokens.muted,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Hủy', style: TextStyle(color: JTokens.muted)),
          ),
          TextButton(
            key: const Key('logout-confirm-btn'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(
              'Đăng xuất',
              style: TextStyle(color: Color(0xFFF87171), fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
    ).then((confirmed) async {
      if (confirmed == true && mounted) {
        final auth = context.read<AuthController?>();
        if (auth != null) {
          await auth.logout();
        }
        if (mounted) {
          Navigator.of(context).pop();
        }
      }
    });
  }

  void _onNavItem(String id) {
    if (id == _selectedId) {
      Navigator.maybePop(
        context,
      ); // the current page's item closes Settings (index.ts:1239)
      return;
    }
    setState(() {
      _selectedId = id;
    });
    SharedPreferences.getInstance().then((p) => p.setString(_lastPageKey, id));
    _setNav(false);
  }

  Widget _buildBody(SettingsPageDef page) {
    // one State per page: without the key the catalog pages (same widget type) kept the previous page's list
    return KeyedSubtree(
      key: ValueKey(page.id),
      child: _pageBuilders[page.id]!(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController?>();
    final isAdmin = auth?.currentUser?.isAdmin ?? true;
    if (!isAdmin && _selectedId == 'prompts') {
      _selectedId = 'overview';
    }
    final page = settingsPages.firstWhere(
      (p) => p.id == _selectedId,
      orElse: () => settingsPages.first,
    );
    final mq = MediaQuery.of(context);
    // --controls-inset 12px on a phone; --dash-top = safe top + 54 (under the island pill); --dash-bottom = --container-bottom
    final dashX = 12.0 + mq.padding.left;
    final dashR = 12.0 + mq.padding.right;
    final top = mq.padding.top + 54;
    final bottom = mq.size.width <= 380 ? 16.0 : 18.0;

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(
            left: dashX,
            top: mq.padding.top + 12,
            child: _RoundButton(
              onTap: () => _setNav(!_navOpen),
              child: MorphIcon(
                icon: _navOpen ? xGlyph : houseGlyph,
                color: JTokens.accent.withValues(alpha: 0.7),
                size: 18,
                strokeWidth: 1.75,
              ),
            ),
          ),
          Positioned(
            left: dashX,
            right: dashR,
            top: top,
            bottom: bottom,
            child: Container(
              decoration: BoxDecoration(
                color: JTokens.bg,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: JTokens.border),
              ),
              clipBehavior: Clip.antiAlias,
              child: Stack(
                children: [
                  Positioned.fill(child: _buildBody(page)),
                  Positioned(
                    top: 14,
                    right: 10,
                    child: GestureDetector(
                      key: const Key('settings-close'),
                      onTap: () => Navigator.maybePop(context),
                      child: Container(
                        width: 40,
                        height: 40,
                        decoration: BoxDecoration(
                          color: JTokens.bg,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: JTokens.border),
                        ),
                        alignment: Alignment.center,
                        child: const MorphIcon(
                          icon: xGlyph,
                          color: JTokens.muted,
                          size: 18,
                          strokeWidth: 1.75,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          AnimatedBuilder(
            animation: _slide,
            builder: (context, _) {
              if (_slide.value == 0 && !_navOpen) {
                return const SizedBox.shrink();
              }
              final navW = _collapsed ? 60.0 : 200.0;
              return Stack(
                children: [
                  // only the band the drawer uses: a layer at a screen edge made iOS Safari drop its status-bar fade
                  Positioned(
                    left: 0,
                    right: 0,
                    top: top,
                    bottom: bottom,
                    child: GestureDetector(
                      key: const Key('settings-scrim'),
                      behavior: HitTestBehavior.opaque,
                      onTap: () => _setNav(false),
                      child: ColoredBox(
                        color: Color.fromRGBO(0, 0, 0, 0.55 * _slide.value),
                      ),
                    ),
                  ),
                  Positioned(
                    left: dashX,
                    top: top,
                    bottom: bottom,
                    child: Transform.translate(
                      offset: Offset(
                        -(navW + 24 + dashX) * (1 - _slide.value),
                        0,
                      ),
                      child: _Nav(
                        collapsed: _collapsed,
                        selectedId: _selectedId,
                        isAdmin: isAdmin,
                        onToggle: _toggleCollapsed,
                        onItem: _onNavItem,
                        onLogout: _confirmLogout,
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

/// `.sd-menu-btn`: 36px round, the control buttons' blue.
class _RoundButton extends StatelessWidget {
  const _RoundButton({required this.onTap, required this.child});

  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) => GestureDetector(
    onTap: onTap,
    behavior: HitTestBehavior.opaque,
    child: Padding(
      padding: const EdgeInsets.all(
        4,
      ), // a 44px touch target around the 36px button
      child: Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: JTokens.accent.withValues(alpha: 0.14),
        ),
        alignment: Alignment.center,
        child: child,
      ),
    ),
  );
}

class _Nav extends StatelessWidget {
  const _Nav({
    required this.collapsed,
    required this.selectedId,
    required this.isAdmin,
    required this.onToggle,
    required this.onItem,
    required this.onLogout,
  });

  final bool collapsed;
  final String selectedId;
  final bool isAdmin;
  final VoidCallback onToggle;
  final void Function(String id) onItem;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final pad = collapsed ? 6.0 : 8.0;
    final filteredGroups = [
      for (final g in navGroups)
        (g.$1, isAdmin ? g.$2 : g.$2.where((id) => id != 'prompts').toList()),
    ].where((g) => g.$2.isNotEmpty).toList();
    return AnimatedContainer(
      key: const Key('settings-nav'),
      duration: const Duration(milliseconds: 200),
      curve: _navEase,
      width: collapsed ? 60 : 200,
      padding: EdgeInsets.symmetric(horizontal: pad, vertical: 12),
      decoration: BoxDecoration(
        color: JTokens.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JTokens.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x80000000),
            blurRadius: 24,
            offset: Offset(4, 0),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _NavHead(collapsed: collapsed, onToggle: onToggle),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (var g = 0; g < filteredGroups.length; g++) ...[
                    _NavGroup(
                      title: filteredGroups[g].$1,
                      first: g == 0,
                      collapsed: collapsed,
                    ),
                    for (final id in filteredGroups[g].$2)
                      _NavItem(
                        page: settingsPages.firstWhere((p) => p.id == id),
                        selected: id == selectedId,
                        collapsed: collapsed,
                        onTap: () => onItem(id),
                      ),
                  ],
                ],
              ),
            ),
          ),
          _NavFooter(collapsed: collapsed, onLogout: onLogout),
        ],
      ),
    );
  }
}

class _NavHead extends StatelessWidget {
  const _NavHead({required this.collapsed, required this.onToggle});

  final bool collapsed;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 48, // min-height 40 + 8 bottom padding
      margin: const EdgeInsets.only(bottom: 4),
      padding: const EdgeInsets.only(bottom: 8),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: JTokens.border)),
      ),
      child: Stack(
        children: [
          Positioned(
            left: 12,
            top: 0,
            bottom: 0,
            child: Center(
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 150),
                opacity: collapsed ? 0 : 1,
                child: const Text(
                  'Bảng điều khiển',
                  softWrap: false,
                  style: TextStyle(
                    fontSize: JTokens.fsBody,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.2,
                    color: JTokens.text,
                  ),
                ),
              ),
            ),
          ),
          AnimatedAlign(
            duration: const Duration(milliseconds: 200),
            curve: _navEase,
            alignment: collapsed ? Alignment.center : Alignment.centerRight,
            child: GestureDetector(
              key: const Key('settings-sidebar-toggle'),
              onTap: onToggle,
              child: Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: const Color(0x08FFFFFF),
                  borderRadius: BorderRadius.circular(7),
                  border: Border.all(color: JTokens.border),
                ),
                alignment: Alignment.center,
                child: MorphIcon(
                  icon: collapsed ? panelLeftGlyph : panelLeftCloseGlyph,
                  color: JTokens.muted,
                  size: 18,
                  strokeWidth: 1.75,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NavGroup extends StatelessWidget {
  const _NavGroup({
    required this.title,
    required this.first,
    required this.collapsed,
  });

  final String title;
  final bool first;
  final bool collapsed;

  @override
  Widget build(BuildContext context) {
    if (collapsed) {
      // the rail: a thin divider instead of the title
      return Container(
        height: 1,
        margin: EdgeInsets.fromLTRB(12, first ? 2 : 8, 12, 8),
        color: JTokens.border,
      );
    }
    return Padding(
      padding: EdgeInsets.fromLTRB(12, first ? 2 : 10, 12, 4),
      child: Opacity(
        opacity: 0.75,
        child: Text(
          title,
          softWrap: false,
          overflow: TextOverflow.clip,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.muted,
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.page,
    required this.selected,
    required this.collapsed,
    required this.onTap,
  });

  final SettingsPageDef page;
  final bool selected;
  final bool collapsed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? const Color(0xFFE0F2FE) : JTokens.muted;
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: GestureDetector(
        key: Key('nav-${page.id}'),
        onTap: onTap,
        behavior: HitTestBehavior.opaque,
        child: Container(
          height: 40,
          decoration: BoxDecoration(
            color: selected ? JTokens.accentSoft : null,
            borderRadius: BorderRadius.circular(8),
          ),
          clipBehavior: Clip.antiAlias,
          child: Stack(
            children: [
              if (selected)
                Positioned(
                  left: 0,
                  top: 8,
                  bottom: 8,
                  child: Container(
                    width: 3,
                    decoration: BoxDecoration(
                      color: JTokens.accent,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
              // the icon keeps its x while the width animates (8+12 open = 6+14 collapsed); the label fades
              OverflowBox(
                alignment: Alignment.centerLeft,
                minWidth: 0,
                maxWidth: double.infinity,
                child: Padding(
                  padding: EdgeInsets.only(left: collapsed ? 14 : 12),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      MorphIcon(
                        key: ValueKey(page.id),
                        icon: selected ? page.activeIcon : page.icon,
                        color: color,
                        size: 18,
                        strokeWidth: 1.75,
                      ),
                      const SizedBox(width: 10),
                      AnimatedOpacity(
                        duration: const Duration(milliseconds: 150),
                        opacity: collapsed ? 0 : 1,
                        child: Text(
                          page.label,
                          softWrap: false,
                          style: TextStyle(
                            fontSize: JTokens.fsUi,
                            fontWeight: FontWeight.w500,
                            color: color,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavFooter extends StatelessWidget {
  const _NavFooter({required this.collapsed, required this.onLogout});

  final bool collapsed;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final dot = Container(
      key: const Key('version-dot'),
      width: 5,
      height: 5,
      decoration: const BoxDecoration(
        shape: BoxShape.circle,
        color: JTokens.ok,
        boxShadow: [BoxShadow(color: Color(0x804ADE80), blurRadius: 6)],
      ),
    );
    final version = Text(
      'v$appVersion',
      softWrap: false,
      style: TextStyle(
        fontSize: collapsed ? 10 : JTokens.fsSmall,
        color: JTokens.muted,
      ),
    );
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.fromLTRB(4, 8, 4, 0),
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: JTokens.border)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          GestureDetector(
            key: const Key('btn-user-logout'),
            onTap: onLogout,
            behavior: HitTestBehavior.opaque,
            child: Container(
              height: 36,
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                color: const Color(0x0AF87171),
              ),
              clipBehavior: Clip.antiAlias,
              child: OverflowBox(
                alignment: Alignment.centerLeft,
                minWidth: 0,
                maxWidth: double.infinity,
                child: Padding(
                  padding: EdgeInsets.only(left: collapsed ? 14 : 12),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        Icons.logout_rounded,
                        size: 18,
                        color: Color(0xFFF87171),
                      ),
                      const SizedBox(width: 10),
                      AnimatedOpacity(
                        duration: const Duration(milliseconds: 150),
                        opacity: collapsed ? 0 : 1,
                        child: const Text(
                          'Đăng xuất',
                          softWrap: false,
                          style: TextStyle(
                            fontSize: JTokens.fsUi,
                            fontWeight: FontWeight.w500,
                            color: Color(0xFFF87171),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          collapsed
              ? Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [dot, const SizedBox(height: 5), version],
                  ),
                )
              : SizedBox(
                  height: 20,
                  child: OverflowBox(
                    maxWidth: double.infinity,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text(
                          'JARVIS',
                          style: TextStyle(
                            fontSize: JTokens.fsSmall,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 0.2,
                            color: JTokens.muted,
                          ),
                        ),
                        const SizedBox(width: 4),
                        dot,
                        const SizedBox(width: 4),
                        version,
                      ],
                    ),
                  ),
                ),
        ],
      ),
    );
  }
}
