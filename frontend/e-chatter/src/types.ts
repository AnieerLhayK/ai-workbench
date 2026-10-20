export interface Folder { id: string; name: string; parent: string | null; collapsed: boolean }
export type Agent = 'codex' | 'deepseek';
export interface ModelChoice {model: string | null; effort: string | null}
export interface Session { id: string; title: string; folder: string | null; character_id: string | null; version: number | null; model: string | null; model_preferences?: Partial<Record<Agent, ModelChoice>>; authorized_agents?: Agent[] }
export interface Character { id: string; name: string; description: string; category: 'developing' | 'runtime'; version: number; source: string }
export interface Message { id: string; session_id: string; role: string; text: string; task_id: string | null; metadata: { character_id?: string; version?: number; kind?: string; execution?: {agent?: Agent; model?: string; effort?: string | null; actual_model?: string; actual_effort?: string | null} } }
export interface Task { id: string; session_id: string; kind: string; status: string; error?: string | null }
export interface Proposal { id: string; task_id: string; session_id: string; kind: string; character_id: string | null; base_version: number | null; status: string; changes: Record<string, { before: string; after: string }> }
export interface RecordEntry { id: string; session_id: string; task_id: string; kind: string; body: string; character_id?: string; version?: number }
export interface Snapshot { app_version?: string; folders: Folder[]; sessions: Session[]; messages: Message[]; characters: Character[]; versions: {id: string; character_id: string; number: number}[]; tasks: Task[]; proposals: Proposal[]; records: RecordEntry[]; settings: { theme: 'light' | 'dark'; characters_root: string; agent?: Agent; model?: string; codex_cli?: string; deepseek_cli?: string; deepseek_auth?: 'account' | 'api_key' }; demo: boolean }
export interface Account { connected: boolean; label: string; agent?: Agent; name?: string; has_key?: boolean; attempt?: {id: string; phase: string} | null; models: {id: string; name: string; default?: boolean; efforts?: {id: string; name: string}[]; default_effort?: string}[] }
export interface Confirmation { token: string; role: string; text: string }
export interface Material { id: string; name: string; as_skill: boolean }
export type AppEvent = { type: 'snapshot'; snapshot: Snapshot } | {type: 'delta'; task_id: string; session_id: string; text: string} | {type: 'done'; task_id: string; session_id: string};
export const emptySnapshot: Snapshot = {folders: [], sessions: [], messages: [], characters: [], versions: [], tasks: [], proposals: [], records: [], settings: {theme: 'light', characters_root: ''}, demo: false};
