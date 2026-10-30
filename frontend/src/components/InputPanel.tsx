import { useCallback, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { Settings2, ImagePlus, Zap, X } from 'lucide-react'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { cpp } from '@codemirror/lang-cpp'
import { java } from '@codemirror/lang-java'
import { oneDark } from '@codemirror/theme-one-dark'
import { useSolveStore } from '@/store/useSolveStore'
import { AiConfigPanel } from './AiConfigPanel'
import { useSolve } from '@/hooks/useSolve'
import type { Language } from '@/types'

const LANGUAGES: { value: Language; label: string }[] = [
  { value: 'python', label: 'Python' },
  { value: 'cpp',    label: 'C++' },
  { value: 'java',   label: 'Java' },
]

function getLangExtension(lang: Language) {
  if (lang === 'python') return [python()]
  if (lang === 'cpp')    return [cpp()]
  return [java()]
}

const PLACEHOLDER = `Paste your competitive programming problem here...

Example:
Given an array of integers and a target, return the indices
of two numbers that add up to target.

Constraints:
  2 ≤ n ≤ 10^5
  -10^9 ≤ nums[i] ≤ 10^9

Input:  nums = [2,7,11,15], target = 9
Output: [0,1]

Press Ctrl+Enter to solve ⚡`

export function InputPanel() {
  const {
    problem, setProblem,
    language, setLanguage,
    imageFile, setImageFile,
    solving, showAiPanel, setShowAiPanel,
  } = useSolveStore()

  const { solve } = useSolve()
  const fileRef   = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handleFile = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) return
    setImageFile(file)
  }, [setImageFile])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.ctrlKey && e.key === 'Enter') solve()
  }, [solve])

  return (
    <div className="flex flex-col h-full overflow-hidden relative">
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-surface shrink-0">
        <span className="text-[10px] font-bold tracking-[2px] uppercase text-dim">
          Problem Input
        </span>
        <div className="flex items-center gap-2">
          {/* Language selector */}
          <div className="flex gap-1">
            {LANGUAGES.map((l) => (
              <button
                key={l.value}
                onClick={() => setLanguage(l.value)}
                className={clsx(
                  'px-3 py-1 rounded-lg border text-[11px] font-mono font-medium transition-all duration-150',
                  language === l.value
                    ? 'bg-accent border-accent text-white'
                    : 'border-border2 text-mid hover:border-accent hover:text-accent'
                )}
              >
                {l.label}
              </button>
            ))}
          </div>

          <div className="w-px h-4 bg-border2" />

          {/* AI Config button */}
          <button
            onClick={() => setShowAiPanel(!showAiPanel)}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition-all duration-150',
              showAiPanel
                ? 'border-purple text-purple bg-purple/10'
                : 'border-border2 text-mid hover:border-purple hover:text-purple'
            )}
          >
            <Settings2 size={12} />
            AI Config
          </button>
        </div>

        {/* AI Config dropdown */}
        {showAiPanel && <AiConfigPanel onClose={() => setShowAiPanel(false)} />}
      </div>

      {/* Input body */}
      <div className="flex-1 flex flex-col p-4 gap-3 overflow-y-auto" onKeyDown={handleKeyDown}>
        {/* Problem text area using CodeMirror */}
        <div className="flex-1 min-h-[240px] rounded-xl overflow-hidden border border-border focus-within:border-accent transition-colors duration-200">
          <CodeMirror
            value={problem}
            onChange={setProblem}
            extensions={getLangExtension(language)}
            theme={oneDark}
            placeholder={PLACEHOLDER}
            style={{ fontSize: 13, height: '100%', minHeight: 240 }}
            basicSetup={{
              lineNumbers:       false,
              foldGutter:        false,
              highlightActiveLine: false,
            }}
          />
        </div>

        {/* Image upload zone */}
        <div
          onClick={() => fileRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          className={clsx(
            'border-2 border-dashed rounded-xl p-4 text-center cursor-pointer transition-all duration-200 text-[12px]',
            imageFile
              ? 'border-green text-green bg-green/5'
              : dragging
              ? 'border-accent text-accent bg-accent/5'
              : 'border-border2 text-dim hover:border-accent hover:text-accent hover:bg-accent/5'
          )}
        >
          {imageFile ? (
            <div className="flex items-center justify-center gap-2">
              <span>✅ {imageFile.name}</span>
              <button
                onClick={(e) => { e.stopPropagation(); setImageFile(null) }}
                className="text-mid hover:text-red transition-colors"
              >
                <X size={14} />
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2">
              <ImagePlus size={14} />
              <span>Drop screenshot or click to upload · Claude Vision reads it directly</span>
            </div>
          )}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />

        {/* Solve button */}
        <button
          onClick={solve}
          disabled={solving}
          className="btn-primary flex items-center justify-center gap-2"
        >
          {solving ? (
            <>
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="w-1.5 h-1.5 rounded-full bg-accent"
                    style={{ animation: `blink 1.2s ease-in-out ${i * 0.2}s infinite` }}
                  />
                ))}
              </span>
              Agents working...
            </>
          ) : (
            <>
              <Zap size={15} />
              SOLVE WITH 5-AGENT PIPELINE
            </>
          )}
        </button>

        <p className="text-center text-[10px] text-dim">
          Ctrl+Enter to solve
        </p>
      </div>
    </div>
  )
}
