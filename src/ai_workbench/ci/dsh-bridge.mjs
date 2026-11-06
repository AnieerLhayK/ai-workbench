import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
const modules=process.env.CI_DSH_MODULES;
const {HarnessSdkJsonRpcServer}=await import(pathToFileURL(`${modules}/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js`).href);
const {JsonRpcLineTransport}=await import(pathToFileURL(`${modules}/@deepseek-ai/dsh-sdk-protocol/lib/index.js`).href);
export const name='ci-repair-transport';
export const inject=['tools','agents','workingDirectory','agentDefaultModel','deepseekAccount','skills'];
export function apply(ctx){
 const wire=new JsonRpcLineTransport(process.stdin,process.stdout);
 const server=new HarnessSdkJsonRpcServer(ctx,wire,{maxTokensAsSuccess:false});
 ctx.tools.guard(exec=>{
  const r=spawnSync(process.env.CI_PYTHON,['-B',process.env.CI_GUARD,process.env.CI_POLICY,'--dsh'],{input:JSON.stringify({name:exec.name,arguments:exec.arguments}),encoding:'utf8',windowsHide:true,timeout:15000});
  if(r.status!==0)return 'CI guard unavailable';
  try{const verdict=JSON.parse(r.stdout);return verdict.allowed?undefined:verdict.reason;}catch{return 'CI guard result invalid';}
 });
 wire.onRequest(async(method,params={})=>{
  await ctx.get('loader').await();
  if(method==='ci/preflight')return {selection:ctx.agentDefaultModel.currentSelection(),accountStatus:(await ctx.deepseekAccount.getState()).status};
  if(method==='ci/verify'){
   if(params.cwd!==process.env.CI_WORKSPACE)throw new Error('Unexpected verification directory');
   return ctx.tools.execute({name:'pwsh',arguments:{command:params.command,description:'Independent configured CI tests',workdir:params.cwd},callId:'ci-independent-verification',signal:new AbortController().signal});
  }
  if(!['initialize','session/prompt','session/wait','shutdown'].includes(method))throw new Error('Unsupported CI operation');
  if(method==='initialize' && params.cwd!==process.env.CI_WORKSPACE)throw new Error('Unexpected CI workspace');
  const value=await server.handleRequest(method,params);
  if(method==='shutdown')setImmediate(async()=>{await ctx.root.fiber.dispose();process.exit(0);});
  return value;
 });
 ctx.effect(()=>{wire.start();return async()=>{await server.shutdown();wire.close();};},'ci:stdio');
}
