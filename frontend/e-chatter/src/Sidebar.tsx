import { useRef, useState } from 'react';
import { Plus, Search, Folder as FolderIcon, FolderPlus, ChevronDown, ChevronRight, FileText, MoreHorizontal, Settings, UserRound } from 'lucide-react';
import type { Account, Folder, Session, Snapshot } from './types';

type Item = {kind: 'folder' | 'session'; id: string};
interface Props { snapshot: Snapshot; account: Account; selected: string; page: string; choose(id: string): void; navigate(page: string): void; createSession(): void; createFolder(parent?: string): void; toggle(folder: Folder): void; edit(kind: 'folder' | 'session', record: Folder | Session): void; move(items: Item[], destination: string | null): void }
export function Sidebar(p: Props) {
  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<Item[]>([]);
  const [anchor, setAnchor] = useState<string>('');
  const [dragging, setDragging] = useState<Item[]>([]);
  const dragItems = useRef<Item[]>([]);
  const [target, setTarget] = useState<string | null>(null);
  const [invalidTarget, setInvalidTarget] = useState(false);
  const key = (item: Item) => `${item.kind}:${item.id}`;
  function visible(parent: string | null): Item[] {return [...p.snapshot.folders.filter(f => f.parent === parent).flatMap(f => [{kind: 'folder' as const, id: f.id}, ...(!f.collapsed ? visible(f.id) : [])]), ...p.snapshot.sessions.filter(s => s.folder === parent).map(s => ({kind: 'session' as const, id: s.id}))];}
  const rows: Item[] = search ? p.snapshot.sessions.filter(s => s.title.includes(search) || p.snapshot.messages.some(m => m.session_id === s.id && m.text.includes(search))).map(s => ({kind: 'session', id: s.id})) : visible(null);
  function select(item: Item, event: React.MouseEvent) {
    const k = key(item);
    if (event.shiftKey && anchor) {const a = rows.findIndex(x => key(x) === anchor), b = rows.findIndex(x => key(x) === k); if (a >= 0 && b >= 0) setSelection(rows.slice(Math.min(a,b), Math.max(a,b)+1)); else {setSelection([item]); setAnchor(k);}}
    else if (event.ctrlKey || event.metaKey) setSelection(old => old.some(x => key(x) === k) ? old.filter(x => key(x) !== k) : [...old, item]);
    else setSelection([item]);
    if (!event.shiftKey || !anchor) setAnchor(k);
  }
  function drag(item: Item, event: React.DragEvent) {const visibleKeys = new Set(rows.map(key)); const chosen = selection.some(x => key(x) === key(item)) ? selection.filter(x => visibleKeys.has(key(x))) : [item]; dragItems.current = chosen; setInvalidTarget(false); setDragging(chosen); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', `${chosen.length} 项`);}
  function validTarget(destination: string) {let cursor: string | null = destination; while (cursor) {if (dragItems.current.some(item => item.kind === 'folder' && item.id === cursor)) return false; cursor = p.snapshot.folders.find(folder => folder.id === cursor)?.parent || null;} return true;}
  function drop(destination: string | null, event: React.DragEvent) {event.preventDefault(); event.stopPropagation(); if (dragItems.current.length) p.move(dragItems.current, destination); dragItems.current = []; setDragging([]); setTarget(null);}
  function sessionRow(session: Session, depth: number) {
    return <div role="treeitem" aria-selected={selection.some(x => x.kind === 'session' && x.id === session.id)} onMouseDown={e => {if (!(e.target as Element).closest('.row-action') && !e.ctrlKey && !e.metaKey && !e.shiftKey && !selection.some(x => x.kind === 'session' && x.id === session.id)) {setSelection([{kind:'session', id:session.id}]); p.choose(session.id);}}} draggable onDragStart={e => drag({kind:'session', id:session.id}, e)} onDragEnd={() => {dragItems.current = []; setDragging([]); setTarget(null);}} className={`tree-row session-row ${selection.some(x => x.kind === 'session' && x.id === session.id) ? 'selected' : ''} ${p.selected === session.id && p.page === 'chat' ? 'current-session' : ''}`} key={session.id} style={{paddingLeft: 18 + depth * 24}}>
      <button className="row-main" onClick={e => {select({kind:'session', id:session.id}, e); if (!e.ctrlKey && !e.metaKey && !e.shiftKey) p.choose(session.id);}}><FileText size={23}/><span>{session.title}</span></button>
      <button className="icon row-action" aria-label={`管理会话 ${session.title}`} onClick={() => p.edit('session', session)}><MoreHorizontal size={17}/></button>
    </div>;
  }
  function children(parent: string | null, depth: number, foldersOnly = false): React.ReactNode {
    return <>{p.snapshot.folders.filter(f => f.parent === parent).map(folder => <div key={folder.id}>
      <div role="treeitem" aria-expanded={!folder.collapsed} aria-selected={selection.some(x => x.kind === 'folder' && x.id === folder.id)} onMouseDown={e => {if (!(e.target as Element).closest('.row-action') && !e.ctrlKey && !e.metaKey && !e.shiftKey && !selection.some(x => x.kind === 'folder' && x.id === folder.id)) setSelection([{kind:'folder', id:folder.id}]);}} draggable onDragStart={e => {e.stopPropagation(); drag({kind:'folder', id:folder.id}, e);}} onDragEnd={() => {dragItems.current = []; setDragging([]); setTarget(null);}} onDragOver={e => {if (dragItems.current.length) {e.preventDefault(); e.stopPropagation(); const valid = validTarget(folder.id); e.dataTransfer.dropEffect = valid ? 'move' : 'none'; setTarget(valid ? folder.id : null); setInvalidTarget(!valid);}}} onDrop={e => {if (validTarget(folder.id)) drop(folder.id, e); else {e.preventDefault(); e.stopPropagation(); setDragging([]); setTarget(null);}}} className={`tree-row folder-row ${target === folder.id ? 'drop-target' : ''} ${selection.some(x => x.kind === 'folder' && x.id === folder.id) ? 'selected' : ''}`} style={{paddingLeft: 10 + depth * 24}}>
        <button className="row-main" onClick={e => {select({kind:'folder', id:folder.id}, e); if (!e.ctrlKey && !e.metaKey && !e.shiftKey) p.toggle(folder);}}>{folder.collapsed ? <ChevronRight size={19}/> : <ChevronDown size={19}/>}<FolderIcon size={24}/><span>{folder.name}</span></button>
        <div className="row-actions"><button className="icon row-action" aria-label={`在 ${folder.name} 中新建分类`} onClick={() => p.createFolder(folder.id)}><Plus size={16}/></button><button className="icon row-action" aria-label={`管理分类 ${folder.name}`} onClick={() => p.edit('folder', folder)}><MoreHorizontal size={17}/></button></div>
      </div>
      {!folder.collapsed && <div role="group">{children(folder.id, depth + 1, foldersOnly)}</div>}
    </div>)}{!foldersOnly && p.snapshot.sessions.filter(s => s.folder === parent).map(s => sessionRow(s, depth))}</>;
  }
  return <aside className="sidebar">
    <div className="brand">e-Chatter</div>
    <div className="sidebar-top"><button className="primary new-session" onClick={p.createSession}><Plus size={27}/>新建会话</button>
      <div className="search"><Search size={21}/><input aria-label="搜索会话" placeholder="搜索会话" value={search} onChange={e => setSearch(e.target.value)}/><button className="icon" aria-label="新建分类" title="新建分类" onClick={() => p.createFolder()}><FolderPlus size={19}/></button></div>
    </div>
    <nav className="session-tree" role="tree" aria-label="会话分类" >{<div className={`tree-drop-root ${target === 'root' ? 'drop-target' : ''}`} onDragOver={e => {if (dragItems.current.length) {e.preventDefault(); setTarget('root'); setInvalidTarget(false);}}} onDrop={e => drop(null, e)}>{dragging.length ? (invalidTarget ? '分类不能移入自身或子分类' : `移到根目录 · ${dragging.length} 项`) : '会话与分类'}</div>}{search ? <>{p.snapshot.sessions.filter(s => s.title.includes(search) || p.snapshot.messages.some(m => m.session_id === s.id && m.text.includes(search))).map(s => sessionRow(s, 0))}{dragging.length > 0 && children(null, 0, true)}</> : children(null, 0)}
      {!p.snapshot.sessions.length && <p className="sidebar-empty">从新建会话开始</p>}
    </nav>
    <div className="sidebar-bottom"><button className={`nav-link ${p.page === 'registry' ? 'selected' : ''}`} onClick={() => p.navigate('registry')}><UserRound size={25}/>Skills 与角色</button><button className={`nav-link ${p.page === 'settings' ? 'selected' : ''}`} onClick={() => p.navigate('settings')}><Settings size={25}/>设置</button></div>
    <button className="account" onClick={() => p.navigate('settings')}><i className={`connection-dot ${p.account.connected ? 'connected' : ''}`}/><span>{p.snapshot.demo ? '演示模式' : p.account.connected ? `已连接 ${p.account.name || (p.snapshot.settings.agent === 'deepseek' ? 'DeepSeek Harness' : 'Codex')}` : p.account.label}</span><ChevronDown size={17}/></button>
  </aside>;
}
