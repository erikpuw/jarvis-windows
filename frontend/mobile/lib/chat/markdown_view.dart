import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:highlight/highlight.dart' as hi;
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:markdown_widget/markdown_widget.dart';

import '../theme/tokens.dart';

// Values below come from frontend/src/style.css (.chat-bubble .bubble-prose ..., phone block: --bubble-font-size 15px).
double get _fs => JTokens.bubbleFont;
double get _fsSmall => JTokens.tableFont;
const _lineHeight = 1.5;
const _code = Color(0xFFE2E8F0);
const _link = Color(0xFF0EA5E9);
const _inlineCode = Color(0xFF38BDF8);
const _mono = ['Menlo', 'SF Mono', 'Cascadia Code', 'Consolas', 'monospace'];

TextStyle get _tableText => TextStyle(
  fontSize: _fsSmall,
  height: _lineHeight,
  color: _code,
);

// highlight.js `github-dark.css` (markdown.ts imports it), keyed by the class names of the `highlight` package.
const _red = TextStyle(color: Color(0xFFFF7B72));
const _purple = TextStyle(color: Color(0xFFD2A8FF));
const _blue = TextStyle(color: Color(0xFF79C0FF));
const _lightBlue = TextStyle(color: Color(0xFFA5D6FF));
const _orange = TextStyle(color: Color(0xFFFFA657));
const _grey = TextStyle(color: Color(0xFF8B949E));
const _green = TextStyle(color: Color(0xFF7EE787));
const _githubDark = <String, TextStyle>{
  'doctag': _red,
  'keyword': _red,
  'meta-keyword': _red,
  'template-tag': _red,
  'template-variable': _red,
  'type': _red,
  'title': _purple,
  'function': _purple,
  'class': _purple,
  'attr': _blue,
  'attribute': _blue,
  'literal': _blue,
  'meta': _blue,
  'number': _blue,
  'operator': _blue,
  'variable': _blue,
  'selector-attr': _blue,
  'selector-class': _blue,
  'selector-id': _blue,
  'regexp': _lightBlue,
  'string': _lightBlue,
  'meta-string': _lightBlue,
  'built_in': _orange,
  'symbol': _orange,
  'comment': _grey,
  'code': _grey,
  'formula': _grey,
  'name': _green,
  'quote': _green,
  'selector-tag': _green,
  'selector-pseudo': _green,
  'section': TextStyle(color: Color(0xFF1F6FEB), fontWeight: FontWeight.bold),
  'bullet': TextStyle(color: Color(0xFFF2CC8F)),
  'emphasis': TextStyle(fontStyle: FontStyle.italic),
  'strong': TextStyle(fontWeight: FontWeight.bold),
};

bool _isRow(String l) {
  final t = l.trim();
  return t.startsWith('|') || (t.contains('|') && !t.startsWith('```'));
}

