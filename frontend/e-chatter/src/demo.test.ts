import { describe, expect, it, vi } from 'vitest';
import { DemoTransport } from './demo';
import type { Snapshot, Confirmation } from './types';

describe('explicit demo application flows', () => {
  it('requires an engineering confirmation and consumes its token', async () => {
    vi.stubGlobal('window', globalThis);
    const app = new DemoTransport();
    await expect(app.call('engineering.start', {session_id: 's1', role: 'maintainer', token: 'invalid'})).rejects.toThrow();
    const c = await app.call<Confirmation>('engineering.prepare', {session_id: 's1', role: 'maintainer'});
    const result = await app.call<{task_id: string}>('engineering.start', {session_id: 's1', role: 'maintainer', token: c.token});
    await app.call('task.cancel', {task_id: result.task_id});
    await expect(app.call('engineering.start', {session_id: 's1', role: 'maintainer', token: c.token})).rejects.toThrow();
  });
  it('warns on character replacement and supports an independent new session', async () => {
    const app = new DemoTransport();
    const warning = await app.call<{warning: string}>('character.load', {session_id: 's1', character_id: 'c2'});
    expect(warning.warning).toContain('一个会话');
    await app.call('character.load', {session_id: 's1', character_id: 'c2', choice: 'new'});
    const s = await app.call<Snapshot>('snapshot');
    expect(s.sessions.find(s => s.id === 's1')?.character_id).toBe('c1');
    expect(s.sessions.at(-1)?.character_id).toBe('c2');
  });
  it('rejects all local paths and account operations', async () => {
    const app = new DemoTransport();
    for (const method of ['path.choose', 'material.attach', 'account.login', 'migration.export']) {
      await expect(app.call(method)).rejects.toThrow('演示模式');
    }
  });
});
