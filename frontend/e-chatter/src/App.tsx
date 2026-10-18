import { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useChatter } from './controller';
import { Sidebar } from './Sidebar';
import { Chat } from './Chat';
import { Settings } from './Settings';
import { Registry } from './Registry';
import { Review } from './Review';
import { Dialog } from './Dialog';
import type { Character, Confirmation, Folder, Material, Message, Proposal, Session, Snapshot } from './types';

type Modal = {kind: 'engineering'; confirmation: Confirmation; text?: string; session: string} | {kind: 'switch'; character: Character; version?: number} | {kind: 'edit'; entity: 'session' | 'folder'; id?: string; name: string; parent: string | null} | {kind: 'import'; path: string} | {kind: 'migration'; preview: {token: string; sessions: number; characters: number; records: number; note: string}} | {kind: 'view'; character: Character; files: Record<string, string>} | {kind: 'found'; entries: {path: string; name: string}[]};

export function App() {
  const c = useChatter();
  const {snapshot, call} = c;
  const [selected, setSelected] = useState('');
  const [page, setPage] = useState('chat');
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [attached, setAttached] = useState<Record<string, Material[]>>({});
  const [modal, setModal] = useState<Modal | null>(null);
  const [review, setReview] = useState<Proposal | null>(null);
  const [formName, setFormName] = useState('');
  const [formParent, setFormParent] = useState('');
  const [category, setCategory] = useState('developing');
  const [confirmed, setConfirmed] = useState(false);
  const [toast, setToast] = useState('');
  const [busy, setBusy] = useState(false);
  const session = snapshot.sessions.find(s => s.id === selected) || snapshot.sessions[0];
  const sid = session?.id || '';
  const materialIds = (attached[sid] || []).map(m => m.id);
  useEffect(() => {const handler = (event: Event) => setPage((event as CustomEvent).detail); document.addEventListener('chatter:navigate', handler); return () => document.removeEventListener('chatter:navigate', handler);}, []);
  useEffect(() => {if (modal?.kind === 'edit') {setFormName(modal.name); setFormParent(modal.parent || '');} if (modal?.kind === 'import') {setCategory('developing'); setConfirmed(false);}}, [modal]);
  useEffect(() => {if (!toast) return; const timer = setTimeout(() => setToast(''), 4000); return () => clearTimeout(timer);}, [toast]);
  const act = useCallback(async (work: () => Promise<unknown>) => {try {await work();} catch {/* error is displayed by the controller */}}, []);
  async function ensureSession() {if (session) return sid; const result = await call<{session_id: string}>('session.save'); setSelected(result.session_id); return result.session_id;}
  async function engineer(role: string) {const id = await ensureSession(); const confirmation = await call<Confirmation>('engineering.prepare', {session_id: id, role}); setModal({kind: 'engineering', confirmation, session: id});}
  async function send() {
    if (!session || !drafts[sid]?.trim()) return;
    const text = drafts[sid];
    const result = await call<{confirmation_required?: Confirmation}>('chat.send', {session_id: sid, text, material_ids: materialIds});
    if (result.confirmation_required) {setModal({kind: 'engineering', confirmation: result.confirmation_required, text, session: sid}); return;}
    setDrafts(previous => ({...previous, [sid]: ''})); setAttached(previous => ({...previous, [sid]: []}));
  }
  async function load(character: Character, version?: number, choice?: string) {
    const id = await ensureSession();
    const result = await call<{warning?: string; session_id?: string}>('character.load', {session_id: id, character_id: character.id, version, choice});
    if (result.warning) setModal({kind: 'switch', character, version});
    else {setSelected(result.session_id || id); setModal(null); setPage('chat');}
  }
  async function choose(kind: string) {return await call<string>('path.choose', {kind});}
  async function importCharacter(path?: string) {const selectedPath = path || await choose('character'); if (selectedPath) setModal({kind: 'import', path: selectedPath});}
  function edit(entity: 'folder' | 'session', row?: Folder | Session, parent?: string) {setModal({kind: 'edit', entity, id: row?.id, name: row ? ('name' in row ? row.name : row.title) : '', parent: row ? ('parent' in row ? row.parent : row.folder) : parent || null});}
  async function attach(asSkill = false) {const path = await choose(asSkill ? 'skill' : 'material'); if (!path) return; const material = await call<Material>('material.attach', {path, as_skill: asSkill}); setAttached(previous => ({...previous, [sid]: [...(previous[sid] || []), material]}));}
  async function doctor(message?: Message) {const id = await ensureSession(); await call('doctor.start', {session_id: id, message_id: message?.id, feedback: drafts[sid] || ''});}
  async function migrate(kind: 'export' | 'import') {const path = await choose(kind); if (!path) return; if (kind === 'export') {await call('migration.export', {path}); setToast('迁移包已导出，不包含 Codex 登录信息。');} else {const preview = await call<{token: string; sessions: number; characters: number; records: number; note: string}>('migration.preview', {path}); setModal({kind: 'migration', preview});}}
  async function modalAction() {
    if (!modal || busy) return; setBusy(true);
    try {
      if (modal.kind === 'engineering') {await call('engineering.start', {session_id: modal.session, role: modal.confirmation.role, token: modal.confirmation.token, text: modal.text || drafts[modal.session], material_ids: (attached[modal.session] || []).map(m => m.id)}); setDrafts(p => ({...p, [modal.session]: ''})); setAttached(p => ({...p, [modal.session]: []}));}
      if (modal.kind === 'edit') {const args = modal.entity === 'folder' ? {name: formName, parent: formParent || null, record_id: modal.id} : {title: formName, folder: formParent || null, record_id: modal.id}; const result = await call<{session_id?: string}>(`${modal.entity}.save`, args); if (result.session_id) {setSelected(result.session_id); setPage('chat');}}
      if (modal.kind === 'import') {await call('character.import', {path: modal.path, category, confirmed_character: confirmed}); setToast('本地角色副本已导入，原始目录保持不变。');}
      if (modal.kind === 'migration') {await call('migration.import', {token: modal.preview.token}); setToast('迁移包已导入，已有记录未被覆盖。');}
      setModal(null);
    } catch {} finally {setBusy(false);}
  }
  const latestReview = review && (snapshot.proposals.find(p => p.id === review.id) || review);
  const closeModal = () => setModal(null);
  if (!c.ready) return <div className="startup"><h1>e-Chatter</h1><p>{c.error || '正在打开本机资料库…'}</p></div>;
  return <div className="app-shell"><Sidebar snapshot={snapshot} account={c.account} selected={sid} page={page} choose={id => {setSelected(id); setPage('chat'); setReview(null);}} navigate={target => {setPage(target); setReview(null);}} createSession={() => void act(async () => {const result = await call<{session_id: string}>('session.save'); setSelected(result.session_id); setPage('chat'); setReview(null);})} createFolder={parent => edit('folder', undefined, parent)} toggle={folder => void act(() => call('folder.save', {record_id: folder.id, name: folder.name, parent: folder.parent, collapsed: !folder.collapsed}))} edit={edit}/>
    {latestReview ? <Review key={latestReview.id} proposal={latestReview} snapshot={snapshot} back={() => setReview(null)} accept={() => void act(async () => {await call('proposal.accept', {proposal_id: latestReview.id}); setToast('已保存为应用内新版本；效果需在新会话中试用。');})}/> : page === 'settings' ? <Settings snapshot={snapshot} account={c.account} back={() => setPage('chat')} theme={theme => void act(() => call('settings.save', {theme}))} changeDirectory={() => void act(async () => {const path = await choose('characters_root'); if (path) await call('settings.save', {characters_root: path});})} migrate={kind => void act(() => migrate(kind))} login={() => void act(async () => {await call('account.login'); setToast('请在系统浏览器完成 Codex 官方登录，再刷新连接状态。');})} refresh={() => void act(() => call('account.status'))} chooseCodex={() => void act(async () => {const path = await choose('codex'); if (path) {await call('settings.save', {codex_cli: path}); await call('account.status');}})}/> : page === 'registry' ? <Registry snapshot={snapshot} importCharacter={() => void act(() => importCharacter())} classify={(id, value) => void act(() => call('character.classify', {character_id: id, category: value}))} view={character => void act(async () => {const result = await call<{files: Record<string, string>}>('character.view', {character_id: character.id}); setModal({kind: 'view', character, files: result.files});})} openDirectory={() => void act(() => call('directory.open'))} refresh={() => void act(async () => {const entries = await call<{path: string; name: string}[]>('character.refresh'); if (entries.length) setModal({kind: 'found', entries}); else setToast('没有发现尚未登记的本地角色。');})}/> : <Chat snapshot={snapshot} session={session} account={c.account} drafts={drafts} setDraft={value => setDrafts(previous => ({...previous, [sid]: value}))} streams={c.streams} send={() => void act(send)} engineer={role => void act(() => engineer(role))} doctor={message => void act(() => doctor(message))} load={(character, version) => void act(() => load(character, version))} attach={value => void act(() => attach(value))} materials={attached[sid] || []} removeMaterial={id => setAttached(previous => ({...previous, [sid]: (previous[sid] || []).filter(m => m.id !== id)}))} review={setReview} cancel={task => void act(() => call('task.cancel', {task_id: task}))} changeModel={model => void act(() => call('settings.save', {model}))} editSession={() => session && edit('session', session)}/>}
    {(c.error || toast) && <div className={`toast ${c.error ? 'error' : ''}`} role="status"><span>{c.error || toast}</span><button className="icon" aria-label="关闭提示" onClick={() => {c.setError(''); setToast('');}}><X size={18}/></button></div>}
    {modal?.kind === 'engineering' && <Dialog title={`调用 ${modal.confirmation.role === 'generator' ? 'Generator' : 'Maintainer'}`} close={closeModal} footer={<><button onClick={closeModal}>取消</button><button className="primary" disabled={busy} onClick={() => void modalAction()}>继续</button></>}><p>{modal.confirmation.text}</p></Dialog>}
    {modal?.kind === 'switch' && <Dialog title="切换角色" close={closeModal} footer={<><button onClick={closeModal}>取消</button><button onClick={() => void act(() => load(modal.character, modal.version, 'continue'))}>仍在本会话切换</button><button className="primary" onClick={() => void act(() => load(modal.character, modal.version, 'new'))}>新建会话</button></>}><p>一个会话建议只使用一个角色，建议在新会话中试用 {modal.character.name}。</p></Dialog>}
    {modal?.kind === 'edit' && <Dialog title={`${modal.id ? '管理' : '新建'}${modal.entity === 'folder' ? '分类' : '会话'}`} close={closeModal} footer={<><button onClick={closeModal}>取消</button><button className="primary" disabled={!formName.trim() || busy} onClick={() => void modalAction()}>保存</button></>}><label className="field-label">名称<input autoFocus value={formName} onChange={e => setFormName(e.target.value)}/></label><label className="field-label">所属分类<select value={formParent} onChange={e => setFormParent(e.target.value)}><option value="">顶层</option>{snapshot.folders.filter(f => f.id !== modal.id).map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label></Dialog>}
    {modal?.kind === 'import' && <Dialog title="导入本地角色" close={closeModal} footer={<><button onClick={closeModal}>取消</button><button className="primary" disabled={!confirmed || busy} onClick={() => void modalAction()}>导入副本</button></>}><p className="path-preview">{modal.path}</p><label className="field-label">分类<select value={category} onChange={e => setCategory(e.target.value)}><option>developing</option><option>runtime</option></select></label><label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>确认这是用于对话与写作的 character skill</label></Dialog>}
    {modal?.kind === 'migration' && <Dialog title="导入迁移包" close={closeModal} footer={<><button onClick={closeModal}>取消</button><button className="primary" disabled={busy} onClick={() => void modalAction()}>确认导入</button></>}><p>{modal.preview.sessions} 个会话 · {modal.preview.characters} 个角色 · {modal.preview.records} 份记录</p><p>{modal.preview.note}</p></Dialog>}
    {modal?.kind === 'view' && <Dialog title={modal.character.name} wide close={closeModal} footer={<><button onClick={closeModal}>关闭</button><button className="primary" onClick={() => void act(() => load(modal.character))}>在会话中加载</button></>}><div className="version-actions">版本：{snapshot.versions.filter(v => v.character_id === modal.character.id).map(v => <button key={v.id} onClick={() => void act(() => load(modal.character, v.number))}>试用 v{v.number}</button>)}</div><p className="muted">{modal.character.description}</p>{Object.entries(modal.files).map(([name, content]) => <details className="source-file" key={name} open={name === 'SKILL.md'}><summary>{name}</summary><pre>{content}</pre></details>)}</Dialog>}
    {modal?.kind === 'found' && <Dialog title="发现本地角色" close={closeModal}><div className="found-list">{modal.entries.map(entry => <button key={entry.path} onClick={() => void importCharacter(entry.path)}>{entry.name}<small>{entry.path}</small></button>)}</div></Dialog>}
  </div>;
}