/// markdown.ts normalizeMarkdownTables: a blank line before and after every table, or the line after it is swallowed.
String normalizeMarkdownTables(String md) {
  if (md.isEmpty || !md.contains('|')) return md;
  final lines = md.split('\n');
  final out = <String>[];
  final delim = RegExp(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$');
  var inTable = false;
  var inCode = false;
  for (var i = 0; i < lines.length; i++) {
    final line = lines[i];
    final t = line.trim();
    final next = i + 1 < lines.length ? lines[i + 1] : null;
    if (t.startsWith('```')) {
      inCode = !inCode;
      inTable = false;
      out.add(line);
      continue;
    }
    if (inCode) {
      out.add(line);
      continue;
    }
    if (t.isEmpty) {
      inTable = false;
      out.add(line);
      continue;
    }
    if (_isRow(line) && next != null && delim.hasMatch(next)) {
      if (out.isNotEmpty && out.last.trim().isNotEmpty) out.add('');
      inTable = true;
      out.add(line);
      continue;
    }
    if (inTable && !(delim.hasMatch(line) || _isRow(line))) {
      inTable = false;
      if (out.isNotEmpty && out.last.trim().isNotEmpty) out.add('');
    }
    out.add(line);
  }
  return out.join('\n');
}

/// While an answer streams, a table at its tail is not drawn row by row (markdown.ts replaceStreamingIncompleteTables):
/// the text before it is shown and a skeleton stands in. Returns the text before the tail table and its column count.
({String head, int cols})? streamingTableTail(String md) {
  if (!md.contains('|')) return null;
  final lines = md.split('\n');
  var inCode = false;
  int? start;
  for (var i = 0; i < lines.length; i++) {
    if (lines[i].trim().startsWith('```')) {
      inCode = !inCode;
      start = null;
    } else if (inCode) {
      continue;
    } else if (_isRow(lines[i])) {
      start ??= i;
    } else {
      start = null;
    }
  }
  if (start == null || inCode) return null;
  final headerDone = lines.length - start > 1;
  final cols = headerDone
      ? lines[start]
            .split('|')
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .length
      : 0;
  return (head: lines.sublist(0, start).join('\n'), cols: cols == 0 ? 3 : cols);
}

final _lf = String.fromCharCode(10);

final _linkDefinition = RegExp(r'^ {0,3}\[[^\]]+\]:\s*\S+');

final _listLine = RegExp(r'^(\s+|[-*+]\s|\d+[.)]\s)');

/// The top-level blocks of [md]: cut at a blank line outside a code fence, except before an indented or list line (a loose list
/// stays one block, or its numbering would restart). A block ends without trailing newlines, so its text only changes when the
/// block itself does.
List<String> splitMarkdownBlocks(String md) {
  final blocks = <String>[];
  final cur = <String>[];
  String? fence; // the open code fence marker (``` or ~~~)
  var gap = false; // blank line(s) seen since the last text line
  void flush() {
    if (cur.isNotEmpty) blocks.add(cur.join('\n'));
    cur.clear();
  }

  for (final line in md.split('\n')) {
    if (fence == null && line.trim().isEmpty) {
      if (cur.isNotEmpty) gap = true;
      continue;
    }
    if (gap) {
      if (_listLine.hasMatch(line)) {
        cur.add('');
      } else {
        flush();
      }
    }
    gap = false;
    cur.add(line);
    final t = line.trim();
    final marker = t.startsWith('```')
        ? '```'
        : t.startsWith('~~~')
        ? '~~~'
        : null;
    if (marker != null && (fence == null || fence == marker)) {
      fence = fence == null ? marker : null;
    }
  }
  flush();
  return blocks;
}

/// How many times a block was turned into widgets: the streaming test checks that finished blocks are not.
@visibleForTesting
int markdownBlockBuilds = 0;

/// How many times a whole answer was walked (split into blocks): a finished answer must not be while another one streams.
@visibleForTesting
int markdownViewBuilds = 0;

class MarkdownView extends StatelessWidget {
  const MarkdownView(
    this.text, {
    super.key,
    this.streaming = false,
    required this.resolveUrl,
    this.onLinkTap,
    this.onReaderTap,
  });

  final String text;
  final bool streaming;

  /// Turns a server-relative image URL (/api/outputs/...) into an absolute one (ServerConfig.http).
  final String Function(String url) resolveUrl;

  /// A tap on a link opens it in the browser (target=_blank).
  final void Function(String url)? onLinkTap;

  /// The small button after an http(s) link (`.reader-trigger-btn`): opens the reader card.
  final void Function(String url, String title)? onReaderTap;

  @override
  Widget build(BuildContext context) {
    markdownViewBuilds++;
    var md = text.replaceAll('\r\n', '\n');
    ({String head, int cols})? tail;
    if (streaming) {
      tail = streamingTableTail(md);
      if (tail != null) md = tail.head;
    }
    // The web appends only the tail of an answer. Here every block is its own keyed widget that turns its text into widgets once
    // and hands the same ones back until that text changes: a finished table keeps its scroll position and is not laid out again.
    final blocks = splitMarkdownBlocks(normalizeMarkdownTables(md));
    // `[text][ref]` resolves against a definition in another block: every block is parsed with the definitions of the answer
    final defs = [
      for (final line in md.split(_lf))
        if (_linkDefinition.hasMatch(line)) line.trim(),
    ];
    final suffix = defs.isEmpty ? '' : '$_lf$_lf${defs.join(_lf)}';
    return DefaultTextStyle.merge(
      style: TextStyle(
        fontSize: _fs,
        height: _lineHeight,
        color: JTokens.chatText,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < blocks.length; i++)
            _MdBlock(key: ValueKey(i), text: blocks[i] + suffix, view: this),
          if (tail != null) TableSkeleton(cols: tail.cols),
        ],
      ),
    );
  }

  List<Widget> _widgets(String md) {
    markdownBlockBuilds++;
    final generator = MarkdownGenerator(
      linesMargin: const EdgeInsets.symmetric(vertical: 3),
      generators: [
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.table.name,
          generator: (e, config, visitor) => _TableNode(config),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.thead.name,
          generator: (e, config, visitor) => _THead(config, visitor),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.tbody.name,
          generator: (e, config, visitor) => _TBody(config, visitor),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.td.name,
          generator: (e, config, visitor) => _Td(e.attributes, visitor),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.li.name,
          generator: (e, config, visitor) => _ListNode(config, visitor),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.strong.name,
          generator: (e, config, visitor) => _StrongNode(),
        ),
        SpanNodeGeneratorWithTag(
          tag: MarkdownTag.a.name,
          generator: (e, config, visitor) =>
              _LinkNode(e.attributes, config.a, e.textContent, onReaderTap),
        ),
        for (final h in const ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
          SpanNodeGeneratorWithTag(
            tag: h,
            generator: (e, config, visitor) => _Heading(switch (h) {
              'h1' => config.h1,
              'h2' => config.h2,
              'h3' => config.h3,
              'h4' => config.h4,
              'h5' => config.h5,
              _ => config.h6,
            }, visitor),
          ),
      ],
    );
    return generator.buildWidgets(md, config: _config());
  }

  MarkdownConfig _config() {
    final body = TextStyle(
      fontSize: _fs,
      height: _lineHeight,
      color: JTokens.chatText,
    );
    return MarkdownConfig(
      configs: [
        PConfig(textStyle: body),
        const _HeadingStyle('h1', 1.08),
        const _HeadingStyle('h2', 1.04),
        const _HeadingStyle('h3', 1),
        const _HeadingStyle('h4', 1),
        const _HeadingStyle('h5', 1),
        const _HeadingStyle('h6', 1),
        LinkConfig(
          style: const TextStyle(
            color: _link,
            fontWeight: FontWeight.w500,
            decoration: TextDecoration.underline,
            decorationStyle: TextDecorationStyle.dashed,
            decorationColor: _link,
          ),
          onTap: (url) => onLinkTap?.call(url),
        ),
        const ListConfig(marginLeft: 16, marginBottom: 2),
        const BlockquoteConfig(
          sideColor: Color(0x5994A3B8),
          sideWith: 2,
          textColor: JTokens.muted,
          padding: EdgeInsets.fromLTRB(10, 4, 0, 4),
          margin: EdgeInsets.symmetric(vertical: 6),
        ),
        const HrConfig(height: 1, color: Color(0x1AFFFFFF)),
        CodeConfig(
          style: TextStyle(
            fontFamily: _mono.first,
            fontFamilyFallback: _mono,
            fontSize: _fsSmall,
            color: _inlineCode,
            backgroundColor: const Color(0x1F0EA5E9),
          ),
        ),
        PreConfig(
          builder: (code, lang) => _CodeBlock(code: code, lang: lang),
        ),
        ImgConfig(builder: (url, attrs) => _Img(resolveUrl(url), attrs['alt'])),
        TableConfig(
          defaultColumnWidth: const MaxColumnWidth(
            FixedColumnWidth(140),
            MinColumnWidth(IntrinsicColumnWidth(), FixedColumnWidth(280)),
          ),
          border: TableBorder.all(color: const Color(0x14FFFFFF)),
          headerRowDecoration: const BoxDecoration(color: Color(0x2E0EA5E9)),
          headerStyle: _tableText,
          headPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          bodyPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          wrapper: (table) => _TableFrame(table),
        ),
      ],
    );
  }
}

