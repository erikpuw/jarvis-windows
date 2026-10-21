class AuthUser {
  final String id;
  final String username;
  final String? displayName;
  final String role; // 'admin' | 'member'
  final String? ttsVoiceId;
  final String? userPronoun;
  final String? aiPronoun;

  const AuthUser({
    required this.id,
    required this.username,
    this.displayName,
    this.role = 'member',
    this.ttsVoiceId,
    this.userPronoun,
    this.aiPronoun,
  });

  bool get isAdmin => role == 'admin';

  factory AuthUser.fromJson(Map<String, dynamic> json) => AuthUser(
    id: json['id']?.toString() ?? '',
    username: json['username']?.toString() ?? '',
    displayName: json['display_name']?.toString(),
    role: json['role']?.toString() ?? 'member',
    ttsVoiceId: json['tts_voice_id']?.toString(),
    userPronoun: json['user_pronoun']?.toString(),
    aiPronoun: json['ai_pronoun']?.toString(),
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'username': username,
    if (displayName != null) 'display_name': displayName,
    'role': role,
    if (ttsVoiceId != null) 'tts_voice_id': ttsVoiceId,
    if (userPronoun != null) 'user_pronoun': userPronoun,
    if (aiPronoun != null) 'ai_pronoun': aiPronoun,
  };
}
