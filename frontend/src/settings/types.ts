import type { IconNode } from "lucide";

declare global {
  interface Window {
    __orbFrames?: number;
  }
}

export type SettingsPageId =
  | "overview"
  | "connect"
  | "voice"
  | "user"
  | "system"
  | "memory"
  | "logs"
  | "agents"
  | "hooks"
  | "skills"
  | "prompts"
  | "commands"
  | "plugins"
  | "mcp"
  | "graphfy"
  | "info";

export interface SettingsPageDef {
  id: SettingsPageId;
  label: string;
  description: string;
  icon: IconNode;
  activeIcon: IconNode;
  needsKey: boolean;
}

export interface AgentItem {
  id: string;
  name: string;
  file: string;
  description: string;
  example: string;
  tools?: string[];
  aliases?: string[];
  /** "@id" — accepted by the command bar (engine/router/fast_paths.resolve_mention). */
  mention?: string;
}

export interface HookItem {
  name: string;
  file: string;
  description: string;
  events: string[];
  runtime?: string;
  active?: boolean;
  file_path?: string;
}

export interface SkillItem {
  name: string;
  folder?: string;
  description: string;
  category?: string;
  tags?: string[];
  file_path?: string;
}

export interface PromptItem {
  id: string;
  name: string;
  title: string;
  description: string;
  size_bytes?: number;
  lines_count?: number;
  file_path?: string;
  content?: string;
}

export interface CommandItem {
  name: string;
  file?: string;
  description: string;
  usage?: string;
  category?: string;
  tags?: string[];
  file_path?: string;
}

export interface PluginItem {
  name: string;
  file?: string;
  description: string;
  runtime?: string;
  active?: boolean;
  file_path?: string;
}

export interface McpServerItem {
  name: string;
  command?: string;
  args?: string[];
  url?: string;
  enabled?: boolean;
  status: string;
  type: string;
}

export interface GpuInfo {
  name: string;
  mem_used_mb?: number;
  mem_total_mb?: number;
  vram_total_mb?: number;
  util_percent?: number;
  temp_c?: number;
}

export interface StatusResponse {
  intelligence_core_ok?: boolean;
  server_engine_ok?: boolean;
  llm_server_ok?: boolean;
  tts_server_ok?: boolean;
  session_active?: boolean;
  memory_count?: number;
  messages_count?: number;
  conversation_turn_count?: number;
  task_count?: number;
  server_port?: number;
  uptime_seconds?: number;
  skill_count?: number;
  command_count?: number;
  hooks_loaded?: number;
  plugins_loaded?: number;
  mcp_total?: number;
  mcp_connected?: number;
  mcp_servers?: McpServerItem[];
  mcp_config?: Record<string, any>;
  readme_content?: string;
  skills_list?: SkillItem[];
  commands_list?: CommandItem[];
  plugins_list?: PluginItem[];
  prompts_list?: PromptItem[];
  hooks_list?: HookItem[];
  agents?: AgentItem[];
  agents_count?: number;
  open_apps?: string[];
  system?: {
    cpu_percent?: number;
    ram_percent?: number;
    ram_used_gb?: number;
    ram_total_gb?: number;
    gpus?: GpuInfo[];
    npus?: string[];
  };
  session_tokens?: {
    input?: number;
    output?: number;
    total?: number;
  };
  env_keys_set?: {
    llama?: boolean;
    fish_audio?: boolean;
    fish_voice_id?: boolean;
    user_name?: string | null;
  };
}

export interface PreferencesResponse {
  user_name?: string;
  honorific?: string;
  calendar_accounts?: string;
}

export interface MemoryItem {
  id: string;
  category: "fact" | "rule" | "context" | "user_pref";
  content: string;
  created_at: string;
  confidence: number;
  reference_count: number;
  has_dependents: boolean;
}
