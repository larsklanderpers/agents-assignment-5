import {NextRequest} from "next/server";
export const dynamic='force-dynamic';
export async function GET(_request:NextRequest,{params}:{params:Promise<{path:string[]}>}){
 const {path}=await params;
 if(!((path.length===1&&['dashboard','export'].includes(path[0]))||(path.length===2&&path[0]==='audit'&&/^[a-zA-Z0-9-]+$/.test(path[1]))))return Response.json({error:'Not found'},{status:404});
 try{const result=await fetch(`${process.env.LANGGRAPH_DEPLOYMENT_URL||'http://127.0.0.1:8000'}/bonus/${path.join('/')}`,{cache:'no-store'});const headers:Record<string,string>={'Content-Type':'application/json','Cache-Control':'no-store'};const disposition=result.headers.get('Content-Disposition');if(disposition)headers['Content-Disposition']=disposition;return new Response(await result.text(),{status:result.status,headers});}catch{return Response.json({error:'Activity service unavailable'},{status:503});}
}
