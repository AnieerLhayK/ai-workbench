import {useEffect, useRef, useState} from 'react';
import {ChevronDown} from 'lucide-react';
import type {Account, ModelChoice} from './types';

export function Models({account, value, disabled, change, task = false}: {account: Account; value: ModelChoice; disabled?: boolean; task?: boolean; change(value: ModelChoice): void}) {
  const effortName = (id: string) => ({off: '关闭', none: '关闭', minimal: '极低', low: '低', medium: '标准', high: '高', xhigh: '很高', max: '最大', ultra: '极致'}[id] || id);
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const model = account.models.find(m => m.id === value.model) || (!value.model ? account.models.find(m => m.default) : undefined);
  useEffect(() => {
    if (!open) return;
    const click = (e: PointerEvent) => {if (!anchor.current?.contains(e.target as Node)) setOpen(false);};
    const key = (e: KeyboardEvent) => {if (e.key === 'Escape') {e.preventDefault(); e.stopPropagation(); setOpen(false); anchor.current?.querySelector('button')?.focus();}};
    document.addEventListener('pointerdown', click); document.addEventListener('keydown', key);
    return () => {document.removeEventListener('pointerdown', click); document.removeEventListener('keydown', key);};
  }, [open]);
  useEffect(() => {setOpen(false);}, [account.agent, disabled]);
  return <div className="models-anchor" ref={anchor}>
    <button className="models-trigger" aria-haspopup="dialog" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)} title={`${account.name || 'Agent'} · ${model?.name || '模型不可用'} · ${value.effort || '默认'}`}>Models<ChevronDown size={16}/></button>
    {open && <div className="models-popover popover" role="dialog" aria-label="Models"><h3>Models</h3><p className="muted">{account.name || (account.agent === 'deepseek' ? 'DeepSeek Harness' : 'Codex')}</p><fieldset><legend>模型</legend>
      <label><input type="radio" name="model" checked={!value.model} onChange={() => change({model: null, effort: null})}/>提供方默认</label>
      {account.models.map(m => <label key={m.id}><input type="radio" name="model" checked={value.model === m.id} onChange={() => change({model: m.id, effort: null})}/>{m.name}</label>)}
      {!account.models.length && <p className="muted">暂无可用模型，请在设置中连接或刷新状态。</p>}
      {value.model && !model && <p role="alert">已保存模型不可用，请重新选择。</p>}
    </fieldset>{Boolean(model?.efforts?.length) && <fieldset><legend>推理强度</legend><div className="effort-options">{[{id: '', name: '默认'}, ...model!.efforts!].map(e => <button key={e.id} aria-pressed={(value.effort || '') === e.id} title={e.name} onClick={() => change({...value, effort: e.id || null})}>{e.id ? effortName(e.id) : '默认'}</button>)}</div></fieldset>}<small>{task ? '仅用于本次工程任务' : '仅用于当前会话'}</small></div>}
  </div>;
}
