import { create } from 'zustand'
import type {
  Language, AiMode, SolveResult, UsageStats,
  AiConfig, PipelineStep, AgentRole,
} from '@/types'

const STEPS: Pick<PipelineStep, 'role' | 'label' | 'icon'>[] = [
  { role: 'analyzer',   label: 'Analyzer',   icon: '🔍' },
  { role: 'strategist', label: 'Strategist',  icon: '🧠' },
  { role: 'coder',      label: 'Coder',       icon: '⌨️' },
  { role: 'reviewer',   label: 'Reviewer',    icon: '👁' },
  { role: 'judge',      label: 'Judge',       icon: '⚖️' },
]

function makeInitialSteps(): PipelineStep[] {
  return STEPS.map((s) => ({ ...s, status: 'idle' as const }))
}

interface SolveStore {
  // ── Input ───────────────────────────────────────────────────────────────────
  problem:    string
  language:   Language
  imageFile:  File | null

  // ── AI Config ───────────────────────────────────────────────────────────────
  aiMode:          AiMode
  manualOverrides: Record<string, string>
  aiConfig:        AiConfig | null

  // ── Solve state ─────────────────────────────────────────────────────────────
  solving:       boolean
  pipelineSteps: PipelineStep[]
  result:        SolveResult | null
  error:         string | null
  rateLimitInfo: { ai: string; ai_label: string; message: string } | null

  // ── Usage ───────────────────────────────────────────────────────────────────
  usage: UsageStats | null

  // ── UI ──────────────────────────────────────────────────────────────────────
  showBrainPanel:  boolean
  showAiPanel:     boolean
  showReasoning:   boolean
  showExplanation: boolean
  explanationText: string

  // ── Actions ─────────────────────────────────────────────────────────────────
  setProblem:       (p: string)         => void
  setLanguage:      (l: Language)       => void
  setImageFile:     (f: File | null)    => void
  setAiMode:        (m: AiMode)         => void
  setManualOverride:(role: string, ai: string) => void
  setAiConfig:      (c: AiConfig)       => void
  setUsage:         (u: UsageStats)     => void
  setSolving:       (v: boolean)        => void
  setResult:        (r: SolveResult | null) => void
  setError:         (e: string | null)  => void
  setRateLimitInfo: (i: { ai: string; ai_label: string; message: string } | null) => void
  setStepStatus:    (role: AgentRole, status: PipelineStep['status'], ai?: string) => void
  resetPipeline:    ()                  => void
  setShowBrainPanel:(v: boolean)        => void
  setShowAiPanel:   (v: boolean)        => void
  setShowReasoning: (v: boolean)        => void
  setShowExplanation:(v: boolean)       => void
  setExplanationText:(t: string)        => void
}

export const useSolveStore = create<SolveStore>((set) => ({
  problem:         '',
  language:        'python',
  imageFile:       null,
  aiMode:          'auto',
  manualOverrides: {},
  aiConfig:        null,
  solving:         false,
  pipelineSteps:   makeInitialSteps(),
  result:          null,
  error:           null,
  rateLimitInfo:   null,
  usage:           null,
  showBrainPanel:  false,
  showAiPanel:     false,
  showReasoning:   false,
  showExplanation: false,
  explanationText: '',

  setProblem:       (p)    => set({ problem: p }),
  setLanguage:      (l)    => set({ language: l }),
  setImageFile:     (f)    => set({ imageFile: f }),
  setAiMode:        (m)    => set({ aiMode: m }),
  setManualOverride:(role, ai) =>
    set((s) => ({ manualOverrides: { ...s.manualOverrides, [role]: ai } })),
  setAiConfig:      (c)    => set({ aiConfig: c }),
  setUsage:         (u)    => set({ usage: u }),
  setSolving:       (v)    => set({ solving: v }),
  setResult:        (r)    => set({ result: r }),
  setError:         (e)    => set({ error: e }),
  setRateLimitInfo: (i)    => set({ rateLimitInfo: i }),

  setStepStatus: (role, status, ai) =>
    set((s) => ({
      pipelineSteps: s.pipelineSteps.map((step) =>
        step.role === role ? { ...step, status, ai: ai ?? step.ai } : step
      ),
    })),

  resetPipeline: () =>
    set({ pipelineSteps: makeInitialSteps(), result: null, error: null, rateLimitInfo: null }),

  setShowBrainPanel:  (v) => set({ showBrainPanel: v }),
  setShowAiPanel:     (v) => set({ showAiPanel: v }),
  setShowReasoning:   (v) => set({ showReasoning: v }),
  setShowExplanation: (v) => set({ showExplanation: v }),
  setExplanationText: (t) => set({ explanationText: t }),
}))
