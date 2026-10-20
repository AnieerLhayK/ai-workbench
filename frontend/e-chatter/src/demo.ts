/** Explicit browser-only memory demo. Never used by a real desktop connection. */
import type { AppEvent, Snapshot, Agent, Confirmation } from './types';
import type { Transport } from './bridge';

export class DemoTransport implements Transport {
  private listeners = new Set<(event: AppEvent) => void>();
  private confirmations = new Map<string, {session_id: string; role: string}>();
  private cancelled = new Set<string>();
  private state: Snapshot = {
    demo: true, settings: {theme: 'light', characters_root: '演示模式 / characters', agent: 'codex'},
    folders: [{id: 'f1', name: '写作练习', parent: null, collapsed: false}, {id: 'f2', name: '随笔', parent: 'f1', collapsed: false}, {id: 'f3', name: '角色实验', parent: null, collapsed: false}, {id: 'f4', name: '节奏测试', parent: 'f3', collapsed: true}],
    sessions: [{id: 's1', title: '关于一段文字的讨论', folder: 'f2', character_id: 'c1', version: 1, model: null}, {id: 's2', title: '改写练习', folder: 'f2', character_id: null, version: null, model: null}],
    characters: [{id: 'c1', name: '样例角色 A', description: '显式演示中的虚构角色', category: 'developing', version: 1, source: 'demo'}, {id: 'c2', name: '样例角色 B', description: '显式演示中的虚构角色', category: 'runtime', version: 1, source: 'demo'}],
    versions: [{id: 'v1', character_id: 'c1', number: 1}, {id: 'v2', character_id: 'c2', number: 1}],
    messages: [{id: 'm1', session_id: 's1', role: 'user', text: '这段话的情绪有些直白，帮我改得克制一点。', task_id: null, metadata: {}}, {id: 'm2', session_id: 's1', role: 'assistant', text: '那段日子里，我常常在夜里想起那次分别。它并没有想象中那样戏剧化，却在不知不觉中改变了我对许多事情的看法。\n\n回过头看，那些看似平常的细节，其实都在悄悄塑造着我。虽然仍会有些失落，但我也逐渐学会接受，并在这种接受中找到新的平衡。\n\n这是内存演示中的示例文字，不代表真实模型输出。', task_id: null, metadata: {character_id: 'c1', version: 1}}], tasks: [], proposals: [], records: [],
  };
  private snapshot() { return structuredClone(this.state); }
  private emit(event: AppEvent) { this.listeners.forEach(listener => listener(event)); }
  private update() { this.emit({type: 'snapshot', snapshot: this.snapshot()}); }
  subscribe(listener: (event: AppEvent) => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; }
  async call<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
    let result: unknown;
    const s = this.state;
    const session = s.sessions.find(row => row.id === args.session_id);
    if (method === 'snapshot') return this.snapshot() as T;
    if (method === 'account.status') {const agent = (args.agent || s.settings.agent || 'codex') as Agent; return {agent, name: agent === 'codex' ? 'Codex' : 'DeepSeek Harness', connected: true, label: '演示连接（不使用真实账号）', models: [{id: 'demo', name: '演示模型 A', default: true, efforts: [{id: 'low', name: '低'}, {id: 'high', name: '高'}]}, {id: 'demo-b', name: '演示模型 B', efforts: []}]} as T;}
    if (method === 'agent.select') {if (s.tasks.some(t => t.status === 'running' || t.kind !== 'chat' && t.status === 'needs_input')) throw new Error('请先完成或取消正在进行的任务'); s.settings.agent = args.agent as Agent; return {snapshot: this.snapshot(), account: await this.call('account.status')} as T;}
    if (method === 'models.save') {if (s.tasks.some(t => t.session_id === args.session_id && t.status === 'running')) throw new Error('请先停止当前会话的生成'); if (session) session.model_preferences = {...session.model_preferences, [String(args.agent)]: {model: args.model, effort: args.effort}}; return this.snapshot() as T;}
    if (method === 'provider.authorize') {if (session) session.authorized_agents = [...(session.authorized_agents || ['codex']), args.agent as Agent]; return this.snapshot() as T;}
    if (method === 'settings.save') { if ('theme' in args) s.settings.theme = args.theme as 'light' | 'dark'; if ('deepseek_auth' in args) s.settings.deepseek_auth = args.deepseek_auth as 'account' | 'api_key'; }
    else if (method === 'session.save') {
      const row = s.sessions.find(row => row.id === args.record_id);
      if (row) Object.assign(row, {title: args.title, folder: args.folder || null});
      else s.sessions.push({id: crypto.randomUUID(), title: String(args.title || '新会话'), folder: args.folder as string || null, character_id: null, version: null, model: null});
      result = {session_id: row?.id || s.sessions.at(-1)!.id, snapshot: this.snapshot()};
    } else if (method === 'folder.save') {
      const row = s.folders.find(row => row.id === args.record_id);
      if (row) Object.assign(row, args);
      else s.folders.push({id: crypto.randomUUID(), name: String(args.name), parent: args.parent as string || null, collapsed: false});
    } else if (method === 'character.classify') { s.characters.find(c => c.id === args.character_id)!.category = args.category as 'runtime' | 'developing'; }
    else if (method === 'character.load') {
      const character = s.characters.find(c => c.id === args.character_id)!;
      if (session?.character_id && session.character_id !== character.id && !args.choice) return {warning: '一个会话建议只使用一个角色，建议在新会话中试用。'} as T;
      let target = session;
      if (args.choice === 'new') { target = {id: crypto.randomUUID(), title: character.name, folder: session?.folder || null, character_id: null, version: null, model: null}; s.sessions.push(target); }
      if (target) { target.character_id = character.id; target.version = character.version; }
      result = {session_id: target?.id, snapshot: this.snapshot()};
    } else if (method === 'engineering.prepare') {
      const token = crypto.randomUUID(); this.confirmations.set(token, {session_id: String(args.session_id), role: String(args.role)});
      return {token, role: args.role, text: args.role === 'generator' ? '根据你提供的材料创建新的角色 skill。' : '根据诊断和反馈调整角色副本，原始文件保持不变。'} as Confirmation as T;
    } else if (method === 'engineering.start' || method === 'doctor.start' || method === 'chat.send') {
      let role = method === 'doctor.start' ? 'doctor' : method === 'engineering.start' ? String(args.role) : 'chat';
      if (method === 'engineering.start') { const token = this.confirmations.get(String(args.token)); if (!token || token.session_id !== args.session_id || token.role !== role) throw new Error('请先确认工程调用'); this.confirmations.delete(String(args.token)); }
      const typed = String(args.text || '').match(/(?:^|\s)[@$](generator|maintainer)\b/i);
      if (typed && role === 'chat') return {confirmation_required: await this.call('engineering.prepare', {session_id: args.session_id, role: typed[1].toLowerCase()})} as T;
      if ((role === 'doctor' || role === 'maintainer') && !session?.character_id) throw new Error('请先加载角色并生成回复');
      const id = crypto.randomUUID(); const sid = String(args.session_id);
      s.tasks.push({id, session_id: sid, kind: role, status: 'running'});
      s.messages.push({id: crypto.randomUUID(), session_id: sid, role: 'user', text: String(args.text || (role === 'doctor' ? '请诊断这条角色回复。' : `调用 ${role}`)), task_id: role === 'chat' ? null : id, metadata: {}});
      const reply = role === 'doctor' ? '演示诊断已保存，可交给 Maintainer 审阅。' : role === 'maintainer' ? '已准备角色副本修改，请审阅。' : role === 'generator' ? '已准备一个演示角色，请审阅后保存。' : '这是内存演示回复。真实模式会使用你的 Codex 与本地角色资源。';
      let length = 0;
      const timer = window.setInterval(() => {
        if (this.cancelled.has(id)) { clearInterval(timer); this.update(); return; }
        length += 3; this.emit({type: 'delta', task_id: id, session_id: sid, text: reply.slice(0, length)});
        if (length < reply.length) return;
        clearInterval(timer); s.tasks.find(t => t.id === id)!.status = 'completed';
        s.messages.push({id: crypto.randomUUID(), session_id: sid, role: 'assistant', text: reply, task_id: role === 'chat' ? null : id, metadata: {...(role === 'chat' ? {character_id: session?.character_id || undefined, version: session?.version || undefined} : {kind: role}), execution: {agent: s.settings.agent || 'codex', model: session?.model_preferences?.[s.settings.agent || 'codex']?.model || 'demo', effort: session?.model_preferences?.[s.settings.agent || 'codex']?.effort}}});
        if (role === 'doctor') s.records.push({id: crypto.randomUUID(), session_id: sid, task_id: id, kind: 'diagnosis', body: '# 演示诊断\n\n可检查语气与叙述节奏。这不是实际模型诊断。'});
        if (role === 'maintainer' || role === 'generator') s.proposals.push({id: crypto.randomUUID(), task_id: id, session_id: sid, kind: role, character_id: session?.character_id || null, base_version: session?.version || null, status: 'pending', changes: {'voice_card.md': {before: '直接说明情绪和态度。\n\n保留原文事实，不补写未经提供的经历。', after: '先保留具体细节，再让情绪从叙述中显现。\n\n保留原文事实，不补写未经提供的经历。'}}});
        this.emit({type: 'done', task_id: id, session_id: sid}); this.update();
      }, 30);
      return {task_id: id, snapshot: this.snapshot()} as T;
    } else if (method === 'task.cancel') { this.cancelled.add(String(args.task_id)); const task = s.tasks.find(t => t.id === args.task_id); if (task) task.status = 'cancelled'; this.emit({type: 'done', task_id: String(args.task_id), session_id: task?.session_id || ''}); }
    else if (method === 'proposal.accept') { const proposal = s.proposals.find(p => p.id === args.proposal_id)!; proposal.status = 'accepted'; if (proposal.character_id) s.characters.find(c => c.id === proposal.character_id)!.version++; }
    else if (method === 'character.view') return {files: {'SKILL.md': '---\nname: sample-character\ndescription: 显式内存演示。\n---\n\n使用克制、原创的表达。'}} as T;
    else throw new Error('演示模式不访问本机文件或账号；请使用真实桌面入口体验此功能。');
    return (result || this.snapshot()) as T;
  }
}
