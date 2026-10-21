import 'dart:typed_data';

/// Mirrors frontend/src/main.ts `State` (minus "restarting").
enum JState { idle, listening, thinking, working, speaking }

sealed class ChatItem {
  const ChatItem();
}

class UserMsg extends ChatItem {
  const UserMsg(this.text, {this.attachmentName, this.pending = false});
  final String text;
  final String? attachmentName;

  /// Queued behind a busy turn (web: the `.pending` bubble).
  final bool pending;
}

class AssistantMsg extends ChatItem {
  const AssistantMsg(this.text, {this.streaming = false});
  final String text;
  final bool streaming;
}

/// An `image_result` card. [url] is stored as the server sent it (may be relative, e.g. /api/outputs/...).
class ImageMsg extends ChatItem {
  const ImageMsg({
    required this.id,
    this.url,
    this.base64,
    this.caption = '',
    this.downloadUrl,
  });
  final String id;
  final String? url;
  final String? base64;
  final String caption;
  final String? downloadUrl;
}

/// A `file` card (Office document from `output_file`). URLs are stored as sent.
class FileMsg extends ChatItem {
  const FileMsg({
    required this.id,
    required this.name,
    required this.url,
    required this.kind,
    this.ext = '',
    this.label = '',
    this.caption = '',
    this.downloadUrl = '',
    this.size,
  });
  final String id;
  final String name;
  final String url;
  final String kind;
  final String ext;
  final String label;
  final String caption;
  final String downloadUrl;
  final int? size;
}

/// notify-island.ts `FlowStep`.
class FlowStep {
  const FlowStep({required this.id, required this.label, required this.status});
  final String id;
  final String label;
  final String status;
}

/// The flow tracker: ordered steps keyed by id (a repeated id updates in place).
class FlowSteps {
  const FlowSteps([this.steps = const []]);
  final List<FlowStep> steps;

  FlowSteps upsert(FlowStep s) {
    final i = steps.indexWhere((e) => e.id == s.id);
    final next = [...steps];
    if (i >= 0) {
      next[i] = s;
    } else {
      next.add(s);
    }
    return FlowSteps(List.unmodifiable(next));
  }
}

/// ask-panel.ts card: type is approve | select | input. [raw] is the whole card map.
class AskCard {
  const AskCard(this.raw);
  final Map<String, dynamic> raw;

  static const types = {'approve', 'select', 'input'};
  static bool isAskCard(Map<String, dynamic>? c) =>
      c != null && types.contains(c['type']);

  String get id => '${raw['id']}';
  String get type => '${raw['type']}';
}

/// reader-card.ts opens from a tap on a `.reader-trigger-btn` (url + title), not from a packet.
class ReaderCard {
  const ReaderCard({required this.url, this.title = ''});
  final String url;
  final String title;
}

/// `media_open` packet.
class MediaOpen {
  const MediaOpen({
    required this.query,
    required this.embedUrl,
    required this.title,
  });
  final String query;
  final String embedUrl;
  final String title;
}

/// welcome.ts `WelcomeData`.
class WelcomeWeather {
  const WelcomeWeather({
    required this.desc,
    this.temp,
    this.kind,
    this.place = '',
  });
  final String desc;
  final double? temp;
  final String? kind;
  final String place;
}

class WelcomeData {
  const WelcomeData({this.greeting, this.tools = const [], this.weather});
  final String? greeting;
  final List<String> tools;
  final WelcomeWeather? weather;
}

sealed class AudioEvent {
  const AudioEvent();
}

class PcmChunk extends AudioEvent {
  const PcmChunk(this.bytes, {this.sampleRate = 48000, this.gapMs = 0});
  final Uint8List bytes;
  final int sampleRate;
  final int gapMs;
}

class EncodedChunk extends AudioEvent {
  const EncodedChunk(this.bytes);
  final Uint8List bytes;
}

class EncodedEnd extends AudioEvent {
  const EncodedEnd();
}

class EncodedWhole extends AudioEvent {
  const EncodedWhole(this.bytes);
  final Uint8List bytes;
}

class StopAudio extends AudioEvent {
  const StopAudio();
}