/// A link, and after an http(s) one the small reader button (markdown.ts: `a.after(btn)` for `.reader-trigger-btn`).
class _LinkNode extends LinkNode {
  _LinkNode(super.attributes, super.config, this.title, this.onReader);

  final String title;
  final void Function(String url, String title)? onReader;

  @override
  InlineSpan build() {
    final span = super.build();
    final url = attributes['href'] ?? '';
    if (onReader == null ||
        !(url.startsWith('http://') || url.startsWith('https://'))) {
      return span;
    }
    return TextSpan(
      children: [
        span,
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: GestureDetector(
            key: const ValueKey('reader-trigger'),
            behavior: HitTestBehavior.opaque,
            onTap: () => onReader!(url, title.trim()),
            child: Container(
              width: 22,
              height: 22,
              margin: const EdgeInsets.only(left: 5),
              decoration: BoxDecoration(
                color: const Color(0x14FFFFFF),
                border: Border.all(color: const Color(0x1FFFFFFF)),
                borderRadius: BorderRadius.circular(4),
              ),
              child: const Icon(
                LucideIcons.bookOpen,
                size: 12,
                color: Color(0xB3FFFFFF),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// `h1`..`h6`: accent blue, 600, line-height 1.3, sized from the bubble font (style.css .bubble-prose h1..h3).
class _HeadingStyle extends HeadingConfig {
  const _HeadingStyle(this._tag, this._scale);
  final String _tag;
  final double _scale;

  @override
  TextStyle get style => TextStyle(
    fontSize: _fs * _scale,
    height: 1.3,
    fontWeight: FontWeight.w600,
    color: JTokens.accent,
  );

  @override
  String get tag => _tag;
}

/// A heading opens a section: 12px above, 4px below (style.css `margin: 12px 0 4px 0`); blocks already sit 3px apart.
class _Heading extends HeadingNode {
  _Heading(super.headingConfig, super.visitor);

  @override
  InlineSpan build() => WidgetSpan(
    child: Padding(
      padding: const EdgeInsets.only(top: 9, bottom: 1),
      child: ProxyRichText(
        childrenSpan,
        richTextBuilder: visitor.richTextBuilder,
      ),
    ),
  );
}

class _TableFrame extends StatelessWidget {
  const _TableFrame(this.table);
  final Widget table;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    margin: const EdgeInsets.symmetric(vertical: 5),
    clipBehavior: Clip.antiAlias,
    decoration: BoxDecoration(
      color: JTokens.bg,
      border: Border.all(color: const Color(0x1AFFFFFF)),
      borderRadius: BorderRadius.circular(6),
    ),
    child: DefaultTextStyle.merge(
      style: _tableText,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: table,
      ),
    ),
  );
}

/// Header cells: white, 600, left-aligned (the package centres them).
class _THead extends THeadNode {
  _THead(super.config, super.visitor);

  @override
  List<TableRow> get rows => [
    for (final tr in children.cast<TrNode>())
      TableRow(
        decoration: config.table.headerRowDecoration,
        children: [
          for (final th in tr.children)
            Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: config.table.headPadding,
                child: ProxyRichText(
                  th.build(),
                  richTextBuilder: visitor.richTextBuilder,
                ),
              ),
            ),
        ],
      ),
  ];

  @override
  TextStyle? get style =>
      _tableText.copyWith(color: Colors.white, fontWeight: FontWeight.w600);
}

class _TBody extends TBodyNode {
  _TBody(super.config, super.visitor);

  @override
  TextStyle? get style => _tableText;
}

class _Td extends TdNode {
  _Td(super.attribute, super.visitor);

  @override
  TextStyle? get style => _tableText;
}

/// List item node: explicitly matches the bubble font size without expanding.
class _ListNode extends ListNode {
  _ListNode(super.config, super.visitor);

  @override
  TextStyle? get style => TextStyle(
    fontSize: _fs,
    height: 1.45,
    color: JTokens.chatText,
  );
}

/// Bold text matching web CSS (white, 600 weight instead of 700 bold).
class _StrongNode extends StrongNode {
  @override
  TextStyle get style =>
      (parentStyle ?? TextStyle(fontSize: _fs, color: JTokens.chatText))
          .copyWith(fontWeight: FontWeight.w600, color: Colors.white);
}

/// markdown.ts "card tables": a table with a row of pictures in every column becomes a wrapping grid of cards.
class _TableNode extends TableNode {
  _TableNode(super.config);

  @override
  TextStyle? get style => _tableText;

  bool _hasImage(SpanNode n) =>
      n is ImageNode || (n is ElementNode && n.children.any(_hasImage));

  @override
  InlineSpan build() {
    final rows = <(bool, List<SpanNode>)>[];
    for (final part in children) {
      if (part is! ElementNode) continue;
      for (final tr in part.children.whereType<ElementNode>()) {
        rows.add((part is THeadNode, tr.children));
      }
    }
    final cols = rows.isEmpty ? 0 : rows.first.$2.length;
    final cardTable =
        cols >= 2 &&
        rows.any((r) => r.$2.length == cols && r.$2.every(_hasImage));
    if (!cardTable) return super.build();
    final cards = <Widget>[];
    for (var c = 0; c < cols; c++) {
      final parts = <Widget>[];
      for (final (head, cells) in rows) {
        if (c >= cells.length) continue;
        final cell = cells[c];
        final span = cell.build();
        if (span.toPlainText().trim().isEmpty && !_hasImage(cell)) continue;
        parts.add(
          Container(
            constraints: head
                ? BoxConstraints(minHeight: _fsSmall * 3)
                : null,
            alignment: Alignment.center,
            child: ProxyRichText(
              span,
              richTextBuilder: (s) => Text.rich(s, textAlign: TextAlign.center),
            ),
          ),
        );
      }
      cards.add(_Card(parts));
    }
    return WidgetSpan(child: _CardGrid(cards));
  }
}

class _CardGrid extends StatelessWidget {
  const _CardGrid(this.cards);
  final List<Widget> cards;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      // grid-template-columns: repeat(auto-fit, minmax(min(130px, 100%), 1fr)); gap 8
      final w = box.maxWidth;
      final n = ((w + 8) / 138).floor().clamp(1, cards.length);
      final cw = (w - 8 * (n - 1)) / n;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [for (final c in cards) SizedBox(width: cw, child: c)],
        ),
      );
    },
  );
}

