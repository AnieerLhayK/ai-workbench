import { useCallback, useEffect, useRef, useState } from 'react';
import { connect, type Transport } from './bridge';
import { emptySnapshot, type Snapshot, type Account } from './types';

export function useChatter() {
  const transport = useRef<Transport | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [account, setAccount] = useState<Account>({connected: false, label: '连接中…', models: []});
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [streams, setStreams] = useState<Record<string, {session_id: string; text: string}>>({});
  useEffect(() => {
    let disposed = false, unsubscribe: (() => void) | undefined;
    connect().then(async client => {
      if (disposed) return;
      transport.current = client;
      unsubscribe = client.subscribe(event => {
        if (event.type === 'snapshot') setSnapshot(event.snapshot);
        else if (event.type === 'delta') setStreams(previous => ({...previous, [event.task_id]: {session_id: event.session_id, text: event.text}}));
        else setStreams(previous => { const value = {...previous}; delete value[event.task_id]; return value; });
      });
      const state = await client.call<Snapshot>('snapshot');
      if (!disposed) { setSnapshot(state); setReady(true); }
      client.call<Account>('account.status').then(value => { if (!disposed) setAccount(value); }).catch(reason => { if (!disposed) {setAccount({connected: false, label: '未连接 Codex', models: []}); setError(reason.message);} });
    }).catch(reason => { if (!disposed) setError(reason.message); });
    return () => {disposed = true; unsubscribe?.();};
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = snapshot.settings.theme; }, [snapshot.settings.theme]);
  const call = useCallback(async <T = unknown>(method: string, args: Record<string, unknown> = {}): Promise<T> => {
    try {
      if (!transport.current) throw new Error('应用连接尚未就绪');
      const result = await transport.current.call<T>(method, args);
      const value = result as {snapshot?: Snapshot; sessions?: unknown};
      if (value?.snapshot) setSnapshot(value.snapshot);
      else if (Array.isArray(value?.sessions)) setSnapshot(result as Snapshot);
      if (method === 'account.status') setAccount(result as Account);
      return result;
    } catch (reason) { setError((reason as Error).message); throw reason; }
  }, []);
  return {snapshot, account, ready, streams, error, setError, call};
}
