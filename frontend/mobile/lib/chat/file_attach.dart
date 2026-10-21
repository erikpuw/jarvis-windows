import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';

/// Opens a URL in the browser or another app, as a `target="_blank"` link does.
Future<bool> launchExternal(Uri url) =>
    launchUrl(url, mode: LaunchMode.externalApplication);

/// The `+` button (`#file-upload`): one file for the next message. Null when the user cancels.
Future<String?> pickUploadFile() async {
  final files = await FilePicker.pickFiles();
  return files.isEmpty ? null : files.first.path;
}

/// `#file-pinned-container`: the pinned file's name with a remove button, in the command bar.
class PinnedFile extends StatelessWidget {
  const PinnedFile({super.key, required this.name, required this.onRemove});

  final String name;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(maxWidth: 150),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0x260EA5E9),
        border: Border.all(color: const Color(0x4D0EA5E9)),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Flexible(
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: JTokens.fsLabel,
                letterSpacing: 0.5,
                color: Color(0xE6FFFFFF),
              ),
            ),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: onRemove,
            child: const Icon(Icons.close, size: 13, color: Color(0x66FFFFFF)),
          ),
        ],
      ),
    );
  }
}

/// A `file` card (`.interactive-card.file-card`): type icon, name, "PDF · 240 KB"; a tap opens the download.
class FileCard extends StatelessWidget {
  const FileCard({super.key, required this.file, required this.downloadUrl});

  final FileMsg file;

  /// Already resolved against the server.
  final String downloadUrl;

  @override
  Widget build(BuildContext context) {
    final ext = file.ext.toUpperCase();
    final meta = [
      if (file.label.isNotEmpty) file.label else if (ext.isNotEmpty) ext,
      if (file.size != null) _size(file.size!),
      if (file.caption.trim().isNotEmpty) file.caption.trim(),
    ].join(' · ');
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 360),
        padding: const EdgeInsets.fromLTRB(10, 6, 6, 6),
        decoration: BoxDecoration(
          color: const Color(0xFF0A0A0A),
          border: Border.all(color: const Color(0xFF262626)),
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.description_outlined,
              size: 30,
              color: Color(0xFFA3A3A3),
            ),
            const SizedBox(width: 10),
            Flexible(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    file.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: JTokens.fsSmall,
                      fontWeight: FontWeight.w500,
                      color: Color(0xFFE5E5E5),
                    ),
                  ),
                  if (meta.isNotEmpty)
                    Text(
                      meta,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: JTokens.fsLabel,
                        color: Color(0xFF737373),
                      ),
                    ),
                ],
              ),
            ),
            IconButton(
              onPressed: () => launchExternal(Uri.parse(downloadUrl)),
              icon: const Icon(
                Icons.download_outlined,
                size: 18,
                color: Color(0xFFA3A3A3),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// "240 KB" from the byte count (engine/core/output_delivery.py sends it with output_file).
String _size(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).round()} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
