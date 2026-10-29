"use client";

import { useState } from "react";
import { useCoAgent, useCopilotChat } from "@copilotkit/react-core";
import { Role, TextMessage } from "@copilotkit/runtime-client-gql";
import { BusinessCase, Department, FinancialRequest } from "@/lib/types";

const DEPARTMENTS: Department[] = ["engineering", "marketing", "operations", "research", "hr"];
const PRIORITIES = ["low", "normal", "high", "urgent"];

export default function RequestForm() {
  const { appendMessage } = useCopilotChat();
  // The graph reads request fields (amount, department, ...) from state, not from chat text,
  // so the form also writes them into the agent state that is sent with the run.
  const { setState } = useCoAgent<Partial<FinancialRequest>>({ name: "approval_agent" });
  const [isOpen, setIsOpen] = useState(false);
  const [formData, setFormData] = useState({
    title: "",
    description: "",
    amount: "",
    department: "engineering" as Department,
    requester: "",
    justification: "",
    priority: "normal",
    current_situation: "unknown" as BusinessCase["current_situation"],
    evidence: "",
    business_impact: "",
    urgency_reason: "",
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const requestId = `REQ-${Date.now()}`;

    const message = `Please process this financial approval request:
- Title: ${formData.title}
- Amount: $${parseFloat(formData.amount).toLocaleString()}
- Department: ${formData.department}
- Requester: ${formData.requester}
- Priority: ${formData.priority}
- Description: ${formData.description}
- Justification: ${formData.justification}
- Current situation (requester-reported): ${formData.current_situation}
- Evidence or source: ${formData.evidence}
- Business impact: ${formData.business_impact}
- Reason for urgency: ${formData.urgency_reason || "Not supplied"}`;

    setState({
      request_id: requestId,
      title: formData.title,
      description: formData.description,
      amount: parseFloat(formData.amount),
      department: formData.department,
      requester: formData.requester,
      justification: formData.justification,
      priority: formData.priority as FinancialRequest["priority"],
      business_case: {
        request_id: requestId,
        current_situation: formData.current_situation,
        evidence: formData.evidence,
        business_impact: formData.business_impact,
        urgency_reason: formData.urgency_reason,
      },
    });
    appendMessage(new TextMessage({ role: Role.User, content: message }));

    setFormData({
      title: "",
      description: "",
      amount: "",
      department: "engineering",
      requester: "",
      justification: "",
      priority: "normal",
      current_situation: "unknown",
      evidence: "",
      business_impact: "",
      urgency_reason: "",
    });
    setIsOpen(false);
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="w-full p-4 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
      >
        + New Approval Request
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-lg shadow-md p-4 space-y-3 max-h-[85vh] overflow-y-auto">
      <h3 className="text-lg font-semibold text-gray-800">New Financial Request</h3>

      <input
        type="text"
        placeholder="Request Title"
        value={formData.title}
        onChange={(e) => setFormData({ ...formData, title: e.target.value })}
        className="w-full p-2 border rounded text-sm"
        required
      />

      <div className="flex gap-2">
        <input
          type="number"
          placeholder="Amount ($)"
          value={formData.amount}
          onChange={(e) => setFormData({ ...formData, amount: e.target.value })}
          className="flex-1 p-2 border rounded text-sm"
          min="0"
          step="0.01"
          required
        />
        <select
          value={formData.department}
          onChange={(e) => setFormData({ ...formData, department: e.target.value as Department })}
          className="flex-1 p-2 border rounded text-sm"
        >
          {DEPARTMENTS.map((dept) => (
            <option key={dept} value={dept}>
              {dept.charAt(0).toUpperCase() + dept.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <input
        type="text"
        placeholder="Your Name"
        value={formData.requester}
        onChange={(e) => setFormData({ ...formData, requester: e.target.value })}
        className="w-full p-2 border rounded text-sm"
        required
      />

      <textarea
        placeholder="Description"
        aria-label="Purchase or action requested"
        value={formData.description}
        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
        className="w-full p-2 border rounded text-sm"
        rows={2}
        required
        maxLength={2000}
      />

      <fieldset className="border border-blue-200 rounded-lg p-3 space-y-3">
        <legend className="text-sm font-semibold text-gray-800 px-1">Business-case facts</legend>
        <p className="text-xs text-gray-600">Separate confirmed facts from assumptions. Urgent priority alone does not establish an outage. If evidence is unavailable, say so.</p>
        <div>
          <label htmlFor="current-situation" className="block text-sm font-medium text-gray-700 mb-1">What is happening now?</label>
          <select id="current-situation" value={formData.current_situation}
            onChange={(e) => setFormData({ ...formData, current_situation: e.target.value as BusinessCase["current_situation"] })}
            className="w-full p-2 border rounded text-sm">
            <option value="unknown">Unknown / not yet confirmed</option>
            <option value="confirmed_outage">Confirmed outage or interruption</option>
            <option value="degraded">Degraded operation / reduced capacity</option>
            <option value="preventive">Preventive / planned need</option>
            <option value="other">Other — explain in evidence</option>
          </select>
        </div>
        <div>
          <label htmlFor="case-evidence" className="block text-sm font-medium text-gray-700 mb-1">Evidence or source</label>
          <textarea id="case-evidence" value={formData.evidence}
            onChange={(e) => setFormData({ ...formData, evidence: e.target.value })}
            placeholder="Ticket, monitoring observation, quote or source and time. If unconfirmed, state what still needs checking."
            rows={2} maxLength={2000} required className="w-full p-2 border rounded text-sm" />
        </div>
        <div>
          <label htmlFor="case-impact" className="block text-sm font-medium text-gray-700 mb-1">Business impact</label>
          <textarea id="case-impact" value={formData.business_impact}
            onChange={(e) => setFormData({ ...formData, business_impact: e.target.value })}
            placeholder="Who or what is affected? Describe the impact of acting or waiting, including any unknowns."
            rows={2} maxLength={2000} required className="w-full p-2 border rounded text-sm" />
        </div>
      </fieldset>

      <textarea
        placeholder="Business Justification"
        aria-label="Business justification and alternatives"
        value={formData.justification}
        onChange={(e) => setFormData({ ...formData, justification: e.target.value })}
        className="w-full p-2 border rounded text-sm"
        rows={2}
        required
        maxLength={2000}
      />
      <p className="text-xs text-gray-600">Explain why this expense is the right response, alternatives considered, cost basis and expected outcome.</p>

      <select
        aria-label="Priority"
        value={formData.priority}
        onChange={(e) => setFormData({ ...formData, priority: e.target.value })}
        className="w-full p-2 border rounded text-sm"
      >
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {p.charAt(0).toUpperCase() + p.slice(1)} Priority
          </option>
        ))}
      </select>

      {formData.priority === "urgent" && (
        <div>
          <label htmlFor="case-urgency" className="block text-sm font-medium text-gray-700 mb-1">Why is this urgent?</label>
          <textarea id="case-urgency" value={formData.urgency_reason}
            onChange={(e) => setFormData({ ...formData, urgency_reason: e.target.value })}
            placeholder="What deadline or consequence makes this urgent? State what supports that claim."
            rows={2} maxLength={2000} required className="w-full p-2 border rounded text-sm" />
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          className="flex-1 p-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
        >
          Submit Request
        </button>
        <button
          type="button"
          onClick={() => setIsOpen(false)}
          className="flex-1 p-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
