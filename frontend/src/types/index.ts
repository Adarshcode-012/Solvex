export type Language = 'python' | 'cpp' | 'java'

export type AiKey = 'claude' | 'gpt4o' | 'gpt4o_mini' | 'gemini'

export type AgentRole = 'analyzer' | 'strategist' | 'coder' | 'reviewer' | 'judge'

export type AiMode = 'auto' | 'manual'

export type StepStatus = 'idle' | 'active' | 'done' | 'failed'

export interface PipelineStep {
  role:   AgentRole
  label:  string
  icon:   string
  status: StepStatus
  ai?:    string
}

export interface AlternateApproach {
  name:           string
  time_complexity: string
  why_not_chosen: string
}

export interface SolveResult {
  status:               'passed' | 'max_retries' | 'pending' | 'failed' | 'unverified' | 'judge_unavailable' | 'compiled_only'
  final_solution:       string
  language:             Language
  dsa_category:         string
  chosen_approach:      string
  reasoning_chain:      string
  time_complexity:      string
  space_complexity:     string
  alternate_approaches: AlternateApproach[]
  review_notes:         string
  iterations_used:      number
  // False when the pass/fail result came from a simulated Judge0 run
  // (no JUDGE0_API_KEY configured on the backend) rather than a real execution.
  verified:             boolean
  error_message:        string
  extracted_problem:    string
  constraints:          Record<string, unknown>
  agents_ai_used:       Record<AgentRole, string>
  pipeline_events:      PipelineEvent[]
}

export interface ExplanationResponse {
  explanation: string
  cached: boolean
}

export interface PipelineEvent {
  agent:     AgentRole | 'judge0'
  status:    string
  ai?:       string
  approach?: string
  iteration?: number
  failure_type?: string
}

export interface UsageStat {
  label:     string
  calls:     number
  tokens_in:  number
  tokens_out: number
  limit:     number
  percent:   number
  available: boolean
  warning:   boolean
  exhausted: boolean
}

export interface UsageStats {
  claude:     UsageStat
  gpt4o:      UsageStat
  gpt4o_mini: UsageStat
  gemini:     UsageStat
}

export interface AgentAssignment {
  ai:    string
  model: string
  label: string
}

export interface AiConfig {
  keys_configured: number
  available:       Record<AiKey, boolean>
  auto_assignment: Record<AgentRole, AgentAssignment>
  mode:            string
}

export interface BrainStats {
  total_attempts:   number
  total_passed:     number
  pass_rate:        number
  patterns_learned: number
  languages_used:   Record<Language, number>
  procedures_count: number
  recent_solves:    RecentSolve[]
}

export interface RecentSolve {
  problem:    string
  approach:   string
  language:   Language
  iterations: number
  passed:     boolean
  timestamp:  string
}

export interface TemporalInsights {
  total_solves:   number
  pass_rate:      number
  avg_iterations: number
  message:        string
  by_category:    Record<string, { total: number; passed: number }>
}

export interface HealthStatus {
  status:      string
  version:     string
  environment: string
  keys:        Record<AiKey, boolean>
  any_ai:      boolean
  judge0:      boolean
}
