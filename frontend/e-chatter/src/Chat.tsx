import { useEffect, useRef, useState } from 'react';
import { ArrowUp, ChevronDown, Paperclip, UserRound, Sparkles, Wrench, FileText, Stethoscope, Square, X, MoreVertical, ChevronRight } from 'lucide-react';
import Markdown from 'react-markdown';
import {Models} from './Models';
import type { Account, ModelChoice, Character, Material, Message, Proposal, Session, Snapshot } from './types';

interface Props {snapshot: Snapshot; session?: Session; account: Account; drafts: Record<string, string>; setDraft(value: string): void; streams: Record<string, {session_id: string; text: string}>; send(): void; engineer(role: string): void; doctor(message?: Message): void; configureDoctor(message: Message): void; load(character: Character, version?: number): void; attach(asSkill?: boolean): void; materials: Material[]; removeMaterial(id: string): void; review(proposal: Proposal): void; cancel(task: string): void; changeModel(value: ModelChoice): void; editSession(): void}
export function Chat(p: Props) {
  const [menu, setMenu] = useState(false);
  const tail = useRef<HTMLDivElement>(null);
  const messages = p.snapshot.messages.filter(m => m.session_id === p.session?.id);
  const current = p.snapshot.characters.find(c => c.id === p.session?.character_id);
  const tasks = p.snapshot.tasks.filter(t => t.session_id === p.session?.id);
  const running = tasks.find(t => t.status === 'running');
  const pending = tasks.find(t => t.status === 'needs_input' && t.kind !== 'chat');
  const streams = Object.entries(p.streams).filter(([,s]) => s.session_id === p.session?.id);
  useEffect(() => { tail.current?.scrollIntoView({block: 'end'}); }, [messages.length, streams.map(([, s]) => s.text).join('')]);
  const characterMenu = <div className="character-menu popover" role="menu" aria-label="选择角色">{(['developing', 'runtime'] as const).map(category => <section key={category}><div className="menu-heading">{category}</div>{p.snapshot.characters.filter(c => c.category === category).map(c => <button role="menuitem" key={c.id} className={current?.id === c.id ? 'selected' : ''} onClick={() => {setMenu(false); p.load(c);}}><UserRound size={23}/>{c.name}</button>)}{!p.snapshot.characters.some(c => c.category === category) && <span className="menu-empty">暂无角色</span>}</section>)}<button className="menu-footer" onClick={() => {setMenu(false); document.dispatchEvent(new CustomEvent('chatter:navigate', {detail: 'registry'}));}}>导入本地角色…</button></div>;
  return <main className="chat-main">
    <header className="chat-header"><h1>{p.session?.title || '新会话'}</h1><div className="header-right"><button className="current-character" onClick={() => setMenu(!menu)}>{current ? `角色：${current.name} · v${p.session?.version}` : '选择角色'}<ChevronDown size={17}/></button><button className="icon" aria-label="管理当前会话" onClick={p.editSession}><MoreVertical size={22}/></button></div></header>
    <div className="conversation"><div className="conversation-inner">
      {!messages.length && <div className="empty-chat"><Sparkles size={35}/><h2>从这里开始一段对话</h2><p>交流、写作，或选择一个你导入的角色。</p>{p.snapshot.demo && <small>当前是内存演示，不访问本机文件或账号。</small>}</div>}
      {messages.map(message => message.role === 'event' ? <div key={message.id} className="load-event">{message.text}</div> : <article key={message.id} className={`message ${message.role}`}>
        <div className={`avatar ${message.role === 'user' ? 'human' : ''}`}>{message.role === 'user' ? <UserRound size={28}/> : <Sparkles size={26}/>}</div>
        <div className="message-content">{message.task_id && <div className="task-label">{p.snapshot.tasks.find(t => t.id === message.task_id)?.kind.replace(/^./, x => x.toUpperCase())}</div>}<div className={message.role === 'user' ? 'user-bubble' : 'prose'}>{message.role === 'user' ? message.text : <><Markdown>{message.text}</Markdown>{message.metadata.execution?.agent && <small className="execution-meta">{message.metadata.execution.agent === 'codex' ? 'Codex' : 'DeepSeek Harness'} · {message.metadata.execution.actual_model || message.metadata.execution.model || '提供方默认'} · {message.metadata.execution.actual_effort || message.metadata.execution.effort || '默认'}</small>}</>}</div>
          {message.role === 'assistant' && message.metadata.character_id && !message.task_id && <button className="message-tool" onClick={() => p.doctor(message)}><Stethoscope size={15}/>诊断这条回复</button>}
          {message.role === 'assistant' && message.metadata.character_id && !message.task_id && <button className="message-tool" onClick={() => p.configureDoctor(message)}>诊断设置…</button>}
        </div>
      </article>)}
      {streams.map(([id, value]) => <article className="message assistant" key={id}><div className="avatar"><Sparkles size={26}/></div><div className="message-content prose"><Markdown>{value.text || '正在思考…'}</Markdown><span className="stream-cursor"/></div></article>)}
      {running && !streams.length && <p className="working">正在处理{running.kind === 'chat' ? '消息' : ` ${running.kind}`}…</p>}
      {tasks.filter(t => t.error).slice(-2).map(t => <div key={t.id} className="task-error">{t.error}</div>)}
      {p.snapshot.records.filter(r => r.session_id === p.session?.id).map(r => <details className="record" key={r.id}><summary><Stethoscope size={18}/>{r.kind === 'diagnosis' ? '诊断记录' : '维护交接'}<ChevronRight size={16}/></summary><div className="prose"><Markdown>{r.body}</Markdown></div></details>)}
      {p.snapshot.proposals.filter(item => item.session_id === p.session?.id).map(item => <button className="proposal-notice" key={item.id} onClick={() => p.review(item)}><FileText size={22}/><span><strong>{item.status === 'accepted' ? '已保存为应用内新版本' : '角色或文稿修改待审阅'}</strong><small>{Object.keys(item.changes).length} 个文件 · 原始文件保持不变</small></span><ChevronRight size={19}/></button>)}
      <div ref={tail}/>
    </div></div>
    <div className="composer-dock">
      {pending && <div className="pending-task"><span>{pending.kind.replace(/^./, x => x.toUpperCase())} · 等待你的补充</span><button onClick={() => p.cancel(pending.id)}>结束任务，返回角色</button></div>}
      {!!p.materials.length && <div className="attachments">{p.materials.map(m => <span key={m.id}><Paperclip size={14}/>{m.name}<button className="icon" aria-label={`移除 ${m.name}`} onClick={() => p.removeMaterial(m.id)}><X size={14}/></button></span>)}</div>}
      <div className="composer"><textarea aria-label="消息" placeholder="写下想说的话，也可以用 @ 引用 skill 或本机路径" value={p.drafts[p.session?.id || ''] || ''} onChange={e => p.setDraft(e.target.value)} onKeyDown={e => {if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault(); if (!running) p.send();}}}/>
        <div className="composer-controls"><div><button className="icon bordered" aria-label="附加写作材料" onClick={() => p.attach(false)}><Paperclip size={23}/></button><button className="text-control" onClick={() => p.attach(true)}>引用 Skill</button></div><div className="send-controls"><Models account={p.account} value={p.session?.model_preferences?.[p.snapshot.settings.agent || 'codex'] || {model: null, effort: null}} disabled={!p.session || Boolean(running)} change={p.changeModel}/>{running ? <button className="send" aria-label="停止生成" onClick={() => p.cancel(running.id)}><Square size={20}/></button> : <button className="send" aria-label="发送消息" disabled={!p.session || !p.drafts[p.session.id]?.trim()} onClick={p.send}><ArrowUp size={25}/></button>}</div></div>
      </div>
      <div className="skill-toolbar"><div className="skill-left"><button onClick={() => p.engineer('generator')}><Wrench size={24}/>Generator</button><button onClick={() => p.engineer('maintainer')}><FileText size={23}/>Maintainer</button><div className="character-anchor"><button className={menu ? 'active' : ''} onClick={() => setMenu(!menu)} aria-expanded={menu}><UserRound size={24}/>Characters<ChevronDown size={17}/></button>{menu && characterMenu}</div></div><button className="doctor" onClick={() => p.doctor()}><Stethoscope size={25}/>doctor</button></div>
    </div>
  </main>;
}