class _Card extends StatelessWidget {
  const _Card(this.parts);
  final List<Widget> parts;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 8),
    decoration: BoxDecoration(
      color: const Color(0x05FFFFFF),
      border: Border.all(color: const Color(0x1AFFFFFF)),
      borderRadius: BorderRadius.circular(6),
    ),
    child: DefaultTextStyle.merge(
      style: _tableText,
      textAlign: TextAlign.center,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        spacing: 4,
        children: parts,
      ),
    ),
  );
}

class _Img extends StatelessWidget {
  const _Img(this.url, this.alt);
  final String url;
  final String? alt;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.fromLTRB(0, 6, 4, 6),
    constraints: const BoxConstraints(maxWidth: 180, maxHeight: 140),
    decoration: BoxDecoration(
      color: const Color(0x0AFFFFFF),
      border: Border.all(color: const Color(0x1AFFFFFF)),
      borderRadius: BorderRadius.circular(8),
    ),
    clipBehavior: Clip.antiAlias,
    child: Image.network(
      url,
      fit: BoxFit.cover,
      errorBuilder: (_, _, _) => Padding(
        padding: const EdgeInsets.all(8),
        child: Text(
          alt ?? '',
          style: TextStyle(color: JTokens.muted, fontSize: _fsSmall),
        ),
      ),
    ),
  );
}

