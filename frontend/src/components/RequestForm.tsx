"use client";

import { useEffect, useRef, useState } from "react";
import { useCoAgent, useCopilotChat } from "@copilotkit/react-core";
import { Role, TextMessage } from "@copilotkit/runtime-client-gql";
import { BusinessCase, Department, FinancialRequest } from "@/lib/types";

const DEPARTMENTS: Department[] = ["engineering", "marketing", "operations", "research", "hr"];
const PRIORITIES: FinancialRequest["priority"][] = ["low", "normal", "high", "urgent"];
const SITUATIONS: Record<BusinessCase["current_situation"], string> = {
  unknown: "Unknown / not yet confirmed",
  confirmed_outage: "Reported outage or interruption",
  degraded: "Degraded operation / reduced capacity",
  preventive: "Preventive / planned need",
  other: "Other — explain in evidence",
};
const STEPS = ["Request details", "Business case", "Review & submit"];
const NO_EVIDENCE = "Supporting evidence is not yet available. The reviewer must confirm the requester's claims.";
const fieldClass = "w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200";
const labelClass = "block text-sm font-medium text-gray-800 mb-1.5";
const helpClass = "text-xs leading-relaxed text-gray-500 mt-1.5";

function emptyDraft() {
  return {
    title: "", description: "", amount: "", department: "engineering" as Department,
    requester: "", justification: "", priority: "normal" as FinancialRequest["priority"],
    current_situation: "unknown" as BusinessCase["current_situation"],
    evidence: "", business_impact: "", urgency_reason: "", parallel_high_risk: false,
  };
}

