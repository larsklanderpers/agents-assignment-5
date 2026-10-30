"use client";

import { useState, ReactNode } from "react";
// useInterrupt replaces useLangGraphInterrupt so every parallel interrupt is
// explicitly addressed; the supplied single-review modal remains in use.
import { useInterrupt } from "@copilotkit/react-core/v2/headless";
import { InterruptData, ApprovalDecision } from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  manager_review: "Manager Review",
  finance_review: "Finance Review",
  final_signoff: "Final Sign-off",
};

const RISK_COLORS: Record<string, string> = {
  low: "text-green-600 bg-green-100",
  medium: "text-yellow-600 bg-yellow-100",
  high: "text-orange-600 bg-orange-100",
  critical: "text-red-600 bg-red-100",
};

const SITUATION_LABELS: Record<string, string> = {
  unknown: "Unknown / not yet confirmed",
  confirmed_outage: "Confirmed outage or interruption (requester-reported)",
  degraded: "Degraded operation / reduced capacity (requester-reported)",
  preventive: "Preventive / planned need",
  other: "Other — see evidence",
};

function ApprovalModal({
  data,
  resolve,
  comments,
  setComments,
  navigation,
  busy,
}: {
  data: InterruptData;
  resolve: (resolution: string) => void;
  comments: string;
  setComments: (text:string)=>void;
  navigation?: ReactNode;
  busy: boolean;
}) {
  const stageLabel = STAGE_LABELS[data.type] || data.type;
  const riskColor = RISK_COLORS[data.risk_level] || "text-gray-600 bg-gray-100";

  const handleDecision = (approved: boolean) => {
    resolve(JSON.stringify({ approved, comments }));
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div role="dialog" aria-modal="true" aria-labelledby="approval-review-title" className="bg-white rounded-xl shadow-2xl max-w-lg w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="bg-blue-600 text-white px-6 py-4 shrink-0">
          {navigation}
          <h2 id="approval-review-title" className="text-xl font-bold">{stageLabel}</h2>
          <p className="text-blue-100 text-sm mt-1">
            Review the rules, supporting facts and your decision responsibilities
          </p>
        </div>

        <div className="p-6 space-y-4 overflow-y-auto min-h-0">
          {/* Request Details */}
          <div className="space-y-3">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Request</p>
                <p className="font-semibold text-gray-900">{data.title}</p>
              </div>
              <span className="text-xs font-mono text-gray-400">{data.request_id}</span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Amount</p>
                <p className="text-lg font-bold text-gray-900">
                  ${data.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">Department</p>
                <p className="font-medium text-gray-900 capitalize">{data.department}</p>
              </div>
            </div>

            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wide">Risk Level</p>
              <span className={`inline-block px-3 py-1 rounded-full text-sm font-semibold mt-1 ${riskColor}`}>
                {data.risk_level?.toUpperCase()}
              </span>
            </div>

            {data.risk_reasoning && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wide">AI Risk Assessment</p>
                <p className="text-sm text-gray-700 mt-1">{data.risk_reasoning}</p>
              </div>
            )}
          </div>

          {data.policy_context && (
            <section aria-label="Applicable rules and reviewer responsibilities" className="rounded-lg border border-blue-200 bg-blue-50 p-4 space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-900">Why this review is required</h3>
                <p className="text-sm text-gray-700 mt-1">{data.policy_context.trigger}</p>
                <p className="text-sm text-gray-700 mt-1">{data.policy_context.stage_reason}</p>
                <p className="text-sm font-medium text-blue-900 mt-2">
                  Required reviewers: {data.policy_context.review_path.join(" → ") || "None when within budget"}
                </p>
              </div>
              {data.policy_context.budget_reference && (
                <div className="rounded bg-white p-3 border border-blue-100 space-y-2">
                  <h3 className="text-sm font-semibold text-gray-900">Budget reference</h3>
                  <dl className="text-sm grid grid-cols-2 gap-x-3 gap-y-1">
                    <dt className="text-gray-600">Department budget</dt>
                    <dd className="font-medium">${data.policy_context.budget_reference.department_budget.toLocaleString()}</dd>
                    <dt className="text-gray-600">This request</dt>
                    <dd className="font-medium">${data.amount.toLocaleString()}</dd>
                    <dt className="text-gray-600">Balance if approved</dt>
                    <dd className={`font-medium ${data.policy_context.budget_reference.remaining_if_approved < 0 ? "text-red-700" : "text-green-700"}`}>
                      ${data.policy_context.budget_reference.remaining_if_approved.toLocaleString()}
                    </dd>
                  </dl>
                  {data.policy_context.budget_reference.over_budget_amount > 0 && (
                    <p className="text-sm font-medium text-red-700">
                      ${data.policy_context.budget_reference.over_budget_amount.toLocaleString()} above the department budget reference.
                    </p>
                  )}
                  <p className="text-xs text-gray-600">{data.policy_context.budget_reference.source}</p>
                  <p className="text-xs font-medium text-gray-700">
                    Automatic budget validation: {data.policy_context.budget_reference.automatically_validated
                      ? "completed earlier in the workflow."
                      : ["high", "critical"].includes(data.risk_level)
                        ? "skipped for this risk level. This comparison is reference information, not a completed budget check."
                        : "not yet run. This comparison does not change the approval route."}
                  </p>
                </div>
              )}
              {!data.policy_context.matches_assessment && (
                <p role="alert" className="text-sm font-medium text-amber-900 bg-amber-100 rounded p-3">
                  The AI assessment differs from the amount/priority rule ({data.policy_context.rule_risk_level}).
                  Verify the request facts and resolve the discrepancy before deciding.
                </p>
              )}
              <details className="text-sm">
                <summary className="cursor-pointer font-medium text-blue-900">View all risk and routing rules</summary>
                <ul className="list-disc pl-5 mt-2 space-y-1 text-gray-700">
                  {data.policy_context.risk_rules.map((rule) => (
                    <li key={rule.level}><span className="font-medium capitalize">{rule.level}:</span> {rule.condition}</li>
                  ))}
                </ul>
                <p className="mt-2 text-gray-700">{data.policy_context.ceiling_rule}</p>
                <p className="mt-2 text-gray-700">{data.policy_context.budget_rule}</p>
              </details>
              <div className="pt-3 border-t border-blue-200">
                <h3 className="text-sm font-semibold text-gray-900">Before you decide</h3>
                <p className="text-xs text-gray-600 mt-1">Human review guidance — the risk label determines the route, not whether the purchase is justified.</p>
                <ul className="list-disc pl-5 mt-2 space-y-1 text-sm text-gray-700">
                  {data.policy_context.review_focus.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            </section>
          )}

          {(data.priority || data.description || data.justification) && (
            <section aria-label="Supporting request facts" className="text-sm space-y-2">
              <h3 className="font-semibold text-gray-900">Supporting request facts</h3>
              {data.priority && <p className="text-gray-700"><span className="font-medium">Priority:</span> <span className="capitalize">{data.priority}</span></p>}
              {data.description && <p className="text-gray-700"><span className="font-medium">Description:</span> {data.description}</p>}
              {data.justification && <p className="text-gray-700"><span className="font-medium">Business justification:</span> {data.justification}</p>}
            </section>
          )}

          <section aria-label="Business-case evidence" className="rounded-lg border border-gray-200 p-4 text-sm space-y-2">
            <h3 className="font-semibold text-gray-900">Business-case evidence</h3>
            <p className="text-xs text-gray-600">These details are supplied by the requester and are not independently verified by the app.</p>
            <p className="text-gray-700"><span className="font-medium">Current situation:</span> {SITUATION_LABELS[data.business_case?.current_situation || "unknown"]}</p>
            <p className="text-gray-700 whitespace-pre-wrap"><span className="font-medium">Evidence or source:</span> {data.business_case?.evidence || "Not supplied — verify the requester's claim."}</p>
            <p className="text-gray-700 whitespace-pre-wrap"><span className="font-medium">Business impact:</span> {data.business_case?.business_impact || "Not supplied."}</p>
            <p className="text-gray-700 whitespace-pre-wrap"><span className="font-medium">Urgency rationale:</span> {data.business_case?.urgency_reason || "Not supplied. Urgent priority alone does not establish an outage."}</p>
            {(!data.business_case || data.business_case.current_situation === "unknown") && (
              <p className="text-amber-900 bg-amber-50 rounded p-2">The current situation is unconfirmed. Check what is known, what is assumed and whether the urgency is justified before deciding.</p>
            )}
          </section>

          {/* Budget Info (finance_review) */}
          {data.type === "finance_review" && !data.policy_context?.budget_reference && (
            <div className="bg-gray-50 rounded-lg p-4 space-y-2">
              <p className="text-sm font-semibold text-gray-700">Budget Information</p>
              {/* High and critical requests skip validate_budget, so these fields can be missing */}
              {data.department_budget == null ? (
                <p className="text-sm text-gray-500">
                  Not checked: high and critical requests skip Budget Validation.
                </p>
              ) : (
              <>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-gray-500">Department Budget:</span>
                  <span className="ml-1 font-medium">
                    ${data.department_budget?.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Remaining:</span>
                  <span className={`ml-1 font-medium ${(data.budget_remaining ?? 0) < 0 ? "text-red-600" : "text-green-600"}`}>
                    ${data.budget_remaining?.toLocaleString()}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className={`w-3 h-3 rounded-full ${data.within_budget ? "bg-green-500" : "bg-red-500"}`} />
                <span className="text-sm font-medium">
                  {data.within_budget ? "Within budget" : "Exceeds budget"}
                </span>
              </div>
              </>
              )}
              {data.manager_comments && (
                <div className="mt-2 pt-2 border-t">
                  <p className="text-xs text-gray-500">Manager Comments:</p>
                  <p className="text-sm text-gray-700 italic">{data.manager_comments}</p>
                </div>
              )}
            </div>
          )}

          {data.type === "finance_review" && data.policy_context?.budget_reference && data.manager_comments && (
            <div className="text-sm text-gray-700"><span className="font-medium">Manager comments:</span> {data.manager_comments}</div>
          )}

          {/* Previous Decisions (final_signoff) */}
          {data.type === "final_signoff" && data.decisions && data.decisions.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4 space-y-2">
              <p className="text-sm font-semibold text-gray-700">Previous Decisions</p>
              {data.decisions.map((decision: ApprovalDecision, idx: number) => (
                <div key={idx} className="flex items-center gap-2 text-sm">
                  <span className={`w-2.5 h-2.5 rounded-full ${decision.approved ? "bg-green-500" : "bg-red-500"}`} />
                  <span className="font-medium">{decision.stage}:</span>
                  <span className={decision.approved ? "text-green-700" : "text-red-700"}>
                    {decision.approved ? "Approved" : "Rejected"}
                  </span>
                  {decision.comments && (
                    <span className="text-gray-500 truncate">- {decision.comments}</span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Comments */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Review Comments
            </label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Add your review comments..."
              className="w-full p-3 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-none"
              rows={3}
            />
          </div>

        </div>
          {/* Keep decisions visible while the reviewer reads the rules. */}
          <div className="flex gap-3 px-6 py-4 border-t bg-white shrink-0">
            <button
              onClick={() => handleDecision(true)}
              disabled={busy}
              className="flex-1 py-3 bg-green-600 text-white rounded-lg font-semibold hover:bg-green-700 transition-colors"
            >
              Approve
            </button>
            <button
              onClick={() => handleDecision(false)}
              disabled={busy}
              className="flex-1 py-3 bg-red-600 text-white rounded-lg font-semibold hover:bg-red-700 transition-colors"
            >
              Reject
            </button>
          </div>
      </div>
    </div>
  );
}

type ReviewItem={id:string;data:InterruptData};
function ReviewGroup({items,resolve}:{items:ReviewItem[];resolve:(payload:unknown,id?:string)=>Promise<unknown>}){
  const [selected,setSelected]=useState(items[0].id);
  const [comments,setComments]=useState<Record<string,string>>({});
  const [answers,setAnswers]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const item=items.find(i=>i.id===selected)||items[0];
  async function decide(value:string){
    if(busy||answers[item.id])return;setBusy(true);setError("");
    const decision=JSON.parse(value);const updated={...answers,[item.id]:decision.approved?'Approve selected':'Reject selected'};setAnswers(updated);
    const next=items.find(i=>!updated[i.id]);if(next)setSelected(next.id);
    try{await resolve(decision,item.id==='legacy'?undefined:item.id);}catch{setError('The decision could not be confirmed. Check the workflow before retrying.');}finally{setBusy(false);}
  }
  const navigation=items.length>1?<div className="mb-3 rounded bg-blue-800 p-3"><p className="text-sm font-semibold">Parallel reviews · both decisions required</p><p className="mt-1 text-xs text-blue-100">Both reviews are open. Decisions are sent together after both selections are recorded.</p><div className="mt-2 flex gap-2">{items.map(i=><button key={i.id} disabled={Boolean(answers[i.id])||busy} onClick={()=>setSelected(i.id)} className={`rounded border px-2 py-1 text-xs ${selected===i.id?'bg-white text-blue-900':'text-white'} disabled:opacity-60`}>{STAGE_LABELS[i.data.type]}{answers[i.id]?` · ${answers[i.id]}`:''}</button>)}</div></div>:null;
  return <ApprovalModal data={item.data} resolve={decide} comments={comments[item.id]||''} setComments={text=>setComments({...comments,[item.id]:text})} busy={busy||Boolean(answers[item.id])} navigation={<>{navigation}{error&&<p role="alert">{error}</p>}</>}/>;
}
export default function ApprovalPanel(){
  const panel=useInterrupt({agentId:'approval_agent',renderInChat:false,render:({interrupts,event,resolve})=>{
    const items:ReviewItem[]=interrupts.length?interrupts.map(i=>({id:i.id,data:((i.metadata as {langgraph?:{raw?:InterruptData}})?.langgraph?.raw||{}) as InterruptData})):[{id:'legacy',data:event.value as InterruptData}];
    return <ReviewGroup key={items.map(i=>i.id).join(':')} items={items} resolve={resolve}/>;
  }});
  return <>{panel}</>;
}