class _CodeBlock extends StatefulWidget {
  const _CodeBlock({required this.code, required this.lang});
  final String code;
  final String lang;

  @override
  State<_CodeBlock> createState() => _CodeBlockState();
}

class _CodeBlockState extends State<_CodeBlock> {
  bool _copied = false;

  /// highlight.js only runs for a fenced block that names a language; an unknown one stays plain (markdown.ts try/catch).
  List<InlineSpan> _spans(TextStyle style) {
    final text = widget.code.trimRight();
    final plain = <InlineSpan>[TextSpan(text: text, style: style)];
    if (widget.lang.isEmpty) return plain;
    try {
      final nodes = hi.highlight.parse(text, language: widget.lang).nodes;
      return nodes == null
          ? plain
          : convertHiNodes(
              nodes,
              _githubDark,
              TextStyle(
                fontFamily: style.fontFamily,
                fontFamilyFallback: style.fontFamilyFallback,
                fontSize: style.fontSize,
                height: style.height,
              ),
              style,
            );
    } catch (_) {
      return plain;
    }
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.code));
    if (!mounted) return;
    setState(() => _copied = true);
    await Future<void>.delayed(const Duration(milliseconds: 1500));
    if (mounted) setState(() => _copied = false);
  }

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(
      fontFamily: _mono.first,
      fontFamilyFallback: _mono,
      fontSize: _fsSmall,
      height: 1.45,
      color: _code,
    );
    const label = TextStyle(
      fontFamily: 'Menlo',
      fontFamilyFallback: _mono,
      fontSize: JTokens.fsLabel,
      color: _inlineCode,
      fontWeight: FontWeight.w600,
    );
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 5),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: const Color(0xE60A0F19),
        border: Border.all(color: const Color(0x400EA5E9)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: const BoxDecoration(
              color: Color(0x140EA5E9),
              border: Border(bottom: BorderSide(color: Color(0x260EA5E9))),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  widget.lang.isEmpty ? 'code' : widget.lang.toLowerCase(),
                  style: label,
                ),
                GestureDetector(
                  onTap: _copy,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 7,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0x1A0EA5E9),
                      border: Border.all(color: const Color(0x4D0EA5E9)),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      _copied ? 'Đã chép!' : 'Sao chép',
                      style: const TextStyle(
                        fontSize: JTokens.fsLabel,
                        color: JTokens.muted,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Text.rich(TextSpan(children: _spans(style), style: style)),
          ),
        ],
      ),
    );
  }
}

