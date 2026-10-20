import { useState } from 'react';
import { Plus, Search, Folder as FolderIcon, FolderPlus, ChevronDown, ChevronRight, FileText, MoreHorizontal, Settings, UserRound } from 'lucide-react';
import type { Account, Folder, Session, Snapshot } from './types';

interface Props { snapshot: Snapshot; account: Account; selected: string; page: string; choose(id: string): void; navigate(page: string): void; createSession(): void; createFolder(parent?: string): void; toggle(folder: Folder): void; edit(kind: 'folder' | 'session', record: Folder | Session): void }
export function Sidebar(p: Props) {
  const [search, setSearch] = useState('');
  function sessionRow(session: Session, depth: number) {
    return <div role="treeitem" aria-selected={p.selected === session.id && p.page === 'chat'} className={`tree-row session-row ${p.selected === session.id && p.page === 'chat' ? 'selected' : ''}`} key={session.id} style={{paddingLeft: 18 + depth * 24}}>
      <button className="row-main" onClick={() => p.choose(session.id)}><FileText size={23}/><span>{session.title}</span></button>
      <button className="icon row-action" aria-label={`管理会话 ${session.title}`} onClick={() => p.edit('session', session)}><MoreHorizontal size={17}/></button>
    </div>;
  }
  function children(parent: string | null, depth: number): React.ReactNode {
    return <>{p.snapshot.folders.filter(f => f.parent === parent).map(folder => <div key={folder.id}>
      <div role="treeitem" aria-expanded={!folder.collapsed} className="tree-row folder-row" style={{paddingLeft: 10 + depth * 24}}>
        <button className="row-main" onClick={() => p.toggle(folder)}>{folder.collapsed ? <ChevronRight size={19}/> : <ChevronDown size={19}/>}<FolderIcon size={24}/><span>{folder.name}</span></button>
        <div className="row-actions"><button className="icon row-action" aria-label={`在 ${folder.name} 中新建分类`} onClick={() => p.createFolder(folder.id)}><Plus size={16}/></button><button className="icon row-action" aria-label={`管理分类 ${folder.name}`} onClick={() => p.edit('folder', folder)}><MoreHorizontal size={17}/></button></div>
      </div>
      {!folder.collapsed && <div role="group">{children(folder.id, depth + 1)}</div>}
    </div>)}{p.snapshot.sessions.filter(s => s.folder === parent).map(s => sessionRow(s, depth))}</>;
  }
  return <aside className="sidebar">
    <div className="brand">e-Chatter</div>
    <div className="sidebar-top"><button className="primary new-session" onClick={p.createSession}><Plus size={27}/>新建会话</button>
      <div className="search"><Search size={21}/><input aria-label="搜索会话" placeholder="搜索会话" value={search} onChange={e => setSearch(e.target.value)}/><button className="icon" aria-label="新建分类" title="新建分类" onClick={() => p.createFolder()}><FolderPlus size={19}/></button></div>
    </div>
    <nav className="session-tree" role="tree" aria-label="会话分类">{search ? p.snapshot.sessions.filter(s => s.title.includes(search) || p.snapshot.messages.some(m => m.session_id === s.id && m.text.includes(search))).map(s => sessionRow(s, 0)) : children(null, 0)}
      {!p.snapshot.sessions.length && <p className="sidebar-empty">从新建会话开始</p>}
    </nav>
    <div className="sidebar-bottom"><button className={`nav-link ${p.page === 'registry' ? 'selected' : ''}`} onClick={() => p.navigate('registry')}><UserRound size={25}/>Skills 与角色</button><button className={`nav-link ${p.page === 'settings' ? 'selected' : ''}`} onClick={() => p.navigate('settings')}><Settings size={25}/>设置</button></div>
    <button className="account" onClick={() => p.navigate('settings')}><i className={`connection-dot ${p.account.connected ? 'connected' : ''}`}/><span>{p.snapshot.demo ? '演示模式' : p.account.connected ? `已连接 ${p.account.name || (p.snapshot.settings.agent === 'deepseek' ? 'DeepSeek Harness' : 'Codex')}` : p.account.label}</span><ChevronDown size={17}/></button>
  </aside>;
}
