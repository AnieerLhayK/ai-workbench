import { useState } from 'react';
import { ChevronLeft, FileText } from 'lucide-react';
import type { Proposal, Snapshot } from './types';

export function Review({proposal, snapshot, back, accept}: {proposal: Proposal; snapshot: Snapshot; back(): void; accept(): void}) {
  const names = Object.keys(proposal.changes);
  const [file, setFile] = useState(names[0]);
  const current = proposal.changes[file] || proposal.changes[names[0]];
  const character = snapshot.characters.find(c => c.id === proposal.character_id);
  return <main className="page-main review-main"><header className="page-header"><button className="back-link" onClick={back}><ChevronLeft size={22}/>返回会话</button><span>{character ? `角色：${character.name}` : '新角色或文稿'}</span></header><div className="review-heading"><h1>审阅角色修改</h1><p>{character?.name || '新角色或文稿'}{proposal.base_version ? ` · v${proposal.base_version} → v${proposal.base_version + 1}` : ''}</p><small>确认后保存为应用内新版本，原始文件保持不变。</small></div>
  <div className="diff-layout"><nav className="diff-files"><p>相关文件（{names.length}）</p>{names.map(name => <button key={name} className={file === name ? 'selected' : ''} onClick={() => setFile(name)}><FileText size={22}/><span>{name}</span></button>)}</nav><section className="diff-column before"><h2>修改前{proposal.base_version ? `　v${proposal.base_version}` : ''}</h2><div>{current.before ? current.before.split('\n\n').map((paragraph, i) => <p className={current.after.includes(paragraph) ? '' : 'changed'} key={i}>{paragraph}</p>) : <p className="muted">新增文件</p>}</div></section><section className="diff-column after"><h2>修改后{proposal.base_version ? `　v${proposal.base_version + 1}` : ''}</h2><div>{current.after.split('\n\n').map((paragraph, i) => <p className={current.before.includes(paragraph) ? '' : 'changed'} key={i}>{paragraph}</p>)}</div></section></div>
  <footer className="review-footer"><button onClick={back}>暂不接纳</button><button className="primary" disabled={proposal.status !== 'pending'} onClick={accept}>{proposal.status === 'accepted' ? '已保存为新版本' : '保存为新版本'}</button></footer></main>;
}
