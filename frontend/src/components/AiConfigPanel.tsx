import { useEffect } from 'react'
import { clsx } from 'clsx'
import { api } from '@/utils/api'
import { useSolveStore } from '@/store/useSolveStore'
import type { AgentRole } from '@/types'

const AGENTS: { role: AgentRole; label: string; icon: string; bestAi: string }[] = [
  { role: 'analyzer',   label: 'Analyzer',   icon: '🔍', bestAi: 'Gemini'  },
  { role: 'strategist', label: 'Strategist',  icon: '🧠', bestAi: 'Claude'  },
  { role: 'coder',      label: 'Coder',       icon: '⌨️', bestAi: 'GPT-4o' },
  { role: 'reviewer',   label: 'Reviewer',    icon: '👁', bestAi: 'Claude'  },
  { role: 'judge',      label: 'Judge',       icon: '⚖️', bestAi: 'GPT-4o-mini' },
]

const AI_BADGE_COLORS: Record<string, string> = {
  claude:     'bg-amber-400/10 text-amber-400',
  gpt4o:      'bg-green/10 text-green',
  gpt4o_mini: 'bg-green/10 text-green',
  gemini:     'bg-blue/10 text-blue',
  none:       'bg-surface3 text-mid',
}

export function AiConfigPanel({ onClose }: { onClose: () => void }) {
  const {
    aiMode, setAiMode, aiConfig, setAiConfig,
    manualOverrides, setManualOverride,
  } = useSolveStore()

  useEffect(() => {
    api.getAiConfig().then(setAiConfig).catch(() => {})
  }, [setAiConfig])

  return (
    <div className="absolute top-[44px] right-4 w-80 bg-surface2 border border-border2 rounded-xl shadow-2xl z-50 overflow-hidden">
      <div className="p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[10px] font-bold tracking-[1.5px] uppercase text-mid">
            AI Configuration
          </span>
          <button onClick={onClose} className="text-dim hover:text-mid transition-colors text-lg leading-none">×</button>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-2 mb-4">
          {(['auto', 'manual'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setAiMode(mode)}
              className={clsx(
                'flex-1 py-1.5 rounded-lg text-[11px] font-semibold capitalize transition-all duration-150 border',
                aiMode === mode
                  ? 'bg-accent border-accent text-white'
                  : 'border-border2 text-mid hover:border-accent hover:text-accent'
              )}
            >
              {mode}
            </button>
          ))}
        </div>

        {/* Auto assignment */}
        {aiMode === 'auto' && aiConfig && (
          <div className="space-y-1">
            {AGENTS.map(({ role, label, icon }) => {
              const assignment = aiConfig.auto_assignment[role]
              const aiKey = assignment?.ai ?? 'none'
              return (
                <div key={role} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                  <span className="text-[12px] font-medium text-[#e2e4f0]">
                    {icon} {label}
                  </span>
                  <span className={clsx('badge text-[10px]', AI_BADGE_COLORS[aiKey] ?? AI_BADGE_COLORS.none)}>
                    {assignment?.label ?? 'No key'}
                  </span>
                </div>
              )
            })}
            <p className="text-[10px] text-dim mt-2 leading-relaxed">
              Auto assigns best AI per role based on available keys.
            </p>
          </div>
        )}

        {/* Manual assignment */}
        {aiMode === 'manual' && (
          <div className="space-y-1">
            {AGENTS.map(({ role, label, icon, bestAi }) => (
              <div key={role} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <div>
                  <span className="text-[12px] font-medium text-[#e2e4f0]">{icon} {label}</span>
                  <div className="text-[10px] text-dim">Best: {bestAi}</div>
                </div>
                <select
                  value={manualOverrides[role] ?? 'auto'}
                  onChange={(e) => setManualOverride(role, e.target.value)}
                  className="bg-surface3 border border-border2 rounded-lg text-[11px] text-[#e2e4f0] px-2 py-1 cursor-pointer outline-none focus:border-accent"
                >
                  <option value="auto">Auto</option>
                  {aiConfig?.available.claude     && <option value="claude">Claude</option>}
                  {aiConfig?.available.gpt4o      && <option value="gpt4o">GPT-4o</option>}
                  {aiConfig?.available.gpt4o_mini && <option value="gpt4o_mini">GPT-4o-mini</option>}
                  {aiConfig?.available.gemini     && <option value="gemini">Gemini</option>}
                </select>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
