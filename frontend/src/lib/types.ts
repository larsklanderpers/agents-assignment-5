/**
 * TypeScript types for the Financial Approval System frontend.
 * These mirror the backend Pydantic models.
 */

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "needs_review";
export type Department = "engineering" | "marketing" | "operations" | "research" | "hr";

export interface BusinessCase {
  request_id: string;
  current_situation: "unknown" | "confirmed_outage" | "degraded" | "preventive" | "other";
  evidence: string;
  business_impact: string;
  urgency_reason: string;
}

export interface FinancialRequest {
  request_id: string;
  title: string;
  description: string;
  amount: number;
  department: Department;
  requester: string;
  justification: string;
  priority: "low" | "normal" | "high" | "urgent";
  business_case?: BusinessCase | null;
}

export interface ApprovalDecision {
  stage: string;
  approved: boolean;
  reviewer: string;
  comments: string;
  timestamp?: string;
}

export interface ApprovalResult {
  request_id: string;
  status: ApprovalStatus;
  risk_level: RiskLevel;
  decisions: ApprovalDecision[];
  total_approvals: number;
  total_rejections: number;
  final_comments: string;
}

export interface InterruptData {
  type: "manager_review" | "finance_review" | "final_signoff";
  request_id: string;
  title: string;
  amount: number;
  department: string;
  risk_level: RiskLevel;
  priority?: FinancialRequest["priority"];
  description?: string;
  justification?: string;
  business_case?: BusinessCase | null;
  policy_context?: {
    risk_rules: { level: RiskLevel; condition: string }[];
    rule_risk_level: RiskLevel;
    matches_assessment: boolean;
    trigger: string;
    review_path: string[];
    stage_reason: string;
    ceiling_rule: string;
    budget_rule: string;
    review_focus: string[];
    budget_reference: {
      department_budget: number;
      requested_amount: number;
      remaining_if_approved: number;
      over_budget_amount: number;
      automatically_validated: boolean;
      source: string;
    };
  };
  risk_reasoning?: string;
  within_budget?: boolean;
  department_budget?: number;
  budget_remaining?: number;
  manager_approved?: boolean;
  manager_comments?: string;
  finance_approved?: boolean;
  finance_comments?: string;
  decisions?: ApprovalDecision[];
}

export interface WorkflowStep {
  name: string;
  label: string;
  status: "pending" | "active" | "completed" | "rejected";
}

export const WORKFLOW_STEPS: WorkflowStep[] = [
  { name: "submit_request", label: "Submit", status: "pending" },
  { name: "assess_risk", label: "Risk Assessment", status: "pending" },
  { name: "manager_review", label: "Manager Review", status: "pending" },
  { name: "validate_budget", label: "Budget Check", status: "pending" },
  { name: "finance_review", label: "Finance Review", status: "pending" },
  { name: "final_signoff", label: "Final Sign-off", status: "pending" },
  { name: "process_request", label: "Processing", status: "pending" },
];
