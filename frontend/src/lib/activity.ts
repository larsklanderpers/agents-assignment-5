"use client";
import {useEffect,useState} from "react";
import {ApprovalDecision} from "./types";
export interface ActivityRequest {run_id:string;request_id:string;title:string;amount:number|null;department:string;risk_level:string|null;status:string;current_stage:string;parallel_reviews:boolean;completed_stages:string[];pending_stages:string[];decisions:ApprovalDecision[];created_at:string;updated_at:string}
export interface Notice {id:number;run_id:string;channel:string;recipient:string;message:string;timestamp:string;delivery:string}
export interface DashboardData {counts:{total:number;pending:number;awaiting_review:number;approved:number;rejected:number;error:number};requests:ActivityRequest[];notifications:Notice[];updated_at:string}
export interface AuditData {request:ActivityRequest;events:{id:number;stage:string;event_type:string;timestamp:string;reviewer:string|null;decision:string|null;details:Record<string,string>}[];notifications:Notice[]}
export function useDashboard(){
 const [data,setData]=useState<DashboardData|null>(null);const [error,setError]=useState("");
 useEffect(()=>{const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
 async function refresh(){try{const response=await fetch('/api/approvals/dashboard',{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error();setData(await response.json());setError('');}catch{if(!controller.signal.aborted)setError('Activity could not refresh. Previously loaded figures may be out of date.');}finally{if(!controller.signal.aborted)timer=setTimeout(refresh,2000);}}
 refresh();return()=>{controller.abort();clearTimeout(timer);};},[]);return {data,error};
}
export function stageName(stage:string){return ({submit_request:'Submit & validate',assess_risk:'Risk assessment',manager_review:'Manager review',validate_budget:'Budget check',finance_review:'Finance review',final_signoff:'Executive sign-off',process_request:'Approval complete',handle_rejection:'Rejection complete',join_parallel_reviews:'Combine parallel decisions'} as Record<string,string>)[stage]||stage;}
