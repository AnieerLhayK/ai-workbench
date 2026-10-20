// App-owned control plane over official Harness services. Never expose credentials.
import {pathToFileURL} from 'node:url';
const moduleRoot = process.env.E_CHATTER_DSH_MODULES;
const load = name => import(pathToFileURL(`${moduleRoot}/@deepseek-ai/${name}/lib/index.js`).href);
const {HarnessSdkJsonRpcServer} = await load('dsh-sdk-jsonrpc-server');
const {JsonRpcLineTransport} = await load('dsh-sdk-protocol');
export const name = 'e-chatter-bridge';
export const inject = ['agents', 'workingDirectory', 'tools', 'llm', 'credentials', 'deepseekAccount', 'webServer'];
export function apply(ctx) {
  const wire = new JsonRpcLineTransport(process.stdin, process.stdout);
  const server = new HarnessSdkJsonRpcServer(ctx, wire, {maxTokensAsSuccess: false});
  const client = {version: process.env.E_CHATTER_VERSION, locale: 'zh_CN', timezoneOffsetSeconds: -new Date().getTimezoneOffset()*60};
  const ref = 'E_CHATTER_DEEPSEEK_KEY';
  const resolveCredential = ctx.credentials.resolve.bind(ctx.credentials);
  const managedOnly = async key => {
    const description = await ctx.credentials.describe(key);
    return description.source === 'file' ? resolveCredential(key) : undefined;
  };
  ctx.credentials.resolve = managedOnly;
  ctx.effect(() => () => {ctx.credentials.resolve = resolveCredential;}, 'e-chatter:managed-credentials');
  const route = process.env.E_CHATTER_DSH_AUTH === 'api_key' ? 'deepseek-official' : 'deepseek-account';
  ctx.tools.guard(() => 'e-Chatter does not permit tools');
  ctx.on('agent/assistant-stream', ({agent, frame}) => {
    const chunk = frame?.chunk;
    if (chunk?.type === 'text-delta') wire.notify('e-chatter/delta', {sessionId: String(agent.session.id), text: chunk.text ?? chunk.delta ?? ''});
  });
  const verify = () => {
    if (ctx.tools.schemas().length !== 0) throw new Error('isolation');
    return {tools: [], guard: true, runtime: 'e-chatter-dsh-1'};
  };
  wire.onRequest(async (method, params = {}) => {
    await ctx.get('loader')?.await();
    verify();
    if (method === 'e-chatter/preflight') return verify();
    if (method === 'e-chatter/status') {
      const account = await ctx.deepseekAccount.getState();
      const key = await ctx.credentials.resolve(ref);
      const connected = route === 'deepseek-account' ? account.status === 'credential-stored' : Boolean(key);
      const models = [];
      if (connected) for (const m of await ctx.llm.listModels(route)) {
        const info = await ctx.llm.resolveModelInfo(route, m.id);
        models.push({id: m.id, name: m.name, info});
      }
      return {connected, account: account.status, has_key: Boolean(key), attempt: account.attempt, models, route};
    }
    if (method === 'e-chatter/auth') {
      if (params.action === 'login') await ctx.deepseekAccount.startSignIn(client, ctx.webServer.getOrigin(), 'web');
      else if (params.action === 'cancel') {
        const state = await ctx.deepseekAccount.getState();
        if (state.attempt) await ctx.deepseekAccount.cancelSignIn(state.attempt.id);
      } else if (params.action === 'logout') await ctx.deepseekAccount.signOut(client);
      else if (params.action === 'save_key' && typeof params.key === 'string' && params.key.trim()) await ctx.credentials.set(ref, params.key.trim());
      else if (params.action === 'clear_key') await ctx.credentials.unset(ref);
      else throw new Error('unsupported auth operation');
      const state = await ctx.deepseekAccount.getState();
      return {pending: Boolean(state.attempt && ['initializing','waiting-browser','exchanging','committing'].includes(state.attempt.phase)), url: state.attempt?.authorizeUrl};
    }
    // Do not allow the SDK's automatic provider mounting or working-directory mutation.
    if (!['initialize', 'session/prompt', 'session/wait', 'shutdown'].includes(method)) throw new Error('unsupported');
    if (method === 'initialize' && params.provider !== route) throw new Error('wrong provider');
    const result = await server.handleRequest(method, params);
    if (method === 'initialize') {
      const effective = await ctx.llm.resolveCallConfig({provider: route, model: params.model, ...(params.reasoningEffort ? {reasoningEffort: params.reasoningEffort} : {})});
      return {...result, execution: {model: effective.model, effort: effective.reasoningEffort ?? null}};
    }
    if (method === 'shutdown') setImmediate(async () => {await ctx.root.fiber.dispose(); process.exit(0);});
    return result;
  });
  ctx.effect(() => {wire.start(); return async () => {await server.shutdown(); wire.close();};}, 'e-chatter:stdio');
}
