import { X } from 'lucide-react'
import { useSolveStore } from '@/store/useSolveStore'

export function ExplanationModal() {
  const { showExplanation, explanationText, setShowExplanation } = useSolveStore()

  if (!showExplanation || !explanationText) return null

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-6"
      onClick={() => setShowExplanation(false)}
    >
      <div
        className="bg-surface2 border border-border2 rounded-2xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="text-[11px] font-bold tracking-[1.5px] uppercase text-mid">
            📚 Algorithm Explanation
          </span>
          <button
            onClick={() => setShowExplanation(false)}
            className="text-dim hover:text-mid transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <pre className="text-[13px] leading-relaxed text-mid whitespace-pre-wrap font-mono">
            {explanationText}
          </pre>
        </div>
      </div>
    </div>
  )
}
