import { useState } from 'react'
import { clsx } from 'clsx'
import { Copy, Check, ChevronDown, ChevronRight, Zap } from 'lucide-react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { cpp } from '@codemirror/lang-cpp'
import { java } from '@codemirror/lang-java'
import { oneDark } from '@codemirror/theme-one-dark'
import toast from 'react-hot-toast'
import { useSolveStore } from '@/store/useSolveStore'
import { api } from '@/utils/api'
import type { Language } from '@/types'

function getLangExt(lang: Language) {
  if (lang === 'python') return [python()]
  if (lang === 'cpp')    return [cpp()]
  return [java()]
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    toast.success('Copied!')
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button onClick={copy} className="btn flex items-center gap-1.5">
      {copied ? <Check size={11} /> : <Copy size={11} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

function Collapsible({
  title, children, defaultOpen = false,
}: {
  title: React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="card">
      <button
        onClick={() => setOpen(!open)}
        className="card-header w-full text-left hover:bg-surface2 transition-colors"
      >
        <div className="card-title">{title}</div>
        {open ? <ChevronDown size={14} className="text-mid" /> : <ChevronRight size={14} className="text-mid" />}
      </button>
      {open && <div className="p-4">{children}</div>}
    </div>
  )
}

export function OutputPanel() {
  const { result, error, rateLimitInfo, solving, language, problem, setExplanationText, setShowExplanation } = useSolveStore()
  const [explaining, setExplaining] = useState(false)

  const requestExplanation = async () => {
    if (!problem.trim() || !result?.final_solution || explaining) return
    setExplaining(true)
    try {
      toast('Generating explanation...', { icon: '📚' })
      const res = await api.explain(
        problem,
        result.final_solution,
        language,
        result.chosen_approach,
        result.reasoning_chain,
      )
      setExplanationText(res.explanation)
      setShowExplanation(true)
    } catch {
      toast.error('Could not generate explanation.')
    } finally {
      setExplaining(false)
    }
  }

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (!solving && !result && !error && !rateLimitInfo) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 text-dim">
        <Zap size={40} className="opacity-20" />
        <p className="text-sm text-center max-w-[240px] leading-relaxed">
          Paste a problem and hit Solve.<br />
          The 5-agent pipeline will reason, strategize, code, review, and verify.
        </p>
        <p className="text-[11px] opacity-60">Ctrl+Enter to run</p>
      </div>
    )
  }

  // ── Rate limit ───────────────────────────────────────────────────────────────
  if (rateLimitInfo) {
    return (
      <div className="p-4">
        <div className="card">
          <div className="card-header">
            <div className="card-title">⚠️ Rate Limit Reached</div>
            <span className="badge badge-yellow">SWITCH AI</span>
          </div>
          <div className="p-4 space-y-2">
            <p className="text-sm text-yellow">{rateLimitInfo.message}</p>
            <p className="text-[12px] text-mid leading-relaxed">
              Go to <strong className="text-[#e2e4f0]">AI Config</strong> → Manual mode →
              switch <strong className="text-[#e2e4f0]">{rateLimitInfo.ai_label}</strong> to another AI,
              or wait for your limit to reset.
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error && !result) {
    return (
      <div className="p-4">
        <div className="card">
          <div className="card-header">
            <div className="card-title">❌ Error</div>
            <span className="badge badge-red">FAILED</span>
          </div>
          <div className="p-4 space-y-2">
            <p className="text-sm text-red">{error}</p>
            <p className="text-[11px] text-mid">
              Make sure the backend is running: <code className="font-mono bg-surface3 px-1.5 py-0.5 rounded">cd backend && python main.py</code>
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (!result) return null

  const passed = result.status === 'passed'
  const judgeUnavailable = result.status === 'unverified' || result.status === 'judge_unavailable'
  const unverifiedRun = judgeUnavailable || (passed && result.verified === false)

  return (
    <div className="flex flex-col gap-3 p-4 overflow-y-auto h-full">

      {/* ── Status + Complexity ─────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            {passed ? (unverifiedRun ? '⚠️ NOT VERIFIED' : '✅ VERIFIED') : judgeUnavailable ? '⚠️ NOT VERIFIED' : '⚠️ BEST ATTEMPT'}
          </div>
          <div className="flex gap-2">
            <span className={clsx('badge', passed && !unverifiedRun ? 'badge-green' : unverifiedRun ? 'badge-yellow' : 'badge-red')}>
              {passed ? (unverifiedRun ? 'NOT VERIFIED' : 'ALL TESTS PASSED') : judgeUnavailable ? 'NOT VERIFIED' : 'PARTIAL'}
            </span>
            {result.dsa_category && (
              <span className="badge badge-accent">{result.dsa_category}</span>
            )}
          </div>
        </div>
        {unverifiedRun && (
          <p className="px-4 pt-2 text-xs text-yellow-500">
            Not verified — Judge0 not available. This solution was not confirmed by an external execution.
          </p>
        )}
        <div className="p-4 grid grid-cols-3 gap-3">
          <div className="bg-surface border border-border rounded-xl p-3">
            <div className="text-[9px] font-bold uppercase tracking-widest text-dim mb-1.5">Time</div>
            <div className="font-mono text-base font-bold text-green truncate">{result.time_complexity || 'N/A'}</div>
          </div>
          <div className="bg-surface border border-border rounded-xl p-3">
            <div className="text-[9px] font-bold uppercase tracking-widest text-dim mb-1.5">Space</div>
            <div className="font-mono text-base font-bold text-green truncate">{result.space_complexity || 'N/A'}</div>
          </div>
          <div className="bg-surface border border-border rounded-xl p-3">
            <div className="text-[9px] font-bold uppercase tracking-widest text-dim mb-1.5">Algorithm</div>
            <div className="text-[11px] font-bold text-accent leading-tight">{result.chosen_approach || 'N/A'}</div>
          </div>
        </div>

        {/* AI used row */}
        {result.agents_ai_used && Object.keys(result.agents_ai_used).length > 0 && (
          <div className="px-4 pb-3 flex flex-wrap gap-2">
            {Object.entries(result.agents_ai_used).map(([role, ai]) => (
              <span key={role} className="text-[10px] font-mono border border-border2 rounded-full px-2 py-0.5 text-mid">
                {role}: {ai}
              </span>
            ))}
            <span className="text-[10px] font-mono border border-border2 rounded-full px-2 py-0.5 text-dim">
              {result.iterations_used} iteration{result.iterations_used !== 1 ? 's' : ''}
            </span>
          </div>
        )}
      </div>

      {/* ── Solution Code ───────────────────────────────────────────────────── */}
      {result.final_solution && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">💻 {language.toUpperCase()} SOLUTION</div>
            <div className="flex gap-2">
              <button onClick={requestExplanation} className="btn text-[10px]" disabled={explaining}>
                {explaining ? '⏳ Explaining...' : '💬 Explain'}
              </button>
              <CopyButton text={result.final_solution} />
            </div>
          </div>
          <div className="border-t border-border">
            <CodeMirror
              value={result.final_solution}
              extensions={getLangExt(language)}
              theme={oneDark}
              editable={false}
              style={{ fontSize: 12 }}
              basicSetup={{ lineNumbers: true, foldGutter: false }}
            />
          </div>
        </div>
      )}

      {/* ── Reasoning chain ─────────────────────────────────────────────────── */}
      {result.reasoning_chain && (
        <Collapsible title="🧠 AGENT REASONING">
          <pre className="text-[12px] leading-relaxed text-mid whitespace-pre-wrap font-mono">
            {result.reasoning_chain}
          </pre>
        </Collapsible>
      )}

      {/* ── Alternates ──────────────────────────────────────────────────────── */}
      {result.alternate_approaches?.length > 0 && (
        <Collapsible title="🔀 ALTERNATE APPROACHES">
          <div className="space-y-2">
            {result.alternate_approaches.map((alt, i) => (
              <div key={i} className="bg-surface border border-border rounded-xl p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[12px] font-semibold text-[#e2e4f0]">{alt.name}</span>
                  <span className="font-mono text-[11px] text-accent">{alt.time_complexity}</span>
                </div>
                <p className="text-[11px] text-mid leading-relaxed">
                  Not chosen: {alt.why_not_chosen}
                </p>
              </div>
            ))}
          </div>
        </Collapsible>
      )}

      {/* ── Error message ────────────────────────────────────────────────────── */}
      {result.error_message && (
        <div className="card">
          <div className="card-header">
            <div className="card-title">📝 Solver Note</div>
          </div>
          <div className="p-4">
            <p className="text-[12px] text-yellow leading-relaxed">{result.error_message}</p>
          </div>
        </div>
      )}
    </div>
  )
}