/// Skeleton standing in for a table that is still being streamed (markdown.ts generateTableSkeleton).
class TableSkeleton extends StatelessWidget {
  const TableSkeleton({super.key, required this.cols});
  final int cols;

  static const _widths = [0.78, 0.85, 0.68, 0.82, 0.72, 0.80];

  Widget _bar(double h, int i) => FractionallySizedBox(
    alignment: Alignment.centerLeft,
    widthFactor: _widths[i % _widths.length],
    child: Container(
      height: h,
      decoration: BoxDecoration(
        color: const Color(0x1AFFFFFF),
        borderRadius: BorderRadius.circular(4),
      ),
    ),
  );

  Widget _cell(double h, int i) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    child: _bar(h, i),
  );

  @override
  Widget build(BuildContext context) {
    final n = cols.clamp(1, 6);
    return _TableFrame(
      Table(
        defaultColumnWidth: const FixedColumnWidth(140),
        border: TableBorder.all(color: const Color(0x14FFFFFF)),
        children: [
          TableRow(
            decoration: const BoxDecoration(color: Color(0x2E0EA5E9)),
            children: [for (var c = 0; c < n; c++) _cell(12, c)],
          ),
          for (var r = 0; r < 3; r++)
            TableRow(
              children: [for (var c = 0; c < n; c++) _cell(10, r * 2 + c)],
            ),
        ],
      ),
    );
  }
}

class _MdBlock extends StatefulWidget {
  const _MdBlock({super.key, required this.text, required this.view});
  final String text;
  final MarkdownView view;

  @override
  State<_MdBlock> createState() => _MdBlockState();
}

class _MdBlockState extends State<_MdBlock> {
  String? _text;
  MarkdownView? _view;
  Widget _built = const SizedBox.shrink();

  @override
  Widget build(BuildContext context) {
    final v = widget.view, old = _view;
    // a different handler (or URL resolver) must reach the tapped link: rebuild, still only this block
    final same =
        old != null &&
        old.onLinkTap == v.onLinkTap &&
        old.onReaderTap == v.onReaderTap &&
        old.resolveUrl == v.resolveUrl;
    if (_text != widget.text || !same) {
      _text = widget.text;
      _view = v;
      _built = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: widget.view._widgets(widget.text),
      );
    }
    return _built;
  }
}
