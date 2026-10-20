import { ChevronLeft, Folder, Upload, Download, Sun, Moon, RefreshCw } from 'lucide-react';
import {useEffect, useState} from 'react';
import type { Account, Agent, Snapshot } from './types';
import {Dialog} from './Dialog';

interface Props {snapshot: Snapshot; account: Account; back(): void; theme(value: string): void; changeDirectory(): void; migrate(kind: 'export' | 'import'): void; call<T = unknown>(method: string, args?: Record<string, unknown>): Promise<T>; chooseAgent(agent: Agent): Promise<void>}
export function Settings(p: Props) {
  const active = p.snapshot.settings.agent || 'codex';
  const [view, setView] = useState<Agent>(active);
  const [account, setAccount] = useState<Account | null>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState('');
  const [visible, setVisible] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [loginId, setLoginId] = useState<string | undefined>();
  async function refresh() {setAccount(await p.call<Account>('account.status', {agent: view}));}
  async function work(action: () => Promise<unknown>) {if (busy) return; setBusy(true); try {await action();} catch {setNotice('操作未完成，请检查提示后重试。');} finally {setBusy(false);}}
  useEffect(() => {let current = true; setAccount(null); setKey(''); setVisible(false); setNotice(''); p.call<Account>('account.status', {agent: view}).then(value => {if (current) setAccount(value);}).catch(() => {}); return () => {current = false;};}, [view, p.snapshot.settings.deepseek_auth, p.snapshot.settings.deepseek_cli, p.snapshot.settings.codex_cli]);
  async function auth(action: string) {const value = await p.call<{pending?: boolean; login_id?: string}>('account.auth', {agent: view, action, ...(action === 'save_key' ? {key} : {}), ...(action === 'cancel' ? {login_id: loginId} : {})}); setKey(''); setLoginId(value.login_id); setNotice(value.pending ? '请在系统浏览器完成官方登录，再刷新状态。' : '操作已完成。'); await refresh();}
  const pending = account?.attempt && ['initializing','waiting-browser','exchanging','committing'].includes(account.attempt.phase);
  useEffect(() => {
    if (!pending) return;
    let live = true, checking = false;
    const timer = setInterval(async () => {if (checking) return; checking = true; try {const value = await p.call<Account>('account.status', {agent: view}); if (live) {setAccount(value); if (value.connected) setNotice('官方登录已完成，可使用此 Agent。'); else if (value.attempt?.phase === 'failed') setNotice('官方登录失败，请重试或检查网络。');}} catch {if (live) setNotice('登录状态读取失败，可刷新状态或取消登录。');} finally {checking = false;}}, 1500);
    return () => {live = false; clearInterval(timer);};
  }, [Boolean(pending), view]);
  return <main className="page-main"><header className="page-header"><h1>设置</h1><button onClick={p.back}><ChevronLeft size={20}/>返回会话</button></header><div className="settings-content">
  <section className="setting-row"><div><h2>外观</h2><p>选择应用的主题外观。</p></div><div className="setting-value"><div className="theme-options">{(['light', 'dark'] as const).map(theme => <button key={theme} role="radio" aria-checked={p.snapshot.settings.theme === theme} className={p.snapshot.settings.theme === theme ? 'theme-option checked' : 'theme-option'} onClick={() => p.theme(theme)}><span className="radio-mark"/>{theme === 'light' ? <Sun size={19}/> : <Moon size={19}/>}<span>{theme === 'light' ? '浅色' : '深色'}</span></button>)}</div><p>主题设置会保存在本机。</p></div></section>
  <section className="setting-row"><div><h2>角色目录</h2><p>设置本地角色文件的存放目录。</p></div><div className="setting-value"><div className="path-row"><input aria-label="角色目录" readOnly value={p.snapshot.settings.characters_root}/><button onClick={p.changeDirectory}><Folder size={18}/>选择目录</button></div><p>用于存放你导入的本地角色；更改位置不会移动或删除旧目录。</p></div></section>
  <section className="setting-row"><div><h2>数据迁移</h2><p>导出或导入本地数据，用于备份<br/>或在不同设备间迁移。</p></div><div className="setting-value"><div className="button-row"><button onClick={() => p.migrate('export')}><Upload size={23}/>导出迁移包</button><button onClick={() => p.migrate('import')}><Download size={23}/>导入迁移包</button></div><p>迁移会话、分类、角色与已保存记录；Agent 登录信息不包含在迁移包中。</p></div></section>
  <section className="setting-row agent-settings"><div><h2>Agent 连接</h2><p>切换后，所有会话的后续发送<br/>使用所选 Agent。</p></div><div className="setting-value">
    <div className="agent-options" role="tablist" aria-label="Agent 配置">{(['codex','deepseek'] as const).map(agent => <button key={agent} role="tab" aria-selected={view === agent} onClick={() => setView(agent)}>{agent === 'codex' ? 'Codex' : 'DeepSeek Harness'}{active === agent && <small>当前使用</small>}</button>)}</div>
    <h3>{view === 'codex' ? 'Codex' : 'DeepSeek Harness'} 配置</h3>
    <div className="path-row"><input aria-label="Agent 本机入口" readOnly value={(view === 'codex' ? p.snapshot.settings.codex_cli : p.snapshot.settings.deepseek_cli) || '自动查找官方入口'}/><button disabled={busy} onClick={() => void work(() => p.chooseAgent(view))}>选择入口…</button></div>
    {view === 'deepseek' && <div className="auth-tabs" role="group" aria-label="认证方式">{(['account','api_key'] as const).map(mode => <button key={mode} aria-pressed={(p.snapshot.settings.deepseek_auth || 'account') === mode} disabled={busy} onClick={() => void work(() => p.call('settings.save', {deepseek_auth: mode}))}>{mode === 'account' ? '官方账号' : 'API Key'}</button>)}</div>}
    <div className="auth-pane">
    {view === 'deepseek' && p.snapshot.settings.deepseek_auth === 'api_key' ? <><label className="field-label">DeepSeek API Key<div className="path-row"><input aria-label="DeepSeek API Key" type={visible ? 'text' : 'password'} autoComplete="off" value={key} placeholder={account?.has_key ? '已保存 Key；输入可替换' : '输入 API Key'} onChange={e => setKey(e.target.value)}/><button onClick={() => setVisible(!visible)}>{visible ? '隐藏' : '显示'}</button></div></label><div className="button-row"><button className="primary" disabled={busy || !key.trim()} onClick={() => void work(() => auth('save_key'))}>保存 Key</button><button disabled={busy || !account?.has_key} onClick={() => setConfirmation('clear_key')}>清除已保存 Key</button></div><p>Key 由本机 Harness 凭据管理保存，不进入聊天或迁移包。</p></> : <><p>通过{view === 'codex' ? ' Codex ' : ' DeepSeek '}官方页面完成登录。</p><div className="button-row"><button className="primary" disabled={busy || Boolean(pending)} onClick={() => void work(() => auth('login'))}>{account?.connected ? '重新登录' : '官方登录'}</button><button disabled={busy} onClick={() => void work(refresh)}><RefreshCw size={16}/>刷新状态</button>{(pending || loginId) && <button disabled={busy} onClick={() => void work(() => auth('cancel'))}>取消登录</button>}{account?.connected && <button disabled={busy} onClick={() => setConfirmation('logout')}>退出登录</button>}</div>{pending && <p role="status">{account?.attempt?.phase === 'initializing' ? '正在向 DeepSeek 初始化授权…' : account?.attempt?.phase === 'waiting-browser' ? '等待你在系统浏览器完成授权…' : '正在确认并保存授权…'}</p>}<p>有效授权会在本机复用，切换 Agent 不重复登录。</p></>}
    </div><p>请另行安装所选 Agent。Codex 需支持受限 app-server 配置；DeepSeek Harness 当前支持 0.2.1-rc.2。未验证版本会停止连接。</p><div className="connection-actions"><span className="codex-status"><i className={`connection-dot ${account?.connected ? 'connected' : ''}`}/>{account?.label || '尚未连接'}</span><button disabled={busy} onClick={() => void work(async () => {await refresh(); setNotice('入口、认证与模型能力已检查；此操作不发送聊天材料。');})}>测试连接</button><button className="primary" disabled={busy || !account?.connected || active === view} onClick={() => void work(async () => {await p.call('agent.select', {agent: view}); setNotice('已切换，所有会话的后续发送使用此 Agent。');})}>使用 {view === 'codex' ? 'Codex' : 'DeepSeek Harness'}</button></div>
    {notice && <p role="status">{notice}</p>}<p>连接设置保存在本机；凭据不会随迁移包导出。</p><p>e-Chatter {p.snapshot.app_version || '演示版'} · Windows 11 x64</p>
  </div></section>
  {confirmation && <Dialog title={confirmation === 'logout' ? '退出当前登录' : '清除已保存 Key'} close={() => setConfirmation(null)} footer={<><button onClick={() => setConfirmation(null)}>取消</button><button className="primary" onClick={() => {const action = confirmation; setConfirmation(null); void work(() => auth(action));}}>确认</button></>}><p>这会移除 e-Chatter 的对应本机授权。独立 Harness 桌面端的配置不受影响。</p></Dialog>}
  </div></main>; }
