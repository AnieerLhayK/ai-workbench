import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

export function Dialog({title, children, footer, close, wide = false}: {title: string; children: ReactNode; footer?: ReactNode; close(): void; wide?: boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {ref.current?.showModal(); return () => {ref.current?.close();};}, []);
  return <dialog ref={ref} className={wide ? 'dialog wide' : 'dialog'} onCancel={event => {event.preventDefault(); close();}}><header><h2>{title}</h2><button className="icon" aria-label="关闭弹窗" onClick={close}><X size={20}/></button></header><div className="dialog-content">{children}</div>{footer && <footer>{footer}</footer>}</dialog>;
}