export default function RequestForm() {
  const { appendMessage } = useCopilotChat();
  const { setState } = useCoAgent<Partial<FinancialRequest>>({ name: "approval_agent" });
  const [isOpen, setIsOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [formData, setFormData] = useState(emptyDraft);
  const [evidenceUnavailable, setEvidenceUnavailable] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const launchRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const evidence = evidenceUnavailable ? NO_EVIDENCE : formData.evidence.trim();
  const hasDraft = Object.entries(formData).some(([key, value]) =>
    ["title", "description", "amount", "requester", "justification", "evidence", "business_impact", "urgency_reason"].includes(key) && Boolean(value));

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!isOpen || !dialog) return;
    if (!dialog.open) dialog.showModal();
    const field = dialog.querySelector<HTMLElement>("input:not([disabled]), textarea:not([disabled]), select");
    (field || headingRef.current)?.focus();
  }, [isOpen, step]);

  function updateField<K extends keyof ReturnType<typeof emptyDraft>>(field: K, value: ReturnType<typeof emptyDraft>[K]) {
    setFormData((previous) => ({ ...previous, [field]: value }));
    setError("");
  }

  function closeDraft() {
    if (isSubmitting) return;
    dialogRef.current?.close();
    setIsOpen(false);
    requestAnimationFrame(() => launchRef.current?.focus());
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSubmitting) return;
    setError("");
    const required: [string, string][] = step === 0
      ? [["Request title", formData.title], ["Requester", formData.requester], ["Purchase or action requested", formData.description]]
      : step === 1
        ? [["Evidence or source", evidence], ["Business impact", formData.business_impact],
           ["Proposed response and alternatives", formData.justification],
           ...(formData.priority === "urgent" ? [["Reason for urgency", formData.urgency_reason] as [string, string]] : [])]
        : [];
    const missing = required.find(([, value]) => !value.trim());
    if (missing) { setError(`${missing[0]} needs a response. State what is unknown rather than leaving it blank.`); return; }
    if (step === 0 && (!Number.isFinite(Number(formData.amount)) || Number(formData.amount) <= 0)) {
      setError("Enter a positive request amount."); return;
    }
    if (step < 2) { setStep(step + 1); return; }

    const requestId = `REQ-${Date.now()}`;
    const request: FinancialRequest = {
      request_id: requestId, title: formData.title.trim(), description: formData.description.trim(),
      amount: Number(formData.amount), department: formData.department, requester: formData.requester.trim(),
      justification: formData.justification.trim(), priority: formData.priority,
      bonus_options: {request_id:requestId,parallel_high_risk:formData.parallel_high_risk},
      business_case: {
        request_id: requestId, current_situation: formData.current_situation,
        evidence, business_impact: formData.business_impact.trim(),
        urgency_reason: formData.priority === "urgent" ? formData.urgency_reason.trim() : "",
      },
    };
    const message = `Please process this financial approval request:
- Title: ${request.title}
- Amount: $${request.amount.toLocaleString()}
- Department: ${request.department}
- Requester: ${request.requester}
- Priority: ${request.priority}
- Description: ${request.description}
- Justification: ${request.justification}
- Current situation (requester-reported): ${SITUATIONS[formData.current_situation]}
- Evidence or source: ${evidence}
- Business impact: ${request.business_case!.business_impact}
- Reason for urgency: ${request.business_case!.urgency_reason || "Not urgent / not applicable"}`;
    setIsSubmitting(true);
    try {
      setState(request);
      await appendMessage(new TextMessage({ role: Role.User, content: message }));
      dialogRef.current?.close();
      setIsOpen(false);
      setFormData(emptyDraft());
      setEvidenceUnavailable(false);
      setStep(0);
    } catch {
      setError("Submission could not be confirmed. Your draft is kept here; check the conversation before retrying.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <>
      <button ref={launchRef} onClick={() => setIsOpen(true)}
        className="w-full rounded-lg bg-blue-600 p-4 font-medium text-white transition-colors hover:bg-blue-700">
        {hasDraft ? "Continue request draft" : "+ New Approval Request"}
      </button>
      {isOpen && (
        <dialog ref={dialogRef} aria-labelledby="new-request-title"
          onCancel={(event) => { event.preventDefault(); closeDraft(); }}
          className="m-auto max-h-[90vh] max-w-3xl rounded-xl border-0 bg-white p-0 text-gray-900 shadow-2xl backdrop:bg-black/50"
          style={{ width: "min(48rem, calc(100vw - 2rem))" }}>
          <form onSubmit={handleSubmit} className="flex max-h-[90vh] flex-col">
            <header className="shrink-0 border-b px-6 pb-5 pt-6 sm:px-8">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 id="new-request-title" className="text-xl font-semibold">New approval request</h2>
                  <p className="mt-1 text-sm text-gray-600">Give reviewers a clear business case, including what still needs confirming.</p>
                </div>
                <button type="button" onClick={closeDraft} disabled={isSubmitting} aria-label="Close and keep draft"
                  className="rounded p-1 text-xl leading-none text-gray-500 hover:bg-gray-100 disabled:opacity-40">×</button>
              </div>
              <ol aria-label="Request progress" className="mt-5 flex gap-2 sm:gap-5">
                {STEPS.map((label, index) => (
                  <li key={label} aria-current={step === index ? "step" : undefined}
                    className={`flex items-center gap-2 text-xs sm:text-sm ${step === index ? "font-semibold text-blue-700" : "text-gray-500"}`}>
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${step === index ? "bg-blue-600 text-white" : index < step ? "bg-blue-100 text-blue-800" : "bg-gray-100"}`}>{index + 1}</span>
                    {label}
                  </li>
                ))}
              </ol>
            </header>

            <div className="min-h-0 space-y-5 overflow-y-auto px-6 py-6 sm:px-8">
              <h3 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">{STEPS[step]}</h3>
              {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
              {step === 0 && (
                <>
                  <div>
                    <label htmlFor="request-title" className={labelClass}>Request title</label>
                    <input id="request-title" placeholder="For example, planned customer-acquisition campaign" value={formData.title}
                      onChange={(e) => updateField("title", e.target.value)} maxLength={200} required className={fieldClass} />
                  </div>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <label htmlFor="requester" className={labelClass}>Requester</label>
                      <input id="requester" placeholder="Your name" value={formData.requester}
                        onChange={(e) => updateField("requester", e.target.value)} maxLength={200} required className={fieldClass} />
                    </div>
                    <div>
                      <label htmlFor="department" className={labelClass}>Department</label>
                      <select id="department" value={formData.department} onChange={(e) => updateField("department", e.target.value as Department)} className={fieldClass}>
                        {DEPARTMENTS.map((department) => <option key={department} value={department}>{department[0].toUpperCase() + department.slice(1)}</option>)}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="request-amount" className={labelClass}>Amount requested (USD)</label>
                      <input id="request-amount" type="number" inputMode="decimal" placeholder="35000.00" value={formData.amount}
                        onChange={(e) => updateField("amount", e.target.value)} min="0.01" step="0.01" required className={fieldClass} />
                      <p className={helpClass}>Include the full expected cost and explain the cost basis in the business case.</p>
                    </div>
                    <div>
                      <label htmlFor="priority" className={labelClass}>Priority</label>
                      <select id="priority" value={formData.priority} onChange={(e) => updateField("priority", e.target.value as FinancialRequest["priority"])} className={fieldClass}>
                        {PRIORITIES.map((priority) => <option key={priority} value={priority}>{priority[0].toUpperCase() + priority.slice(1)}</option>)}
                      </select>
                      <p className={helpClass}>Choose Urgent only when you can explain the deadline or consequence of delay.</p>
                    </div>
                  </div>
                  <div>
                    <label htmlFor="request-description" className={labelClass}>What are you requesting?</label>
                    <textarea id="request-description" placeholder="Describe the purchase or action, its scope, and what the amount covers."
                      value={formData.description} onChange={(e) => updateField("description", e.target.value)} rows={3} maxLength={2000} required className={fieldClass} />
                  </div>
                  <label className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
                    <input type="checkbox" className="mt-1" checked={formData.parallel_high_risk} onChange={e=>updateField("parallel_high_risk",e.target.checked)}/>
                    <span><b>Bonus: parallel high-risk reviews</b><br/>If assessed High, open Manager and Finance together. Both must approve; either can reject. Low, Medium and Critical keep their standard routes.</span>
                  </label>
                </>
              )}

              {step === 1 && (
                <>
                  <p className="rounded-lg bg-blue-50 p-3 text-sm leading-relaxed text-blue-900">Separate observations from assumptions. A priority label does not establish that a service is down. Unknown information can be stated explicitly.</p>
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <label htmlFor="current-situation" className={labelClass}>What is happening now?</label>
                      <select id="current-situation" value={formData.current_situation}
                        onChange={(e) => updateField("current_situation", e.target.value as BusinessCase["current_situation"])} className={fieldClass}>
                        {Object.entries(SITUATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                      <p className={helpClass}>Describe the current condition, not the outcome you hope this request will deliver.</p>
                    </div>
                    <div>
                      <label htmlFor="case-evidence" className={labelClass}>What supports that description?</label>
                      <textarea id="case-evidence" placeholder="Identify a ticket, observation, quote or source, and when it was recorded."
                        value={evidenceUnavailable ? NO_EVIDENCE : formData.evidence}
                        onChange={(e) => updateField("evidence", e.target.value)} readOnly={evidenceUnavailable}
                        rows={3} maxLength={2000} required={!evidenceUnavailable} className={`${fieldClass} ${evidenceUnavailable ? "bg-gray-50" : ""}`} />
                      <label className="mt-2 flex items-start gap-2 text-sm text-gray-700">
                        <input type="checkbox" checked={evidenceUnavailable} onChange={(e) => { setEvidenceUnavailable(e.target.checked); setError(""); }} className="mt-0.5" />
                        Supporting evidence is not yet available
                      </label>
                    </div>
                    <div>
                      <label htmlFor="case-impact" className={labelClass}>Who or what is affected?</label>
                      <textarea id="case-impact" placeholder="Describe the business impact of acting or waiting. Label estimates and unknowns."
                        value={formData.business_impact} onChange={(e) => updateField("business_impact", e.target.value)} rows={4} maxLength={2000} required className={fieldClass} />
                    </div>
                    <div>
                      <label htmlFor="case-justification" className={labelClass}>Why this response and this cost?</label>
                      <textarea id="case-justification" placeholder="Explain the expected benefit, cost basis and alternatives considered, including a smaller scope or waiting."
                        value={formData.justification} onChange={(e) => updateField("justification", e.target.value)} rows={4} maxLength={2000} required className={fieldClass} />
                    </div>
                  </div>
                  {formData.priority === "urgent" && (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                      <label htmlFor="case-urgency" className={labelClass}>What makes this urgent?</label>
                      <textarea id="case-urgency" placeholder="State the deadline or consequence of delay, and what supports that claim."
                        value={formData.urgency_reason} onChange={(e) => updateField("urgency_reason", e.target.value)} rows={2} maxLength={2000} required className={fieldClass} />
                      <p className={helpClass}>Required because you selected Urgent. Reviewers will still verify the claim.</p>
                    </div>
                  )}
                </>
              )}

              {step === 2 && (
                <>
                  <p className="text-sm text-gray-600">Check what reviewers will receive. Use Back to correct anything before submitting.</p>
                  <div className="rounded-lg border border-gray-200 p-4">
                    <h4 className="font-semibold">{formData.title}</h4>
                    <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                      <div><dt className="text-gray-500">Amount (USD)</dt><dd className="mt-1 font-medium">${Number(formData.amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}</dd></div>
                      <div><dt className="text-gray-500">Department</dt><dd className="mt-1 capitalize">{formData.department}</dd></div>
                      <div><dt className="text-gray-500">Requester</dt><dd className="mt-1">{formData.requester}</dd></div>
                      <div><dt className="text-gray-500">Priority</dt><dd className="mt-1 capitalize">{formData.priority}</dd></div>
                      <div><dt className="text-gray-500">Review mode</dt><dd className="mt-1">{formData.parallel_high_risk?"High risk: Manager + Finance in parallel":"Standard sequential workflow"}</dd></div>
                    </dl>
                  </div>
                  <dl className="space-y-4 text-sm">
                    {[
                      ["Purchase or action requested", formData.description],
                      ["Current situation — requester-reported", SITUATIONS[formData.current_situation]],
                      ["Supporting evidence or source", evidence],
                      ["Business impact", formData.business_impact],
                      ["Proposed response, cost and alternatives", formData.justification],
                      ...(formData.priority === "urgent" ? [["Reason for urgency", formData.urgency_reason]] : []),
                    ].map(([label, value]) => (
                      <div key={label}><dt className="font-medium text-gray-800">{label}</dt><dd className="mt-1 whitespace-pre-wrap text-gray-600">{value}</dd></div>
                    ))}
                  </dl>
                  <p className={`rounded-lg p-3 text-sm ${evidenceUnavailable || formData.current_situation === "unknown" ? "bg-amber-50 text-amber-900" : "bg-blue-50 text-blue-900"}`}>
                    {evidenceUnavailable || formData.current_situation === "unknown"
                      ? "Some facts remain unconfirmed. Reviewers will see that uncertainty and must evaluate it before deciding."
                      : "The facts and evidence above are requester-reported. The app does not independently verify them."}
                  </p>
                </>
              )}
            </div>

            <footer className="shrink-0 border-t bg-gray-50 px-6 py-4 sm:px-8">
              <div className="flex items-center justify-between gap-3">
                <button type="button" onClick={closeDraft} disabled={isSubmitting} className="text-sm font-medium text-gray-600 hover:text-gray-900 disabled:opacity-40">Save & close</button>
                <div className="flex gap-3">
                  {step > 0 && <button type="button" disabled={isSubmitting} onClick={() => { setStep(step - 1); setError(""); }} className="rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium hover:bg-gray-100 disabled:opacity-40">Back</button>}
                  <button type="submit" disabled={isSubmitting} className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60">
                    {isSubmitting ? "Submitting…" : step === 0 ? "Continue to business case" : step === 1 ? "Review request" : "Submit request"}
                  </button>
                </div>
              </div>
              <p className="mt-2 text-xs text-gray-500">{step === 2 ? "Submitting starts the assessment and approval workflow." : "Your draft is kept while this page stays open. Nothing is submitted until the final step."}</p>
            </footer>
          </form>
        </dialog>
      )}
    </>
  );
}
