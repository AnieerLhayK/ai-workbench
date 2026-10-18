import type { AppEvent } from './types';

interface Signal<T> { connect(callback: (value: T) => void): void }
interface NativeBridge { dispatch(value: string): void; result: Signal<string>; event: Signal<string> }
declare global { interface Window { qt?: { webChannelTransport: unknown }; QWebChannel?: new (transport: unknown, done: (channel: { objects: { chatter: NativeBridge } }) => void) => unknown } }
export interface Transport { call<T = unknown>(method: string, args?: Record<string, unknown>): Promise<T>; subscribe(listener: (event: AppEvent) => void): () => void }

export async function connect(): Promise<Transport> {
  if (!window.qt) {
    if (new URLSearchParams(location.search).has('demo')) {
      const { DemoTransport } = await import('./demo');
      return new DemoTransport();
    }
    throw new Error('请通过 e-Chatter 桌面入口使用，浏览器预览需显式指定 ?demo=1。');
  }
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'qrc:///qtwebchannel/qwebchannel.js';
    script.onload = () => resolve(); script.onerror = () => reject(new Error('桌面桥接加载失败'));
    document.head.appendChild(script);
  });
  return new Promise((resolve) => {
    new window.QWebChannel!(window.qt!.webChannelTransport, ({objects}) => {
      const pending = new Map<string, {resolve: (value: unknown) => void; reject: (error: Error) => void}>();
      const listeners = new Set<(event: AppEvent) => void>();
      objects.chatter.result.connect((encoded) => {
        const message = JSON.parse(encoded);
        const waiter = pending.get(message.id); if (!waiter) return;
        pending.delete(message.id);
        message.error ? waiter.reject(new Error(message.error)) : waiter.resolve(message.result);
      });
      objects.chatter.event.connect((encoded) => { const event = JSON.parse(encoded); listeners.forEach(listener => listener(event)); });
      resolve({
        call<T>(method: string, args = {}) { return new Promise<T>((done, reject) => {
          const id = crypto.randomUUID(); pending.set(id, {resolve: done as (value: unknown) => void, reject});
          objects.chatter.dispatch(JSON.stringify({id, method, args}));
        }); },
        subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener); }; },
      });
    });
  });
}
